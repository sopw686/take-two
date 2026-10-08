import "./styles.css";
import { api } from "./api";
import { h } from "./dom";
import { renderEditor } from "./editor";
import { renderRehearse, stopRehearsal } from "./rehearse";
import { renderReport } from "./report";
import { openSettings } from "./settings";
import { state } from "./state";
import { renderTakes } from "./takes";

type Tab = "script" | "rehearse" | "report" | "takes";
const main = document.getElementById("main") as HTMLElement;
const tabs = document.getElementById("tabs") as HTMLElement;
const privacy = document.getElementById("privacy") as HTMLElement;

function currentTab(): Tab {
  const t = location.hash.replace("#", "") as Tab;
  return (["script", "rehearse", "report", "takes"] as Tab[]).includes(t) ? t : "script";
}

function go(tab: Tab): void {
  if (location.hash !== `#${tab}`) location.hash = tab;
  else render();
}

function render(): void {
  const tab = currentTab();
  tabs.querySelectorAll("a").forEach((a) => a.classList.toggle("active", a.dataset.tab === tab));
  if (tab !== "rehearse") stopRehearsal();
  (document.getElementById("player") as HTMLAudioElement).pause();
  switch (tab) {
    case "script": renderEditor(main); break;
    case "rehearse": renderRehearse(main, () => go("report")); break;
    case "report": renderReport(main); break;
    case "takes": void renderTakes(main, () => go("report")); break;
  }
}

async function boot(): Promise<void> {
  try {
    state.health = await api.health();
    if (!state.settings) state.setSettings({ ...state.health.defaults });
    const stt = state.health.stt;
    privacy.replaceChildren(
      state.health.audio_leaves_machine
        ? h("span", { class: "warn" }, `Audio is sent to a cloud transcription service (${stt.backend}) because the server was configured with a key for it.`)
        : h("span", {}, `Audio stays on this computer. Transcription runs locally with ${stt.model} on ${stt.device}${stt.loaded ? "" : " (loading…)"}.`),
      state.health.llm.available
        ? h("span", { class: "muted" }, ` Suggestions use ${state.health.llm.provider}; it only ever sees script text and measured numbers, never audio.`)
        : h("span", { class: "muted" }, " No LLM key configured: suggestions are off, everything else works."),
    );
  } catch (err) {
    privacy.replaceChildren(h("span", { class: "warn" }, `Cannot reach the Marked server: ${(err as Error).message}`));
  }
  if (!state.scriptText) {
    try {
      state.setScript((await api.sample()).text);
    } catch {
      /* server down; editor stays empty */
    }
  }
  const last = state.lastTakeId();
  if (last && !state.analysis) {
    try {
      state.setAnalysis(await api.getTake(last));
    } catch {
      /* take may have been deleted */
    }
  }
  render();
}

window.addEventListener("hashchange", render);
(document.getElementById("settings-btn") as HTMLButtonElement).addEventListener("click", () => openSettings(async () => {
  const a = state.analysis;
  if (a) {
    try {
      state.setAnalysis(await api.reanalyze(a.take_id, state.scriptText, state.effectiveSettings()));
    } catch (err) {
      console.warn("re-analysis after settings change failed", err);
    }
  }
  render();
}));
void boot();
