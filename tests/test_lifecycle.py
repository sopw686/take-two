"""Take lifecycle: a failed take keeps its folder and can be retried or deleted; example takes."""

import io
import json
import os
from datetime import datetime, timedelta

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from take_two import app as app_mod
from take_two import config, pipeline, takes
from take_two.audio import SR
from take_two.config import Settings
from take_two.llm import set_llm
from take_two.llm.base import NullLLM
from take_two.stt.base import Transcript, Word

SCRIPT = "## Intro [0:10]\nTrees are great and they cool the street.\n"


class Stub:
    calls = 0

    def transcribe(self, audio, sample_rate=16000, initial_prompt=None):
        Stub.calls += 1
        text = "Trees are great and they cool the street."
        words = [Word(w, 0.2 + 0.3 * i, 0.45 + 0.3 * i) for i, w in enumerate(text.split())]
        return Transcript(words=words, text=text, backend="stub", model="stub", device="cpu")


class Boom:
    def transcribe(self, *args, **kwargs):
        raise RuntimeError("speech model exploded")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TAKES_DIR", tmp_path)
    Stub.calls = 0
    holder = {"t": Stub()}
    monkeypatch.setattr(pipeline, "get_transcriber", lambda: holder["t"])
    set_llm(NullLLM())  # never reach a real model, whatever the machine's environment
    yield TestClient(app_mod.app, base_url="http://127.0.0.1"), holder, tmp_path
    set_llm(None)
    takes.QUEUED.clear()  # takes created but deliberately never processed by a test
    takes.ACTIVE.clear()


def _wav(seconds=3.0):
    buf = io.BytesIO()
    t = np.arange(int(seconds * SR)) / SR
    sf.write(buf, (0.1 * np.sin(2 * np.pi * 150 * t)).astype(np.float32), SR, format="WAV")
    return buf.getvalue()


def _post_take(c, **data):
    return c.post("/api/takes", files={"audio": ("take.wav", _wav(), "audio/wav")},
                  data={"script": SCRIPT, "label": "first", **data})


def _fail_one(c, holder):
    holder["t"] = Boom()
    r = _post_take(c)
    holder["t"] = Stub()
    assert r.status_code == 500, r.text
    return r.json()["detail"]["take_id"]


def test_failed_take_keeps_folder_and_reports_take_id(env):
    c, holder, tmp = env
    holder["t"] = Boom()
    r = _post_take(c)
    assert r.status_code == 500
    detail = r.json()["detail"]
    assert "exploded" in detail["message"]
    tid = detail["take_id"]
    meta = takes.load_meta(tid)
    assert meta["status"] == "failed" and "exploded" in meta["error"] and meta["label"] == "first"
    assert meta["settings"] == Settings().model_dump()
    assert (tmp / tid / "script.md").exists() and (tmp / tid / "audio.orig.wav").exists()
    listed = c.get("/api/takes").json()
    assert listed[0]["take_id"] == tid and listed[0]["status"] == "failed" and listed[0]["retryable"] is True
    assert "exploded" in listed[0]["error"]


def test_retry_resumes_from_saved_upload_and_keeps_label(env):
    c, holder, _ = env
    tid = _fail_one(c, holder)
    created = takes.load_meta(tid)["created_at"]
    r = c.post(f"/api/takes/{tid}/retry")
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["take_id"] == tid and a["label"] == "first" and a["created_at"] == created
    assert a["lines"][0]["status"] == "ok" and Stub.calls == 1
    assert c.get("/api/takes").json()[0]["status"] == "done"
    assert c.post(f"/api/takes/{tid}/retry").status_code == 409


def test_retry_skips_transcription_when_transcript_was_saved(env, monkeypatch):
    c, _, _ = env
    real = pipeline.reanalyze

    def broken(*args, **kwargs):
        raise ValueError("analysis bug")
    monkeypatch.setattr(pipeline, "reanalyze", broken)
    r = _post_take(c)
    assert r.status_code == 500 and "analysis bug" in r.json()["detail"]["message"]
    monkeypatch.setattr(pipeline, "reanalyze", real)
    tid = r.json()["detail"]["take_id"]
    assert c.post(f"/api/takes/{tid}/retry").status_code == 200
    assert Stub.calls == 1  # the saved transcript was reused


def test_failed_improv_take_keeps_topic_and_retries_as_improv(env):
    c, holder, tmp = env
    holder["t"] = Boom()
    r = c.post("/api/improv", files={"audio": ("take.wav", _wav(), "audio/wav")}, data={"topic": " trees ", "goal_s": "60"})
    holder["t"] = Stub()
    assert r.status_code == 500
    tid = r.json()["detail"]["take_id"]
    assert json.loads((tmp / tid / "improv.json").read_text(encoding="utf-8"))["topic"] == "trees"
    listed = c.get("/api/takes").json()[0]
    assert listed["mode"] == "improv" and listed["topic"] == "trees" and listed["status"] == "failed"
    a = c.post(f"/api/takes/{tid}/retry").json()
    assert a["mode"] == "improv" and a["topic"] == "trees"


def test_legacy_folder_with_only_the_upload(env):
    c, _, tmp = env
    tid = "20261008-004237-3698"
    (tmp / tid).mkdir()
    (tmp / tid / "audio.orig.wav").write_bytes(_wav())
    row = c.get("/api/takes").json()[0]
    assert row["status"] == "failed" and row["retryable"] is True and row["needs_script"] is True
    assert "no details" in row["error"]
    assert c.post(f"/api/takes/{tid}/retry").status_code == 400
    r = c.post(f"/api/takes/{tid}/retry", json={"script": SCRIPT})
    assert r.status_code == 200, r.text
    assert r.json()["lines"][0]["status"] == "ok"


def test_retry_refuses_finished_takes_and_both_refuse_busy_ones(env):
    c, holder, _ = env
    done = _post_take(c).json()["take_id"]
    assert c.post(f"/api/takes/{done}/retry").status_code == 409
    tid = _fail_one(c, holder)
    takes.ACTIVE.add(tid)
    try:
        assert c.post(f"/api/takes/{tid}/retry").status_code == 409
        assert c.delete(f"/api/takes/{tid}").status_code == 409
    finally:
        takes.ACTIVE.discard(tid)


def test_delete_unfinished_take(env):
    c, holder, tmp = env
    tid = _fail_one(c, holder)
    assert c.delete(f"/api/takes/{tid}").status_code == 200
    assert not (tmp / tid).exists() and c.get("/api/takes").json() == []
    assert c.delete(f"/api/takes/{tid}").status_code == 404


def test_unfinished_take_without_its_recording_can_only_be_deleted(env):
    c, holder, tmp = env
    tid = _fail_one(c, holder)
    (tmp / tid / "audio.orig.wav").unlink()
    row = c.get("/api/takes").json()[0]
    assert row["status"] == "failed" and row["retryable"] is False
    assert c.post(f"/api/takes/{tid}/retry").status_code == 400
    assert c.delete(f"/api/takes/{tid}").status_code == 200


def test_processing_status_survives_only_while_this_process_works_on_it(env):
    c, _, _ = env
    tid = takes.new_take("script", upload=_wav(), original_name="t.wav", script=SCRIPT)
    assert takes.take_status(tid)["status"] == "processing"  # created here, waiting to be processed
    assert c.post(f"/api/takes/{tid}/retry").status_code == 409
    takes.QUEUED.discard(tid)
    st = takes.take_status(tid)
    assert st["error"].startswith("Interrupted") and st["retryable"] is True
    # A server that stopped mid-take comes back as a new process: the take is retryable right away.
    takes.update_meta(tid, owner={"boot_id": "a-previous-run", "started_at": datetime.now().isoformat()})
    st = takes.take_status(tid)
    assert st["status"] == "failed" and st["retryable"] is True
    assert c.post(f"/api/takes/{tid}/retry").status_code == 200


def test_claim_is_exclusive_and_released():
    with takes.claim("20990101-000000-abcd"):
        with pytest.raises(takes.Busy):
            with takes.claim("20990101-000000-abcd"):
                pass
    assert not takes.is_busy("20990101-000000-abcd")


@pytest.mark.parametrize("name,expected", [("a.wav:x", "audio.orig.bin"), ("TAKE.WEBM", "audio.orig.webm"),
                                           ("blob", "audio.orig.bin"), ("", "audio.orig.bin")])
def test_upload_suffix_is_sanitized(env, name, expected):
    tid = takes.new_take("script", upload=b"x", original_name=name, script=SCRIPT)
    assert takes.orig_audio(tid).name == expected
    assert {p.name for p in takes.take_path(tid).iterdir()} == {expected, "script.md", "take.json"}


def test_a_failed_creation_leaves_nothing_busy(env, monkeypatch):
    c, _, tmp = env
    real = pipeline.shutil.copyfile

    def broken(src, dst, *a, **k):
        if str(src).endswith("transcript.json"):
            raise OSError("disk full")
        return real(src, dst, *a, **k)
    monkeypatch.setattr(pipeline.shutil, "copyfile", broken)
    before = set(takes.QUEUED)
    with pytest.raises(OSError):
        c.post("/api/examples/coral")
    assert takes.QUEUED == before and not any(tmp.iterdir())


def test_retry_uses_saved_settings_unless_new_ones_are_sent(env):
    c, holder, _ = env
    holder["t"] = Boom()
    tid = _post_take(c, settings='{"short_pause_s": 0.2}').json()["detail"]["take_id"]
    holder["t"] = Stub()
    assert c.post(f"/api/takes/{tid}/retry").json()["settings"]["short_pause_s"] == 0.2
    tid = _fail_one(c, holder)
    a = c.post(f"/api/takes/{tid}/retry", json={"settings": {"short_pause_s": 0.3}, "label": "x"}).json()
    assert a["settings"]["short_pause_s"] == 0.3 and a["label"] == "x"
    meta = takes.load_meta(tid)
    assert meta["settings"]["short_pause_s"] == 0.3 and meta["label"] == "x"


def test_reanalysis_refuses_unfinished_and_busy_takes(env, monkeypatch):
    c, _, _ = env
    real = pipeline.reanalyze

    def broken(*args, **kwargs):
        raise ValueError("analysis bug")
    monkeypatch.setattr(pipeline, "reanalyze", broken)
    tid = _post_take(c).json()["detail"]["take_id"]
    monkeypatch.setattr(pipeline, "reanalyze", real)
    r = c.post(f"/api/takes/{tid}/reanalyze", json={})
    assert r.status_code == 409 and "retry it instead" in r.json()["detail"]
    done = _post_take(c).json()["take_id"]
    imp = c.post("/api/improv", files={"audio": ("take.wav", _wav(), "audio/wav")}, data={"topic": "trees"}).json()["take_id"]
    takes.ACTIVE.update({done, imp})
    try:
        assert c.post(f"/api/takes/{done}/reanalyze", json={}).status_code == 409
        assert c.post(f"/api/improv/{imp}/reanalyze", json={}).status_code == 409
    finally:
        takes.ACTIVE.difference_update({done, imp})


def test_coaching_is_saved_unless_a_reanalysis_changed_the_numbers(env, monkeypatch):
    import take_two.coaching as coaching
    from take_two.llm.fake_llm import FakeLLM
    c, _, _ = env
    tid = _post_take(c).json()["take_id"]
    set_llm(FakeLLM())
    try:
        monkeypatch.setattr(coaching, "coach", lambda data, llm, earlier: {"available": True, "suggestions": [], "all_met": True})
        assert c.post(f"/api/takes/{tid}/coach").status_code == 200
        assert "coaching" in takes.load_take(tid)

        def racing(data, llm, earlier):  # a Settings change lands while the model is answering
            pipeline.reanalyze(tid, SCRIPT, Settings(short_pause_s=0.2))
            return {"available": True, "suggestions": [{"text": "stale 1"}], "all_met": False}
        monkeypatch.setattr(coaching, "coach", racing)
        c.post(f"/api/takes/{tid}/coach")
        stored = takes.load_take(tid)
        assert stored["settings"]["short_pause_s"] == 0.2 and "coaching" not in stored
    finally:
        set_llm(None)


def test_improv_coach_saves_content_choice_and_drops_stale_results(env, monkeypatch):
    import take_two.improv_coach as ic
    c, _, tmp = env
    tid = c.post("/api/improv", files={"audio": ("take.wav", _wav(), "audio/wav")}, data={"topic": "trees"}).json()["take_id"]
    monkeypatch.setattr(ic, "coach_improv", lambda *a, **k: {"coaching": {"available": False, "suggestions": []},
                                                              "content_review": {"available": False, "items": []}})
    c.post(f"/api/improv/{tid}/coach", json={"content": True})
    assert json.loads((tmp / tid / "improv.json").read_text(encoding="utf-8"))["content"] is True
    assert "content_review" in takes.load_take(tid)
    c.post(f"/api/improv/{tid}/coach", json={"content": False})
    stored = takes.load_take(tid)
    assert stored["content"] is False and "content_review" not in stored

    def racing(*a, **k):
        pipeline.reanalyze_improv(tid, Settings(improv_filler_per_100=50))
        return {"coaching": {"available": True, "suggestions": [{"text": "stale 2"}]}}
    monkeypatch.setattr(ic, "coach_improv", racing)
    c.post(f"/api/improv/{tid}/coach", json={"content": False})
    stored = takes.load_take(tid)
    assert stored["settings"]["improv_filler_per_100"] == 50 and stored.get("coaching", {}).get("suggestions") != [{"text": "stale 2"}]


def test_listing_ignores_stray_folders_and_temp_files(env):
    c, _, tmp = env
    _post_take(c)
    (tmp / "notatake").mkdir()
    (tmp / ".analysis.json.ab12.tmp").write_text("{", encoding="utf-8")
    assert len(c.get("/api/takes").json()) == 1


def test_save_json_retries_when_the_file_is_held_open(tmp_path, monkeypatch):
    real = os.replace
    fails = {"n": 2}

    def flaky(src, dst):
        if fails["n"]:
            fails["n"] -= 1
            raise PermissionError("held open")
        return real(src, dst)
    monkeypatch.setattr(os, "replace", flaky)
    takes.save_json(tmp_path / "x.json", {"a": 1})
    assert json.loads((tmp_path / "x.json").read_text(encoding="utf-8")) == {"a": 1}
    assert not list(tmp_path.glob("*.tmp"))


def test_empty_upload_is_refused_before_a_folder_exists(env):
    c, _, tmp = env
    r = c.post("/api/takes", files={"audio": ("take.wav", b"", "audio/wav")}, data={"script": SCRIPT})
    assert r.status_code == 400 and not any(tmp.iterdir())


# ---- example take ------------------------------------------------------------------------

def test_example_take_needs_no_speech_model(env):
    c, holder, _ = env
    holder["t"] = Boom()  # would fail the take if speech-to-text were called
    r = c.post("/api/examples/coral", json={"settings": {}})
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["label"] == pipeline.EXAMPLE_LABEL and a["kind"] == "example" and a["example"] == "coral"
    assert sum(1 for ln in a["lines"] if ln["status"] == "ok") >= 8
    assert c.post("/api/examples/nope").status_code == 404


def test_reanalysis_keeps_kind_and_label(env):
    c, _, _ = env
    tid = c.post("/api/examples/coral").json()["take_id"]
    a = c.post(f"/api/takes/{tid}/reanalyze", json={"settings": {"short_pause_s": 0.2}}).json()
    assert a["kind"] == "example" and a["label"] == pipeline.EXAMPLE_LABEL and a["settings"]["short_pause_s"] == 0.2


def test_example_is_left_out_of_comparisons_and_the_median(env):
    c, _, _ = env
    ex = c.post("/api/examples/coral").json()["take_id"]
    assert takes.latest_median_wpm() is None
    assert [a["take_id"] for a in takes.takes_with_same_script(ex)] == [ex]
    # A real take of the same script (same transcript, so no speech model needed).
    src = config.EXAMPLES_DIR / "coral"
    tid = takes.new_take("script", upload=src / "audio.wav", original_name="audio.wav",
                         script=(src / "script.md").read_text(encoding="utf-8"))
    (takes.take_path(tid) / "transcript.json").write_bytes((src / "transcript.json").read_bytes())
    real = pipeline.process_take(tid)
    assert [a["take_id"] for a in takes.takes_with_same_script(tid)] == [tid]
    assert takes.latest_median_wpm() == real["baseline"]["median_wpm"]


def test_example_define_check_is_cached_across_reanalysis(env):
    from take_two.define import DefineJudgement, DefineJudgements
    from take_two.llm import set_llm

    class Counting:
        name, model, available = "counting", "m", True
        calls = 0

        def complete_structured(self, system, user, output, max_tokens=16000):
            Counting.calls += 1
            return DefineJudgements(judgements=[DefineJudgement(term="degree heating weeks", spoken=True,
                                                                defined_at_or_before_first_use=False)])
    c, _, _ = env
    set_llm(Counting())
    try:
        tid = c.post("/api/examples/coral").json()["take_id"]
        for pause in (0.5, 0.9):
            assert c.post(f"/api/takes/{tid}/reanalyze", json={"settings": {"short_pause_s": pause}}).status_code == 200
    finally:
        set_llm(None)
    assert Counting.calls == 1


# ---- background jobs ------------------------------------------------------------------------

def _wait_job(c, tid, timeout=20.0):
    import time
    t0 = time.time()
    while time.time() - t0 < timeout:
        job = c.get(f"/api/jobs/{tid}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_job_reports_stages_in_order_and_its_result(env, monkeypatch):
    c, _, _ = env
    seen = []
    real = pipeline.process_take

    def spy(take_id, progress=None, settings=None):
        return real(take_id, lambda s: (seen.append(s), progress(s)), settings)
    monkeypatch.setattr(pipeline, "process_take", spy)
    script = SCRIPT + "[DEFINE: trees] Trees are great.\n"
    r = c.post("/api/jobs/takes", files={"audio": ("take.wav", _wav(), "audio/wav")}, data={"script": script, "label": "j"})
    assert r.status_code == 200, r.text
    tid = r.json()["take_id"]
    assert r.json()["stages"] == list(pipeline.STAGES["script"])
    job = _wait_job(c, tid)
    assert job["status"] == "done" and seen == ["decoding", "transcribing", "aligning", "definition check"]
    assert job["result"] == c.get(f"/api/takes/{tid}").json() and job["result"]["label"] == "j"


def test_failed_job_reports_error_and_take_id_and_retry_job_resumes(env):
    c, holder, _ = env
    holder["t"] = Boom()
    tid = c.post("/api/jobs/takes", files={"audio": ("take.wav", _wav(), "audio/wav")}, data={"script": SCRIPT}).json()["take_id"]
    job = _wait_job(c, tid)
    assert job["status"] == "failed" and "exploded" in job["error"] and job["take_id"] == tid
    holder["t"] = Stub()
    assert c.post(f"/api/jobs/retry/{tid}").status_code == 200
    assert _wait_job(c, tid)["status"] == "done" and Stub.calls == 1


def test_improv_job_and_busy_take(env):
    c, _, _ = env
    r = c.post("/api/jobs/improv", files={"audio": ("take.wav", _wav(), "audio/wav")}, data={"topic": "trees"})
    tid = r.json()["take_id"]
    assert r.json()["stages"] == list(pipeline.STAGES["improv"])
    assert _wait_job(c, tid)["result"]["mode"] == "improv"
    failed = _fail_one(c, env[1])
    takes.ACTIVE.add(failed)
    try:
        assert c.post(f"/api/jobs/retry/{failed}").status_code == 409
    finally:
        takes.ACTIVE.discard(failed)


def test_job_status_survives_a_restart_by_reading_the_folder(env):
    c, holder, _ = env
    tid = _fail_one(c, holder)  # synchronous route: no job record in memory
    job = c.get(f"/api/jobs/{tid}").json()
    assert job["status"] == "failed" and "exploded" in job["error"]
    done = _post_take(c).json()["take_id"]
    assert c.get(f"/api/jobs/{done}").json()["status"] == "done"


def test_focus_counts_earlier_real_takes_of_the_same_script_only(env):
    c, _, _ = env
    first = _post_take(c).json()["take_id"]
    takes.update_analysis(first, lambda a: {**a, "created_at": "2000-01-01T00:00:00"})
    second = _post_take(c).json()
    item = next(i for i in second["focus"]["items"] if i["mark"] == "Section Intro")
    assert item["takes"] == 2 and item["repeat"] == 2  # under budget in both takes
    # Re-analyzing the older take only looks further back in time.
    again = c.post(f"/api/takes/{first}/reanalyze", json={}).json()
    assert all(i["takes"] == 1 for i in again["focus"]["items"])
    # An example of a script that also has real takes still counts only itself.
    src = config.EXAMPLES_DIR / "coral"
    real = takes.new_take("script", upload=src / "audio.wav", original_name="audio.wav",
                          script=(src / "script.md").read_text(encoding="utf-8"))
    (takes.take_path(real) / "transcript.json").write_bytes((src / "transcript.json").read_bytes())
    pipeline.process_take(real)
    ex = c.post("/api/examples/coral").json()
    assert ex["focus"]["items"] and all(i["takes"] == 1 for i in ex["focus"]["items"])


def _blocking_process(monkeypatch, gate):
    """Make every job wait on `gate` after reporting the transcribing stage."""
    real = pipeline.process_take

    def slow(take_id, progress=None, settings=None):
        def stage(s):
            progress(s)
            if s == "transcribing":
                gate.wait(10)
        return real(take_id, stage, settings)
    monkeypatch.setattr(pipeline, "process_take", slow)


def test_job_status_while_running_and_queued(env, monkeypatch):
    import threading
    import time
    c, _, _ = env
    gate = threading.Event()
    _blocking_process(monkeypatch, gate)
    a = c.post("/api/jobs/takes", files={"audio": ("take.wav", _wav(), "audio/wav")}, data={"script": SCRIPT}).json()
    assert a["stage"] == "starting"  # nothing ahead of it
    deadline = time.time() + 10
    while c.get(f"/api/jobs/{a['take_id']}").json()["stage"] != "transcribing":
        assert time.time() < deadline
        time.sleep(0.02)
    assert c.get(f"/api/jobs/{a['take_id']}").json()["status"] == "running"
    b = c.post("/api/jobs/takes", files={"audio": ("take.wav", _wav(), "audio/wav")}, data={"script": SCRIPT}).json()
    assert b["status"] == "queued" and b["stage"] == "queued"
    gate.set()
    assert _wait_job(c, a["take_id"])["status"] == "done" and _wait_job(c, b["take_id"])["status"] == "done"


def test_a_queued_retry_is_listed_as_being_processed(env, monkeypatch):
    import threading
    import time
    c, holder, _ = env
    failed = _fail_one(c, holder)
    gate = threading.Event()
    _blocking_process(monkeypatch, gate)
    a = c.post("/api/jobs/takes", files={"audio": ("take.wav", _wav(), "audio/wav")}, data={"script": SCRIPT}).json()
    deadline = time.time() + 10
    while c.get(f"/api/jobs/{a['take_id']}").json()["stage"] != "transcribing":
        assert time.time() < deadline
        time.sleep(0.02)
    assert c.post(f"/api/jobs/retry/{failed}").status_code == 200
    row = next(t for t in c.get("/api/takes").json() if t["take_id"] == failed)
    assert row["status"] == "processing" and row["retryable"] is False and row["error"] is None
    gate.set()
    assert _wait_job(c, failed)["status"] == "done"


def test_retry_checks_the_scripts_settings_line(env):
    c, holder, tmp = env
    tid = _fail_one(c, holder)
    for url in (f"/api/takes/{tid}/retry", f"/api/jobs/retry/{tid}"):
        r = c.post(url, json={"script": "<!-- take-two: nope=1 -->\n" + SCRIPT})
        assert r.status_code == 400 and "nope" in r.json()["detail"]
    assert (tmp / tid / "script.md").read_text(encoding="utf-8") == SCRIPT  # nothing saved from the refused retry
    # A saved script whose line only works with the settings it was recorded with.
    holder["t"] = Boom()
    r = _post_take(c, script="<!-- take-two: improv_wpm_min=200 -->\n" + SCRIPT, settings=json.dumps({"improv_wpm_max": 250}))
    holder["t"] = Stub()
    assert r.status_code == 500, r.text
    tid2 = r.json()["detail"]["take_id"]
    r = c.post(f"/api/takes/{tid2}/retry", json={"settings": {"improv_wpm_max": 170}})
    assert r.status_code == 400 and "improv_wpm_min must not exceed improv_wpm_max" in r.json()["detail"]
    r = c.post(f"/api/takes/{tid2}/retry")  # the saved settings still fit
    assert r.status_code == 200, r.text
    assert r.json()["settings_from_script"] == {"improv_wpm_min": 200.0}
