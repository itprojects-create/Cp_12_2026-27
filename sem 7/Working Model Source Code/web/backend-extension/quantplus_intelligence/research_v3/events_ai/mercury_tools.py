"""Bounded Mercury-3 research integration (W4.3): a deterministic dispatcher for
safe research calls plus a strict, fail-closed chat client for cited memos.

Hard boundaries (blueprint §10.4):
- Mercury NEVER gets shell execution, raw SQL writes, arbitrary URLs, network
  fetch, secrets, self-generated P&L or order tools. It can only REQUEST a
  research tool from a frozen allowlist; the dispatcher validates the request
  schema, executes ONLY the deterministic W2/W3 functions, and returns a typed
  envelope whose numbers come from those tools — never from the model.
- Every dispatch is schema-valid, budgeted, idempotent (same idempotency_key
  returns the same cached envelope) and logged with source/config versions.
- Jev NEEDS_REVIEW or evidence conflicts may route here for a cited memo, but
  a memo can never override source fact checks or reclassify anything.
- Fail-closed: dispatcher disabled or budget exhausted → REFUSED; chat client
  disabled/key missing → MercuryUnavailable (PROVIDER_UNAVAILABLE), never a
  silent substitution by another model.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Protocol

DISPATCHER_VERSION = "events_ai_mercury_dispatcher/1"
MEMO_PROMPT_VERSION = "events_ai_mercury_prompt/1"
MAX_CALLS_PER_SESSION = 8

# Frozen allowlist: name -> {kind, args schema (name -> validator id)}
TOOL_SPECS: dict[str, dict] = {
    "lab.run_backtest": {"kind": "research", "args": {"spec_fingerprint": "sha256"}},
    "lab.run_sweep": {"kind": "research",
                      "args": {"spec_fingerprint": "sha256", "grid_name": "enum:default"}},
    "lab.challenge_finding": {"kind": "research", "args": {"result_ref": "result_id"}},
    "lab.research_journal_status": {"kind": "read", "args": {}},
}

UNSAFE_ARG_PATTERN = re.compile(
    r"(\.\./|\\\\|/etc/|select\s|insert\s|update\s|delete\s|drop\s|import\s|"
    r"eval\(|exec\(|__|;\s*|\bopen\(|\bsocket\b|\bsubprocess\b|\bpopen\b)", re.I)

_UNSAFE_TOOL_CHARS = re.compile(r"[^a-z0-9_.]")


class DispatcherRefused(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class DispatcherConfig:
    enabled: bool = False
    max_calls_per_session: int = MAX_CALLS_PER_SESSION

    @classmethod
    def from_env(cls, env: dict | None = None) -> "DispatcherConfig":
        env = dict(os.environ if env is None else env)
        return cls(
            enabled=str(env.get("QUANTPLUS_MERCURY_RESEARCH_ENABLED", "false")).lower()
            in ("1", "true", "yes", "on"),
        )


class ResearchToolDispatcher:
    """Validates + executes allowlisted research tool requests deterministically.

    ``executors`` maps allowlisted tool name -> callable(args_dict) -> dict.
    In production these are thin wrappers over W2 ``lab.run_backtest`` /
    ``run_sweep`` / ``challenge_finding`` / ``research_journal_status`` — the
    same deterministic engines, never model-generated numbers.
    """

    def __init__(self, executors: dict[str, Callable[[dict], dict]],
                 config: DispatcherConfig | None = None):
        self.executors = dict(executors)
        self.config = config if config is not None else DispatcherConfig()
        self._calls = 0
        self._cache: dict[str, dict] = {}

    def handle(self, request_json: dict) -> dict:
        envelope = {
            "dispatcher_version": DISPATCHER_VERSION,
            "tool": None,
            "idempotency_key": None,
            "status": None,
            "refusal_reason": None,
            "result": None,
            "result_sha256": None,
            "produced_by": None,
        }
        try:
            tool = request_json.get("tool")
            if not isinstance(tool, str) or _UNSAFE_TOOL_CHARS.search(tool):
                raise DispatcherRefused("REFUSED_UNKNOWN_TOOL")
            if tool not in TOOL_SPECS:
                raise DispatcherRefused("REFUSED_NOT_IN_ALLOWLIST")
            envelope["tool"] = tool
            idem = request_json.get("idempotency_key")
            if not isinstance(idem, str) or not (8 <= len(idem) <= 64) \
                    or not re.fullmatch(r"[A-Za-z0-9_\-]+", idem):
                raise DispatcherRefused("REFUSED_IDEMPOTENCY_KEY")
            envelope["idempotency_key"] = idem
            if idem in self._cache:
                return self._cache[idem]
            if not self.config.enabled:
                raise DispatcherRefused("REFUSED_DISPATCHER_DISABLED")
            if self._calls >= self.config.max_calls_per_session:
                raise DispatcherRefused("REFUSED_BUDGET_EXHAUSTED")

            spec = TOOL_SPECS[tool]
            args = request_json.get("args")
            if not isinstance(args, dict) or set(args.keys()) != set(spec["args"].keys()):
                raise DispatcherRefused("REFUSED_INVALID_ARGS_SCHEMA")
            # Unsafe-argument scan FIRST: a malformed value that also looks
            # like an injection/SQL/path is reported as unsafe, not invalid.
            for value in args.values():
                if isinstance(value, str) and UNSAFE_ARG_PATTERN.search(value):
                    bad = [name for name, v in args.items() if v == value]
                    raise DispatcherRefused(f"REFUSED_UNSAFE_ARG:{bad[0]}")
            for name, validator in spec["args"].items():
                value = args.get(name)
                if validator == "sha256":
                    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
                        raise DispatcherRefused(f"REFUSED_INVALID_ARGS:{name}")
                elif validator == "enum:default":
                    if value != "default":
                        raise DispatcherRefused(f"REFUSED_INVALID_ARGS:{name}")
                elif validator == "result_id":
                    if not isinstance(value, str) or not re.fullmatch(
                            r"[0-9a-f]{64}(:[0-9]+)?", value):
                        raise DispatcherRefused(f"REFUSED_INVALID_ARGS:{name}")
                if isinstance(value, str) and UNSAFE_ARG_PATTERN.search(value):
                    raise DispatcherRefused(f"REFUSED_UNSAFE_ARG:{name}")
            if tool not in self.executors:
                raise DispatcherRefused("REFUSED_EXECUTOR_UNBOUND")
            self._calls += 1
            try:
                result = self.executors[tool](args)
            except DispatcherRefused:
                raise
            except Exception as exc:  # noqa: BLE001 — typed, sanitized
                envelope["status"] = "ERROR"
                envelope["refusal_reason"] = f"EXECUTOR_ERROR:{type(exc).__name__}"
                envelope["produced_by"] = "deterministic:" + tool
                self._cache[idem] = envelope
                return envelope
            envelope["status"] = "OK"
            envelope["result"] = result
            envelope["result_sha256"] = hashlib.sha256(
                json.dumps(result, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=True, allow_nan=False).encode("utf-8")).hexdigest()
            envelope["produced_by"] = "deterministic:" + tool
        except DispatcherRefused as refused:
            envelope["status"] = "REFUSED"
            envelope["refusal_reason"] = refused.reason
        if envelope["idempotency_key"] is not None:
            self._cache[envelope["idempotency_key"]] = envelope
        return envelope


# -- Mercury chat client ------------------------------------------------------
MERCURY_PROVIDERS = {
    "inceptionlabs_direct": {
        "host": "https://api.inceptionlabs.ai",
        "key_env": "INCEPTION_API_KEY",
        "model_env": "INCEPTION_MODEL",
        "default_model": "mercury-3",
    },
}


class MercuryUnavailable(Exception):
    """Typed, sanitized: provider off / key missing / transport failure."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class MercuryChatTransport(Protocol):
    def chat(self, url: str, headers: dict[str, str], body: bytes, timeout_s: float
             ) -> tuple[int, bytes]: ...


class UrllibMercuryTransport:
    def chat(self, url, headers, body, timeout_s):
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()
        except Exception as exc:  # noqa: BLE001
            raise MercuryUnavailable(f"transport_failure:{type(exc).__name__}") from None


MEMO_SYSTEM_PROMPT = (
    "You are a research memo writer inside a quantitative research system. "
    "You receive one deterministic tool result (JSON) and write a short memo. "
    "Rules: cite ONLY numbers that appear verbatim in the tool result; never "
    "add your own estimates, prices, returns or recommendations; never give "
    "trading instructions; if the result is a refusal or a DATA_BLOCKED state, "
    "say so plainly. Research only."
)

_NUMBER_PATTERN = re.compile(r"-?\d+\.\d+|-?\d{2,}")


@dataclass(frozen=True)
class ResearchMemo:
    model_id: str
    prompt_version: str
    content_sha256: str
    grounded: bool
    grounding_problems: list[str]
    content_length: int


class MercuryResearchClient:
    """OpenAI-compatible chat client for ONE pinned model, fail-closed."""

    def __init__(self, provider: str = "inceptionlabs_direct",
                 transport: MercuryChatTransport | None = None,
                 env: dict | None = None, timeout_s: float = 30.0,
                 max_tokens: int = 512, clock: Callable[[], float] = time.time):
        if provider not in MERCURY_PROVIDERS:
            raise MercuryUnavailable(f"unknown_provider:{provider}")
        self.provider = MERCURY_PROVIDERS[provider]
        self.transport = transport if transport is not None else UrllibMercuryTransport()
        self.env = dict(os.environ if env is None else env)
        self.timeout_s = timeout_s
        self.max_tokens = max_tokens
        self.model = self.env.get(self.provider["model_env"], "") or self.provider["default_model"]

    def request_memo(self, tool_envelope: dict) -> ResearchMemo:
        key = self.env.get(self.provider["key_env"], "").strip()
        if not key:
            raise MercuryUnavailable("missing_secret:" + self.provider["key_env"])
        payload = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": MEMO_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(tool_envelope, sort_keys=True,
                                                       separators=(",", ":"),
                                                       ensure_ascii=True)},
            ],
            "max_tokens": self.max_tokens,
        }, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        url = self.provider["host"] + "/v1/chat/completions"
        headers = {"Authorization": "Bearer " + key,
                   "Content-Type": "application/json", "Accept": "application/json"}
        status, raw = self.transport.chat(url, headers, payload, self.timeout_s)
        if status != 200:
            raise MercuryUnavailable(f"HTTP_{status}")
        try:
            data = json.loads(raw.decode("utf-8", "replace"))
        except (ValueError, UnicodeDecodeError):
            raise MercuryUnavailable("RESPONSE_MALFORMED") from None
        returned_model = data.get("model")
        content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        if returned_model != self.model:
            # Pinned model discipline: record the mismatch, never substitute.
            problems = [f"MODEL_MISMATCH:{returned_model}"]
            return self._memo(content, [problems[0]] + self._grounding(content, tool_envelope))
        return self._memo(content, self._grounding(content, tool_envelope))

    def _grounding(self, content: str, tool_envelope: dict) -> list[str]:
        """Every multi-digit number in the memo must exist in the tool result."""
        problems = []
        result_json = json.dumps(tool_envelope.get("result"), sort_keys=True,
                                 separators=(",", ":"), ensure_ascii=True, allow_nan=False)
        for token in _NUMBER_PATTERN.findall(content or ""):
            if token not in result_json:
                problems.append(f"UNGROUND_NUMBER:{token}")
        return problems

    def _memo(self, content: str, problems: list[str]) -> ResearchMemo:
        return ResearchMemo(
            model_id=self.model,
            prompt_version=MEMO_PROMPT_VERSION,
            content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            grounded=not problems,
            grounding_problems=problems,
            content_length=len(content),
        )
