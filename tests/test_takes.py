import pytest

from marked import config, takes
from marked.config import Settings


@pytest.mark.parametrize("bad", ["", "C:", "D:foo", "..", "../x", "a/b", "20261008-004237-3698/..", "x" * 20])
def test_take_path_rejects_anything_but_generated_ids(bad, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TAKES_DIR", tmp_path)
    with pytest.raises(ValueError):
        takes.take_path(bad)


def test_take_path_accepts_generated_id(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TAKES_DIR", tmp_path)
    tid = takes.new_take_id()
    assert takes.take_path(tid) == tmp_path / tid


def test_settings_reject_inverted_wpm_band():
    with pytest.raises(ValueError):
        Settings(conventions_wpm_min=200, conventions_wpm_max=100)
