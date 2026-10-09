"""The real recording path in a real browser: Chrome's fake microphone plays the synthetic fixture.

Record -> stop -> background analysis -> report renders, in script mode and in Improvise, against a live
server with real local speech-to-text. Opt-in because it needs Google Chrome (or Playwright's bundled
Chromium), loads the speech model, and takes about two minutes.
Run with:  uv run pytest -m browser -v
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
FIXTURE_WAV = FIXTURES / "fixture.wav"           # 33.7 s of synthetic speech reading fixture_script.md
SCRIPT = (FIXTURES / "fixture_script.md").read_text(encoding="utf-8")
DIST_INDEX = ROOT / "frontend" / "dist" / "index.html"
STARTUP_S = 180      # the first load of the speech model can be slow
ANALYSIS_S = 120


def _dist_problem() -> str | None:
    """FastAPI serves frontend/dist, so a missing or stale build would test old code."""
    if not DIST_INDEX.exists():
        return "frontend/dist/index.html is missing; run `npm run build` in frontend/"
    built = DIST_INDEX.stat().st_mtime
    sources = [p for p in (ROOT / "frontend" / "src").rglob("*") if p.is_file()] + [ROOT / "frontend" / "index.html"]
    newer = [p for p in sources if p.exists() and p.stat().st_mtime > built]
    if newer:
        return f"frontend/dist is older than {newer[0].relative_to(ROOT)}; run `npm run build` in frontend/"
    return None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _kill_tree(proc: subprocess.Popen) -> None:
    # `uv run` starts uvicorn as a child process: stopping uv alone would leave the server running.
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    else:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    problem = _dist_problem()
    if problem:
        pytest.skip(problem)
    takes_dir = tmp_path_factory.mktemp("takes")
    log_path = takes_dir.parent / "server.log"
    port = _free_port()
    uv = shutil.which("uv")
    cmd = [uv, "run"] if uv else [sys.executable, "-m"]
    cmd += ["uvicorn", "take_two.app:app", "--host", "127.0.0.1", "--port", str(port)]
    # The fake server voice (tones, labelled) lets the examiner speak in a browser that may have no voices.
    env = {**os.environ, "TAKE_TWO_TAKES_DIR": str(takes_dir), "TAKE_TWO_TTS": "fake"}
    log = open(log_path, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                            start_new_session=sys.platform != "win32")
    base = f"http://127.0.0.1:{port}"

    def log_tail() -> str:
        log.flush()
        return log_path.read_text(encoding="utf-8", errors="replace")[-3000:]

    try:
        deadline = time.monotonic() + STARTUP_S
        stt: dict = {}
        while True:
            if proc.poll() is not None:
                pytest.fail(f"server exited with code {proc.returncode}:\n{log_tail()}")
            try:
                stt = httpx.get(f"{base}/api/health", timeout=5).json()["stt"]
                if stt.get("loaded"):
                    break
            except (httpx.HTTPError, ValueError, KeyError):
                pass
            if time.monotonic() > deadline:
                pytest.fail(f"speech model not loaded after {STARTUP_S} s (last stt status: {stt}):\n{log_tail()}")
            time.sleep(1)
        yield base
    finally:
        _kill_tree(proc)
        log.close()


@pytest.fixture(scope="module")
def playwright_instance():
    sync_api = pytest.importorskip("playwright.sync_api", reason="playwright is a dev dependency: uv sync")
    with sync_api.sync_playwright() as pw:
        yield pw


CHROME_ARGS = [
    "--use-fake-ui-for-media-stream",
    "--use-fake-device-for-media-stream",
    f"--use-file-for-fake-audio-capture={FIXTURE_WAV}%noloop",
    "--autoplay-policy=no-user-gesture-required",
]


@pytest.fixture
def browser(playwright_instance):
    """A fresh browser per test: the fake microphone plays the fixture from its start, once."""
    from playwright.sync_api import Error

    errors = []
    for channel in ("chrome", None):
        try:
            b = playwright_instance.chromium.launch(channel=channel, args=CHROME_ARGS)
            break
        except Error as exc:
            errors.append(f"{channel or 'bundled chromium'}: {str(exc).splitlines()[0]}")
    else:
        pytest.skip("no usable browser (install Google Chrome, or run `uv run playwright install chromium`): "
                    + "; ".join(errors))
    yield b
    b.close()


class Session:
    """One page on the app, collecting uncaught page errors (any one fails the test)."""

    def __init__(self, browser, base: str, local_storage: dict[str, object]):
        self.base = base
        self.context = browser.new_context()
        self.context.grant_permissions(["microphone"], origin=base)
        # Seed localStorage before the app's own script reads it.
        seed = json.dumps({k: json.dumps(v) for k, v in local_storage.items()})
        self.context.add_init_script(f"for (const [k, v] of Object.entries({seed})) localStorage.setItem(k, v);")
        self.page = self.context.new_page()
        self.page_errors: list[str] = []
        self.console_errors: list[str] = []
        self.page.on("pageerror", lambda e: self.page_errors.append(str(e)))
        self.page.on("console", lambda m: m.type == "error" and self.console_errors.append(m.text))

    def check(self) -> None:
        assert not self.page_errors, f"uncaught errors in the page: {self.page_errors}"

    def wait_for(self, js: str, timeout_s: float, what: str) -> None:
        """Poll a JS condition, failing fast on a page error and showing the page's status text on timeout."""
        deadline = time.monotonic() + timeout_s
        while not self.page.evaluate(js):
            self.check()
            if time.monotonic() > deadline:
                status = self.page.evaluate("[...document.querySelectorAll('.run-panel, .status')].map(e => e.innerText.trim()).filter(Boolean).join(' | ')")
                pytest.fail(f"timed out after {timeout_s:.0f} s waiting for {what}; page says: {status!r}; "
                            f"hash={self.page.evaluate('location.hash')!r}; console errors: {self.console_errors}")
            self.page.wait_for_timeout(250)

    def take(self) -> dict:
        """The take the page just opened (the id it stored), as the server has it."""
        stored = self.page.evaluate("localStorage.getItem('taketwo.lastTake')")
        assert stored, "the page opened a report without storing its take id"
        take_id = json.loads(stored)
        r = httpx.get(f"{self.base}/api/takes/{take_id}", timeout=10)
        r.raise_for_status()
        return r.json()

    def close(self) -> None:
        self.context.close()


def test_script_mode_record_stop_report(server, browser):
    s = Session(browser, server, {"taketwo.script": SCRIPT})
    try:
        page = s.page
        page.goto(f"{server}/#rehearse")
        rec = page.locator(".rec-btn")
        rec.click()
        s.wait_for("document.querySelector('.rec-btn')?.textContent === 'Stop and analyze'", 20, "recording to start")
        started = time.monotonic()

        # The teleprompter is on screen and highlights the planned line while recording.
        now = page.locator(".prompter .pl-now")
        assert now.count() == 1 and now.is_visible()
        first_line = now.inner_text()
        page.wait_for_timeout(20_000)
        assert page.locator(".prompter .pl-now").count() == 1
        assert page.locator(".prompter .pl-now").inner_text() != first_line, "highlight did not follow the section budgets"

        # 33.7 s of speech, then about a second of silence (%noloop) before stopping.
        page.wait_for_timeout(max(0, (started + 35.0 - time.monotonic()) * 1000))
        s.check()
        rec.click()
        s.wait_for("location.hash === '#report' && document.querySelectorAll('.script-report .line').length > 0",
                   ANALYSIS_S, "the script report")
        assert page.locator(".script-report .line").count() == 9

        take = s.take()
        assert take.get("mode", "script") == "script"
        assert 33.0 <= take["duration_s"] <= 37.0, take["duration_s"]
        statuses = [line["status"] for line in take["lines"]]
        assert len(statuses) == 9
        assert statuses.count("ok") >= 7, statuses
        s.check()
    finally:
        s.close()


def test_improvise_record_stop_report(server, browser):
    prefs = {"category": "All", "goal_s": 30, "content": False, "prep_s": 0, "topic": "", "custom": ""}
    s = Session(browser, server, {"taketwo.improv": prefs})
    try:
        page = s.page
        page.goto(f"{server}/#improvise")
        start = page.get_by_role("button", name="Start", exact=True)  # not the examiner's "Start the session"
        start.wait_for()
        start.click()
        stop = page.get_by_role("button", name="Stop and analyze")
        stop.wait_for(timeout=20_000)   # no thinking time: straight to recording
        page.wait_for_timeout(15_000)
        s.check()
        stop.click()
        s.wait_for("location.hash === '#report' && !!document.querySelector('.metric-grid')", ANALYSIS_S,
                   "the Improvise report")

        take = s.take()
        assert take["mode"] == "improv"
        assert take["topic"]
        assert 13.0 <= take["duration_s"] <= 18.0, take["duration_s"]
        s.check()
    finally:
        s.close()


# Every voice played and every microphone opened or closed, with the time, so the order can be checked.
TRACE_JS = """
window.__trace = [];
const mark = (what) => window.__trace.push([what, performance.now()]);
const play = HTMLMediaElement.prototype.play;
HTMLMediaElement.prototype.play = function () {
  if (!this.closest || !this.closest('body')) {  // the voice's own element; the take player is in the page
    mark('voice-start');
    this.addEventListener('ended', () => mark('voice-end'), { once: true });
    this.addEventListener('pause', () => mark('voice-end'), { once: true });
  }
  return play.call(this);
};
const gum = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
navigator.mediaDevices.getUserMedia = async (c) => {
  const st = await gum(c);
  mark('mic-on');
  st.getTracks().forEach((t) => { const stop = t.stop.bind(t); t.stop = () => { mark('mic-off'); stop(); }; });
  return st;
};
localStorage.setItem('taketwo.voice.examiner', 'server');
"""


def test_spoken_examiner_session(server, browser):
    """Three typed questions, asked by the fake server voice, answered through the fake microphone.
    Proves the state transitions, that the microphone is never open while the examiner speaks, that each
    answer is saved as an Improvise take of the session, and the closing text. It cannot prove how the voice
    sounds, or that a real loudspeaker would not leak into a real microphone."""
    questions = ["How do you know the effect is real?", "What would change your mind?", "Who should care about this?"]
    s = Session(browser, server, {
        "taketwo.improv": {"source": "examiner", "category": "All", "goal_s": 60, "content": False, "prep_s": 0,
                           "topic": "", "custom": "", "question": None, "qcustom": ""},
        "taketwo.examiner": {"source": "typed", "typed": chr(10).join(questions)},
        "taketwo.settings": {"examiner_questions": 3, "examiner_think_s": 0, "examiner_max_answer_s": 10, "examiner_silence_s": 3},
    })
    s.context.add_init_script(TRACE_JS)
    try:
        page = s.page
        page.goto(f"{server}/#improvise")
        page.get_by_role("button", name="Start the session").click()
        s.wait_for("document.querySelector('.examiner-phase')?.textContent.startsWith('Question 1 of 3. Listening.')", 30,
                   "the first answer to be recorded")
        s.wait_for("/^Session (complete|ended)/.test(document.querySelector('.examiner-phase')?.textContent ?? '')",
                   3 * ANALYSIS_S, "the session to finish")
        s.check()
        say = page.locator(".examiner-phase").inner_text()
        assert say.startswith("Session complete."), say

        trace = [e[0] for e in page.evaluate("window.__trace")]
        # Questions, then the closing line: four voices. Three answers: three microphones, each closed again.
        assert trace.count("mic-on") == 3, trace
        open_mic = False
        voice = 0
        for what in trace:
            if what == "voice-start":
                assert not open_mic, f"the examiner spoke while the microphone was open: {trace}"
                voice += 1
            elif what == "voice-end":
                voice = max(0, voice - 1)
            elif what == "mic-on":
                assert voice == 0, f"the microphone opened while the examiner was speaking: {trace}"
                open_mic = True
            elif what == "mic-off":
                open_mic = False

        takes = httpx.get(f"{server}/api/takes", timeout=10).json()
        mine = [httpx.get(f"{server}/api/takes/{t['take_id']}", timeout=10).json() for t in takes if t.get("mode") == "improv"]
        mine = [a for a in mine if (a.get("session") or {}).get("id", "").startswith("ex-")]
        assert sorted(a["topic"] for a in mine) == sorted(questions), (
            say, page.locator(".examiner-answers").inner_text(), [(t.get("mode"), t.get("topic"), t.get("status")) for t in takes])
        assert len({a["session"]["id"] for a in mine}) == 1
        assert all(a["duration_s"] <= 11.5 for a in mine), [a["duration_s"] for a in mine]
        session = httpx.get(f"{server}/api/improv/session/{mine[0]['session']['id']}", timeout=10).json()
        assert session["closing"].startswith("You answered 3 questions.")
        assert session["closing"] in say
        assert page.get_by_role("button", name="Open its report").count() == 3
    finally:
        s.close()
