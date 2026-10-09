import { runAnalysis, unsavedRecordingNote } from "./analysisRun";
import { api } from "./api";
import { clear, fmtClock, h } from "./dom";
import { Meter, extFor, pickMimeType } from "./meter";
import { createPrompter } from "./prompter";
import { plannedSectionAt, sections } from "./scriptinfo";
import { state } from "./state";
import type { Analysis } from "./types";

let stream: MediaStream | null = null;
let recorder: MediaRecorder | null = null;
let chunks: Blob[] = [];
let meter: Meter | null = null;
let startedAt = 0;
let timer = 0;
let latestDb = -100;
let paceRec: SpeechRecognitionLike | null = null;
let viewAbort: AbortController | null = null;

interface SpeechRecognitionLike {
  continuous: boolean; interimResults: boolean; lang: string;
  onresult: ((ev: SpeechRecognitionEventLike) => void) | null;
  onerror: ((ev: unknown) => void) | null;
  start(): void; stop(): void;
}
interface SpeechRecognitionEventLike {
  resultIndex: number;
  results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }>;
}

const CALIBRATION_SENTENCE = "The quick brown fox jumps over the lazy dog, and the results were clear by the third week.";

export function renderRehearse(root: HTMLElement, goToReport: () => void): void {
  clear(root);
  viewAbort?.abort();
  viewAbort = new AbortController();
  const script = state.scriptText;
  const secs = sections(script);
  if (!script.trim()) {
    root.append(h("p", { class: "muted" }, "Write or load a script first (Script tab)."));
    return;
  }
  const prompter = createPrompter(script, viewAbort.signal);

  const clock = h("div", { class: "clock" }, "0:00");
  const planned = h("div", { class: "planned muted" }, "");
  const meterBar = h("div", { class: "meter-fill" });
  const meterLabel = h("div", { class: "meter-label muted small" }, "");
  const meterWrap = h("div", { class: "meter" }, h("div", { class: "meter-track" }, h("div", { class: "meter-baseline" }), meterBar), meterLabel);
  const status = h("p", { class: "status muted", role: "status" }, "");
  const runPanel = h("div", { class: "run-panel" }, unsavedRecordingNote());
  const recBtn = h("button", { class: "primary rec-btn", type: "button" }, "Start recording") as HTMLButtonElement;
  const labelInput = h("input", { type: "text", placeholder: "Label this take (optional)", class: "label-input" }) as HTMLInputElement;

  const updatePlanned = () => {
    const t = (performance.now() - startedAt) / 1000;
    clock.textContent = fmtClock(t);
    prompter.tick(t);
    const p = plannedSectionAt(secs, t);
    if (p.section) planned.textContent = `Planned section at this point: ${p.section.name || "Untitled"} (${fmtClock(p.into)} of ${fmtClock(p.total)} budget)`;
    else if (p.total > 0) planned.textContent = `Past the total budget by ${fmtClock(p.into)}`;
    else planned.textContent = "No section budgets set; add [m:ss] to section headers to track them here.";
  };

  const showLevel = (db: number) => {
    latestDb = db;
    const base = state.calibration?.baseline_db ?? null;
    if (base !== null) {
      const rel = db - base;
      const pct = Math.max(0, Math.min(100, 50 + rel * 2.5));
      meterBar.style.width = `${pct}%`;
      meterBar.className = "meter-fill " + (rel > 6 ? "loud" : rel < -12 ? "quiet" : "ok");
      meterLabel.textContent = db < -60 ? "silence" : `${rel >= 0 ? "+" : ""}${rel.toFixed(0)} dB relative to your calibrated level`;
    } else {
      const pct = Math.max(0, Math.min(100, (db + 60) * (100 / 60)));
      meterBar.style.width = `${pct}%`;
      meterBar.className = "meter-fill ok";
      meterLabel.textContent = db < -60 ? "silence" : `${db.toFixed(0)} dBFS (calibrate below to make this relative to you)`;
    }
  };

  async function openMic(): Promise<MediaStream> {
    if (stream) return stream;
    stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false } });
    meter = new Meter();
    meter.onLevel = showLevel;
    await meter.start(stream);
    return stream;
  }
  function closeMic(): void {
    meter?.stop();
    meter = null;
    stream?.getTracks().forEach((t) => t.stop());
    stream = null;
  }

  async function startRecording(): Promise<void> {
    try {
      const s = await openMic();
      const mime = pickMimeType();
      recorder = new MediaRecorder(s, mime ? { mimeType: mime } : undefined);
      chunks = [];
      recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      recorder.onstop = async () => {
        const blob = new Blob(chunks, { type: recorder?.mimeType || mime || "audio/webm" });
        closeMic();
        stopPace();
        clearInterval(timer);
        prompter.stop();
        forgetBtn?.removeAttribute("disabled");
        settingsBtn()?.removeAttribute("disabled");
        await submit(blob, `take.${extFor(blob.type)}`);
      };
      recorder.start(250);
      startPace();
      startedAt = performance.now();
      timer = window.setInterval(updatePlanned, 200);
      updatePlanned();
      prompter.start();
      recBtn.blur();  // Space moves the teleprompter now; it must not reach the button
      forgetBtn?.setAttribute("disabled", "");
      // Saving Settings re-renders the tab, which would orphan the live take.
      settingsBtn()?.setAttribute("disabled", "");
      recBtn.textContent = "Stop and analyze";
      recBtn.classList.add("recording");
      fileInput.disabled = true;
      runPanel.replaceChildren(...[unsavedRecordingNote()].filter((x): x is HTMLElement => x !== null));
      status.textContent = "Recording. Speak as you would in the talk.";
    } catch (err) {
      status.textContent = `Microphone unavailable: ${(err as Error).message}. You can upload a recording instead.`;
    }
  }

  async function submit(blob: Blob, filename: string): Promise<void> {
    recBtn.setAttribute("disabled", "");
    fileInput.disabled = true;
    recBtn.textContent = "Analyzing…";
    status.textContent = "";
    const label = labelInput.value.trim();
    const settings = state.effectiveSettings();
    const ok = await runAnalysis({
      host: runPanel, blob, filename,
      message: state.health?.audio_leaves_machine
        ? "Transcribing with the configured cloud service…"
        : `Transcribing on this computer (${state.health?.stt.model ?? "local model"})…`,
      start: () => api.createTake(blob, filename, script, settings, label),
      retry: async (id) => {
        recBtn.setAttribute("disabled", "");
        fileInput.disabled = true;
        try {
          return await (api.retryTake(id, { settings }) as Promise<Analysis>);
        } catch (err) {
          recBtn.removeAttribute("disabled");
          fileInput.disabled = false;
          throw err;
        }
      },
      open: (a) => state.setAnalysis(a),
      goToReport,
      onAbandon: () => {
        if (recorder?.state === "recording") {
          recorder.onstop = null;
          recorder.stop();
        }
        closeAll();
        renderRehearse(root, goToReport);
      },
    });
    if (!ok) {
      recBtn.removeAttribute("disabled");
      fileInput.disabled = false;
      recBtn.textContent = "Start recording";
      recBtn.classList.remove("recording");
    }
  }

  recBtn.addEventListener("click", () => {
    if (recorder && recorder.state === "recording") recorder.stop();
    else void startRecording();
  });

  const fileInput = h("input", { type: "file", accept: "audio/*,.webm,.wav,.m4a,.mp3,.ogg" }) as HTMLInputElement;
  fileInput.addEventListener("change", () => {
    const f = fileInput.files?.[0];
    if (f) void submit(f, f.name);
  });

  // Calibration -------------------------------------------------------------
  const calibInfo = h("p", { class: "muted small" },
    state.calibration ? `Calibrated ${new Date(state.calibration.measured_at).toLocaleString()} at ${state.calibration.baseline_db.toFixed(0)} dBFS.` : "Not calibrated yet. The meter will show absolute levels until you do.");
  const calibBtn = h("button", { class: "ghost-btn", type: "button" }, "Calibrate (4 s)") as HTMLButtonElement;
  calibBtn.addEventListener("click", async () => {
    try {
      await openMic();
    } catch (err) {
      calibInfo.textContent = `Microphone unavailable: ${(err as Error).message}`;
      return;
    }
    calibBtn.setAttribute("disabled", "");
    const samples: number[] = [];
    const end = performance.now() + 4000;
    calibInfo.textContent = "Read the sentence aloud now…";
    await new Promise<void>((resolve) => {
      const iv = setInterval(() => {
        if (latestDb > -55) samples.push(latestDb);
        if (performance.now() > end) {
          clearInterval(iv);
          resolve();
        }
      }, 50);
    });
    if (recorder?.state !== "recording") closeMic();
    calibBtn.removeAttribute("disabled");
    if (samples.length < 10) {
      calibInfo.textContent = "Heard too little speech to calibrate. Try again a little closer to the microphone.";
      return;
    }
    samples.sort((a, b) => a - b);
    const median = samples[Math.floor(samples.length / 2)];
    state.setCalibration({ baseline_db: median, measured_at: new Date().toISOString() });
    calibInfo.textContent = `Calibrated: your normal speaking level is ${median.toFixed(0)} dBFS. The meter is now relative to you.`;
  });

  // Live pace (stretch): browser speech recognition, opt-in because Chrome's implementation
  // sends audio to the browser vendor. Hidden entirely where the API does not exist.
  const SR = (window as unknown as { SpeechRecognition?: new () => SpeechRecognitionLike }).SpeechRecognition
    ?? (window as unknown as { webkitSpeechRecognition?: new () => SpeechRecognitionLike }).webkitSpeechRecognition;
  const paceOpt = h("input", { type: "checkbox" }) as HTMLInputElement;
  const paceValue = h("div", { class: "value muted" }, "–");
  const pacePanel = SR ? h("div", { class: "pace" },
    h("h3", {}, "Live pace (approximate)"),
    h("label", { class: "small" }, paceOpt, " Use the browser's speech recognition for a rough live words-per-minute. ",
      h("span", { class: "warn" }, "In Chrome this sends audio to Google; off by default.")),
    paceValue) : null;
  const startPace = () => {
    if (!SR || !paceOpt.checked) return;
    const rec = new SR();
    rec.continuous = true;
    rec.interimResults = true;
    rec.lang = "en-US";
    const samples: { t: number; words: number }[] = [];
    let committed = 0;
    rec.onresult = (ev: SpeechRecognitionEventLike) => {
      let interim = 0;
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const n = ev.results[i][0].transcript.trim().split(/\s+/).filter(Boolean).length;
        if (ev.results[i].isFinal) committed += n;
        else interim += n;
      }
      samples.push({ t: performance.now(), words: committed + interim });
      const now = performance.now();
      const old = samples.find((s) => now - s.t <= 10000) ?? samples[0];
      const dt = (now - old.t) / 1000;
      if (dt > 3) {
        const wpm = Math.max(0, (samples[samples.length - 1].words - old.words) / (dt / 60));
        paceValue.textContent = `${Math.round(wpm)} wpm over the last ${Math.round(dt)} s`;
        paceValue.className = "value";
      }
    };
    rec.onerror = () => { paceValue.textContent = "speech recognition unavailable"; };
    try {
      rec.start();
      paceRec = rec;
    } catch {
      paceValue.textContent = "could not start";
    }
  };
  const stopPace = () => {
    try { paceRec?.stop(); } catch { /* ignore */ }
    paceRec = null;
  };

  const sectionList = h("ul", { class: "section-list" },
    ...secs.map((s) => h("li", {}, h("span", { class: "sec-name" }, s.name || "Untitled"), " ",
      h("span", { class: "muted" }, s.budget_s !== null ? fmtClock(s.budget_s) : "no budget", ` · ${s.words} words`))));

  const forgetBtn = state.calibration ? h("button", { class: "ghost-btn small", type: "button", onClick: () => { state.setCalibration(null); renderRehearse(root, goToReport); } }, "Forget calibration") : null;

  root.append(
    h("div", { class: "rehearse-layout" },
      h("div", { class: "rehearse-main" },
        h("div", { class: "rec-bar" },
          h("div", { class: "rec-bar-row" }, clock, recBtn, labelInput),
          planned, status, runPanel),
        prompter.el,
      ),
      h("aside", { class: "rehearse-side" },
        h("div", { class: "meter-panel" }, h("h3", {}, "Loudness"), meterWrap, pacePanel),
        h("h3", {}, "Sections"),
        sectionList,
        h("div", { class: "upload-panel" },
          h("h3", {}, "…or upload a recording"),
          h("p", { class: "muted small" }, "Any audio file works (webm, wav, m4a, mp3). Useful for takes recorded on a phone."),
          fileInput),
        h("details", { class: "side-details", open: !state.calibration },
          h("summary", {}, "Calibration"),
          h("p", { class: "small" }, "Read this at your normal speaking volume:"),
          h("blockquote", {}, CALIBRATION_SENTENCE),
          calibBtn,
          calibInfo,
          forgetBtn),
      ),
    ),
  );
}

export function stopRehearsal(): void {
  viewAbort?.abort();
  viewAbort = null;
  if (recorder && recorder.state === "recording") recorder.stop();
  else closeAll();
}
const settingsBtn = () => document.getElementById("settings-btn");

function closeAll(): void {
  settingsBtn()?.removeAttribute("disabled");
  try { paceRec?.stop(); } catch { /* ignore */ }
  paceRec = null;
  meter?.stop();
  meter = null;
  stream?.getTracks().forEach((t) => t.stop());
  stream = null;
  clearInterval(timer);
}
