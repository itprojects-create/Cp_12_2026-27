"""Central config: LLM provider, model routing, token caps. No secrets logged."""
from __future__ import annotations
import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    CODECRAFT_KEY_1: str = ""
    CODECRAFT_KEY_2: str = ""
    CODECRAFT_KEY_3: str = ""
    CODECRAFT_KEY_4: str = ""
    CODECRAFT_KEY_5: str = ""
    CODECRAFT_BASE_URL: str = "https://codecraftapi.com/v1"
    ANALYST_MODEL: str = "deepseek-v4-pro-0813"
    DECIDER_MODEL: str = "claude-sonnet-5"
    # OpenRouter is the active prediction provider. The CodeCraft settings above
    # remain as a compatibility fallback for existing offline tools and older
    # deployments; when an OpenRouter key is present it always takes precedence.
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_KEY: str = ""  # legacy alias used by the original probe gateway
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_MODEL: str = "nvidia/nemotron-3-ultra-550b-a55b:free"
    # Inception Labs / Mercury (2026-11-01): the active prediction/chat provider.
    # OpenAI-compatible chat at api.inceptionlabs.ai/v1; Mercury 3 documents
    # structured outputs and tool calling on /v1/chat/completions and launch
    # pricing of $0.10/M input, $0.35/M output (1M context). Temperature is
    # documented adjustable in 0.5–1.0, so roles use 0.7 here instead of 0.0.
    # NOTE: "Mercury Decide" is a native /v1/decisions model, NOT chat — never
    # set it as a chat model here.
    INCEPTION_API_KEY: str = ""
    INCEPTION_BASE_URL: str = "https://api.inceptionlabs.ai/v1"
    INCEPTION_MODEL: str = "mercury-3"
    # Experiential Labs (2026-10-28): the active prediction/chat provider. Its hosted
    # gateway is OpenAI-compatible (chat-capable models) with xpl_ keys, funded by
    # platform credits (1 credit = $0.01). Takes precedence over OpenRouter, which
    # remains as a fallback lane. NOTE: gpt-6-luna-decisions is NOT usable here — it
    # is a native Decisions-API model (POST /v1/decisions), not a chat model.
    EXPLABS_API_KEY: str = ""
    EXPLABS_BASE_URL: str = "https://api.experientiallabs.ai/v1"
    EXPLABS_MODEL: str = "gpt-6-luna"
    PROMPT_VERSION: str = "m12"  # m12: evidence grounding for deciders (prereg_manager_evidence.md) — new sids
    # Direction policy: "llm" = the research pipeline chooses direction (default,
    # unchanged). "trend" = code sets direction from the PIT ^NSEI market trend and
    # the LLM only sizes/vetoes (pre-registered H1, data/prereg_v4_trend_direction.md).
    DIRECTION_POLICY: str = "llm"
    SESSION_TOKEN_CAP: int = 120000
    DAY_TOKEN_CAP: int = 3000000  # ~3% of 100M pool/day: allows one full eval (~1.2M) + dev headroom
    RATE_MIN_INTERVAL_S: float = 1.0  # self-pacing: min seconds between calls on the same key
    RATE_MAX_COOLDOWN_S: float = 300.0  # cap on honored Retry-After cooldowns
    # OpenRouter's free tier caps 50 REQUESTS/day per account (observed header
    # `x-ratelimit-limit: 50`); chat and every prediction role share one key.
    # 0 disables the local guard (e.g. a paid plan with no such daily cap).
    DAILY_REQUEST_CAP: int = 50
    # Key specialization (dashboard truth 2026-09-19): key1 (index 0) holds the funded
    # 100M pool. ALL roles prefer it; keys 2-5 are tried only as 429 fallback and are
    # quarantined on first 402 (unfunded). Deciders are pinned to key1 strictly.
    DECIDER_KEY_IDX: int = 0
    ANALYST_KEY_IDXS: list[int] = [0, 1, 2, 3, 4]
    DATABASE_URL: str = ""
    MONGO_URL: str = ""
    # Browser frontend origins allowed to call /api/v1 (comma-separated). Defaults
    # cover the common local dev servers; set FRONTEND_ORIGINS in prod. The CORS
    # regex additionally allows any localhost port (dev convenience only).
    FRONTEND_ORIGINS: str = (
        "http://localhost:3000,http://localhost:5173,"
        "http://127.0.0.1:3000,http://127.0.0.1:5173")
    # Governance migration §55: explicit authority flags. Defaults are safe —
    # the LLM research pipeline runs, but nothing LLM-originated may command
    # capital. DIRECTION_POLICY above now only selects the *research* decision
    # path; capital authority is governed by the flags below + constitution R1.
    LLM_DIRECTION_AUTHORITY: bool = False  # LLM direction has no capital authority
    LLM_MONEY_AUTHORITY: bool = False  # no LLM output commands capital, ever
    LLM_OVERLAY_ENABLED: bool = False  # production defaults to no-LLM overlay (§23)
    RESEARCH_AGENT_ENABLED: bool = True
    RESEARCH_FOUNDRY_ENABLED: bool = True
    RESEARCH_MEMORY_ENABLED: bool = True
    FALSIFICATION_REQUIRED: bool = True
    PIT_REQUIRED_FOR_PROMOTION: bool = True
    FORWARD_REQUIRED_FOR_PROMOTION: bool = True
    # Data acquisition (§70): safe defaults. Collectors never bypass access
    # controls; credentials (if ever needed) come only from environment.
    DATA_ACQUISITION_ENABLED: bool = True
    NSE_ANNOUNCEMENTS_ENABLED: bool = True
    BSE_ANNOUNCEMENTS_ENABLED: bool = True
    NSE_MARKET_EOD_ENABLED: bool = True
    NSE_DERIVATIVES_ENABLED: bool = True
    CDSL_FPI_ENABLED: bool = True
    DATA_RAW_ROOT: str = "data/raw"
    REQUEST_TIMEOUT_SECONDS: float = 30.0
    REQUEST_MIN_INTERVAL_SECONDS: float = 1.5
    ALLOW_PAID_SOURCE: bool = False
    # Server-only market credentials. Access token is the full app_id:token value.
    FYERS_ACCESS_TOKEN: str = ""
    FYERS_CLIENT_ID: str = ""
    FYERS_SECRET_KEY: str = ""
    FYERS_REDIRECT_URI: str = ""
    YAHOO_QUOTE_REFRESH_SECONDS: float = 15.0
    STOCK_PREDICTION_REFRESH_SECONDS: int = 900
    STOCK_PREDICTION_MAX_CONCURRENT: int = 2
    # Serve completed research immediately while the unchanged full graph refreshes.
    STOCK_PREDICTION_MAX_STALE_SECONDS: int = 86400
    STOCK_PREDICTION_WARM_ENABLED: bool = True
    STOCK_PREDICTION_WARM_SYMBOLS: str = "HDFCBANK,RELIANCE,TCS,INFY,ICICIBANK"
    STOCK_PREDICTION_WARM_INTERVAL_SECONDS: int = 30
    STOCK_PREDICTION_WARM_AHEAD_SECONDS: int = 300
    STOCK_PREDICTION_WARM_DAY_TOKEN_FRACTION: float = 0.5
    # Warming also spends REQUESTS from the same daily provider budget. Stop
    # warming once this share of DAILY_REQUEST_CAP is spent so foreground
    # visitors and chat keep headroom (0.6 x 50 = 30 ≈ two warmed sessions).
    STOCK_PREDICTION_WARM_DAY_REQUEST_FRACTION: float = 0.6
    # Required for website proxy requests when set; never expose via VITE_*.
    WEBSITE_API_KEY: str = ""

    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.FRONTEND_ORIGINS.split(",") if o.strip()]

    def codecraft_keys(self) -> list[str]:
        keys = [self.CODECRAFT_KEY_1, self.CODECRAFT_KEY_2, self.CODECRAFT_KEY_3,
                self.CODECRAFT_KEY_4, self.CODECRAFT_KEY_5]
        return [k for k in keys if k]

    def openrouter_key(self) -> str:
        return self.OPENROUTER_API_KEY or self.OPENROUTER_KEY

    def explabs_key(self) -> str:
        return self.EXPLABS_API_KEY

    def inception_key(self) -> str:
        return self.INCEPTION_API_KEY

    def provider_keys(self) -> list[str]:
        """Return credentials for the active prediction provider.

        Priority: Inception (Mercury) > Experiential Labs > OpenRouter > legacy
        CodeCraft pool. A configured higher-priority key must never fall back to
        stale lower-priority credentials (the same rule as the OpenRouter cutover).
        """
        if self.inception_key():
            return [self.inception_key()]
        if self.explabs_key():
            return [self.explabs_key()]
        key = self.openrouter_key()
        return [key] if key else self.codecraft_keys()

    def provider_base_url(self) -> str:
        if self.inception_key():
            return self.INCEPTION_BASE_URL
        if self.explabs_key():
            return self.EXPLABS_BASE_URL
        return self.OPENROUTER_BASE_URL if self.openrouter_key() else self.CODECRAFT_BASE_URL

    def analyst_model(self) -> str:
        if self.inception_key():
            return self.INCEPTION_MODEL
        if self.explabs_key():
            return self.EXPLABS_MODEL
        return self.OPENROUTER_MODEL if self.openrouter_key() else self.ANALYST_MODEL

    def decider_model(self) -> str:
        if self.inception_key():
            return self.INCEPTION_MODEL
        if self.explabs_key():
            return self.EXPLABS_MODEL
        return self.OPENROUTER_MODEL if self.openrouter_key() else self.DECIDER_MODEL

    def provider_name(self) -> str:
        if self.inception_key():
            return "inception"
        if self.explabs_key():
            return "experiential"
        return "openrouter" if self.openrouter_key() else "codecraft"

    def provider_temperature_offset(self) -> float:
        """Mercury 3 documents temperature 0.5–1.0; pick the low end for determinism.

        OpenRouter's 0.0 is stored as False-ish in role_config; this helper only
        overrides the temperature when the active provider is Inception.
        """
        return 0.7 if self.inception_key() else 0.0

    # Role -> (model, key_index, temperature, max_tokens)
    def role_config(self, role: str) -> dict:
        # Mercury 3 documents a 0.5–1.0 temperature range; provider_temperature_offset
        # returns 0.7 for Inception and 0.0 elsewhere, keeping legacy behavior intact.
        offset = self.provider_temperature_offset()
        deciders = {"research_manager", "devils_advocate", "portfolio_manager"}
        if role in deciders:
            # 16000: CodeCraft docs' tier for hard reasoning; v5.1 devil prompt is long
            # and sonnet hit finish=length at 8192 (empty content, crashed session).
            return {"model": self.decider_model(), "key_idx": self.DECIDER_KEY_IDX,
                    "temperature": offset or (0.0 if self.openrouter_key() else 0.15),
                    "max_tokens": 16000}
        # analysts / debate / trader / risk prefer the funded key (idx 0); the gateway
        # falls back across the rest only on 429s and quarantines 402s. See codecraft.py.
        key_map = {"technical": 0, "fundamentals": 0, "news": 0, "macro": 0, "events": 0,
                   "bull": 0, "bear": 0, "trader": 0, "risk_agg": 0, "risk_con": 0, "risk_neu": 0}
        return {"model": self.analyst_model(), "key_idx": key_map.get(role, 0),
                "temperature": offset or (0.0 if self.openrouter_key() else 0.2),
                "max_tokens": 8192}

settings = Settings()
