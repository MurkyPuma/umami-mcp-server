"""Tests for environment-driven configuration."""

import pytest

from umami_mcp.config import ConfigError, Settings


def test_api_key_auth_is_accepted():
    settings = Settings.from_env(
        {"UMAMI_API_URL": "https://umami.test/", "UMAMI_API_KEY": "secret"}
    )
    assert settings.uses_api_key is True
    assert settings.api_key == "secret"
    # Trailing slash is normalized off so path joins are clean.
    assert settings.api_url == "https://umami.test"


def test_username_password_auth_is_accepted():
    settings = Settings.from_env(
        {
            "UMAMI_API_URL": "https://umami.test",
            "UMAMI_USERNAME": "admin",
            "UMAMI_PASSWORD": "pw",
            "UMAMI_TEAM_ID": "team-1",
        }
    )
    assert settings.uses_api_key is False
    assert settings.username == "admin"
    assert settings.team_id == "team-1"


def test_missing_url_raises():
    with pytest.raises(ConfigError):
        Settings.from_env({"UMAMI_API_KEY": "secret"})


def test_missing_auth_raises():
    # URL present but neither api key nor a full username/password pair.
    with pytest.raises(ConfigError):
        Settings.from_env({"UMAMI_API_URL": "https://umami.test", "UMAMI_USERNAME": "admin"})


def test_timeout_parsing():
    settings = Settings.from_env(
        {"UMAMI_API_URL": "https://umami.test", "UMAMI_API_KEY": "k", "UMAMI_TIMEOUT": "5"}
    )
    assert settings.timeout == 5.0


@pytest.mark.parametrize("bad", ["abc", "-1", "0"])
def test_bad_timeout_raises(bad):
    with pytest.raises(ConfigError):
        Settings.from_env(
            {"UMAMI_API_URL": "https://umami.test", "UMAMI_API_KEY": "k", "UMAMI_TIMEOUT": bad}
        )
