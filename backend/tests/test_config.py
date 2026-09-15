"""Tests for settings that have parsing/derivation logic worth checking
directly, rather than just trusting os.getenv defaults."""

from taskos.config import Settings


def test_allowed_origins_defaults_to_wildcard_list():
    s = Settings(allowed_origins_raw="*")
    assert s.allowed_origins == ["*"]


def test_allowed_origins_splits_and_trims_a_comma_separated_list():
    s = Settings(allowed_origins_raw="https://a.example, https://b.example")
    assert s.allowed_origins == ["https://a.example", "https://b.example"]


def test_allowed_origins_ignores_empty_entries():
    s = Settings(allowed_origins_raw="https://a.example,,  ,")
    assert s.allowed_origins == ["https://a.example"]
