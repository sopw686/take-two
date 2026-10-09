"""Take management: rename, delete with drills, export (HTML, zip) and the outcomes CSV."""

import csv
import io
import json
import re
import zipfile

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from take_two import app as app_mod
from take_two import config, export, pipeline, takes
from take_two.audio import SR
from take_two.llm import set_llm
from take_two.llm.base import NullLLM
from take_two.stt.base import Transcript, Word

SCRIPT = ("## Intro [0:05]\n[KEY] Trees are great / and they cool the street.\n"
          "## Close [0:02]\nShade [DEFINE: canopy] helps everyone.\n")
SAID = "Trees are great and they cool the street. Shade helps everyone."


class Stub:
    def transcribe(self, audio, sample_rate=16000, initial_prompt=None):
        words = [Word(w, 0.2 + 0.3 * i, 0.45 + 0.3 * i) for i, w in enumerate(SAID.split())]
        return Transcript(words=words, text=SAID, backend="stub", model="stub", device="cpu")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TAKES_DIR", tmp_path)
    monkeypatch.setattr(pipeline, "get_transcriber", lambda: Stub())
    set_llm(NullLLM())
    yield TestClient(app_mod.app, base_url="http://127.0.0.1")
    set_llm(None)
    takes.QUEUED.clear()
    takes.ACTIVE.clear()


def _wav():
    buf = io.BytesIO()
    t = np.arange(int(5 * SR)) / SR
    sf.write(buf, (0.1 * np.sin(2 * np.pi * 150 * t)).astype(np.float32), SR, format="WAV")
    return buf.getvalue()


def _take(c, label="Run 1", script=SCRIPT):
    r = c.post("/api/takes", files={"audio": ("t.wav", _wav(), "audio/wav")}, data={"script": script, "label": label})
    assert r.status_code == 200, r.text
    return r.json()


def _drill(c, parent, index=0):
    r = c.post(f"/api/takes/{parent}/drill", files={"audio": ("d.wav", _wav(), "audio/wav")}, data={"kind": "line", "index": str(index)})
    assert r.status_code == 200, r.text
    return r.json()["take_id"]


# ---- rename -------------------------------------------------------------------------------------

def test_a_new_label_survives_re_analysis(client):
    a = _take(client)
    r = client.patch(f"/api/takes/{a['take_id']}", json={"label": "  Dress   rehearsal  "})
    assert r.json() == {"take_id": a["take_id"], "label": "Dress rehearsal"}
    assert client.get(f"/api/takes/{a['take_id']}").json()["label"] == "Dress rehearsal"
    b = client.post(f"/api/takes/{a['take_id']}/reanalyze", json={}).json()
    assert b["label"] == "Dress rehearsal"
    assert [t["label"] for t in client.get("/api/takes").json()] == ["Dress rehearsal"]
    assert client.patch("/api/takes/20990101-000000-0000", json={"label": "x"}).status_code == 404


# ---- delete -------------------------------------------------------------------------------------

def test_deleting_a_take_removes_its_drills_and_says_what_goes(client, tmp_path):
    a = _take(client)["take_id"]
    other = _take(client, "Run 2")["take_id"]
    d1, d2 = _drill(client, a), _drill(client, a)
    info = client.get(f"/api/takes/{a}/storage").json()
    assert info["drills"] == 2 and info["bytes"] > 0 and info["drill_bytes"] > 0 and info["folder"].endswith(a)
    r = client.delete(f"/api/takes/{a}").json()
    assert r == {"deleted": a, "drills": sorted([d1, d2])}
    assert sorted(p.name for p in tmp_path.iterdir()) == [other]


def test_a_take_being_analyzed_is_not_deleted(client, tmp_path):
    a = _take(client)["take_id"]
    d = _drill(client, a)
    takes.ACTIVE.add(d)  # a drill still running keeps its parent too
    try:
        assert client.delete(f"/api/takes/{a}").status_code == 409
    finally:
        takes.ACTIVE.discard(d)
    assert (tmp_path / a).exists() and (tmp_path / d).exists()


def test_an_open_file_turns_into_a_retry_message(client, monkeypatch):
    a = _take(client)["take_id"]

    def locked(_):
        raise PermissionError("in use")
    monkeypatch.setattr(takes, "delete_take", locked)
    r = client.delete(f"/api/takes/{a}")
    assert r.status_code == 409 and "still open" in r.json()["detail"]


# ---- export -------------------------------------------------------------------------------------

def test_the_html_export_is_self_contained(client):
    a = _take(client)
    r = client.get(f"/api/takes/{a['take_id']}/export.html")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    page = r.text
    assert "data:audio/wav;base64," in page
    # Nothing is fetched when it opens: no external scripts, styles, images or links.
    assert not re.search(r'(src|href)="(?!data:)', page), re.findall(r'(?:src|href)="[^"]{0,40}', page)
    assert "http://" not in page and "https://" not in page
    # The tooltips are printed: the KEY numbers, the pause between its words, the DEFINE verdict.
    assert "KEY: Rate:" in page and "/ between “great” and “and”" in page and "DEFINE “canopy”" in page
    assert "Run 1" in page and ("✓" in page or "✗" in page)


def test_the_size_estimate_matches_the_export(client):
    tid = _take(client)["take_id"]
    est = client.get(f"/api/takes/{tid}/export/estimate").json()["bytes"]
    actual = len(client.get(f"/api/takes/{tid}/export.html").content)
    assert abs(est - actual) < 64


def test_export_refuses_what_it_cannot_print(client, tmp_path):
    imp = client.post("/api/improv", files={"audio": ("a.wav", _wav(), "audio/wav")}, data={"topic": "Trees", "goal_s": "30"})
    assert imp.status_code == 200, imp.text
    assert client.get(f"/api/takes/{imp.json()['take_id']}/export.html").status_code == 409
    with pytest.raises(ValueError):
        export.report_html("20990101-000000-0000")


def test_the_zip_holds_the_take_and_its_drills(client):
    a = _take(client)["take_id"]
    d = _drill(client, a)
    r = client.get(f"/api/takes/{a}/export.zip")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    for f in ("analysis.json", "audio.wav", "script.md", "transcript.json", "take.json"):
        assert f"{a}/{f}" in names and f"{a}/drills/{d}/{f}" in names


# ---- outcomes -----------------------------------------------------------------------------------

def test_outcomes_hold_statuses_and_numbers_but_no_words(client):
    a = _take(client, "Secret label")
    d = _drill(client, a["take_id"])
    client.post("/api/examples/coral", json={})
    client.post("/api/improv", files={"audio": ("a.wav", _wav(), "audio/wav")}, data={"topic": "Secret topic", "goal_s": "30"})
    r = client.get("/api/outcomes.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    text = r.text
    rows = list(csv.DictReader(io.StringIO(text)))
    assert {row["take_id"] for row in rows} == {a["take_id"], d}  # no example, no Improvise take
    assert {row["drill_of"] for row in rows if row["take_id"] == d} == {a["take_id"]}
    ids = {row["mark_id"] for row in rows if row["take_id"] == a["take_id"]}
    assert {"median", "section:S1", "section:S2", "KEY:L1", "KEY:L1:rate", "KEY:L1:pause", "/:L1:W3", "DEFINE:L2"} <= ids
    pause = next(row for row in rows if row["mark_id"] == "/:L1:W3" and row["take_id"] == a["take_id"])
    assert pause["unit"] == "s" and float(pause["target"]) == 0.7 and pause["status"]
    # No label, topic, script word or transcript word appears anywhere.
    for word in ("Secret", "Trees", "canopy", "Intro", "Shade", "street"):
        assert word not in text


def test_a_long_label_is_cut_to_120_characters(client):
    a = _take(client)["take_id"]
    r = client.patch(f"/api/takes/{a}", json={"label": "x" * 200})
    assert len(r.json()["label"]) == 120 and len(client.get(f"/api/takes/{a}").json()["label"]) == 120


def test_the_zip_leaves_out_half_written_files(client):
    a = _take(client)["take_id"]
    (takes.take_path(a) / ".analysis.json.ab12.tmp").write_text("{}", encoding="utf-8")
    (takes.take_path(a) / ".audio.part.wav").write_bytes(b"RIFF")
    names = zipfile.ZipFile(io.BytesIO(client.get(f"/api/takes/{a}/export.zip").content)).namelist()
    assert not any(n.endswith(".tmp") or "/.audio.part" in n for n in names) and f"{a}/analysis.json" in names


def test_drill_rows_use_the_full_scripts_positions(client):
    a = _take(client)["take_id"]
    d = _drill(client, a, index=1)  # the [DEFINE] line, line 2 of the full script
    rows = list(csv.DictReader(io.StringIO(client.get("/api/outcomes.csv").text)))
    ids = {r["mark_id"] for r in rows if r["take_id"] == d}
    assert "DEFINE:L2" in ids and "DEFINE:L1" not in ids
    assert not any(i.startswith("section:") for i in ids)  # a line drill times a line, not its section


def test_the_export_prints_the_presets_the_whole_talk_and_what_the_example_is(client):
    a = _take(client, script="<!-- take-two: conventions_enabled=true -->\n" + SCRIPT)["take_id"]
    takes.update_analysis(a, lambda x: {**x, "fit_total": {"status": "over", "cut": {"text": "The whole talk ran 0:04 over."}}})
    page = client.get(f"/api/takes/{a}/export.html").text
    assert "Conference conventions" in page and "Filler words:" in page and "The whole talk ran 0:04 over." in page
    assert "conventions_enabled on" in page  # where the setting came from
    ex = client.post("/api/examples/coral", json={}).json()["take_id"]
    client.patch(f"/api/takes/{ex}", json={"label": "My take"})  # renaming does not hide what it is
    assert "Example take (synthetic voice)" in client.get(f"/api/takes/{ex}/export.html").text


def test_a_section_without_lines_has_nothing_to_time():
    from take_two.analysis import analyze
    from take_two.config import Settings
    from take_two.focus import focus
    from take_two.marks import parse_script
    from take_two.outcomes import outcome_rows
    from tests.helpers import make_transcript, silences_from_gaps
    script = parse_script("## One [0:05]\nTrees are great and cool.\n## Two\n<!-- no notes -->\n## Three [0:05]\nShade helps everyone here.\n")
    tr = make_transcript("trees are great and cool shade helps everyone here")
    a = analyze(script, tr, silences_from_gaps(tr), Settings(), 5.0)
    assert [s["status"] for s in a["sections"]][1] == "no_lines"
    assert "Two" not in a["fit_total"].get("reason", "") and not any("Two" in s for s in a["summary"])
    assert "could not be measured" not in (focus(a, []).get("note") or "")
    assert not any(r["mark_id"] == "section:S2" for r in outcome_rows(a))
