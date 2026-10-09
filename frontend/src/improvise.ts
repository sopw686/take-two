/** Improvise: pick a topic and a time goal, think for a moment, speak unscripted, get coached.
 *  No script and no marks; the report compares the take with editable reference bands. */

import { runAnalysis, unsavedRecordingNote } from "./analysisRun";
import { api } from "./api";
import { clear, fmtClock, h } from "./dom";
import { Recorder, showLevel } from "./recorder";
import { state } from "./state";
import type { ImprovAnalysis, Topic } from "./types";

const PREFS_KEY = "taketwo.improv";
const GOALS = [30, 60, 120, 180, 300];
const PREP = [0, 15, 30];

interface Prefs { category: string; goal_s: number; content: boolean; prep_s: number; topic: string; custom: string }

function loadPrefs(): Prefs {
  const d: Prefs = { category: "All", goal_s: 60, content: false, prep_s: 15, topic: "", custom: "" };
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
  clearInterval(ticker);
  active?.cancel();
  active = null;
}

/** Pre-fill the next take with a topic (used by "Try again" on the report). */
export function presetTopic(topic: string): void {
  const p = loadPrefs();
  p.custom = "";
  p.topic = topic;
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
  const currentTopic = () => prefs.custom.trim() || prefs.topic;
  const showTopic = () => {
    topicText.textContent = currentTopic() || "Shuffle for a topic";
    const t = topics.find((x) => x.text === currentTopic());
    topicMeta.textContent = prefs.custom.trim() ? "your own topic" : t ? `${t.category} · ${t.level}` : "";
    startBtn.toggleAttribute("disabled", !currentTopic());
  };
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
    fileInput.setAttribute("disabled", "");
    void submit(f, f.name, runPanel, () => fileInput.removeAttribute("disabled"));
  });

  async function submit(blob: Blob, filename: string, host: HTMLElement, onFail: () => void): Promise<void> {
    const content = prefs.content && !!llm?.available;
    const topic = currentTopic();
    const label = labelInput.value.trim();
    const settings = state.effectiveSettings();
    const ok = await runAnalysis({
      host, blob, filename,
      message: state.health?.audio_leaves_machine
        ? "Transcribing with the configured cloud service…"
        : `Transcribing and measuring on this computer (${state.health?.stt.model ?? "local model"})…`,
      start: () => api.createImprov(blob, filename, topic, prefs.goal_s, content, settings, label),
      retry: (id) => api.retryTake(id, { settings }) as Promise<ImprovAnalysis>,
      open: (a) => state.setImprov(a),
      goToReport,
      onAbandon: () => void renderImprovise(root, goToReport),
    });
    if (!ok) onFail();
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
      hint.textContent = frac < 0.8 ? "" : frac < 1 ? "Start heading for your closing line." : "Time. Land your last sentence and stop.";
      if (frac >= 2) void finish(); // safety stop
    };
    tick();
    ticker = window.setInterval(tick, 200);
  }

  root.append(
    h("div", { class: "improv-setup" },
      h("section", { class: "card topic-card" },
        h("div", { class: "topic-head" }, h("h3", {}, "Topic"), h("button", { class: "ghost-btn", type: "button", onClick: shuffle }, "Shuffle")),
        topicText, topicMeta, catChips, customInput),
      h("div", { class: "improv-options" },
        h("section", { class: "card" }, h("h3", {}, "Time goal"), goalChips,
          h("label", { class: "small muted" }, "Custom ", customGoal)),
        h("section", { class: "card" }, h("h3", {}, "Thinking time"), prepChips,
          h("p", { class: "muted small" }, "A short pause to choose an opening line before the clock starts."))),
      h("section", { class: "card" }, h("h3", {}, "Coaching"), modes),
      h("div", { class: "rec-panel" }, startBtn, labelInput, status, runPanel),
      h("details", { class: "card" }, h("summary", {}, "…or upload a recording on this topic"),
        h("p", { class: "muted small" }, "Any audio file works (webm, wav, m4a, mp3)."), fileInput),
      h("p", { class: "muted small" }, "What gets measured: time against your goal, pace, filler words, long pauses and restarts, hedges (“I think”, “kind of”), "
        + "statements that end rising or fading, words that were hard to catch, and vocal variety (pitch range, loudness, pace changes, pauses between sentences, opening energy). "
        + "Every target is a reference band you can change in Settings; there is no overall score.")),
  );
  if (!currentTopic()) shuffle();
  else showTopic();
}
