"""Server configuration, resolved from environment variables.

This is intentionally a pure, side-effect-free dataclass with a ``from_env``
constructor. The original server validated config and logged in to Umami at module
import time, which crashed on import when env vars were missing and made the code
hard to test. Here, nothing happens until the client is actually built.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass


class ConfigError(RuntimeError):
    """Raised when the environment is missing required configuration."""


@dataclass(frozen=True)
class Settings:
    """Resolved Umami connection settings.

    Authentication is either:
      * an API key (Umami Cloud / newer self-hosted), sent as ``x-umami-api-key``, or
      * a username + password, exchanged for a bearer token via ``/api/auth/login``.
    """

    api_url: str
    api_key: str | None = None
    username: str | None = None
    password: str | None = None
    team_id: str | None = None
    timeout: float = 30.0

    @property
    def uses_api_key(self) -> bool:
        return bool(self.api_key)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        """Build settings from a mapping (defaults to ``os.environ``).

        Raises:
            ConfigError: If ``UMAMI_API_URL`` is missing, or neither an API key nor a
                username/password pair is provided.
        """
        env = os.environ if env is None else env

        api_url = (env.get("UMAMI_API_URL") or "").strip()
        if not api_url:
            raise ConfigError("UMAMI_API_URL is required (your Umami base URL).")

        api_key = (env.get("UMAMI_API_KEY") or "").strip() or None
        username = (env.get("UMAMI_USERNAME") or "").strip() or None
        password = env.get("UMAMI_PASSWORD") or None
        team_id = (env.get("UMAMI_TEAM_ID") or "").strip() or None

        if not api_key and not (username and password):
            raise ConfigError(
                "Provide either UMAMI_API_KEY, or both UMAMI_USERNAME and "
                "UMAMI_PASSWORD."
            )

        timeout = _parse_timeout(env.get("UMAMI_TIMEOUT"))

        return cls(
            api_url=api_url.rstrip("/"),
            api_key=api_key,
            username=username,
            password=password,
            team_id=team_id,
            timeout=timeout,
        )


def _parse_timeout(raw: str | None, default: float = 30.0) -> float:
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"UMAMI_TIMEOUT must be a number, got {raw!r}.") from exc
    if value <= 0:
        raise ConfigError("UMAMI_TIMEOUT must be positive.")
    return value
