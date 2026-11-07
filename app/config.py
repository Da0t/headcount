"""Runtime settings, read from environment variables (and .env if python-dotenv is installed)."""
from __future__ import annotations

import os
from dataclasses import dataclass, fields, replace

try:  # optional
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass


def _flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass
class Settings:
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    gemini_timeout: float = 6.0

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_api_key_sid: str = ""  # optional SK... key, used with its secret instead of the auth token for REST calls
    twilio_api_key_secret: str = ""
    twilio_from_number: str = ""
    public_base_url: str = ""
    twilio_validate: bool = True
    send_sms: bool = True

    phones_file: str = "residents_phones.json"
    stagger: float = 2.0
    ring_timeout: float = 20.0
    retry_gap: float = 15.0
    max_attempts: int = 3
    autopilot: bool = True

    @property
    def twilio_api_key_ready(self) -> bool:
        return bool(self.twilio_api_key_sid and self.twilio_api_key_secret)

    @property
    def twilio_ready(self) -> bool:
        creds = bool(self.twilio_auth_token) or self.twilio_api_key_ready
        return all([self.twilio_account_sid, creds, self.twilio_from_number, self.public_base_url])

    @property
    def gemini_ready(self) -> bool:
        return bool(self.gemini_api_key)


def load_settings(**overrides) -> Settings:
    """Build Settings from the environment. Keyword overrides win (tests use them to shrink timers)."""
    s = Settings(
        gemini_api_key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "",
        gemini_model=os.getenv("GEMINI_MODEL") or "gemini-3.8-flash",
        gemini_timeout=_float("HEADCOUNT_GEMINI_TIMEOUT", 6.0),
        twilio_account_sid=os.getenv("TWILIO_ACCOUNT_SID", ""),
        twilio_auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
        twilio_api_key_sid=os.getenv("TWILIO_API_KEY_SID", ""),
        twilio_api_key_secret=os.getenv("TWILIO_API_KEY_SECRET", ""),
        twilio_from_number=os.getenv("TWILIO_FROM_NUMBER", ""),
        public_base_url=os.getenv("PUBLIC_BASE_URL", "").rstrip("/"),
        twilio_validate=_flag("TWILIO_VALIDATE", "1"),
        send_sms=_flag("HEADCOUNT_SEND_SMS", "1"),
        phones_file=os.getenv("HEADCOUNT_PHONES", "residents_phones.json"),
        stagger=_float("HEADCOUNT_STAGGER", 2.0),
        ring_timeout=_float("HEADCOUNT_RING_TIMEOUT", 20.0),
        retry_gap=_float("HEADCOUNT_RETRY_GAP", 15.0),
        max_attempts=int(_float("HEADCOUNT_MAX_ATTEMPTS", 3)),
        autopilot=_flag("HEADCOUNT_AUTOPILOT", "1"),
    )
    valid = {f.name for f in fields(Settings)}
    unknown = set(overrides) - valid
    if unknown:
        raise TypeError(f"unknown settings: {sorted(unknown)}")
    return replace(s, **overrides)
