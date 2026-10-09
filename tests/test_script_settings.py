"""Settings carried in the script: <!-- take-two: name=value ... --> on its first line."""

import io
import json

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from take_two import app as app_mod
from take_two import config, pipeline, takes
from take_two.audio import SR
from take_two.config import ScriptSettingsError, Settings, effective_settings, script_overrides
from take_two.llm import set_llm
from take_two.llm.base import NullLLM
from take_two.marks import drill_script, parse_script
from take_two.stt.base import Transcript, Word

BODY = "## Intro [0:10]\nTrees are great and they cool the street.\n"
HEADER = "<!-- take-two: short_pause_s=0.9 conventions_enabled=true -->\n"


def test_the_script_overrides_the_request_which_overrides_the_defaults():
    requested = Settings(short_pause_s=0.5, long_pause_s=2.0)
    st, over = effective_settings(requested, HEADER + BODY)
    assert over == {"short_pause_s": 0.9, "conventions_enabled": True}
    assert st.short_pause_s == 0.9 and st.conventions_enabled  # from the script
    assert st.long_pause_s == 2.0                                 # from the request
    assert st.key_slower_pct == Settings().key_slower_pct        # default
    assert effective_settings(requested, BODY) == (requested, {})


def test_the_settings_line_is_the_first_non_blank_line_only():
    assert script_overrides("\n\n  <!-- TAKE-TWO: key_slower_pct=15 -->\n" + BODY) == {"key_slower_pct": 15.0}
    assert script_overrides("<!-- marked: key_slower_pct=15 -->\n" + BODY) == {"key_slower_pct": 15.0}  # earlier name
    assert script_overrides(BODY + HEADER) == {}  # further down it is an ordinary comment
    assert script_overrides("<!-- a note -->\n" + HEADER + BODY) == {}
    assert script_overrides("<!-- take-two: -->\n" + BODY) == {}


@pytest.mark.parametrize("line, words", [
    ("<!-- take-two: nope=1 -->", ["unknown setting", "nope", "README"]),
    ("<!-- take-two: short_pause=0.8 -->", ["unknown setting", "short_pause", "the nearest name is short_pause_s"]),
    ("<!-- take-two: short_pause_s=99 -->", ["short_pause_s", "99", "less than or equal to 5"]),
    ("<!-- take-two: baseline_min_words=4.5 -->", ["baseline_min_words", "4.5"]),
    ("<!-- take-two: conventions_enabled=maybe -->", ["conventions_enabled", "maybe"]),
    ("<!-- take-two: short_pause_s -->", ["short_pause_s", "not name=value"]),
    ("<!-- take-two: short_pause_s=0.8 short_pause_s=0.9 -->", ["short_pause_s", "twice"]),
    ("<!-- take-two: short_pause_s=0.8", ["close with -->"]),
    ("<!-- take-two: short_pause_s=0.8 --> Hello", ["nothing may follow -->"]),
    ("<!-- take-two: short_pause_s=0.8 --> <!-- a note -->", ["nothing may follow -->"]),
])
def test_a_bad_settings_line_names_the_problem(line, words):
    with pytest.raises(ScriptSettingsError) as err:
        script_overrides(line + "\n" + BODY)
    assert all(w in str(err.value) for w in words), str(err.value)


def test_values_are_checked_together_with_the_request():
    # 200 is a valid minimum on its own; it only clashes with a maximum below it.
    assert effective_settings(Settings(improv_wpm_max=250), "<!-- take-two: improv_wpm_min=200 -->\nHi.")[1] == {"improv_wpm_min": 200.0}
    with pytest.raises(ScriptSettingsError, match="improv_wpm_min must not exceed improv_wpm_max"):
        effective_settings(Settings(), "<!-- take-two: improv_wpm_min=200 -->\nHi.")


def test_the_settings_line_moves_no_line_numbers_and_keeps_the_script_key():
    assert [ln.text for ln in parse_script(HEADER + BODY).lines] == [ln.text for ln in parse_script(BODY).lines]
    assert takes.script_key(HEADER + BODY) == takes.script_key(BODY)
    assert takes.script_key("<!-- take-two: short_pause_s=0.5 -->\n" + BODY) == takes.script_key(HEADER + BODY)


def test_a_drill_keeps_the_settings_line():
    for kind in ("line", "section"):
        text, _ = drill_script(HEADER + BODY, kind, 0)
        assert text.startswith(HEADER) and script_overrides(text) == script_overrides(HEADER + BODY)


# ---- through the pipeline and the routes ----------------------------------------------------------

class Stub:
    prompts: list = []

    def transcribe(self, audio, sample_rate=16000, initial_prompt=None):
        Stub.prompts.append(initial_prompt)
        text = "Trees are great and they cool the street."
        words = [Word(w, 0.2 + 0.3 * i, 0.45 + 0.3 * i) for i, w in enumerate(text.split())]
        return Transcript(words=words, text=text, backend="stub", model="stub", device="cpu")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TAKES_DIR", tmp_path)
    monkeypatch.setattr(pipeline, "get_transcriber", lambda: Stub())
    Stub.prompts = []
    set_llm(NullLLM())
    yield TestClient(app_mod.app, base_url="http://127.0.0.1")
    set_llm(None)
    takes.QUEUED.clear()


def _wav():
    buf = io.BytesIO()
    t = np.arange(int(3 * SR)) / SR
    sf.write(buf, (0.1 * np.sin(2 * np.pi * 150 * t)).astype(np.float32), SR, format="WAV")
    return buf.getvalue()


def _post(c, script, settings=None):
    data = {"script": script}
    if settings is not None:
        data["settings"] = json.dumps(settings)
    return c.post("/api/takes", files={"audio": ("t.wav", _wav(), "audio/wav")}, data=data)


def test_the_settings_line_changes_the_speech_to_text_prompt(client):
    assert _post(client, BODY).status_code == 200
    assert _post(client, HEADER + BODY).status_code == 200
    assert Stub.prompts[0] is None and "Um" in Stub.prompts[1]  # conventions switch on the filler-keeping prompt


def test_the_analysis_records_where_each_setting_came_from(client):
    a = _post(client, HEADER + BODY, {"short_pause_s": 0.5, "long_pause_s": 2.0}).json()
    assert a["settings"]["short_pause_s"] == 0.9 and a["settings"]["long_pause_s"] == 2.0
    assert a["settings_request"]["short_pause_s"] == 0.5
    assert a["settings_from_script"] == {"short_pause_s": 0.9, "conventions_enabled": True}
    assert "conventions" in a
    # Re-analysis without the line goes back to the dialog's values, and the take keeps its history.
    b = client.post(f"/api/takes/{a['take_id']}/reanalyze",
                    json={"script": BODY, "settings": {"short_pause_s": 0.5}}).json()
    assert b["settings"]["short_pause_s"] == 0.5 and b["settings_from_script"] == {} and b["script_key"] == a["script_key"]


def test_a_bad_settings_line_is_refused_before_a_take_exists(client, tmp_path):
    r = _post(client, "<!-- take-two: short_pause=0.8 -->\n" + BODY)
    assert r.status_code == 400 and "short_pause" in r.json()["detail"]
    assert not any(tmp_path.iterdir())
    r = client.post("/api/jobs/takes", files={"audio": ("t.wav", _wav(), "audio/wav")},
                    data={"script": "<!-- take-two: key_slower_pct=500 -->\n" + BODY})
    assert r.status_code == 400 and "key_slower_pct" in r.json()["detail"]
    assert not any(tmp_path.iterdir())


def test_re_analysis_and_drills_check_the_settings_line(client):
    a = _post(client, BODY).json()
    r = client.post(f"/api/takes/{a['take_id']}/reanalyze", json={"script": "<!-- take-two: nope=1 -->\n" + BODY})
    assert r.status_code == 400 and "nope" in r.json()["detail"]
    assert takes.load_take(a["take_id"])["settings_from_script"] == {}  # the saved script is untouched
    assert (takes.take_path(a["take_id"]) / "script.md").read_text(encoding="utf-8") == BODY
    parent = _post(client, HEADER + BODY).json()
    d = client.post(f"/api/takes/{parent['take_id']}/drill", files={"audio": ("d.wav", _wav(), "audio/wav")},
                    data={"kind": "line", "index": "0"}).json()
    assert d["settings_from_script"] == {"short_pause_s": 0.9, "conventions_enabled": True}


def test_the_editor_can_ask_what_the_line_sets(client):
    r = client.post("/api/script/settings", json={"script": HEADER + BODY}).json()
    assert r == {"from_script": {"short_pause_s": 0.9, "conventions_enabled": True}, "error": None}
    r = client.post("/api/script/settings", json={"script": "<!-- take-two: nope=1 -->\n" + BODY}).json()
    assert r["from_script"] == {} and "nope" in r["error"]


def test_a_drill_is_refused_when_the_parents_line_clashes_with_its_settings(client, tmp_path):
    parent = _post(client, "<!-- take-two: improv_wpm_min=200 -->\n" + BODY, {"improv_wpm_max": 250})
    assert parent.status_code == 200, parent.text
    pid = parent.json()["take_id"]
    for url in (f"/api/takes/{pid}/drill", f"/api/jobs/drill/{pid}"):
        r = client.post(url, files={"audio": ("d.wav", _wav(), "audio/wav")}, data={"kind": "line", "index": "0"})
        assert r.status_code == 400 and "improv_wpm_min" in r.json()["detail"]
    assert takes.drills_of(pid) == [] and [p.name for p in tmp_path.iterdir()] == [pid]


def test_re_analysis_sends_the_script_without_carriage_returns(client, monkeypatch):
    a = _post(client, BODY).json()
    seen = {}

    def record(take_id, script, settings, label=None):
        seen["script"] = script
        return {}
    monkeypatch.setattr(pipeline, "reanalyze", record)
    client.post(f"/api/takes/{a['take_id']}/reanalyze", json={"script": (HEADER + BODY).replace("\n", "\r\n")})
    assert seen["script"] == HEADER + BODY
