/** Spoken examiner: a hands-free Q&A session. The examiner asks each question aloud, a cue tone marks the
 *  start of the thinking time, recording starts on its own when that ends, and the answer ends after the
 *  speaker's own silence threshold, at the maximum length, or on Space. Each answer is an ordinary Improvise
 *  take whose topic is the question. With an API key the examiner may ask one short follow-up per question,
 *  written from the answer's transcript and numbers only. The keyboard always works: Space, R, S, Esc. */

import { runAnalysis } from "./analysisRun";
import { api } from "./api";
import { fmtClock, h } from "./dom";
import { announce, initial, step, type SessionEvent, type SessionState } from "./examinerMachine";
import { Recorder, showLevel } from "./recorder";
import { textPlan } from "./schedule";
import { silenceDetector } from "./silence";
import { getSpeaker, stopAll, voicePicker, voicesReady } from "./speaker";
import { state } from "./state";
import type { ImprovAnalysis, Question, Settings } from "./types";

const PREFS_KEY = "taketwo.examiner";
type Source = "proposed" | "typed" | "mix";
interface Prefs { source: Source; typed: string }

function loadPrefs(): Prefs {
  try {
    return { source: "typed", typed: "", ...(JSON.parse(localStorage.getItem(PREFS_KEY) ?? "{}") as Partial<Prefs>) };
  } catch {
    return { source: "typed", typed: "" };
  }
}
function savePrefs(p: Prefs): void {
  try { localStorage.setItem(PREFS_KEY, JSON.stringify(p)); } catch { /* storage may be unavailable */ }
}

let live: { abort: () => void } | null = null;

/** End a running session (a tab change): answers already recorded are kept. */
export function stopExaminer(): void {
  live?.abort();
  live = null;
}

/** The setup panel. `typedPath` switches Improvise to "Questions about my script" when voice or microphone is missing. */
export function examinerSetup(root: HTMLElement, goToReport: () => void, typedPath: () => void): HTMLElement {
  const prefs = loadPrefs();
  const cur = state.effectiveSettings();
  const llm = state.health?.llm;
  const script = state.scriptText;
  const status = h("p", { class: "small", role: "status" });

  const sourceRadios = (["proposed", "typed", "mix"] as Source[]).map((id) => {
    const r = h("input", { type: "radio", name: "examiner-source", value: id }) as HTMLInputElement;
    r.checked = prefs.source === id;
    r.disabled = id !== "typed" && (!llm?.available || !script.trim());
    r.addEventListener("change", () => { prefs.source = id; savePrefs(prefs); });
    const label = { proposed: "Proposed from my script", typed: "My own questions", mix: "A mix of both" }[id];
    return h("label", { class: r.disabled ? "disabled" : "" }, r, h("span", {}, label));
  });
  if (sourceRadios.every((l) => !(l.firstChild as HTMLInputElement).checked) || (sourceRadios.find((l) => (l.firstChild as HTMLInputElement).checked)?.firstChild as HTMLInputElement).disabled) {
    (sourceRadios[1].firstChild as HTMLInputElement).checked = true;
    prefs.source = "typed";
  }
  const typed = h("textarea", { class: "label-input", rows: "4", style: "width:100%",
    placeholder: "One question per line, the way someone would ask it out loud." }) as HTMLTextAreaElement;
  typed.value = prefs.typed;
  typed.addEventListener("input", () => { prefs.typed = typed.value; savePrefs(prefs); });

  const num = (key: keyof Settings, label: string, min: number, max: number, stepBy: number, help: string) => {
    const inp = h("input", { type: "number", min: String(min), max: String(max), step: String(stepBy), value: String(cur[key]) }) as HTMLInputElement;
    inp.addEventListener("change", () => {
      const v = Math.min(max, Math.max(min, parseFloat(inp.value)));
      if (!Number.isFinite(v)) return;
      inp.value = String(v);
      state.setSettings({ ...state.effectiveSettings(), [key]: key === "examiner_questions" ? Math.round(v) : v });
    });
    return h("label", { class: "setting", "data-setting": key }, h("span", {}, label, h("small", { class: "muted" }, help)), inp);
  };

  const start = h("button", { class: "primary big", type: "button" }, "Start the session") as HTMLButtonElement;
  start.addEventListener("click", async () => {
    start.disabled = true;
    status.className = "small";
    status.textContent = "Getting the questions…";
    const qs = await questionsFor(prefs, script, state.effectiveSettings().examiner_questions);
    start.disabled = false;
    if (typeof qs === "string") { status.className = "small warn"; status.textContent = qs; return; }
    await voicesReady();
    const ok = getSpeaker("examiner").available();
    if (!ok.ok) {
      status.className = "small warn";
      status.replaceChildren(`The examiner cannot ask aloud: ${ok.reason} You can still answer the same questions by reading them: `,
        h("button", { class: "linklike small", type: "button", onClick: typedPath }, "Questions about my script"), ".");
      return;
    }
    runSession(root, qs, goToReport, typedPath);
  });

  return h("div", { class: "examiner-setup" },
    h("p", { class: "muted small" }, "A hands-free Q&A: the examiner asks each question aloud, you answer out loud with your eyes on your notes, and recording starts and stops on its own. Each answer is measured as an Improvise take on that question."),
    h("h4", {}, "Questions"),
    h("div", { class: "goal-grid" }, ...sourceRadios),
    !llm?.available ? h("p", { class: "muted small" }, "Proposed questions and follow-ups need an ANTHROPIC_API_KEY on the server. Without one, type the questions you expect; the examiner asks them and moves on without follow-ups.")
      : !script.trim() ? h("p", { class: "muted small" }, "Proposed questions come from the script on your Script tab, which is empty.") : null,
    typed,
    h("div", { class: "settings-grid" },
      num("examiner_questions", "How many questions", 3, 6, 1, "3 to 6."),
      num("examiner_think_s", "Thinking time before each answer (s)", 0, 60, 1, "Counted down after a short tone."),
      num("examiner_max_answer_s", "Longest answer (s)", 10, 600, 5, "Recording stops here even if you are still talking."),
      num("examiner_silence_s", "Silence that ends an answer (s)", 1, 10, 0.5, "After you have started speaking.")),
    voicePicker("examiner", "Examiner voice"),
    h("p", { class: "muted small" }, "Keys during the session: ", h("kbd", {}, "Space"), " finish your answer · ", h("kbd", {}, "R"), " hear the question again · ",
      h("kbd", {}, "S"), " skip · ", h("kbd", {}, "Esc"), " end the session. The microphone is never on while the examiner speaks."),
    h("div", { class: "rec-panel" }, start, status));
}

/** Questions for the session, or the reason there are none. */
async function questionsFor(prefs: Prefs, script: string, n: number): Promise<Question[] | string> {
  const typed: Question[] = prefs.typed.split(/\r?\n/).map((l) => l.trim().slice(0, 200)).filter(Boolean).map((text) => ({ text }));
  let proposed: Question[] = [];
  if (prefs.source !== "typed") {
    try {
      const r = await api.improvQuestions(script);
      if (!r.available || r.reason) return r.reason ?? "No questions could be proposed.";
      proposed = r.questions;
    } catch (err) {
      return `Could not get questions: ${(err as Error).message}`;
    }
  }
  const pool = prefs.source === "typed" ? typed : prefs.source === "proposed" ? proposed
    : Array.from({ length: Math.max(typed.length, proposed.length) }, (_, i) => [typed[i], proposed[i]]).flat().filter((q): q is Question => !!q);
  if (pool.length < 3) return `The session needs at least 3 questions; there ${pool.length === 1 ? "is" : "are"} ${pool.length}. ${prefs.source === "typed" ? "Type one per line." : ""}`;
  return pool.slice(0, n);
}

/** A short tone that marks the start of the thinking time; it ends before the microphone opens. */
function cueTone(): Promise<void> {
  return new Promise((resolve) => {
    try {
      const ctx = new AudioContext();
      const o = ctx.createOscillator();
      const g = ctx.createGain();
      o.frequency.value = 880;
      g.gain.setValueAtTime(0.0001, ctx.currentTime);
      g.gain.exponentialRampToValueAtTime(0.2, ctx.currentTime + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.18);
      o.connect(g).connect(ctx.destination);
      o.start();
      o.stop(ctx.currentTime + 0.2);
      o.onended = () => { void ctx.close(); window.setTimeout(resolve, 80); };
    } catch {
      resolve();
    }
  });
}

function runSession(root: HTMLElement, questions: Question[], goToReport: () => void, typedPath: () => void): void {
  stopExaminer();
  const settings = state.effectiveSettings();
  const sessionId = `ex-${Date.now().toString(36)}`;
  const when = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  let s: SessionState = initial();
  let rec: Recorder | null = null;
  let timer = 0;
  let lastTake: string | null = null;  // the answer a follow-up is about
  const done: { take_id: string; label: string }[] = [];

  const progress = h("p", { class: "muted small" });
  const say = h("p", { class: "examiner-phase", role: "status", "aria-live": "polite" });
  const qText = h("div", { class: "topic-text examiner-question" });
  const clock = h("div", { class: "clock" });
  const meterBar = h("div", { class: "meter-fill" });
  const meterLabel = h("div", { class: "meter-label muted small" });
  const answers = h("div", { class: "examiner-answers" });
  const btn = (label: string, key: string, ev: SessionEvent["type"]) =>
    h("button", { class: "ghost-btn", type: "button", onClick: () => dispatch({ type: ev } as SessionEvent) }, label, " ", h("kbd", {}, key));
  const doneBtn = btn("Done", "Space", "answered");
  const repeatBtn = btn("Hear again", "R", "repeat");
  const skipBtn = btn("Skip", "S", "skip");
  const endBtn = h("button", { class: "primary", type: "button", onClick: () => dispatch({ type: "abort" }) }, "End session ", h("kbd", {}, "Esc"));
  const panel = h("section", { class: "card examiner-live" },
    h("div", { class: "topic-head" }, h("h3", {}, "Spoken examiner"), progress),
    qText, say, clock,
    h("div", { class: "meter" }, h("div", { class: "meter-track" }, h("div", { class: "meter-baseline" }), meterBar), meterLabel),
    h("div", { class: "live-actions" }, doneBtn, repeatBtn, skipBtn, endBtn),
    answers);
  root.replaceChildren(panel);

  const onKey = (e: KeyboardEvent) => {
    const t = e.target as HTMLElement | null;
    if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
    const map: Record<string, SessionEvent["type"]> = { " ": "answered", r: "repeat", R: "repeat", s: "skip", S: "skip", Escape: "abort" };
    const ev = map[e.key];
    if (!ev) return;
    e.preventDefault();
    if (e.type === "keydown") dispatch({ type: ev } as SessionEvent);
  };
  document.addEventListener("keydown", onKey);
  document.addEventListener("keyup", onKey);  // a focused button would act on Space at keyup

  const question = () => questions[s.index];
  const spoken = () => s.followup ?? question().text;

  function dispatch(e: SessionEvent): void {
    const before = s;
    s = step(s, e);
    if (s === before) return;
    // Leaving a phase: silence the voice, stop the countdown, close or discard the microphone as needed.
    if (before.phase === "asking") getSpeaker("examiner").stop();
    window.clearInterval(timer);
    if (before.phase === "recording" && s.phase !== "analyzing") { rec?.cancel(); rec = null; }
    render();
    void enter(before);
  }

  function render(): void {
    progress.textContent = s.phase === "done" ? "" : `Question ${s.index + 1} of ${s.total}${s.followup ? " · follow-up" : ""}`;
    qText.textContent = s.phase === "done" ? "" : spoken();
    const text = announce(s);
    if (say.textContent !== text) say.textContent = text;
    (doneBtn as HTMLButtonElement).disabled = s.phase !== "recording";
    (repeatBtn as HTMLButtonElement).disabled = s.phase !== "asking" && s.phase !== "thinking";
    (skipBtn as HTMLButtonElement).disabled = !["asking", "thinking", "recording"].includes(s.phase);
    endBtn.hidden = s.phase === "done";
    panel.classList.toggle("listening", s.phase === "recording");
  }

  async function enter(before: SessionState): Promise<void> {
    const mine = s;
    const still = () => s === mine;
    switch (s.phase) {
      case "asking": {
        stopAll();
        clock.textContent = "";
        try {
          await getSpeaker("examiner").speak(textPlan(spoken()));
        } catch (err) {
          say.textContent = `The examiner's voice stopped working: ${(err as Error).message}`;
          return;
        }
        if (still()) dispatch({ type: "spoken" });
        return;
      }
      case "thinking": {
        await cueTone();
        if (!still()) return;
        const end = performance.now() + settings.examiner_think_s * 1000;
        const tick = () => {
          const left = (end - performance.now()) / 1000;
          clock.textContent = fmtClock(Math.max(0, Math.ceil(left)));
          if (left <= 0 && still()) { window.clearInterval(timer); dispatch({ type: "thought" }); }
        };
        tick();
        if (still()) timer = window.setInterval(tick, 100);
        return;
      }
      case "recording": {
        stopAll();  // never record a voice
        const r = new Recorder();
        rec = r;
        const det = silenceDetector({ silenceS: settings.examiner_silence_s, maxS: settings.examiner_max_answer_s });
        const t0 = performance.now();
        try {
          await r.start((db) => {
            showLevel(db, meterBar, meterLabel, state.calibration?.baseline_db ?? null);
            if (!still()) return;
            const t = (performance.now() - t0) / 1000;
            clock.textContent = fmtClock(Math.floor(t));
            const v = det.feed(t, db);
            if (v !== "listening") dispatch({ type: "answered" });
          });
        } catch (err) {
          rec = null;
          // Said where it stays: the "done" line below is rewritten when the session ends.
          panel.insertBefore(h("p", { class: "warn", role: "alert" },
            `The microphone is unavailable (${(err as Error).message}), so the session stopped. You can answer the same questions by uploading a recording: `,
            h("button", { class: "linklike", type: "button", onClick: typedPath }, "Questions about my script"), "."), say);
          dispatch({ type: "abort" });
        }
        return;
      }
      case "analyzing": {
        const r = rec;
        rec = null;
        if (!r) return;
        const { blob, filename } = await r.stop();
        const q = before.followup ? { text: before.followup } : question();
        const label = `Examiner ${when} · ${before.followup ? `follow-up to Q${before.index + 1}` : `Q${before.index + 1}`}`;
        const host = h("div", { class: "run-panel" });
        const row = h("div", { class: "examiner-answer" }, h("strong", {}, label), h("div", { class: "small muted" }, q.text), host);
        answers.prepend(row);
        let result: ImprovAnalysis | null = null;
        const ok = await runAnalysis<ImprovAnalysis>({
          host, blob, filename,
          message: `Measuring your answer on this computer (${state.health?.stt.model ?? "local model"})…`,
          start: () => api.startImprovJob(blob, filename, q.text, null, false, settings, label, q,
            { id: sessionId, index: before.index, total: before.total, followup_of: before.followup ? lastTake : null }),
          retry: (id) => api.startRetryJob(id, { settings }),
          open: (a) => { result = a; },
          goToReport: () => undefined,
        });
        const a = result as ImprovAnalysis | null;
        if (!ok || !a) { if (still()) dispatch({ type: "failed" }); return; }
        done.push({ take_id: a.take_id, label });
        host.replaceChildren(h("span", { class: "small muted" }, a.summary[0] ?? ""), " ", openLink(a.take_id, goToReport));
        let followup: string | null = null;
        if (!before.followup) {
          lastTake = a.take_id;
          try {
            const f = await api.followup(a.take_id, state.scriptText);
            followup = f.followup?.text ?? null;
            if (!f.followup && f.reason) host.append(h("div", { class: "small muted" }, f.reason));
            if (f.followup?.provider?.includes("fake")) host.append(h("div", { class: "small muted" }, "Follow-up from the fake development stand-in, not a model."));
          } catch { /* no follow-up; the session goes on */ }
        }
        if (still()) dispatch({ type: "analyzed", followup });
        return;
      }
      case "done": {
        document.removeEventListener("keydown", onKey);
        document.removeEventListener("keyup", onKey);
        live = null;
        clock.textContent = "";
        meterLabel.textContent = "";
        let closing = "";
        try {
          closing = (await api.examinerSession(sessionId, s.skipped)).closing;
        } catch (err) {
          closing = `The session's answers could not be read back: ${(err as Error).message}`;
        }
        qText.textContent = closing;
        say.textContent = s.aborted ? `Session ended. ${closing}` : `Session complete. ${closing}`;
        panel.append(h("p", {}, h("button", { class: "ghost-btn", type: "button", onClick: () => { stopAll(); void import("./improvise").then((m) => m.renderImprovise(root, goToReport)); } }, "New session")));
        if (done.length) {
          try { await getSpeaker("examiner").speak(textPlan(closing)); } catch { /* the text is on screen */ }
        }
        return;
      }
    }
  }

  live = { abort: () => { if (s.phase !== "done") dispatch({ type: "abort" }); stopAll(); document.removeEventListener("keydown", onKey); document.removeEventListener("keyup", onKey); } };
  dispatch({ type: "start", total: questions.length });
}

function openLink(takeId: string, goToReport: () => void): HTMLElement {
  return h("button", { class: "linklike small", type: "button", onClick: async () => {
    stopExaminer();
    state.setTake(await api.getAnyTake(takeId));
    goToReport();
  } }, "Open its report");
}
