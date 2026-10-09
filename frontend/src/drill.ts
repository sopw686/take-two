/** Line and section drills from the report: record just one [KEY] line or one section and judge it
 *  against the median of the full take it came from (a one-line take has no median of its own). */

import { runAnalysis } from "./analysisRun";
import { api } from "./api";
import { h } from "./dom";
import { player, playSegment, stopSegment } from "./player";
import { Recorder, showLevel } from "./recorder";
import { state } from "./state";
import type { Analysis } from "./types";

let active: { rec: Recorder | null; panel: HTMLElement } | null = null;
const settingsBtn = () => document.getElementById("settings-btn");

/** Close the open drill panel (and drop a recording in progress). */
export function stopDrill(): void {
  if (active?.rec) settingsBtn()?.removeAttribute("disabled");
  active?.rec?.cancel();
  active?.panel.remove();
  active = null;
}

/** A Drill button that opens the recorder right after `anchor` (a report line or section heading). */
export function drillButton(parent: Analysis, kind: "line" | "section", index: number, what: string, anchor: () => HTMLElement): HTMLElement {
  return h("button", { class: "ghost-btn small drill-btn", type: "button", title: `Record just ${what} and compare it with this take's median`,
    onClick: (e) => { e.stopPropagation(); openDrill(parent, kind, index, what, anchor()); } }, "Drill");
}

function openDrill(parent: Analysis, kind: "line" | "section", index: number, what: string, anchor: HTMLElement): void {
  stopDrill();
  const meterBar = h("div", { class: "meter-fill" });
  const meterLabel = h("div", { class: "meter-label muted small" }, "");
  const status = h("p", { class: "status muted small", role: "status" },
    parent.baseline.median_wpm
      ? `Say ${what} once. It is judged against this take's median of ${parent.baseline.median_wpm.toFixed(0)} wpm.`
      : `Say ${what} once. This take has no median, so rates cannot be compared; pauses still are.`);
  const runPanel = h("div", { class: "run-panel" });
  const result = h("div", { class: "drill-result" });
  const recBtn = h("button", { class: "primary", type: "button" }, "Record") as HTMLButtonElement;
  const fileInput = h("input", { type: "file", accept: "audio/*,.webm,.wav,.m4a,.mp3,.ogg", "aria-label": "Upload a recording of this drill" }) as HTMLInputElement;
  const panel = h("div", { class: "drill-panel", onClick: (e) => e.stopPropagation() },
    h("div", { class: "drill-head" }, h("strong", {}, `Drill: ${what}`), h("span", { class: "spacer" }),
      h("button", { class: "ghost-btn small", type: "button", onClick: stopDrill }, "Close")),
    status,
    h("div", { class: "drill-controls" }, recBtn, h("label", { class: "small muted" }, "or upload ", fileInput)),
    h("div", { class: "meter" }, h("div", { class: "meter-track" }, h("div", { class: "meter-baseline" }), meterBar), meterLabel),
    runPanel, result);
  anchor.after(panel);
  active = { rec: null, panel };

  const submit = async (blob: Blob, filename: string) => {
    recBtn.disabled = true;
    fileInput.disabled = true;
    const settings = state.effectiveSettings();
    await runAnalysis<Analysis>({
      host: runPanel, blob, filename,
      message: state.health?.audio_leaves_machine
        ? "Transcribing with the configured cloud service…"
        : `Transcribing on this computer (${state.health?.stt.model ?? "local model"})…`,
      start: () => api.startDrillJob(parent.take_id, blob, filename, kind, index, settings),
      retry: (id) => api.startRetryJob(id, { settings }),
      open: (d) => showResult(d),
      goToReport: () => undefined,  // the result stays here, under the line
      onFail: () => { recBtn.disabled = false; fileInput.disabled = false; },
    });
  };
  const showResult = (d: Analysis) => {
    runPanel.replaceChildren();
    recBtn.disabled = false;
    fileInput.disabled = false;
    recBtn.textContent = "Record again";
    result.replaceChildren(
      h("ul", { class: "drill-summary" }, ...(d.drill_summary ?? d.summary).map((s) => h("li", {}, s))),
      h("button", { class: "linklike small", type: "button", onClick: () => { stopSegmentAndPlay(d); } }, "Hear this try"));
  };
  // The try plays through the shared player and the report's recording is put back when it ends.
  const stopSegmentAndPlay = (d: Analysis) => {
    playSegment(d.audio_url, 0, d.duration_s, () => {
      const p = player();
      if (p.src.endsWith(d.audio_url)) p.src = parent.audio_url;
    });
  };

  recBtn.addEventListener("click", async () => {
    if (active?.rec?.recording) {
      const rec = active.rec;
      active.rec = null;
      recBtn.textContent = "Record";
      settingsBtn()?.removeAttribute("disabled");
      const { blob, filename } = await rec.stop();
      await submit(blob, filename);
      return;
    }
    stopSegment();
    player().pause();  // the playback must not end up in the recording
    recBtn.disabled = true;  // one recorder at a time, even if the microphone prompt is slow
    const rec = new Recorder();
    try {
      await rec.start((db) => showLevel(db, meterBar, meterLabel, state.calibration?.baseline_db ?? null));
    } catch (err) {
      recBtn.disabled = false;
      status.textContent = `Microphone unavailable: ${(err as Error).message}. You can upload a recording instead.`;
      return;
    }
    if (!active || active.panel !== panel) {
      rec.cancel();
      return;
    }
    active.rec = rec;
    recBtn.disabled = false;
    fileInput.disabled = true;
    // Saving Settings re-renders the report, which would throw the recording away.
    settingsBtn()?.setAttribute("disabled", "");
    result.replaceChildren();
    runPanel.replaceChildren();
    recBtn.textContent = "Stop and compare";
  });
  fileInput.addEventListener("change", () => {
    const f = fileInput.files?.[0];
    if (f) void submit(f, f.name);
  });
}
