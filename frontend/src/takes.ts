import { api } from "./api";
import { clear, fmtTime, h } from "./dom";
import { state } from "./state";
import type { CompareResult, TakeSummary } from "./types";

function statusWord(s: string): string {
  return ({ met: "met", near: "close", diverged: "diverged", short: "short", missing: "missing", unmeasurable: "n/a",
    not_found: "not found", over: "over", under: "under", no_budget: "no budget", defined: "defined", undefined: "undefined",
    never_spoken: "not spoken", not_checked: "n/a" } as Record<string, string>)[s] ?? s;
}
function statusClass(s: string): string {
  if (s === "defined") return "st-met";
  if (s === "undefined" || s === "never_spoken") return "st-diverged";
  return `st-${s}`;
}

function compareCard(cmp: CompareResult): HTMLElement {
  const takesHead = cmp.takes_info.map((t, i) => h("th", { title: new Date(t.created_at ?? "").toLocaleString() }, t.label || `take ${i + 1}`));
  const rows = cmp.marks.map((m) => {
    const name = m.kind === "KEY" ? `KEY · line ${(m.line ?? 0) + 1}` : m.kind === "section" ? `section ${m.name}` : m.kind === "DEFINE" ? `DEFINE: ${m.term}` : `${m.kind} · line ${(m.line ?? 0) + 1}`;
    const cells = cmp.takes_info.map((_, i) => {
      const st = m.statuses[i];
      const v = m.values[i];
      const val = v === null || v === undefined ? "" : m.kind === "KEY" ? ` ${v > 0 ? "+" : ""}${Math.round(v)}%` : m.kind === "section" ? ` ${v > 0 ? "+" : ""}${Math.round(v)} s` : ` ${v.toFixed(2)} s`;
      return h("td", {}, st ? h("span", { class: `mark ${statusClass(st)}` }, statusWord(st) + val) : h("span", { class: "muted" }, "–"));
    });
    return h("tr", {}, h("td", { class: "cmp-name" }, name, h("div", { class: "muted small" }, m.text ?? "")), ...cells);
  });
  return h("section", { class: "card" },
    h("h3", {}, `Across ${cmp.takes} take${cmp.takes === 1 ? "" : "s"} of this script`),
    cmp.summary.length ? h("ul", {}, ...cmp.summary.map((s) => h("li", {}, s))) : h("p", { class: "muted small" }, cmp.takes < 2 ? "Record another take of the same script to compare." : "No mark diverged in two or more takes."),
    h("div", { class: "cmp-wrap" }, h("table", { class: "cmp" }, h("thead", {}, h("tr", {}, h("th", {}, "Mark"), ...takesHead)), h("tbody", {}, ...rows))),
    h("p", { class: "muted small" }, "Percentages are the key line's rate against that take's own median; seconds are measured silences, or the section's time over (+) or under (−) its budget."));
}

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
  const cmpHolder = h("div", {});
  if (state.analysis && state.current === "script") {
    api.compare(state.analysis.take_id).then((cmp) => cmpHolder.replaceChildren(compareCard(cmp))).catch(() => undefined);
  }
  root.append(
    cmpHolder,
    h("p", { class: "muted small" }, "Each take keeps its audio, transcript and analysis under takes/<id>/. Open one to see its report, or re-analyze it against an edited script."),
    h("ul", { class: "take-list" }, ...takes.map((t) => h("li", { class: (state.current === "improv" ? state.improv?.take_id : state.analysis?.take_id) === t.take_id ? "current" : "" },
      t.mode === "improv" ? h("span", { class: "mode-badge" }, "Improvise") : null,
      h("button", { class: "linklike", type: "button", onClick: async () => {
        state.setTake(await api.getAnyTake(t.take_id));
        openReport();
      } }, t.mode === "improv" ? `${t.topic ?? "Improvise"}${t.label ? ` · ${t.label}` : ""}` : t.label || t.take_id),
      h("span", { class: "muted small" }, ` ${new Date(t.created_at).toLocaleString()} · ${fmtTime(t.duration_s)} · ${t.stt.model}`),
      h("ul", { class: "small" }, ...t.summary.map((s) => h("li", {}, s)))))),
  );
}
