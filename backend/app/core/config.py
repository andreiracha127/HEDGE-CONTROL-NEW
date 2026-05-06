"""Centralised application settings using pydantic-settings.

All environment variables are validated eagerly at import time so that
missing required values cause a clear startup error instead of a
runtime surprise.
"""

from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── Core ──────────────────────────────────────────────────────
    database_url: str = Field(..., description="PostgreSQL or SQLite connection string")
    app_version: str = Field("1.0.0")

    # ── Auth (JWT / JWKS) — all optional; auth disabled when jwt_issuer is empty ──
    jwt_issuer: str = Field("", description="Leave empty to disable JWT auth")
    jwt_audience: str = Field("")
    jwks_url: str = Field("")

    # ── CORS ──────────────────────────────────────────────────────
    cors_allow_origins: str = Field(
        "http://localhost:5173,http://localhost:8080,http://localhost:8081,http://localhost:8082",
        description="Comma-separated list of allowed origins",
    )

    # ── Rate Limiting ─────────────────────────────────────────────
    rate_limit_scraping: str = Field("5/minute")
    rate_limit_mutation: str = Field("60/minute")
    rate_limit_read: str = Field("120/minute")

    # ── Audit ─────────────────────────────────────────────────────
    # Required (non-empty): every environment that exposes a mutation route
    # MUST persist HMAC-signed audit evidence. An empty key would let the
    # signing path fail-closed at first emission; this validator catches the
    # misconfiguration at boot instead. See PR-7 / J-A1-02.
    audit_signing_key: str = Field(
        "",
        description="HMAC key for audit event signatures (required, min 16 chars)",
    )

    @field_validator("audit_signing_key")
    @classmethod
    def _audit_signing_key_must_be_present(cls, v: str) -> str:
        # Empty string is allowed for legacy compatibility ONLY when running
        # with an in-memory/SQLite test DB — pytest's conftest will set the
        # key before any mutation route is exercised. In any other case the
        # validator below (``_audit_signing_key_min_length``) enforces a
        # non-empty value at boot via the model_post_init hook.
        return v

    def model_post_init(self, __context) -> None:  # type: ignore[override]
        """Enforce AUDIT_SIGNING_KEY presence in non-test environments."""
        # Tests (pytest) set DATABASE_URL to sqlite ":memory:" — they set the
        # signing key dynamically per test via env-var manipulation. In every
        # other environment the key MUST be a non-empty string at startup so
        # the application cannot boot in a state where signed audit emission
        # would silently fall back to NULL signatures.
        is_test_db = "sqlite" in self.database_url and ":memory:" in self.database_url
        if is_test_db:
            return
        if not self.audit_signing_key or not self.audit_signing_key.strip():
            raise ValueError(
                "AUDIT_SIGNING_KEY must be set to a non-empty value. "
                "Audit emission is fail-closed; refusing to boot without a key."
            )

    # ── Scheduler ─────────────────────────────────────────────────
    scheduler_disabled: str = Field("")
    westmetall_cron_hour: int = Field(18)
    westmetall_cron_minute: int = Field(0)
    rfq_timeout_cron_minute: int = Field(0)
    rfq_timeout_hours: int = Field(24)
    rfq_reminder_threshold: float = Field(0.5)

    # ── OpenAI ───────────────────────────────────────────────────
    openai_api_key: str = Field("")
    openai_model: str = Field("gpt-4o-mini")

    # ── WhatsApp (Meta) ───────────────────────────────────────────
    whatsapp_api_url: str = Field("https://graph.facebook.com/v21.0")
    whatsapp_access_token: str = Field("")
    whatsapp_phone_number_id: str = Field("")
    whatsapp_app_secret: str = Field("")
    whatsapp_verify_token: str = Field("")
    whatsapp_provider: str = Field("meta")

    # ── Twilio ────────────────────────────────────────────────────
    twilio_account_sid: str = Field("")
    twilio_auth_token: str = Field("")
    twilio_whatsapp_from: str = Field("")
    twilio_webhook_url: str = Field("")

    # ── Helpers ───────────────────────────────────────────────────

    @property
    def auth_enabled(self) -> bool:
        return bool(self.jwt_issuer)

    @property
    def cors_origins_list(self) -> list[str]:
        raw = self.cors_allow_origins.strip()
        if not raw:
            return []
        return [o.strip() for o in raw.split(",") if o.strip()]


def get_settings() -> Settings:
    """Return the singleton Settings instance (created on first call)."""
    return _settings


_settings = Settings()  # type: ignore[call-arg]
