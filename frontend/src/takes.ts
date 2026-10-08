import { api } from "./api";
import { clear, fmtTime, h } from "./dom";
import { state } from "./state";
import type { TakeSummary } from "./types";

export async function renderTakes(root: HTMLElement, openReport: () => void): Promise<void> {
  clear(root);
  root.append(h("p", { class: "muted" }, "Loading takes…"));
  let takes: TakeSummary[] = [];
  try {
    takes = await api.listTakes();
  } catch (err) {
    clear(root).append(h("p", { class: "muted" }, `Could not list takes: ${(err as Error).message}`));
    return;
  }
  clear(root);
  if (!takes.length) {
    root.append(h("p", { class: "muted" }, "No takes yet. Takes are saved as files under takes/ next to the app."));
    return;
  }
  root.append(
    h("p", { class: "muted small" }, "Each take keeps its audio, transcript and analysis under takes/<id>/. Open one to see its report, or re-analyze it against an edited script."),
    h("ul", { class: "take-list" }, ...takes.map((t) => h("li", { class: state.analysis?.take_id === t.take_id ? "current" : "" },
      h("button", { class: "linklike", type: "button", onClick: async () => {
        state.setAnalysis(await api.getTake(t.take_id));
        openReport();
      } }, t.label || t.take_id),
      h("span", { class: "muted small" }, ` ${new Date(t.created_at).toLocaleString()} · ${fmtTime(t.duration_s)} · ${t.stt.model}`),
      h("ul", { class: "small" }, ...t.summary.map((s) => h("li", {}, s)))))),
  );
}
