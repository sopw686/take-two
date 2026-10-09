/** Improvise: pick a topic and a time goal, think for a moment, speak unscripted, get coached.
 *  No script and no marks; the report compares the take with editable reference bands. */

import { runAnalysis, unsavedRecordingNote } from "./analysisRun";
import { examinerSetup, stopExaminer } from "./examiner";
import { api } from "./api";
import { clear, fmtClock, h } from "./dom";
import { Recorder, showLevel } from "./recorder";
import { state } from "./state";
import { parseScript } from "./scriptinfo";
import type { ImprovAnalysis, Question, Topic } from "./types";

const PREFS_KEY = "taketwo.improv";
const GOALS = [30, 60, 120, 180, 300];
const PREP = [0, 15, 30];

interface Prefs {
  category: string; goal_s: number; content: boolean; prep_s: number; topic: string; custom: string;
  /** "questions": answer a likely audience question about the script instead of a topic. */
  source: "topic" | "questions" | "examiner"; question: Question | null; qcustom: string;
}

function loadPrefs(): Prefs {
  const d: Prefs = { category: "All", goal_s: 60, content: false, prep_s: 15, topic: "", custom: "", source: "topic", question: null, qcustom: "" };
  try {
    return { ...d, ...(JSON.parse(localStorage.getItem(PREFS_KEY) ?? "{}") as Partial<Prefs>) };
  } catch {
    return d;
  }
}
function savePrefs(p: Prefs): void {
  try { localStorage.setItem(PREFS_KEY, JSON.stringify(p)); } catch { /* storage may be unavailable */ }
}

let topicsCache: { categories: string[]; topics: Topic[] } | null = null;
let active: Recorder | null = null;
let ticker = 0;

export function stopImprovise(): void {
  stopExaminer();
  clearInterval(ticker);
  active?.cancel();
  active = null;
}

/** Questions proposed for a script, kept while the page is open so switching tabs does not ask again. */
let questionsCache: { script: string; questions: Question[]; note: string } | null = null;

/** Pre-fill the next take with a topic, or with the question it answered (used by "Try again" on the report). */
export function presetTopic(topic: string, question?: Question | null): void {
  const p = loadPrefs();
  if (question) {
    p.source = "questions";
    p.question = question.tag ? question : null;
    p.qcustom = question.tag ? "" : question.text;
  } else {
    p.source = "topic";
    p.custom = "";
    p.topic = topic;
  }
  savePrefs(p);
}

export async function renderImprovise(root: HTMLElement, goToReport: () => void): Promise<void> {
  stopImprovise();
  clear(root);
  if (!topicsCache) {
    try {
      topicsCache = await api.improvTopics();
    } catch (err) {
      root.append(h("p", { class: "muted" }, `Could not load topics: ${(err as Error).message}`));
      return;
    }
  }
  const { categories, topics } = topicsCache;
  const prefs = loadPrefs();

  // ---- topic --------------------------------------------------------------------
  const pool = () => topics.filter((t) => prefs.category === "All" || t.category === prefs.category);
  const shuffle = () => {
    const p = pool().filter((t) => t.text !== prefs.topic);
    const pick = p[Math.floor(Math.random() * p.length)] ?? pool()[0];
    prefs.topic = pick?.text ?? "";
    prefs.custom = "";
    customInput.value = "";
    savePrefs(prefs);
    showTopic();
  };
  const topicText = h("div", { class: "topic-text" });
  const topicMeta = h("div", { class: "muted small" });
  const customInput = h("input", { type: "text", class: "label-input topic-custom", maxlength: "200", placeholder: "…or type your own topic", value: prefs.custom }) as HTMLInputElement;
  customInput.addEventListener("input", () => { prefs.custom = customInput.value; savePrefs(prefs); showTopic(); });
  const currentQuestion = (): Question | null =>
    prefs.qcustom.trim() ? { text: prefs.qcustom.trim().split(/\s+/).join(" ") } : prefs.question;
  const currentTopic = () => prefs.source === "questions"
    ? currentQuestion()?.text ?? ""
    : prefs.custom.trim() || prefs.topic;
  const showTopic = () => {
    topicText.textContent = currentTopic() || "Shuffle for a topic";
    const t = topics.find((x) => x.text === currentTopic());
    topicMeta.textContent = prefs.custom.trim() ? "your own topic" : t ? `${t.category} · ${t.level}` : "";
    startBtn.toggleAttribute("disabled", !currentTopic());
    fileInput.toggleAttribute("disabled", !currentTopic());  // an upload answers the same topic or question
  };

  // ---- questions about my script (defense Q&A) ---------------------------------------
  const script = state.scriptText;
  const lineCount = parseScript(script).lines.length;
  const qList = h("div", { class: "goal-grid question-list" });
  const qNote = h("p", { class: "muted small", role: "status" });
  const qCustom = h("input", { type: "text", class: "label-input topic-custom", maxlength: "200",
    placeholder: "…or type your own question", value: prefs.qcustom }) as HTMLInputElement;
  let shown: Question[] = [];
  // The checked radio always shows the question Start will use (a typed question wins over a picked one).
  const syncRadios = () => qList.querySelectorAll<HTMLInputElement>("input").forEach((inp, i) => {
    inp.checked = !prefs.qcustom.trim() && prefs.question?.text === shown[i]?.text;
  });
  qCustom.addEventListener("input", () => {
    prefs.qcustom = qCustom.value;
    savePrefs(prefs);
    syncRadios();
    showTopic();
  });
  const showQuestions = (qs: Question[], note: string) => {
    qNote.textContent = note;
    shown = qs;
    if (prefs.question && !qs.some((q) => q.text === prefs.question?.text)) {
      prefs.question = null;  // a question no longer on screen must not be answered by accident
      savePrefs(prefs);
    }
    qList.replaceChildren(...qs.map((q) => {
      const inp = h("input", { type: "radio", name: "improv-question" }) as HTMLInputElement;
      inp.addEventListener("change", () => {
        prefs.question = q;
        prefs.qcustom = "";
        qCustom.value = "";
        savePrefs(prefs);
        showTopic();
      });
      return h("label", { title: q.line_text ? `Line ${(q.line_index ?? 0) + 1}: ${q.line_text}` : undefined }, inp,
        h("span", {}, q.text, h("small", {}, `${q.tag ?? ""} · about line ${(q.line_index ?? 0) + 1}`)));
    }));
    syncRadios();
    showTopic();
  };
  const genBtn = h("button", { class: "ghost-btn", type: "button", onClick: async () => {
    genBtn.setAttribute("disabled", "");
    qNote.textContent = `Reading your script (${lineCount} lines)…`;
    try {
      const r = await api.improvQuestions(script);
      const dropped = r.dropped.reduce((n, d) => n + d.count, 0);
      const note = !r.available || r.reason ? (r.reason ?? "")
        : `${r.questions.length} questions from ${qllm?.provider ?? "the model"}, which read only your script.`
          + (dropped ? ` ${dropped} more were dropped because the app could not check them (${r.dropped.map((d) => d.reason).join(", ")}).` : "");
      questionsCache = { script, questions: r.questions, note };
      showQuestions(r.questions, note);
    } catch (err) {
      qNote.textContent = `Could not get questions: ${(err as Error).message}`;
    }
    genBtn.removeAttribute("disabled");
  } }, "Propose likely questions") as HTMLButtonElement;
  const qllm = state.health?.llm;
  const genReason = !script.trim() ? "Write or load a script on the Script tab first."
    : !qllm?.available ? (qllm?.reason ?? "Proposing questions needs an ANTHROPIC_API_KEY on the server.") : "";
  if (genReason) genBtn.setAttribute("disabled", "");
  if (questionsCache && questionsCache.script === script) showQuestions(questionsCache.questions, questionsCache.note);
  else if (prefs.question?.tag) showQuestions([prefs.question], "The question you picked last time.");
  const questionsPanel = h("div", { class: "questions-panel" },
    h("p", { class: "muted small" }, "Practise the questions after your talk, pitch, defense or interview. Pick one the model proposes from the script on your Script tab, or type a question you expect. Your answer is an Improvise take on that question."),
    h("div", { class: "toolbar" }, genBtn, genReason ? h("span", { class: "muted small" }, genReason) : null),
    qNote, qList, qCustom);
  const catChips = h("div", { class: "chips" }, ...["All", ...categories].map((c) => {
    const b = h("button", { type: "button", class: `chip${prefs.category === c ? " on" : ""}` }, c) as HTMLButtonElement;
    b.addEventListener("click", () => {
      prefs.category = c;
      catChips.querySelectorAll(".chip").forEach((x) => x.classList.toggle("on", x === b));
      shuffle();
    });
    return b;
  }));

  // ---- goal --------------------------------------------------------------------------
  const customGoal = h("input", { type: "text", class: "label-input goal-custom", placeholder: "m:ss",
    value: GOALS.includes(prefs.goal_s) ? "" : fmtClock(prefs.goal_s) }) as HTMLInputElement;
  const goalChips = h("div", { class: "chips" }, ...GOALS.map((g) => {
    const b = h("button", { type: "button", class: `chip${prefs.goal_s === g && !customGoal.value ? " on" : ""}`, "data-g": g }, g < 60 ? `${g} s` : `${g / 60} min`) as HTMLButtonElement;
    b.addEventListener("click", () => {
      prefs.goal_s = g;
      customGoal.value = "";
      savePrefs(prefs);
      goalChips.querySelectorAll(".chip").forEach((x) => x.classList.toggle("on", x === b));
    });
    return b;
  }));
  customGoal.addEventListener("input", () => {
    const m = /^(\d+):(\d{1,2})$/.exec(customGoal.value.trim()) ?? /^(\d+)$/.exec(customGoal.value.trim());
    if (!m) return;
    const s = m.length === 3 && m[2] !== undefined ? parseInt(m[1], 10) * 60 + parseInt(m[2], 10) : parseInt(m[1], 10);
    if (s >= 10 && s <= 1800) {
      prefs.goal_s = s;
      savePrefs(prefs);
      goalChips.querySelectorAll(".chip").forEach((x) => x.classList.remove("on"));
    }
  });

  // ---- coaching mode -------------------------------------------------------------------
  const llm = state.health?.llm;
  const mode = (id: string, label: string, hint: string, disabled = false) => {
    const inp = h("input", { type: "radio", name: "improv-mode", value: id, disabled }) as HTMLInputElement;
    inp.checked = (id === "content") === (prefs.content && !!llm?.available);
    inp.addEventListener("change", () => { prefs.content = id === "content"; savePrefs(prefs); });
    return h("label", { class: disabled ? "disabled" : "" }, inp, h("span", {}, label, h("small", {}, hint)));
  };
  const modes = h("div", { class: "goal-grid" },
    mode("delivery", "Delivery only", "Measured on this computer: pace, fillers, hesitation, confidence, clarity and vocal variety."),
    mode("content", "Delivery + content",
      llm?.available ? `Also asks ${llm.provider} to review your hook, staying on topic, suspense and ending. It reads the transcript text only, never audio.`
        : "Needs an ANTHROPIC_API_KEY on the server.", !llm?.available));

  // ---- prep time ------------------------------------------------------------------------
  const prepChips = h("div", { class: "chips" }, ...PREP.map((p) => {
    const b = h("button", { type: "button", class: `chip${prefs.prep_s === p ? " on" : ""}` }, p ? `${p} s` : "none") as HTMLButtonElement;
    b.addEventListener("click", () => {
      prefs.prep_s = p;
      savePrefs(prefs);
      prepChips.querySelectorAll(".chip").forEach((x) => x.classList.toggle("on", x === b));
    });
    return b;
  }));

  const labelInput = h("input", { type: "text", placeholder: "Label this take (optional)", class: "label-input" }) as HTMLInputElement;
  const status = h("p", { class: "status muted", role: "status" }, "");
  const runPanel = h("div", { class: "run-panel" }, unsavedRecordingNote());
  const startBtn = h("button", { class: "primary big", type: "button" }, "Start") as HTMLButtonElement;
  startBtn.addEventListener("click", () => void runSession());

  const fileInput = h("input", { type: "file", accept: "audio/*,.webm,.wav,.m4a,.mp3,.ogg" }) as HTMLInputElement;
  fileInput.addEventListener("change", () => {
    const f = fileInput.files?.[0];
    if (!f) return;
    if (!currentTopic()) {
      status.textContent = prefs.source === "questions" ? "Pick or type a question first." : "Choose a topic first.";
      fileInput.value = "";
      return;
    }
    fileInput.setAttribute("disabled", "");
    void submit(f, f.name, runPanel, () => fileInput.removeAttribute("disabled"));
  });

  async function submit(blob: Blob, filename: string, host: HTMLElement, onFail: () => void): Promise<void> {
    const content = prefs.content && !!llm?.available;
    const topic = currentTopic();
    const label = labelInput.value.trim();
    const settings = state.effectiveSettings();
    await runAnalysis<ImprovAnalysis>({
      host, blob, filename,
      message: state.health?.audio_leaves_machine
        ? "Transcribing with the configured cloud service…"
        : `Transcribing and measuring on this computer (${state.health?.stt.model ?? "local model"})…`,
      start: () => api.startImprovJob(blob, filename, topic, prefs.goal_s, content, settings, label,
        prefs.source === "questions" ? currentQuestion() : null),
      retry: (id) => api.startRetryJob(id, { settings }),
      open: (a) => state.setImprov(a),
      goToReport,
      onFail,
      onAbandon: () => void renderImprovise(root, goToReport),
    });
  }

  // ---- the session: prep countdown, then recording against the goal ------------------------
  async function runSession(): Promise<void> {
    const topic = currentTopic();
    if (!topic) return;
    const goal = prefs.goal_s;
    const big = h("div", { class: "clock" }, "");
    const phase = h("div", { class: "phase muted" }, "");
    const hint = h("p", { class: "status muted", role: "status" }, "");
    const livePanel = h("div", { class: "run-panel" });
    const bar = h("div", { class: "goal-fill" });
    const meterBar = h("div", { class: "meter-fill" });
    const meterLabel = h("div", { class: "meter-label muted small" }, "");
    const stopBtn = h("button", { class: "primary big recording", type: "button" }, "Stop and analyze") as HTMLButtonElement;
    const cancelBtn = h("button", { class: "ghost-btn", type: "button" }, "Cancel") as HTMLButtonElement;
    const skipBtn = h("button", { class: "ghost-btn", type: "button" }, "Start speaking now") as HTMLButtonElement;
    const panel = h("div", { class: "improv-live" },
      h("div", { class: "live-topic" }, topic),
      phase, big,
      h("div", { class: "goal-track" }, bar),
      hint,
      h("div", { class: "live-actions" }, skipBtn, stopBtn, cancelBtn),
      livePanel,
      h("div", { class: "meter" }, h("div", { class: "meter-track" }, h("div", { class: "meter-baseline" }), meterBar), meterLabel));
    stopBtn.hidden = true;
    clear(root).append(panel);

    let done = false;
    cancelBtn.addEventListener("click", () => {
      done = true;
      stopImprovise();
      void renderImprovise(root, goToReport);
    });

    // Prep countdown (skippable).
    if (prefs.prep_s > 0) {
      phase.textContent = "Thinking time: plan an opening line and where you'll end";
      await new Promise<void>((resolve) => {
        const end = performance.now() + prefs.prep_s * 1000;
        const tick = () => {
          const left = Math.max(0, (end - performance.now()) / 1000);
          big.textContent = fmtClock(Math.ceil(left));
          if (left <= 0) { clearInterval(ticker); resolve(); }
        };
        skipBtn.onclick = () => { clearInterval(ticker); resolve(); };
        tick();
        ticker = window.setInterval(tick, 100);
      });
    }
    if (done) return;
    skipBtn.hidden = true;

    const rec = new Recorder();
    active = rec;
    try {
      await rec.start((db) => showLevel(db, meterBar, meterLabel, state.calibration?.baseline_db ?? null));
    } catch (err) {
      active = null;
      void renderImprovise(root, goToReport).then(() => {
        root.querySelector(".improv-setup .status")!.textContent = `Microphone unavailable: ${(err as Error).message}. You can upload a recording instead.`;
      });
      return;
    }
    phase.textContent = "Speaking";
    stopBtn.hidden = false;
    const t0 = performance.now();
    const finish = async () => {
      if (done) return;
      done = true;
      clearInterval(ticker);
      stopBtn.setAttribute("disabled", "");
      cancelBtn.setAttribute("disabled", "");
      stopBtn.textContent = "Analyzing…";
      const { blob, filename } = await rec.stop();
      active = null;
      hint.textContent = "";
      await submit(blob, filename, livePanel, () => {
        stopBtn.hidden = true;
        cancelBtn.hidden = true;
      });
    };
    stopBtn.addEventListener("click", () => void finish());
    const tick = () => {
      const t = (performance.now() - t0) / 1000;
      const left = goal - t;
      big.textContent = left >= 0 ? fmtClock(Math.ceil(left)) : `+${fmtClock(-left)}`;
      bar.style.width = `${Math.min(100, (t / goal) * 100)}%`;
      const frac = t / goal;
      panel.classList.toggle("wrap-up", frac >= 0.8 && frac < 1);
      panel.classList.toggle("overtime", frac >= 1);
      const next = frac < 0.8 ? "" : frac < 1 ? "Start heading for your closing line." : "Time. Land your last sentence and stop.";
      if (hint.textContent !== next) hint.textContent = next;  // a live region: write only on change
      if (frac >= 2) void finish(); // safety stop
    };
    tick();
    ticker = window.setInterval(tick, 200);
  }

  const examinerPanel = examinerSetup(root, goToReport, () => {
    prefs.source = "questions";
    savePrefs(prefs);
    void renderImprovise(root, goToReport);
  });
  const topicPanel = h("div", { class: "topic-panel" },
    h("div", { class: "topic-head" }, h("h3", {}, "Topic"), h("button", { class: "ghost-btn", type: "button", onClick: shuffle }, "Shuffle")),
    topicText, topicMeta, catChips, customInput);
  const sourceBtns: HTMLButtonElement[] = [];
  function sourceChip(id: Prefs["source"], label: string): HTMLButtonElement {
    const b = h("button", { type: "button", class: "chip", "aria-pressed": String(prefs.source === id), onClick: () => {
      prefs.source = id;
      savePrefs(prefs);
      showSource();
      if (id === "topic" && !currentTopic()) shuffle();
      else showTopic();
    } }, label) as HTMLButtonElement;
    b.dataset.source = id;
    sourceBtns.push(b);
    return b;
  }
  function showSource(): void {
    topicPanel.hidden = prefs.source !== "topic";
    questionsPanel.hidden = prefs.source !== "questions";
    examinerPanel.hidden = prefs.source !== "examiner";
    for (const el of root.querySelectorAll<HTMLElement>(".not-examiner")) el.hidden = prefs.source === "examiner";
    for (const b of sourceBtns) {
      b.classList.toggle("on", b.dataset.source === prefs.source);
      b.setAttribute("aria-pressed", String(b.dataset.source === prefs.source));
    }
  }

  root.append(
    h("div", { class: "improv-setup" },
      h("section", { class: "card topic-card" },
        h("div", { class: "chips source-chips" }, sourceChip("topic", "A topic"), sourceChip("questions", "Questions about my script"),
          sourceChip("examiner", "Spoken examiner")),
        topicPanel, questionsPanel, examinerPanel),
      h("div", { class: "improv-options not-examiner" },
        h("section", { class: "card" }, h("h3", {}, "Time goal"), goalChips,
          h("label", { class: "small muted" }, "Custom ", customGoal)),
        h("section", { class: "card" }, h("h3", {}, "Thinking time"), prepChips,
          h("p", { class: "muted small" }, "A short pause to choose an opening line before the clock starts."))),
      h("section", { class: "card not-examiner" }, h("h3", {}, "Coaching"), modes),
      h("div", { class: "rec-panel not-examiner" }, startBtn, labelInput, status, runPanel),
      h("details", { class: "card not-examiner" }, h("summary", {}, "…or upload a recording of your answer"),
        h("p", { class: "muted small" }, "Any audio file works (webm, wav, m4a, mp3)."), fileInput),
      h("p", { class: "muted small" }, "What gets measured: time against your goal, pace, filler words, long pauses and restarts, hedges (“I think”, “kind of”), "
        + "statements that end rising or fading, words that were hard to catch, and vocal variety (pitch range, loudness, pace changes, pauses between sentences, opening energy). "
        + "Every target is a reference band you can change in Settings; there is no overall score.")),
  );
  showSource();
  if (prefs.source === "topic" && !currentTopic()) shuffle();
  else showTopic();
}
