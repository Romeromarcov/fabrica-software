"""Tests de los toggles de autonomía expuestos en /config (config_store).

Verifica que AUTO_MERGE_ENABLED / PARALLEL_FEATURES_ENABLED / FACTORY_MODIFIER_ENABLED:
- vienen en `false` por defecto (default seguro),
- se persisten en el .env del volumen (round-trip true/false),
sin tocar el entorno real (ENV_PATH redirigido a tmp_path).
"""
import pytest

import ui.config_store as cs

AUTONOMY_FLAGS = ("AUTO_MERGE_ENABLED", "PARALLEL_FEATURES_ENABLED", "FACTORY_MODIFIER_ENABLED")


@pytest.fixture
def store(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    monkeypatch.setattr(cs, "ENV_PATH", env)
    # Aislar del entorno real para que el overlay de os.environ no contamine.
    for flag in AUTONOMY_FLAGS:
        monkeypatch.delenv(flag, raising=False)
    return cs.ConfigStore()


def test_autonomy_flags_in_defaults_and_false():
    for flag in AUTONOMY_FLAGS:
        assert cs.DEFAULTS[flag] == "false"
        assert flag in cs.KNOWN_KEYS


def test_defaults_load_false(store):
    cfg = store.load(masked=False)
    for flag in AUTONOMY_FLAGS:
        assert cfg[flag] == "false"


def test_save_persists_true(store):
    store.save({f: "true" for f in AUTONOMY_FLAGS})
    cfg = store.load(masked=False)
    for flag in AUTONOMY_FLAGS:
        assert cfg[flag] == "true"
    # y queda escrito en el .env del volumen
    on_disk = cs.ENV_PATH.read_text(encoding="utf-8")
    assert "AUTO_MERGE_ENABLED=true" in on_disk


def test_save_can_toggle_back_to_false(store):
    store.save({f: "true" for f in AUTONOMY_FLAGS})
    store.save({f: "false" for f in AUTONOMY_FLAGS})
    cfg = store.load(masked=False)
    for flag in AUTONOMY_FLAGS:
        assert cfg[flag] == "false"


def test_env_file_overrides_environment(store, monkeypatch):
    # Railway inyecta false; la edición de la UI (archivo .env) gana.
    monkeypatch.setenv("AUTO_MERGE_ENABLED", "false")
    store.save({"AUTO_MERGE_ENABLED": "true"})
    assert store.load(masked=False)["AUTO_MERGE_ENABLED"] == "true"
