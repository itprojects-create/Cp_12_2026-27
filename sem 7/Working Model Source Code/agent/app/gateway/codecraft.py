"""OpenAI-compatible prediction gateway with retry, caps and circuit breaking.

Experiential Labs is the active production provider (OpenAI-compatible hosted
gateway funded by platform credits); OpenRouter remains a fallback lane. The
module name is retained so the agent graph and existing integrations keep
their stable import path.
"""
from __future__ import annotations
import itertools
import json
import re
import threading
import time
from datetime import date, datetime, timedelta, timezone
from openai import OpenAI, APIConnectionError, APIStatusError, APITimeoutError, RateLimitError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception
from app.config import settings

# SDK-level retries DISABLED (max_retries=0): a 429 must surface immediately so the
# gateway can rotate to the next key instead of sleeping on one hot key.
# Tenacity handles conn/timeout/5xx per key; 429s are handled by key rotation below.
_TRANSIENT = (APIConnectionError, APITimeoutError, APIStatusError)
_TRANSIENT_NORETRY = (RateLimitError,)  # never retried on same key: rotate instead

# --- Model body policy -------------------------------------------------------
# Some gateway models reject optional request fields with 400
# unsupported_parameter ("temperature on a reasoning-only route" per the
# Experiential contract). gpt-6-luna, for example, accepts sampling only when
# reasoning is none (sampling_requires_reasoning_none), so temperature must be
# omitted on its default reasoning route. The policy comes from the provider's
# free catalog read (GET /v1/models) and then self-heals: a field named by a
# 400's `param` is dropped and remembered for the process lifetime.
_body_policies: dict[str, dict] = {}
_body_policy_lock = threading.Lock()


def _policy_from_catalog_entry(entry) -> dict | None:
    temp = getattr(entry, "supports_temperature", None)
    reasoning_none = getattr(entry, "sampling_requires_reasoning_none", None)
    structured = getattr(entry, "supports_structured_output", None)
    max_tokens_field = getattr(entry, "chat_max_tokens_field", None)
    if temp is None and reasoning_none is None and structured is None and max_tokens_field is None:
        return None  # capability flags unavailable: stay optimistic, adapt on 400s
    return {"temperature": bool(temp) and not bool(reasoning_none),
            "response_format": bool(structured),
            "max_tokens_field": max_tokens_field or "max_tokens"}


def _seed_body_policy(api_key: str, base_url: str, model: str):
    """Best-effort free catalog read (10s budget); an unknown model stays adaptive."""
    try:
        probe = OpenAI(api_key=api_key, base_url=base_url, timeout=10.0, max_retries=0)
        entry = next((m for m in probe.models.list() if m.id == model), None)
        if entry is not None:
            policy = _policy_from_catalog_entry(entry)
            if policy is not None:
                with _body_policy_lock:
                    _body_policies.setdefault(model, policy)
    except Exception:
        pass  # catalog hiccup must never block inference; 400 adaptation covers us


def _effective_body(model: str, messages: list, temperature: float | None,
                    max_tokens: int) -> dict:
    with _body_policy_lock:
        policy = _body_policies.get(model) or {}
    body: dict = {"model": model, "messages": messages}
    if policy.get("temperature", True) and temperature is not None:
        body["temperature"] = temperature
    if policy.get("response_format", True):
        body["response_format"] = {"type": "json_object"}
    body[policy.get("max_tokens_field") or "max_tokens"] = max_tokens
    return body


def _unsupported_param(exc: Exception) -> str | None:
    """The offending field name from a 400 unsupported_parameter, else None."""
    body = getattr(exc, "body", None)
    hay = json.dumps(body) if isinstance(body, dict) else str(exc)
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        param = body["error"].get("param")
        if isinstance(param, str) and param:
            return param
    match = re.search(r'"param"\s*:\s*"([^"]+)"', hay)
    return match.group(1) if match else None


def _apply_rejection(model: str, body: dict, param: str) -> bool:
    """Drop/replace the field the provider named; remember it per model.

    Returns True when the request was adapted and may be retried as-is.
    """
    policy: dict = {}
    adapted = False
    if param == "temperature" and "temperature" in body:
        body.pop("temperature")
        policy["temperature"] = False
        adapted = True
    elif param == "top_p" and "top_p" in body:
        body.pop("top_p")
        adapted = True
    elif param == "response_format" and "response_format" in body:
        body.pop("response_format")
        policy["response_format"] = False
        adapted = True
    elif param == "max_tokens" and "max_tokens" in body:
        body["max_completion_tokens"] = body.pop("max_tokens")
        policy["max_tokens_field"] = "max_completion_tokens"
        adapted = True
    elif param == "max_completion_tokens" and "max_completion_tokens" in body:
        body.pop("max_completion_tokens")
        adapted = True  # route caps output implicitly; retry minimal
    if policy:
        with _body_policy_lock:
            _body_policies.setdefault(model, {}).update(policy)
    return adapted


def _credit_state(exc: Exception) -> str | None:
    """Classify an Experiential-style 429 insufficient_quota body.

    'credits': the account has no platform credits (insufficient_credits /
    model_requires_payment) — top-up territory, not a daily wall.
    'daily': a free-tier/key daily cap (free_limit, key_daily_cap) that resets.
    None: unrecognized shape (OpenRouter daily detection still applies).
    """
    body = getattr(exc, "body", None)
    if not isinstance(body, dict):
        return None
    hay = json.dumps(body)
    if "insufficient_credits" in hay or "model_requires_payment" in hay:
        return "credits"
    if "free_limit" in hay or "key_daily_cap" in hay or "free limit" in hay:
        return "daily"
    return None

class TokenCapBreach(RuntimeError):
    pass

class OutOfFunds(RuntimeError):
    """402/insufficient_funds: account-wide, rotating keys cannot help. Stop and top up."""
    pass

class ProviderUnavailable(RuntimeError):
    """All configured keys are unavailable for authentication or authorization."""
    pass

class DailyQuotaExhausted(RuntimeError):
    """The provider account is out of daily requests (e.g. OpenRouter free tier 50/day).

    Distinct from a burst 429: rotating keys and retrying cannot help until the
    provider resets the counter. Carries the reset epoch (seconds) for messaging.
    """
    def __init__(self, reset_at: float | None = None, detail: str = ""):
        self.reset_at = reset_at
        super().__init__(detail or "Provider daily request quota is exhausted")

_IST = timezone(timedelta(hours=5, minutes=30))

def _fmt_reset(epoch: float) -> str:
    try:
        return datetime.fromtimestamp(epoch, _IST).strftime("%d %b %H:%M IST")
    except (OverflowError, OSError, ValueError):
        return "the provider's daily reset"

def _next_utc_midnight(epoch: float) -> float:
    """OpenRouter's free daily counters reset at 00:00 UTC."""
    day = datetime.fromtimestamp(epoch, timezone.utc)
    return (day.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).timestamp()

def _daily_reset_from(exc: Exception) -> float | None:
    """Return a reset epoch when a 429 is a DAILY quota, else None (burst 429).

    OpenRouter daily-limit responses carry `metadata.limit_source`
    (`openrouter_free_tier_daily`), a `Rate limit exceeded: free-models-per-day`
    message, `x-ratelimit-remaining: 0` and an `x-ratelimit-reset` epoch (ms).
    Treating those like an ordinary Retry-After caused hours-long retry storms:
    every prediction attempt re-hit the 50/day wall instead of failing fast.
    """
    daily = False
    reset: float | None = None
    try:
        headers = exc.response.headers  # type: ignore[union-attr]
        remaining = headers.get("x-ratelimit-remaining")
        if remaining is not None:
            daily = daily or float(remaining) <= 0
        raw = headers.get("x-ratelimit-reset")
        if raw:
            value = float(raw)
            reset = value / 1000.0 if value > 1e12 else value  # OpenRouter sends ms.
    except Exception:
        pass
    body = getattr(exc, "body", None)
    hay = ""
    if isinstance(body, dict):
        hay = json.dumps(body)
    else:
        try:
            hay = exc.response.text  # type: ignore[union-attr]
        except Exception:
            hay = ""
    if hay:
        if "free-models-per-day" in hay or "limit_source" in hay and "daily" in hay:
            daily = True
        if reset is None:
            match = re.search(r'"reset_at"\s*:\s*"([^"]+)"', hay)
            if match:
                try:
                    reset = datetime.fromisoformat(match.group(1).replace("Z", "+00:00")).timestamp()
                except ValueError:
                    pass
    if not daily:
        return None
    return reset if (reset and reset > time.time()) else _next_utc_midnight(time.time())

def _retry_after(exc: Exception, default: float = 60.0) -> float:
    """Honor the provider's Retry-After header (429s); clamp to configured max."""
    try:
        raw = exc.response.headers.get("retry-after")  # type: ignore[union-attr]
        secs = float(raw)
        return max(1.0, min(secs, settings.RATE_MAX_COOLDOWN_S))
    except Exception:
        return default

def _status_of(exc: Exception) -> int | None:
    return getattr(exc, "status_code", None)

def _retryable_transport_error(exc: BaseException) -> bool:
    # APIStatusError includes terminal 4xx, not just server failures. Let the
    # outer loop quarantine/rotate immediately instead of waiting 2+4+8+16s.
    if isinstance(exc, (APIConnectionError, APITimeoutError)):
        return True
    code = getattr(exc, "status_code", None)
    return isinstance(exc, APIStatusError) and code is not None and (
        code == 408 or 500 <= code < 600)

class Gateway:
    def __init__(self):
        keys = settings.provider_keys()
        if not keys:
            raise RuntimeError("No LLM provider keys configured")
        self.provider = settings.provider_name()
        self.clients = [OpenAI(api_key=k, base_url=settings.provider_base_url(),
                               timeout=120.0, max_retries=0) for k in keys]
        self._rr = itertools.cycle(range(len(self.clients)))
        self._lock = threading.Lock()
        self.session_usage: dict[str, int] = {}
        self.day_usage: int = 0
        self._day: date | None = None
        self._failures: dict[int, int] = {}
        self._breaker_open_until: dict[int, float] = {}
        self._dead: set[int] = set()  # quarantined keys (401/403): never retried
        self._dead_reason: dict[int, str] = {}
        self._last_call: dict[int, float] = {}  # per-key pacing timestamps
        self.calls: list[dict] = []  # auditable LLM call ledger (role/model/tokens per call)
        self.day_requests: int = 0  # provider request count, not tokens (free tiers cap REQUESTS/day)
        self._daily_quota_until: dict[int, float] = {}  # per-key provider daily-quota reset (epoch s)
        self._day, self.day_usage, self.day_requests, quota_reset, reset_provider = self._load_day()
        if quota_reset > time.time() and reset_provider == self.provider:
            # Persisted account-wide truth for THIS provider: a restart during
            # quota exhaustion keeps failing fast instead of re-discovering the
            # wall per boot. Another provider's ledger row must not block us
            # (the OpenRouter cutover would otherwise inherit its 429 wall).
            self._daily_quota_until = {i: quota_reset for i in range(len(self.clients))}
        if self.provider in ("experiential", "inception"):
            base = settings.provider_base_url()
            for model in {settings.analyst_model(), settings.decider_model()}:
                _seed_body_policy(settings.explabs_key() if self.provider == "experiential"
                                  else settings.inception_key(), base, model)

    def reset_quarantined_keys(self):
        """Allow an explicit user retry to revalidate keys without restarting the service.

        Quarantine is useful for a single failing request, but it used to survive
        indefinitely in this process. After a temporary provider outage or a
        balance/key update, every later Quant AI run then failed before making a
        provider request. Only an explicit retry calls this method; background
        warming never clears the safety state.
        """
        with self._lock:
            self._dead.clear()
            self._dead_reason.clear()
            self._failures.clear()
            self._breaker_open_until.clear()

    def _quarantine(self, idx: int, reason: str):
        with self._lock:
            self._dead.add(idx)
            self._dead_reason[idx] = reason

    def _load_day(self):
        today = date.today()
        try:
            from app.db import sqlite_conn
            conn = sqlite_conn()
            # Additive migrations, each guarded independently: a column that
            # already exists must not silently skip the other (the combined
            # ALTER once left quota_reset missing and zeroed the day read).
            existing = {row[1] for row in conn.execute("PRAGMA table_info(usage_daily)")}
            for column, ddl in (("requests", "INTEGER NOT NULL DEFAULT 0"),
                                ("quota_reset", "REAL NOT NULL DEFAULT 0"),
                                ("provider", "TEXT NOT NULL DEFAULT ''")):
                if column not in existing:
                    conn.execute(f"ALTER TABLE usage_daily ADD COLUMN {column} {ddl}")
            conn.commit()
            row = conn.execute(
                "SELECT tokens, requests, quota_reset, provider FROM usage_daily WHERE day=?",
                (today.isoformat(),)).fetchone()
            if not row:
                return today, 0, 0, 0.0, ""
            return (today, int(row[0] or 0), int(row[1] or 0),
                    float(row[2] or 0.0), str(row[3] or ""))
        except Exception:
            return today, 0, 0, 0.0, ""

    def _persist_quota_reset(self, reset: float):
        """Remember a provider daily-quota reset so a RESTART keeps failing fast.

        Without persistence, a backend restart during quota exhaustion re-learns
        the wall by making one doomed provider call and briefly misreports the
        quota as available to the chat pre-flight and trust room.
        """
        if self.provider not in ("openrouter", "experiential", "inception"):
            return  # per-key daily state only proven for these single-account providers
        try:
            from app.db import sqlite_conn
            today = date.today().isoformat()
            conn = sqlite_conn()
            conn.execute(
                "INSERT INTO usage_daily(day, tokens, requests, quota_reset, provider) "
                "VALUES (?,0,0,?,?) ON CONFLICT(day) DO UPDATE SET quota_reset=excluded.quota_reset, "
                "provider=excluded.provider", (today, reset, self.provider))
            conn.commit()
        except Exception:
            pass

    def _pick(self, prefer: int) -> tuple[int, OpenAI]:
        now = time.time()
        for _ in range(len(self.clients)):
            idx = prefer % len(self.clients)
            if idx not in self._dead and self._breaker_open_until.get(idx, 0) < now:
                return idx, self.clients[idx]
            prefer += 1
        # every key cooling/quarantined: take the least-bad (earliest to recover, live keys first)
        live = [i for i in range(len(self.clients)) if i not in self._dead]
        pool = live or list(range(len(self.clients)))
        idx = min(pool, key=lambda i: self._breaker_open_until.get(i, 0))
        return idx, self.clients[idx]

    def _pace(self, idx: int):
        """Self-pacing: never exceed ~1/RATE_MIN_INTERVAL_S RPM per key regardless of bursts."""
        gap = settings.RATE_MIN_INTERVAL_S
        if gap <= 0:
            return
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._last_call.get(idx, 0.0) + gap)
            # Reserve a distinct slot before releasing the lock. Parallel
            # analysts must not all sleep until the same instant and burst 429s.
            self._last_call[idx] = slot
            wait = slot - now
        if wait > 0:
            time.sleep(wait)

    def _track(self, session_id: str, tokens: int):
        today = date.today()
        if self._day != today:
            self._day, self.day_usage, self.day_requests = today, 0, 0
        self.session_usage[session_id] = self.session_usage.get(session_id, 0) + tokens
        self.day_usage += tokens
        self.day_requests += 1
        try:  # persistent ledger: survives restarts, guards the 100M pool
            from app.db import sqlite_conn
            sqlite_conn().execute(
                "INSERT INTO usage_daily(day, tokens, requests) VALUES (?,?,1) "
                "ON CONFLICT(day) DO UPDATE SET tokens=tokens+excluded.tokens, "
                "requests=usage_daily.requests+1",
                (today.isoformat(), tokens))
            sqlite_conn().commit()
        except Exception:
            pass
        if self.session_usage[session_id] > settings.SESSION_TOKEN_CAP:
            raise TokenCapBreach(f"session {session_id} exceeded {settings.SESSION_TOKEN_CAP} tokens")
        if self.day_usage > settings.DAY_TOKEN_CAP:
            raise TokenCapBreach(f"day cap {settings.DAY_TOKEN_CAP} exceeded")

    def _quota_blocked_until(self, idx: int) -> float:
        """When this key may next be billed: the later of its provider daily reset
        and the local request-cap reset. 0.0 means not blocked."""
        cap = settings.DAILY_REQUEST_CAP
        with self._lock:
            provider_reset = self._daily_quota_until.get(idx, 0.0)
            requests = self.day_requests
        if cap and requests >= cap:
            return max(provider_reset, _next_utc_midnight(time.time()))
        return provider_reset if provider_reset > time.time() else 0.0

    def _quota_error(self, blocked: dict[int, float]) -> DailyQuotaExhausted:
        reset = min(blocked.values())
        cap = settings.DAILY_REQUEST_CAP
        if cap and self.day_requests >= cap:
            detail = (f"local daily request cap {cap} reached ({self.day_requests} today); "
                      f"resets {_fmt_reset(reset)}")
        else:
            detail = (f"{self.provider} daily request quota exhausted ({len(blocked)}/"
                      f"{len(self.clients)} keys blocked); resets {_fmt_reset(reset)}")
        return DailyQuotaExhausted(reset, detail)

    def quota_status(self) -> dict:
        """Provider quota truth for endpoints/UI: is today's request budget spent?"""
        now = time.time()
        with self._lock:
            resets = {i: v for i, v in self._daily_quota_until.items() if v > now}
            requests = self.day_requests
            tokens = self.day_usage
            day = self._day
        if day != date.today():
            self._day, self.day_usage, self.day_requests, _persisted, _prov = self._load_day()
            with self._lock:
                self._daily_quota_until.clear()
                requests, tokens = self.day_requests, self.day_usage
        cap = settings.DAILY_REQUEST_CAP or None
        cap_hit = bool(cap and requests >= cap)
        reset = min(resets.values(), default=None)
        if reset is None and cap_hit:
            reset = _next_utc_midnight(now)
        return {"provider": self.provider, "requests_today": requests,
                "daily_request_cap": cap, "tokens_today": tokens,
                "token_cap": settings.DAY_TOKEN_CAP,
                "exhausted": bool(resets) or cap_hit,
                "reset_at": datetime.fromtimestamp(reset, timezone.utc).isoformat() if reset else None,
                "reset_ist": _fmt_reset(reset) if reset else None,
                "seconds_until_reset": max(0, int(reset - now)) if reset else None}

    # Retry budget: 5 attempts with backoff up to 60s. Provider 502s carry
    # retry_after: 60 — fast 1/2/4s retries burn out before the origin recovers,
    # so backoff must reach the minute scale for unattended eval runs.
    @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=2, min=2, max=60),
           retry=retry_if_exception(_retryable_transport_error),
           reraise=True)
    def _call_once(self, client: OpenAI, model: str, messages: list, temperature: float, max_tokens: int) -> tuple[str, int]:
        body = _effective_body(model, messages, temperature, max_tokens)
        # Adaptive body: a 400 unsupported_parameter names the offending field in
        # `param`; drop/replace it (remembered per model) and retry immediately
        # on the same key. Cap the adaptations so a persistently rejected body
        # surfaces its error instead of looping.
        attempts = 0
        while True:
            try:
                resp = client.chat.completions.create(**body)
                break
            except APIStatusError as e:
                param = _unsupported_param(e) if getattr(e, "status_code", None) == 400 else None
                attempts += 1
                if param is None or attempts > 2 or not _apply_rejection(model, body, param):
                    raise
        choice = resp.choices[0]
        if choice.finish_reason != "stop":
            raise RuntimeError(f"LLM did not finish (finish_reason={choice.finish_reason}); "
                               "prompt likely too large for reasoning budget — shrink inputs, don't retry blindly")
        msg = choice.message.content or ""
        if not msg.strip():
            raise RuntimeError("LLM returned empty content")
        usage = resp.usage
        tokens = (usage.total_tokens if usage else 0) or (len(str(messages)) // 4 + len(msg) // 4)
        return msg, tokens

    def complete_json(self, *, role: str, session_id: str, system: str, user: str) -> str:
        # Pre-flight day-cap check: once the day budget is known-spent, refuse
        # BEFORE billing another call. (The post-call check in _track alone can't
        # do this — it fires only after the provider has already billed the call,
        # which is how the 2026-10-06 eval burned 4.38M tokens past its cap.)
        if self.day_usage > settings.DAY_TOKEN_CAP:
            raise TokenCapBreach(f"day cap {settings.DAY_TOKEN_CAP} exceeded")
        cfg = settings.role_config(role)
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        # Key preference: Sonnet deciders prefer the funded key first, then fall
        # back across the rest in order (strict pinning stranded deciders when the
        # preferred key's origin flaps 502 while other keys serve the same model
        # fine — observed 2026-09-20: idx0/idx1 502, idx2/idx3 OK, idx4 402).
        # 402-quarantine below still protects unfunded keys; preference order means
        # zero behavior change while the preferred key is healthy.
        if cfg["model"] == settings.decider_model():
            allowed = [settings.DECIDER_KEY_IDX] + [
                i for i in settings.ANALYST_KEY_IDXS if i != settings.DECIDER_KEY_IDX]
        else:
            allowed = list(settings.ANALYST_KEY_IDXS)
        # Only indices that actually have a configured key can ever be
        # quarantined; a static list longer than the real key count would make
        # the all-allowed-dead checks unreachable (raw provider errors then
        # escape instead of OutOfFunds/ProviderUnavailable).
        allowed = [i for i in allowed if 0 <= i < len(self.clients)]
        # Daily-quota pre-flight (request counts, not tokens): the OpenRouter
        # free tier caps 50 REQUESTS/day for the whole account — chat and all
        # prediction roles share it. Once spent, refuse BEFORE billing another
        # doomed call or sleeping on cooldowns.
        blocked = {i: until for i in allowed if (until := self._quota_blocked_until(i)) > time.time()}
        if blocked:
            raise self._quota_error(blocked)
        last: Exception | None = None
        saw_402 = False
        for _ in range(3):  # outer passes: outlast 429 waves on pinned keys
            acted = False
            for shift in range(len(self.clients)):
                with self._lock:
                    if allowed and all(i in self._dead for i in allowed):
                        reasons = {self._dead_reason.get(i) for i in allowed}
                        if saw_402 or reasons == {"funds"}:
                            raise OutOfFunds("all keys report insufficient funds; top up before retrying")
                        raise ProviderUnavailable(
                            "all configured API keys are quarantined; check provider credentials"
                        )
                    idx, client = self._pick((cfg["key_idx"] + shift) % len(self.clients))
                if idx not in allowed or idx in self._dead:
                    continue
                if self._quota_blocked_until(idx) > time.time():
                    continue  # this key is out of daily requests; rotate instead of billing a doomed call
                acted = True
                self._pace(idx)
                try:
                    text, tokens = self._call_once(client, cfg["model"], messages,
                                                   cfg["temperature"], cfg["max_tokens"])
                except TokenCapBreach:
                    # Terminal budget condition, NOT a per-key failure: rotating
                    # keys cannot help, and treating it as one polluted failure
                    # counters and opened breakers on healthy keys. Stop now.
                    raise
                except RateLimitError as e:  # hot key: honor Retry-After, try next allowed
                    credit = _credit_state(e)
                    if credit == "credits":
                        # Account-wide empty balance: rotating keys cannot help.
                        # Fail fast with the actionable fix instead of burning
                        # the retry budget (an empty wallet is not a 429 wave).
                        raise OutOfFunds(
                            "provider credits exhausted; top up or verify the account "
                            "at the provider console") from e
                    self._breaker_open_until[idx] = time.time() + _retry_after(e)
                    reset = _daily_reset_from(e)
                    if credit == "daily" and reset is None:
                        # Experiential free-limit/key-daily-cap 429s name no reset
                        # time; the counters are daily, so assume the UTC boundary.
                        reset = _next_utc_midnight(time.time())
                    if reset is not None:
                        # Daily quota, not a burst: remember the reset so later
                        # calls fail fast instead of re-hitting the same wall.
                        with self._lock:
                            self._daily_quota_until[idx] = max(
                                self._daily_quota_until.get(idx, 0.0), reset)
                        self._persist_quota_reset(reset)
                        from app.log import log as qlog
                        qlog(session_id, "llm", role, "daily quota blocked",
                             model=cfg["model"], key=idx, reset_epoch=reset)
                    last = e
                    continue
                except Exception as e:
                    code = _status_of(e)
                    if code == 402 or "insufficient_funds" in str(getattr(e, "code", "")):
                        # Unfunded key, not necessarily an empty account: quarantine it and
                        # try the next key. OutOfFunds only if every key says 402.
                        self._quarantine(idx, "funds")
                        saw_402 = True
                        last = e
                        continue
                    if code in (401, 403):  # revoked/narrow key: quarantine permanently, try next
                        self._quarantine(idx, "auth")
                        last = e
                        continue
                    self._failures[idx] = self._failures.get(idx, 0) + 1
                    if self._failures[idx] >= 3:
                        self._breaker_open_until[idx] = time.time() + 120
                    last = e
                    continue
                self._failures[idx] = 0
                with self._lock:
                    self._track(session_id, tokens)
                    self.calls.append({"session": session_id, "role": role, "model": cfg["model"],
                                       "key": idx, "tokens": tokens})
                from app.log import log as qlog
                qlog(session_id, "llm", role, "called", model=cfg["model"], key=idx, tokens=tokens,
                     session_total=self.session_usage.get(session_id, 0))
                return text
            # Ride out 429 AND transient 5xx/conn/timeout waves across passes; stop
            # for terminal outcomes (success returns; auth/quota handled below).
            # 402/401/403 set last too but must NOT trigger another pass on their
            # own — they mean "try other keys", not "wait and retry".
            # A provider DAILY quota is not a wave to ride out: the 3-pass loop
            # sleeping 120s just re-hit the same 50/day wall for hours
            # (2026-10-27 14:05+ IST). When every live allowed key is blocked
            # until reset, stop immediately with the actionable error.
            live = [i for i in allowed if i not in self._dead]
            blocked_untils = {i: u for i in live if (u := self._quota_blocked_until(i)) > time.time()}
            if live and len(blocked_untils) == len(live):
                raise self._quota_error(blocked_untils)
            code = _status_of(last) if isinstance(last, Exception) else None
            transient = (last is not None
                         and (isinstance(last, RateLimitError)
                              or (isinstance(last, _TRANSIENT)
                                  and (code is None or code in (429, 500, 502, 503, 504)))))
            if not acted or not transient:
                break
            # allowed keys all cooling or flapping: wait out the shortest cooldown
            # (capped), else a short backoff to avoid hot-spinning 502s, then retry
            with self._lock:
                wait = min((self._breaker_open_until.get(i, 0) for i in allowed), default=0.0) - time.time()
            if wait > 0:
                time.sleep(min(wait, 120.0))
            else:
                time.sleep(5.0)
        if last is None:
            raise RuntimeError("no allowed API key available for role " + role)
        with self._lock:
            all_dead = bool(allowed) and all(i in self._dead for i in allowed)
        # OutOfFunds ONLY when every key is quarantined (genuinely no funds
        # anywhere). A trailing 402 from one unfunded key while live keys are
        # merely cooling is NOT account-wide exhaustion — surface the raw error
        # so the caller can resume after the flap (never misreport funds).
        if saw_402 and all_dead:
            raise OutOfFunds("all keys report insufficient funds; top up before retrying") from last
        if all_dead and all(self._dead_reason.get(i) == "auth" for i in allowed):
            raise ProviderUnavailable(
                "all configured API keys were rejected; check provider credentials"
            ) from last
        raise last

gateway = Gateway()
