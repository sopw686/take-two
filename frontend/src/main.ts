import "./styles.css";
import { api, ApiError } from "./api";
import { stopDrill } from "./drill";
import { closeHear } from "./hearit";
import { stopAll } from "./speaker";
import { stopSegment } from "./player";
import { h } from "./dom";
import { renderEditor } from "./editor";
import { presetTopic, renderImprovise, stopImprovise } from "./improvise";
import { renderImprovReport } from "./improvreport";
import { renderRehearse, stopRehearsal } from "./rehearse";
import { renderReport } from "./report";
import { openSettings } from "./settings";
import { state } from "./state";
import { installTipPinning } from "./status";
import { renderTakes } from "./takes";

type Tab = "script" | "rehearse" | "improvise" | "report" | "takes";
const main = document.getElementById("main") as HTMLElement;
const tabs = document.getElementById("tabs") as HTMLElement;
const privacy = document.getElementById("privacy") as HTMLElement;

function currentTab(): Tab {
  const t = location.hash.replace("#", "") as Tab;
  return (["script", "rehearse", "improvise", "report", "takes"] as Tab[]).includes(t) ? t : "script";
}

function go(tab: Tab): void {
  if (location.hash !== `#${tab}`) location.hash = tab;
  else render();
}

function render(): void {
  const tab = currentTab();
  tabs.querySelectorAll("a").forEach((a) => a.classList.toggle("active", a.dataset.tab === tab));
  if (tab !== "rehearse") stopRehearsal();
  if (tab !== "improvise") stopImprovise();
  stopDrill();
  closeHear();
  stopAll();
  stopSegment();
  const p = document.getElementById("player") as HTMLAudioElement;
  p.pause();
  p.ontimeupdate = null;  // the view that set it is gone
  switch (tab) {
    case "script": renderEditor(main); break;
    case "rehearse": renderRehearse(main, () => go("report")); break;
    case "improvise": void renderImprovise(main, () => go("report")); break;
    case "report":
      if (state.current === "improv" && state.improv) renderImprovReport(main, (topic, question) => { presetTopic(topic, question); go("improvise"); });
      else renderReport(main);
      break;
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
      state.health.tts?.sends
        ? h("span", { class: "warn" }, ` Hear it can use ${state.health.tts.label}, which sends ${state.health.tts.sends}, only if you pick that voice; the default is your browser's voice.`)
        : "",
    );
  } catch (err) {
    privacy.replaceChildren(h("span", { class: "warn" }, `Cannot reach the Take Two server: ${(err as Error).message}`));
  }
  if (!state.scriptText) {
    try {
      state.setScript((await api.sample()).text);
    } catch {
      /* server down; editor stays empty */
    }
  }
  if (!state.analysis && !state.improv) await openStartupTake();
  render();
}

/** The take this browser last opened, else the newest finished take on disk (a fresh browser should not say "No take yet"). */
async function openStartupTake(): Promise<void> {
  const last = state.lastTakeId();
  if (last) {
    try {
      state.setTake(await api.getAnyTake(last));
      return;
    } catch {
      /* deleted, or never finished */
    }
  }
  try {
    const done = (await api.listTakes()).filter((t) => (t.status ?? "done") === "done" && t.kind !== "drill");
    const pick = done.find((t) => (t.kind ?? "take") === "take") ?? done[0];
    if (pick) state.setTake(await api.getAnyTake(pick.take_id));
  } catch {
    /* server down: the report shows its empty state */
  }
}

installTipPinning();
window.addEventListener("hashchange", render);
(document.getElementById("settings-btn") as HTMLButtonElement).addEventListener("click", () => openSettings(async () => {
  let failed: unknown = null;
  try {
    if (state.current === "improv" && state.improv) {
      state.setImprov(await api.reanalyzeImprov(state.improv.take_id, state.effectiveSettings()));
    } else if (state.analysis) {
      // null: keep the take's own script; the editor may hold a different one.
      state.setAnalysis(await api.reanalyze(state.analysis.take_id, null, state.effectiveSettings()));
    }
  } catch (err) {
    failed = err;  // e.g. the take's script sets a value the new settings clash with
  }
  render();
  if (failed) {
    const msg = failed instanceof ApiError ? failed.detail : (failed as Error).message;
    main.prepend(h("p", { class: "small warn", role: "status" }, `The settings were saved, but re-analyzing the open take with them failed: ${msg}`));
  }
}));
void boot();
