"""
DispatchResolve AI — Application Configuration.

Centralized, validated, environment-aware settings for:

- Application identity and runtime environment
- HTTP server and CORS security
- Database connectivity
- Authentication and token security
- Gnani Prisma Speech-to-Text
- Gnani Timbre Text-to-Speech
- AI reasoning provider configuration
- Audio upload restrictions
- Operational SLA and escalation policies
- External API resilience
- Observability and logging

Security principles:
1. Never hardcode credentials.
2. Never expose secrets in logs or API responses.
3. Fail closed for unsafe production configurations.
4. Allow local development without real API credentials.
5. Keep external integrations disabled until configured.
"""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import (
    Field,
    SecretStr,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)

# ============================================================
# PROJECT PATHS
# ============================================================

BACKEND_ROOT = Path(__file__).resolve().parents[2]

PROJECT_ROOT = BACKEND_ROOT.parent

ENV_FILE = BACKEND_ROOT / ".env"

DEFAULT_DATABASE_PATH = BACKEND_ROOT / "dispatchresolve.db"


# ============================================================
# SUPPORTED CONFIGURATION TYPES
# ============================================================

Environment = Literal[
    "development",
    "testing",
    "staging",
    "production",
]

LogLevel = Literal[
    "DEBUG",
    "INFO",
    "WARNING",
    "ERROR",
    "CRITICAL",
]

ReasoningProvider = Literal[
    "disabled",
    "rules",
    "openai_compatible",
]

PositiveSeconds = Annotated[
    int,
    Field(ge=1, le=300),
]


# ============================================================
# MAIN SETTINGS CLASS
# ============================================================


class Settings(BaseSettings):
    """
    Validated application configuration.

    Environment variables override defaults.

    Secrets are represented using Pydantic SecretStr.

    Settings are immutable after initialization to prevent
    accidental runtime changes.
    """

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
        validate_default=True,
        frozen=True,
        secrets_dir=None,
    )

    # --------------------------------------------------------
    # APPLICATION IDENTITY
    # --------------------------------------------------------

    APP_NAME: str = "DispatchResolve AI"

    APP_VERSION: str = "0.1.0"

    APP_DESCRIPTION: str = (
        "Multilingual AI-powered courier exception management and verified resolution platform."
    )

    APP_ENV: Environment = "development"

    DEBUG: bool = False

    API_V1_PREFIX: str = "/api/v1"

    # --------------------------------------------------------
    # HTTP SERVER
    # --------------------------------------------------------

    HOST: str = "127.0.0.1"

    PORT: int = Field(
        default=8000,
        ge=1,
        le=65535,
    )

    ALLOWED_HOSTS: list[str] = Field(
        default_factory=lambda: [
            "localhost",
            "127.0.0.1",
        ]
    )

    CORS_ORIGINS: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]
    )

    CORS_ALLOW_CREDENTIALS: bool = False

    # --------------------------------------------------------
    # DATABASE
    # --------------------------------------------------------

    DATABASE_URL: str = Field(default=f"sqlite:///{DEFAULT_DATABASE_PATH}")

    DATABASE_ECHO: bool = False

    DATABASE_POOL_SIZE: int = Field(
        default=10,
        ge=1,
        le=100,
    )

    DATABASE_MAX_OVERFLOW: int = Field(
        default=20,
        ge=0,
        le=100,
    )

    DATABASE_POOL_TIMEOUT: PositiveSeconds = 30

    # --------------------------------------------------------
    # AUTHENTICATION
    # --------------------------------------------------------

    JWT_SECRET_KEY: SecretStr | None = None

    JWT_ALGORITHM: Literal["HS256", "HS384", "HS512"] = "HS256"

    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=30,
        ge=1,
        le=1440,
    )

    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(
        default=7,
        ge=1,
        le=30,
    )

    PASSWORD_MIN_LENGTH: int = Field(
        default=12,
        ge=8,
        le=128,
    )

    # --------------------------------------------------------
    # GNANI AI — CREDENTIALS
    # --------------------------------------------------------

    GNANI_API_KEY: SecretStr | None = None

    GNANI_STT_API_KEY: SecretStr | None = None

    GNANI_TTS_API_KEY: SecretStr | None = None

    # These endpoints must come from official Gnani docs.
    # Never guess production endpoint URLs.

    GNANI_STT_ENDPOINT: str | None = None

    GNANI_TTS_ENDPOINT: str | None = None

    GNANI_STT_MODEL: str | None = None

    GNANI_TTS_MODEL: str | None = None

    GNANI_STT_LANGUAGE: str = "auto"

    GNANI_TTS_LANGUAGE: str = "hi-IN"

    GNANI_TTS_VOICE: str | None = None

    GNANI_TIMEOUT_SECONDS: PositiveSeconds = 45

    GNANI_MAX_RETRIES: int = Field(
        default=2,
        ge=0,
        le=5,
    )

    GNANI_RETRY_BASE_SECONDS: float = Field(
        default=1.0,
        ge=0.1,
        le=10.0,
    )

    # --------------------------------------------------------
    # AI REASONING
    # --------------------------------------------------------

    AI_REASONING_PROVIDER: ReasoningProvider = "rules"

    AI_API_KEY: SecretStr | None = None

    AI_BASE_URL: str | None = None

    AI_MODEL_NAME: str | None = None

    AI_TEMPERATURE: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
    )

    AI_MAX_OUTPUT_TOKENS: int = Field(
        default=1024,
        ge=128,
        le=8192,
    )

    AI_REQUEST_TIMEOUT_SECONDS: PositiveSeconds = 30

    AI_ENABLE_CASE_SUMMARIES: bool = True

    AI_ENABLE_ETA_EXTRACTION: bool = True

    AI_ENABLE_ACTION_RECOMMENDATIONS: bool = True

    AI_ENABLE_CONTRADICTION_DETECTION: bool = True

    # --------------------------------------------------------
    # AUDIO SECURITY
    # --------------------------------------------------------

    MAX_AUDIO_UPLOAD_MB: int = Field(
        default=15,
        ge=1,
        le=50,
    )

    MAX_AUDIO_DURATION_SECONDS: int = Field(
        default=120,
        ge=5,
        le=600,
    )

    ALLOWED_AUDIO_MIME_TYPES: list[str] = Field(
        default_factory=lambda: [
            "audio/wav",
            "audio/x-wav",
            "audio/mpeg",
            "audio/mp4",
            "audio/webm",
            "audio/ogg",
        ]
    )

    AUDIO_STORAGE_DIR: Path = BACKEND_ROOT / "runtime" / "audio"

    STORE_RAW_AUDIO: bool = False

    # --------------------------------------------------------
    # LOGISTICS WORKFLOW
    # --------------------------------------------------------

    PICKUP_GRACE_PERIOD_MINUTES: int = Field(
        default=15,
        ge=0,
        le=240,
    )

    SLA_CHECK_INTERVAL_SECONDS: int = Field(
        default=60,
        ge=10,
        le=3600,
    )

    MAX_COMMITMENT_REVISIONS: int = Field(
        default=3,
        ge=1,
        le=20,
    )

    ESCALATION_LEVEL_1_MINUTES: int = Field(
        default=15,
        ge=1,
        le=1440,
    )

    ESCALATION_LEVEL_2_MINUTES: int = Field(
        default=60,
        ge=1,
        le=2880,
    )

    ESCALATION_LEVEL_3_MINUTES: int = Field(
        default=180,
        ge=1,
        le=4320,
    )

    REQUIRE_PICKUP_SCAN_FOR_CLOSURE: bool = True

    ENABLE_AUTOMATIC_ESCALATION: bool = True

    ENABLE_REAL_OUTBOUND_CALLS: bool = False

    ENABLE_EXTERNAL_NOTIFICATIONS: bool = False

    # --------------------------------------------------------
    # DEMONSTRATION CONTROLS
    # --------------------------------------------------------

    DEMO_MODE: bool = True

    DEMO_SEED_SHIPMENT_COUNT: int = Field(
        default=50,
        ge=1,
        le=10000,
    )

    DEMO_ALLOW_TIME_TRAVEL: bool = True

    DEMO_ALLOW_SYNTHETIC_PICKUP_SCANS: bool = True

    # --------------------------------------------------------
    # OBSERVABILITY
    # --------------------------------------------------------

    LOG_LEVEL: LogLevel = "INFO"

    LOG_JSON: bool = False

    ENABLE_REQUEST_LOGGING: bool = True

    LOG_SENSITIVE_PAYLOADS: bool = False

    ENABLE_METRICS: bool = True

    # ========================================================
    # FIELD VALIDATORS
    # ========================================================

    @field_validator(
        "CORS_ORIGINS",
        "ALLOWED_HOSTS",
        "ALLOWED_AUDIO_MIME_TYPES",
        mode="before",
    )
    @classmethod
    def parse_string_list(cls, value: object) -> object:
        """
        Accept either a JSON array or comma-separated values
        from environment variables.
        """

        if not isinstance(value, str):
            return value

        value = value.strip()

        if not value:
            return []

        if value.startswith("["):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValueError("Expected a valid JSON array.") from exc

            if not isinstance(parsed, list):
                raise ValueError("Expected a JSON array.")

            return parsed

        return [item.strip() for item in value.split(",") if item.strip()]

    @field_validator("API_V1_PREFIX")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        if not re.fullmatch(r"/[a-zA-Z0-9/_-]+", value):
            raise ValueError(
                "API prefix must start with '/' and contain only safe URL path characters."
            )

        return value.rstrip("/")

    @field_validator(
        "GNANI_STT_ENDPOINT",
        "GNANI_TTS_ENDPOINT",
        "AI_BASE_URL",
    )
    @classmethod
    def validate_external_url(
        cls,
        value: str | None,
        info: ValidationInfo,
    ) -> str | None:
        if value is None or not value.strip():
            return None

        value = value.strip()
        parsed = urlsplit(value)

        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise ValueError(
                f"{info.field_name} must be a valid "
                "HTTP(S) URL without embedded credentials "
                "or URL fragments."
            )

        if (parsed.scheme != "https") and (
            parsed.hostname
            not in {
                "localhost",
                "127.0.0.1",
                "::1",
            }
        ):
            raise ValueError("External API URLs must use HTTPS.")

        return value

    @field_validator("CORS_ORIGINS")
    @classmethod
    def validate_cors_origins(
        cls,
        value: list[str],
    ) -> list[str]:
        for origin in value:
            parsed = urlsplit(origin)

            if origin == "*":
                continue

            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
                or parsed.username is not None
                or parsed.password is not None
            ):
                raise ValueError(f"Invalid CORS origin: {origin}")

        return value

    @field_validator("DATABASE_URL")
    @classmethod
    def validate_database_url(
        cls,
        value: str,
    ) -> str:
        supported_prefixes = (
            "sqlite:///",
            "postgresql://",
            "postgresql+psycopg://",
        )

        if not value.startswith(supported_prefixes):
            raise ValueError("Supported databases are SQLite and PostgreSQL.")

        return value

    # ========================================================
    # CROSS-FIELD SECURITY VALIDATION
    # ========================================================

    @model_validator(mode="after")
    def validate_runtime_security(self) -> Settings:
        """
        Reject configurations that would create obvious
        security risks in production.
        """

        if not (
            self.ESCALATION_LEVEL_1_MINUTES
            < self.ESCALATION_LEVEL_2_MINUTES
            < self.ESCALATION_LEVEL_3_MINUTES
        ):
            raise ValueError("Escalation thresholds must be strictly increasing.")

        if (self.CORS_ALLOW_CREDENTIALS) and ("*" in self.CORS_ORIGINS):
            raise ValueError("Wildcard CORS cannot be used with credentials.")

        if self.APP_ENV == "production":
            if self.DEBUG:
                raise ValueError("DEBUG must be disabled in production.")

            if self.DEMO_MODE:
                raise ValueError("Demo mode must be disabled in production.")

            if self.DEMO_ALLOW_TIME_TRAVEL:
                raise ValueError("Simulated time must be disabled in production.")

            if self.DEMO_ALLOW_SYNTHETIC_PICKUP_SCANS:
                raise ValueError("Synthetic pickup scans must be disabled in production.")

            if self.LOG_SENSITIVE_PAYLOADS:
                raise ValueError("Sensitive payload logging is not permitted in production.")

            if "*" in self.CORS_ORIGINS:
                raise ValueError("Wildcard CORS is forbidden in production.")

            if not self.JWT_SECRET_KEY:
                raise ValueError("JWT_SECRET_KEY is required in production.")

            if len(self.JWT_SECRET_KEY.get_secret_value()) < 32:
                raise ValueError("Production JWT secret must contain at least 32 characters.")

            if not self.DATABASE_URL.startswith(
                (
                    "postgresql://",
                    "postgresql+psycopg://",
                )
            ):
                raise ValueError("Production requires PostgreSQL.")

            if not self.REQUIRE_PICKUP_SCAN_FOR_CLOSURE:
                raise ValueError("Evidence-based closure cannot be disabled in production.")

        return self

    # ========================================================
    # DERIVED PROPERTIES
    # ========================================================

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def is_development(self) -> bool:
        return self.APP_ENV == "development"

    @property
    def gnani_stt_key(self) -> SecretStr | None:
        """
        Use service-specific credentials if available,
        otherwise fall back to the shared Gnani key.
        """
        return self.GNANI_STT_API_KEY or self.GNANI_API_KEY

    @property
    def gnani_tts_key(self) -> SecretStr | None:
        return self.GNANI_TTS_API_KEY or self.GNANI_API_KEY

    @property
    def gnani_stt_configured(self) -> bool:
        return bool(self.gnani_stt_key and self.GNANI_STT_ENDPOINT)

    @property
    def gnani_tts_configured(self) -> bool:
        return bool(self.gnani_tts_key and self.GNANI_TTS_ENDPOINT)

    @property
    def gnani_ready(self) -> bool:
        return self.gnani_stt_configured and self.gnani_tts_configured

    @property
    def reasoning_model_configured(self) -> bool:
        if self.AI_REASONING_PROVIDER in {
            "disabled",
            "rules",
        }:
            return True

        return bool(self.AI_API_KEY and self.AI_BASE_URL and self.AI_MODEL_NAME)

    @property
    def max_audio_upload_bytes(self) -> int:
        return self.MAX_AUDIO_UPLOAD_MB * 1024 * 1024

    # ========================================================
    # SAFE DIAGNOSTICS
    # ========================================================

    def safe_summary(self) -> dict[str, object]:
        """
        Return a restricted, non-sensitive status summary.

        Never return API keys, JWT secrets, database URLs,
        provider endpoints or full model configuration.
        """

        return {
            "app_name": self.APP_NAME,
            "version": self.APP_VERSION,
            "environment": self.APP_ENV,
            "debug": self.DEBUG,
            "demo_mode": self.DEMO_MODE,
            "gnani_stt_configured": (self.gnani_stt_configured),
            "gnani_tts_configured": (self.gnani_tts_configured),
            "reasoning_provider": (self.AI_REASONING_PROVIDER),
            "reasoning_configured": (self.reasoning_model_configured),
            "pickup_verification_required": (self.REQUIRE_PICKUP_SCAN_FOR_CLOSURE),
        }


# ============================================================
# CACHED SETTINGS FACTORY
# ============================================================


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Load settings once per process.

    This prevents repeated environment parsing.

    Tests can call get_settings.cache_clear()
    when environment overrides are needed.
    """

    settings = Settings()

    logging.getLogger(__name__).info(
        "DispatchResolve configuration loaded: environment=%s, demo_mode=%s",
        settings.APP_ENV,
        settings.DEMO_MODE,
    )

    return settings


# ============================================================
# MODULE EXPORTS
# ============================================================

__all__ = [
    "Settings",
    "get_settings",
    "BACKEND_ROOT",
    "PROJECT_ROOT",
    "ENV_FILE",
]
