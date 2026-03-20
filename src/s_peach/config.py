"""Configuration model with YAML loading and env var overrides."""

from __future__ import annotations

import os
from ipaddress import IPv4Network
from pathlib import Path
from typing import Any

import structlog
import yaml
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = structlog.get_logger()


class ServerConfig(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 7777


class KokoroConfig(BaseSettings):
    """Kokoro-82M model-specific configuration."""

    speed: float = 1.0

    @field_validator("speed")
    @classmethod
    def validate_speed(cls, v: float) -> float:
        if not (0.1 <= v <= 5.0):
            raise ValueError(
                f"Invalid speed {v}. Must be between 0.1 and 5.0."
            )
        return v


class KittenConfig(BaseSettings):
    """KittenTTS model-specific configuration."""

    speed: float = 1.0

    @field_validator("speed")
    @classmethod
    def validate_speed(cls, v: float) -> float:
        if not (0.1 <= v <= 5.0):
            raise ValueError(
                f"Invalid speed {v}. Must be between 0.1 and 5.0."
            )
        return v


class ChatterboxConfig(BaseSettings):
    """Chatterbox Turbo model-specific configuration."""

    device: str = "cpu"


class Settings(BaseSettings):
    """Main application settings.

    Priority (highest wins): env vars > YAML file > defaults.
    Env vars use S_PEACH_ prefix, nested with __ delimiter.
    """

    model_config = SettingsConfigDict(
        env_prefix="S_PEACH_",
        env_nested_delimiter="__",
    )

    server: ServerConfig = Field(default_factory=ServerConfig)
    kokoro: KokoroConfig = Field(default_factory=KokoroConfig)
    kitten: KittenConfig = Field(default_factory=KittenConfig)
    chatterbox: ChatterboxConfig = Field(default_factory=ChatterboxConfig)
    enabled_models: list[str] = Field(default=["kokoro"])
    language: str = "en"  # Global default language (ISO 639-1 code, e.g. en, fr, zh)
    queue_depth: int = 10
    queue_max_depth: int = 50
    queue_ttl: int = 60
    max_text_length: int = 1000
    tts_timeout: int = 120
    fade_ms: int = 10          # fade in/out duration in milliseconds
    trim_end_ms: int = 0      # trim this many ms from end of each clip
    silence_pad_ms: int = 300  # silence appended after each clip for DAC drain
    ip_whitelist: list[str] = Field(
        default=[
            "127.0.0.1/32",
            "172.17.0.0/24",
            "10.0.0.0/8",
            "192.168.0.0/16",
        ]
    )
    api_key: str | None = None
    log_level: str = "info"
    voices: dict[str, dict[str, str]] = Field(default_factory=dict)

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"debug", "info", "warn", "warning", "error", "critical"}
        if v.lower() not in allowed:
            raise ValueError(
                f"Invalid log_level '{v}'. Must be one of: {sorted(allowed)}"
            )
        return v.lower()

    @field_validator("ip_whitelist")
    @classmethod
    def validate_cidrs(cls, v: list[str]) -> list[str]:
        for cidr in v:
            try:
                IPv4Network(cidr, strict=False)
            except ValueError as e:
                raise ValueError(f"Invalid CIDR '{cidr}': {e}") from e
        return v

    @field_validator("queue_depth")
    @classmethod
    def validate_queue_depth(cls, v: int) -> int:
        if v < 1:
            raise ValueError("queue_depth must be >= 1")
        return v

    @field_validator("enabled_models")
    @classmethod
    def validate_enabled_models(cls, v: list[str]) -> list[str]:
        known = {"kitten-mini", "kitten-micro", "kitten-nano", "kokoro", "chatterbox-turbo", "chatterbox", "chatterbox-multi"}
        for m in v:
            if m not in known:
                raise ValueError(
                    f"Unknown model '{m}' in enabled_models. "
                    f"Known models: {sorted(known)}"
                )
        if not v:
            raise ValueError("enabled_models must not be empty")
        return v

    @model_validator(mode="after")
    def validate_queue_limits(self) -> Settings:
        if self.queue_depth > self.queue_max_depth:
            raise ValueError(
                f"queue_depth ({self.queue_depth}) cannot exceed "
                f"queue_max_depth ({self.queue_max_depth})"
            )
        return self

    @property
    def ip_networks(self) -> list[IPv4Network]:
        return [IPv4Network(cidr, strict=False) for cidr in self.ip_whitelist]


def _load_yaml(config_path: Path) -> dict[str, Any]:
    """Load YAML config file, returning its contents or empty dict."""
    if config_path.exists():
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
        return data
    return {}


def _resolve_config_path() -> Path | None:
    """Resolve config file path using priority chain.

    Resolution order:
    1. $S_PEACH_CONFIG (explicit override — error if missing)
    2. ./server.yaml (project-local, for development)
    3. ~/.config/s-peach/server.yaml (user install via XDG)
    4. None (use built-in defaults)
    """
    from s_peach.paths import config_file

    # 1. Explicit env var override
    env_path = os.environ.get("S_PEACH_CONFIG")
    if env_path is not None:
        path = Path(env_path)
        if not path.exists():
            raise FileNotFoundError(
                f"Config file not found: {env_path} "
                f"(set via S_PEACH_CONFIG env var)"
            )
        return path

    # 2. Project-local config (development mode)
    local_path = Path("server.yaml")
    if local_path.exists():
        return local_path

    # 3. XDG user config
    xdg_path = config_file()
    if xdg_path.exists():
        return xdg_path

    # 4. No config file found — use defaults
    return None


def load_settings() -> Settings:
    """Load settings: env vars (S_PEACH_*) override YAML, YAML overrides defaults."""
    resolved_path = _resolve_config_path()

    if resolved_path is not None:
        yaml_data = _load_yaml(resolved_path)
        logger.info("config_loaded", path=str(resolved_path))
    else:
        yaml_data = {}
        logger.info("config_using_defaults")

    # Build settings from defaults first, then layer YAML, then env vars win via pydantic-settings.
    # To ensure env vars beat YAML: only pass YAML values for fields that don't have an env override.
    env_prefix = "S_PEACH_"
    filtered: dict[str, Any] = {}
    for key, value in yaml_data.items():
        env_key = f"{env_prefix}{key.upper()}"
        if key in ("server", "kokoro", "kitten", "chatterbox"):
            # Handle nested: check S_PEACH_SERVER__HOST, S_PEACH_CHATTERBOX__DEVICE etc.
            if isinstance(value, dict):
                nested_prefix = f"{env_prefix}{key.upper()}__"
                has_any_override = any(
                    f"{nested_prefix}{k.upper()}" in os.environ
                    for k in value
                )
                if not has_any_override:
                    filtered[key] = value
                else:
                    # Pass only sub-keys without env overrides
                    sub = {}
                    for k, v in value.items():
                        if f"{nested_prefix}{k.upper()}" not in os.environ:
                            sub[k] = v
                    if sub:
                        filtered[key] = sub
            else:
                filtered[key] = value
        elif env_key not in os.environ:
            filtered[key] = value

    return Settings(**filtered)


def setup_logging(level: str) -> None:
    """Configure structlog with the given log level."""
    import logging

    log_level = getattr(logging, level.upper(), logging.INFO)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(exception_formatter=structlog.dev.plain_traceback),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
