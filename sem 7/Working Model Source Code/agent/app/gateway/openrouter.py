"""Standalone OpenRouter gateway for probes and compatibility tools.

The main prediction graph uses the shared provider-aware gateway in
``app.gateway.codecraft``. This module keeps a standalone interface for probes
and scripts that explicitly select OpenRouter. Its interface mirrors
app.gateway.codecraft.Gateway.complete_json so scripts can swap providers with
--provider openrouter without touching agent logic, prompts, or frozen gates.

Model choice is env-driven; defaults are the free tier validated against the v5.1
BROKEN canary 2026-09-19 (deepseek-v4-flash-0731:free fires BROKEN + override=true
first try, finish=stop, schema-clean). glm-5.2:free was upstream rate-limited at
validation time; nemotron-3-super/ultra-550b also pass the canary but are slower.
nemotron-3.5-lightning:free dumps chain-of-thought and needs >4k tokens — avoided.

IMPORTANT methodology note: results produced via this gateway are NOT comparable
to CodeCraft/sonnet official numbers. Any report generated on OpenRouter models
must label the model explicitly and must NOT be presented as the v5.1 official
eval (which stays pinned to CodeCraft sonnet on the new-24 set once it recovers).

Config (env, never committed — .env is gitignored):
  OPENROUTER_API_KEY         required (OPENROUTER_KEY is a legacy alias)
  OPENROUTER_BASE_URL       default https://openrouter.ai/api/v1
  OPENROUTER_DECIDER_MODEL  default nvidia/nemotron-3-ultra-550b-a55b:free
  OPENROUTER_ANALYST_MODEL  default nvidia/nemotron-3-ultra-550b-a55b:free
  OPENROUTER_MAX_TOKENS     default 8000 (reasoning models burn budget thinking;
                            4000 truncated lightning mid-thought at validation)
"""
from __future__ import annotations
import os
import time
from datetime import date
from openai import OpenAI, APIConnectionError, APITimeoutError, APIStatusError


def _load_dotenv():
    """Minimal .env loader (no new dependency — python-dotenv isn't in requirements).

    pydantic-settings reads .env itself for CodeCraft config; this module uses
    os.getenv directly so it needs the same file loaded into the environment.
    Looks in CWD first, then the agent-service dir above this file.
    """
    seen = set()
    for cand in (os.path.join(os.getcwd(), ".env"),
                 os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
                     os.path.abspath(__file__)))), ".env")):
        if cand in seen or not os.path.isfile(cand):
            continue
        seen.add(cand)
        try:
            with open(cand, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    if k and k not in os.environ:
                        os.environ[k] = v
        except OSError:
            pass


_load_dotenv()


def _get(name: str, default: str = "") -> str:
    v = os.getenv(name, default)
    return v.strip().strip('"').strip("'")

_EXTRA_HEADERS = {
    "HTTP-Referer": "https://github.com/anomalyco/opencode",
    "X-Title": "QuantPlus v5.1 devil probe",
}


class OpenRouterGateway:
    def __init__(self):
        key = _get("OPENROUTER_API_KEY") or _get("OPENROUTER_KEY")
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY not set (see module docstring)")
        base = _get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        self.decider_model = _get("OPENROUTER_DECIDER_MODEL",
                                  "nvidia/nemotron-3-ultra-550b-a55b:free")
        self.analyst_model = _get("OPENROUTER_ANALYST_MODEL",
                                  "nvidia/nemotron-3-ultra-550b-a55b:free")
        self.max_tokens = int(_get("OPENROUTER_MAX_TOKENS", "8000") or "8000")
        self.client = OpenAI(api_key=key, base_url=base, timeout=120.0, max_retries=0)
        self.session_usage: dict[str, int] = {}
        self.day_usage: int = 0
        self.calls: list[dict] = []

    def _model_for(self, role: str) -> str:
        deciders = {"research_manager", "devils_advocate", "portfolio_manager"}
        return self.decider_model if role in deciders else self.analyst_model

    def complete_json(self, *, role: str, session_id: str, system: str, user: str) -> str:
        model = self._model_for(role)
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        last: Exception | None = None
        for attempt in range(4):
            try:
                resp = self.client.chat.completions.create(
                    model=model, messages=messages, temperature=0.15,
                    max_tokens=self.max_tokens,
                    response_format={"type": "json_object"},
                    extra_headers=_EXTRA_HEADERS)
                choice = resp.choices[0]
                msg = choice.message.content or ""
                if choice.finish_reason == "length" or not msg.strip():
                    raise RuntimeError(
                        f"LLM did not finish (finish_reason={choice.finish_reason}); "
                        f"model {model} needs a bigger OPENROUTER_MAX_TOKENS "
                        f"(current {self.max_tokens}) — raise it, don't retry blindly")
                usage = resp.usage
                tokens = ((usage.total_tokens if usage else 0)
                          or (len(str(messages)) // 4 + len(msg) // 4))
                self.session_usage[session_id] = self.session_usage.get(session_id, 0) + tokens
                self.day_usage += tokens
                self.calls.append({"session": session_id, "role": role,
                                   "model": model, "tokens": tokens})
                return msg
            except Exception as e:
                last = e
                status = getattr(e, "status_code", None)
                # 429 upstream on shared free tier: back off and retry same model.
                if status == 429 or "rate-limited" in str(e).lower():
                    time.sleep(min(15 * (attempt + 1), 60))
                    continue
                if isinstance(e, (APIConnectionError, APITimeoutError, APIStatusError)):
                    time.sleep(min(5 * (attempt + 1), 30))
                    continue
                raise
        raise last if last else RuntimeError("openrouter: no attempt made")


def get_gateway() -> OpenRouterGateway:
    """Build a fresh gateway (picks up current env — useful for tests)."""
    return OpenRouterGateway()


# Module-level singleton mirroring app.gateway.codecraft.gateway.
# Raises at import time if the OpenRouter key is missing so explicitly selected
# probe runs fail before attempting a model call.
gateway: OpenRouterGateway = OpenRouterGateway()
