"""Jev (System One) provider adapter: dependency-injected, fail-closed, budgeted.

Security and determinism properties (blueprint §10.2, W4 handoff B2/B3/B7):
- HOST ALLOWLIST per provider: ``typesafe_direct`` may only ever talk to
  https://api.typesafe.ai and reads TYPESAFE_API_KEY; ``experientiallabs_gateway``
  may only talk to https://api.experientiallabs.ai and reads EXPLABS_API_KEY.
  A gateway token is never sent to the TypeSafe host and vice versa; there is
  no silent provider substitution.
- API keys live in server environment variables only; they never enter
  request logs, exception text, reports or the store.
- Retries: bounded idempotent retries for 429 (honoring Retry-After, capped)
  and transient 5xx/timeouts only. 400/401/403/422 never retry.
- Circuit breaker: repeated hard failures open the breaker; calls fail fast
  to UNAVAILABLE until the cooldown passes (injected clock, deterministic).
- Budget: per-UTC-day request/token/cost meter with preflight BEFORE any call;
  exhausted budget → UNAVAILABLE (BUDGET_EXHAUSTED), never a degraded answer.
- Model pinning: request model must be in the provider's callable allowlist
  and the response model must be in the provider's allowed returned set.
  Any other returned model is MODEL_MISMATCH → INVALID (no silent acceptance
  of an alias move).
- With QUANTPLUS_JEV_ENABLED=false (default) the adapter denies everything.
"""
from __future__ import annotations

import hashlib
import json
import os
import time as _time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Protocol

from quantplus_intelligence.research_v3.events_ai.contracts import (
    EventClassification, IssuerEventEvidence, canonical_json)
from quantplus_intelligence.research_v3.events_ai.rubric import (
    REVIEW_CONFIDENCE_THRESHOLD, build_questions, rubric_sha256)
from quantplus_intelligence.research_v3.events_ai.validation import (
    _rejecting_loads, evidence_problems, scan_injection,
    validate_systemone_response)

PROVIDERS = ("typesafe_direct", "experientiallabs_gateway", "fake")

# Host allowlist and credential variable, per provider (no cross-usage).
PROVIDER_SETTINGS = {
    "typesafe_direct": {
        "hosts": ("https://api.typesafe.ai",),
        "key_env": "TYPESAFE_API_KEY",
        "callable_models": ("jev-1.14.0", "jev-latest"),
        "returned_models": ("jev-1.14.0", "jev-latest"),
        "input_price_usd_per_token": 0.042e-6,   # official docs; output tokens free
        "output_price_usd_per_token": 0.0,
    },
    "experientiallabs_gateway": {
        "hosts": ("https://api.experientiallabs.ai",),
        "key_env": "EXPLABS_API_KEY",
        "callable_models": ("jev-latest",),      # discovered entitlement 2026-11-13
        "returned_models": ("jev-latest",),
        # Platform-credit gateway reports its own cost field; the TypeSafe price
        # is the conservative fallback estimate until a verified gateway price.
        "input_price_usd_per_token": 0.042e-6,
        "output_price_usd_per_token": 0.0,
    },
    "fake": {
        "hosts": ("fake://local",),
        "key_env": "",
        "callable_models": ("jev-1.14.0",),
        "returned_models": ("jev-1.14.0",),
        "input_price_usd_per_token": 0.0,
        "output_price_usd_per_token": 0.0,
    },
}

ENDPOINT_PATH = "/v1/systemone"
MAX_BODY_BYTES = 64_000
MAX_RESPONSE_BYTES = 262_144
HARD_FAILURE_STATUSES = (400, 401, 403, 422)     # never retried
TRANSIENT_STATUSES = (429, 500, 502, 503, 504)
MAX_RETRIES = 2
CIRCUIT_FAILURE_THRESHOLD = 3
CIRCUIT_COOLDOWN_S = 300.0


class TransportError(Exception):
    """Sanitized transport failure: status/summary only, never the key."""

    def __init__(self, summary: str):
        super().__init__(summary)
        self.summary = summary


class SystemOneTransport(Protocol):
    """Minimal DI seam: one POST, returns (status, body_bytes)."""

    def post(self, url: str, headers: dict[str, str], body: bytes, timeout_s: float
             ) -> tuple[int, bytes]: ...


class UrllibSystemOneTransport:
    """Default transport over urllib (no third-party dependency)."""

    def post(self, url, headers, body, timeout_s):
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()
        except Exception as exc:  # noqa: BLE001 — sanitized, no key in message
            raise TransportError(f"transport_failure:{type(exc).__name__}") from None


@dataclass
class UsageMeter:
    """Per-UTC-day usage meter keyed by provider (requests, tokens, USD)."""

    entries: dict = field(default_factory=dict)

    def day_key(self, provider: str, now_epoch: float) -> str:
        day = _time.strftime("%Y-%m-%d", _time.gmtime(now_epoch))
        return f"{day}|{provider}"

    def snapshot(self, provider: str, now_epoch: float) -> dict:
        entry = self.entries.get(self.day_key(provider, now_epoch), {})
        return {
            "requests": int(entry.get("requests", 0)),
            "input_tokens": int(entry.get("input_tokens", 0)),
            "output_tokens": int(entry.get("output_tokens", 0)),
            "cost_usd": float(entry.get("cost_usd", 0.0)),
        }

    def record(self, provider: str, now_epoch: float, input_tokens: int,
               output_tokens: int, cost_usd: float) -> None:
        key = self.day_key(provider, now_epoch)
        entry = self.entries.setdefault(
            key, {"requests": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
        entry["requests"] += 1
        entry["input_tokens"] += int(input_tokens)
        entry["output_tokens"] += int(output_tokens)
        entry["cost_usd"] += float(cost_usd)


@dataclass
class CircuitBreaker:
    """Deterministic breaker: N consecutive hard failures open a cooldown."""

    threshold: int = CIRCUIT_FAILURE_THRESHOLD
    cooldown_s: float = CIRCUIT_COOLDOWN_S
    consecutive_failures: int = 0
    open_until: float = 0.0

    def allow(self, now_epoch: float) -> bool:
        return now_epoch >= self.open_until

    def record_success(self) -> None:
        self.consecutive_failures = 0

    def record_hard_failure(self, now_epoch: float) -> None:
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.threshold:
            self.open_until = now_epoch + self.cooldown_s
            self.consecutive_failures = 0


@dataclass
class JevConfig:
    enabled: bool = False
    provider: str = "typesafe_direct"
    model: str = "jev-1.14.0"
    max_requests_per_day: int = 10
    max_spend_usd_per_day: float = 0.25
    timeout_s: float = 20.0
    base_url_override: str = ""          # must still be in the provider allowlist

    @classmethod
    def from_env(cls, env: dict | None = None) -> "JevConfig":
        env = dict(os.environ if env is None else env)

        def flag(name: str, default: str) -> str:
            return str(env.get(name, default)).strip()

        provider = flag("QUANTPLUS_JEV_PROVIDER", "typesafe_direct")
        return cls(
            enabled=flag("QUANTPLUS_JEV_ENABLED", "false").lower() in ("1", "true", "yes", "on"),
            provider=provider if provider in PROVIDERS else "typesafe_direct",
            model=flag("QUANTPLUS_JEV_MODEL", "jev-1.14.0"),
            max_requests_per_day=int(flag("QUANTPLUS_JEV_MAX_REQUESTS_PER_DAY", "10")),
            max_spend_usd_per_day=float(flag("QUANTPLUS_JEV_MAX_SPEND_USD_PER_DAY", "0.25")),
            timeout_s=float(flag("QUANTPLUS_JEV_TIMEOUT_S", "20")),
            base_url_override=flag("QUANTPLUS_JEV_BASE_URL", ""),
        )


_UNAVAILABLE = "UNAVAILABLE"
_INVALID = "INVALID"
_NEEDS_REVIEW = "NEEDS_REVIEW"
_VALID = "VALID"


class JevProviderAdapter:
    """Classifies IssuerEventEvidence via SystemOne; never trades, never invents.

    The adapter returns an EventClassification for EVERY call path (success,
    refusal or failure) — failures become typed UNAVAILABLE/INVALID/NEEDS_REVIEW
    statuses, never a favourable default.
    """

    def __init__(
        self,
        config: JevConfig,
        transport: SystemOneTransport | None = None,
        env: dict | None = None,
        clock: Callable[[], float] = _time.time,
        sleeper: Callable[[float], None] = _time.sleep,
        meter: UsageMeter | None = None,
        breaker: CircuitBreaker | None = None,
        allowed_issuers: frozenset[str] | None = None,
    ):
        self.config = config
        self.env = dict(os.environ if env is None else env)
        self.transport = transport if transport is not None else UrllibSystemOneTransport()
        self.clock = clock
        self.sleeper = sleeper
        self.meter = meter if meter is not None else UsageMeter()
        self.breaker = breaker if breaker is not None else CircuitBreaker()
        self.allowed_issuers = allowed_issuers   # optional strict issuer allowlist
        self.provider_settings = PROVIDER_SETTINGS[config.provider]
        self._rubric = build_questions()
        self._rubric_sha = rubric_sha256()

    # -- public entry point -------------------------------------------------
    def classify(self, evidence: IssuerEventEvidence) -> EventClassification:
        now = self.clock()
        requested_model = self.config.model

        if not self.config.enabled:
            return self._no_judgment(evidence, requested_model, _UNAVAILABLE, "PROVIDER_DISABLED")
        if not self.breaker.allow(now):
            return self._no_judgment(evidence, requested_model, _UNAVAILABLE, "CIRCUIT_OPEN")

        ev_problems = evidence_problems(evidence)
        if ev_problems:
            return self._no_judgment(evidence, requested_model, _INVALID,
                                     "EVIDENCE_INVALID:" + ";".join(ev_problems))
        if self.allowed_issuers is not None \
                and evidence.canonical_issuer.upper() not in self.allowed_issuers:
            return self._no_judgment(evidence, requested_model, _INVALID, "WRONG_ISSUER")
        if scan_injection(evidence.excerpt_text):
            # Evidence is untrusted data: never classify an injected filing.
            return self._no_judgment(evidence, requested_model, _NEEDS_REVIEW,
                                     "INJECTION_SUSPECTED")

        usage_today = self.meter.snapshot(self.config.provider, now)
        if usage_today["requests"] >= self.config.max_requests_per_day:
            return self._no_judgment(evidence, requested_model, _UNAVAILABLE,
                                     "BUDGET_EXHAUSTED:requests_per_day")
        settings = self.provider_settings
        projected = usage_today["cost_usd"]
        if projected >= self.config.max_spend_usd_per_day:
            return self._no_judgment(evidence, requested_model, _UNAVAILABLE,
                                     "BUDGET_EXHAUSTED:spend_per_day")

        if requested_model not in settings["callable_models"]:
            return self._no_judgment(evidence, requested_model, _INVALID,
                                     f"MODEL_NOT_CALLABLE:{requested_model}")

        body = self._build_body(evidence)
        body_bytes = json.dumps(body, sort_keys=True,
                                separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        if len(body_bytes) > MAX_BODY_BYTES:
            return self._no_judgment(evidence, requested_model, _INVALID,
                                     "REQUEST_TOO_LARGE")
        request_sha = hashlib.sha256(body_bytes).hexdigest()

        try:
            status, raw = self._send(body_bytes)
        except TransportError as exc:
            self.breaker.record_hard_failure(now)
            return self._no_judgment(evidence, requested_model, _UNAVAILABLE,
                                     f"TRANSPORT_FAILURE:{exc.summary}",
                                     request_sha=request_sha)
        raw_sha = hashlib.sha256(raw).hexdigest()
        if len(raw) > MAX_RESPONSE_BYTES:
            return self._no_judgment(evidence, requested_model, _NEEDS_REVIEW,
                                     "RESPONSE_TOO_LARGE", request_sha, raw_sha)
        if status != 200:
            self.breaker.record_hard_failure(now)
            reason = self._http_reason(status, raw)
            cls_status = _UNAVAILABLE if status in (429, 500, 502, 503, 504, 529) or status >= 500 \
                else _INVALID
            return self._no_judgment(
                evidence, requested_model, cls_status, reason,
                request_sha=request_sha, raw_sha=raw_sha)

        try:
            payload = _rejecting_loads(raw)
        except (ValueError, UnicodeDecodeError):
            self.breaker.record_hard_failure(now)
            return self._no_judgment(evidence, requested_model, _INVALID,
                                     "RESPONSE_MALFORMED", request_sha, raw_sha)

        parsed, problems = validate_systemone_response(
            self._rubric, payload, settings["returned_models"])
        if problems:
            # Any contract violation is INVALID: missing/extra answers, wrong
            # types, unknown options, bad distributions, NaN, model mismatch.
            self.breaker.record_hard_failure(now)
            return self._no_judgment(evidence, requested_model, _INVALID,
                                     "RESPONSE_INVALID:" + ";".join(problems),
                                     request_sha, raw_sha)

        returned_model = parsed["model"]
        self.breaker.record_success()
        in_tokens = int(parsed.get("input_tokens", 0))
        out_tokens = int(parsed.get("output_tokens", 0))
        cost = in_tokens * settings["input_price_usd_per_token"] \
            + out_tokens * settings["output_price_usd_per_token"]
        self.meter.record(self.config.provider, now, in_tokens, out_tokens, cost)

        event_type_answer = parsed["event_type"]
        guidance = parsed["explicit_guidance_change"]
        materiality = parsed["materiality"]
        status = _VALID
        reasons: list[str] = []
        if event_type_answer["confidence"] < REVIEW_CONFIDENCE_THRESHOLD \
                or materiality["confidence"] < REVIEW_CONFIDENCE_THRESHOLD:
            status = _NEEDS_REVIEW
            reasons.append("LOW_CONFIDENCE")
        return EventClassification(
            event_uid=evidence.event_uid,
            event_id=evidence.event_id,
            provider=self.config.provider,
            model_id=returned_model,
            requested_model=requested_model,
            rubric_sha256=self._rubric_sha,
            request_payload_sha256=request_sha,
            raw_response_sha256=raw_sha,
            status=status,
            status_reason=";".join(reasons) if reasons else None,
            event_type=event_type_answer["choice"],
            event_type_probabilities=event_type_answer["probabilities"],
            event_type_confidence=event_type_answer["confidence"],
            explicit_guidance_change=guidance,
            materiality_score=materiality["score"],
            materiality_confidence=materiality["confidence"],
            materiality_probabilities=materiality["probabilities"],
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            cost_estimate_usd=cost,
        )

    # -- internals -----------------------------------------------------------
    def _build_body(self, evidence: IssuerEventEvidence) -> dict:
        return {
            "model": self.config.model,
            "state": {
                "issuer": evidence.canonical_issuer,
                "ticker": evidence.ticker,
                "document_id": evidence.document_id,
                "official_excerpt": evidence.excerpt_text,
                "available_at": evidence.available_at,
            },
            "questions": self._rubric,
        }

    def _send(self, body_bytes: bytes) -> tuple[int, bytes]:
        settings = self.provider_settings
        if self.config.base_url_override:
            base = self.config.base_url_override.rstrip("/")
        else:
            base = settings["hosts"][0]
        if base not in settings["hosts"]:
            # Raised before any network activity; no key ever leaves the allowlist.
            raise TransportError(f"host_not_in_allowlist:{base}")
        key = self.env.get(settings["key_env"], "").strip() if settings["key_env"] else ""
        if settings["key_env"] and not key:
            raise TransportError(f"missing_secret:{settings['key_env']}")
        url = base + ENDPOINT_PATH
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if key:
            headers["Authorization"] = "Bearer " + key
        attempt = 0
        while True:
            status, raw = self.transport.post(url, headers, body_bytes, self.config.timeout_s)
            if status == 200:
                return status, raw
            if status == 429 and attempt < MAX_RETRIES:
                retry_after = _parse_retry_after(raw)
                self.sleeper(min(retry_after, 5.0))
                attempt += 1
                continue
            if status in (500, 502, 503, 504, 529) and attempt < MAX_RETRIES:
                self.sleeper(0.05)
                attempt += 1
                continue
            return status, raw

    def _http_reason(self, status: int, raw: bytes) -> str:
        summary = "no_body" if not raw else raw[:200].decode("utf-8", "replace")
        summary = _sanitize(summary)
        return f"HTTP_{status}:{summary}"

    def _no_judgment(self, evidence, requested_model, status, reason,
                     request_sha: str = "", raw_sha: str = "") -> EventClassification:
        return EventClassification(
            event_uid=evidence.event_uid,
            event_id=evidence.event_id,
            provider=self.config.provider,
            model_id=requested_model,
            requested_model=requested_model,
            rubric_sha256=self._rubric_sha,
            request_payload_sha256=request_sha,
            raw_response_sha256=raw_sha,
            status=status,
            status_reason=reason,
        )


def _parse_retry_after(raw: bytes) -> float:
    try:
        payload = json.loads(raw.decode("utf-8", "replace"))
        value = payload.get("retry_after") or payload.get("retryAfter")
        return float(value)
    except Exception:  # noqa: BLE001
        return 1.0


_SECRET_PATTERNS = ("Bearer ", "xpl_", "sk_", "api_key", "apikey", "authorization")
_SECRET_PREFIXES = ("xpl_", "sk_", "cc_", "dahl", "kclm")


def _sanitize(text: str) -> str:
    """Strip anything that could carry a credential out of error summaries."""
    lowered = text.lower()
    for token in _SECRET_PATTERNS:
        if token.lower() in lowered:
            return "[redacted]"
    for prefix in _SECRET_PREFIXES:
        start = 0
        while True:
            index = text.find(prefix, start)
            if index < 0:
                break
            end = index + len(prefix)
            while end < len(text) and (text[end].isalnum() or text[end] in "-_."):
                end += 1
            text = text[:index] + "[redacted]" + text[end:]
            start = index + len("[redacted]")
    return text
