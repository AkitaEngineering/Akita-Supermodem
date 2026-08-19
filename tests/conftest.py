import pytest


@pytest.fixture(autouse=True)
def _akita_temp_checkpoints(tmp_path, monkeypatch):
    monkeypatch.setenv("AKITA_CHECKPOINT_DIR", str(tmp_path / "checkpoints"))
