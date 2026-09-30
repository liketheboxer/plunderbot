"""Settings that come from the environment (Exocomp settings and secrets).

Everything a Quartermaster changes day to day (channels, hours, roles) lives in the
database instead, set with /admin commands, so it survives refits without a redeploy.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    discord_token: str
    data_dir: Path
    dev_guild_id: int | None
    default_timezone: str
    ready_file: Path
    log_level: str
    anthropic_api_key: str | None = None
    kagi_api_key: str | None = None
    parley_model: str = "claude-haiku-4-5"
    # The Magical Samurai's PlunderBot module (Daisho). Exocomp sets all of these at each refit once the
    # Captain has issued the module token; without the token the bot simply doesn't sync.
    samurai_url: str | None = None          # where the API is (SAMURAI_URL)
    samurai_public_url: str | None = None   # where people open the screens (SAMURAI_PUBLIC_URL)
    module_token: str | None = None         # SAMURAI_MODULE_TOKEN
    unit: str = "plunderbot"                # EXOCOMP_UNIT: the unit's short name, in the screens' address

    @property
    def db_path(self) -> Path:
        return self.data_dir / "plunderbot.db"


def _optional_int(name: str) -> int | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError as e:
        raise SystemExit(f"{name} must be a number (a Discord ID), got {raw!r}") from e


def load_dotenv(path: Path = Path(".env")) -> None:
    """For local runs: read KEY=value lines from .env without overriding real environment variables."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load() -> Config:
    load_dotenv()
    token = os.environ.get("DISCORD_TOKEN", "").strip()
    if not token:
        raise SystemExit("DISCORD_TOKEN is not set. Add it as a secret on the unit in Exocomp.")
    return Config(
        discord_token=token,
        data_dir=Path(os.environ.get("DATA_DIR", "/data")),
        dev_guild_id=_optional_int("DEV_GUILD_ID"),
        default_timezone=os.environ.get("DEFAULT_TIMEZONE", "America/Los_Angeles"),
        ready_file=Path(os.environ.get("READY_FILE", "/tmp/ready")),
        log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", "").strip() or None,
        kagi_api_key=os.environ.get("KAGI_API_KEY", "").strip() or None,
        parley_model=os.environ.get("PARLEY_MODEL", "").strip() or "claude-haiku-4-5",
        samurai_url=(os.environ.get("SAMURAI_URL", "").strip().rstrip("/") or None),
        samurai_public_url=(os.environ.get("SAMURAI_PUBLIC_URL", "").strip().rstrip("/")
                            or os.environ.get("SAMURAI_URL", "").strip().rstrip("/") or None),
        module_token=os.environ.get("SAMURAI_MODULE_TOKEN", "").strip() or None,
        unit=os.environ.get("EXOCOMP_UNIT", "").strip() or "plunderbot",
    )
