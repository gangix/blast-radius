from __future__ import annotations

from blast_radius.config import DEFAULT_SERVER, DataHubConfig


def test_from_env_blank_values_fall_back_to_defaults(monkeypatch):
    for var in ("DATAHUB_GMS_URL", "BLAST_RADIUS_PREFIX", "BLAST_RADIUS_PLATFORM",
                "BLAST_RADIUS_FABRIC", "DATAHUB_GMS_TOKEN"):
        monkeypatch.setenv(var, "")
    cfg = DataHubConfig.from_env()
    assert cfg.server == DEFAULT_SERVER
    assert cfg.instance_prefix == "b2fd91"
    assert cfg.platform == "snowflake"
    assert cfg.fabric == "PROD"
    assert cfg.token is None


def test_from_env_uses_provided_values(monkeypatch):
    monkeypatch.setenv("DATAHUB_GMS_URL", "https://dh.example.com")
    monkeypatch.setenv("BLAST_RADIUS_PREFIX", "acme")
    cfg = DataHubConfig.from_env()
    assert cfg.server == "https://dh.example.com"
    assert cfg.instance_prefix == "acme"
