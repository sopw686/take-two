import { api } from "./api";
import { clear, fmtTime, h } from "./dom";
import { state } from "./state";
import { statusChip } from "./status";
import type { CompareResult, TakeSummary } from "./types";

function statusWord(s: string): string {
  return ({ met: "met", near: "close", diverged: "diverged", short: "short", missing: "missing", unmeasurable: "n/a",
    not_found: "not found", over: "over", under: "under", no_budget: "no budget", defined: "defined", undefined: "undefined",
    never_spoken: "not spoken", not_checked: "n/a" } as Record<string, string>)[s] ?? s;
}

function compareCard(cmp: CompareResult): HTMLElement {
  const takesHead = cmp.takes_info.map((t, i) => h("th", { title: new Date(t.created_at ?? "").toLocaleString() }, t.label || `take ${i + 1}`));
  const rows = cmp.marks.map((m) => {
    const name = m.kind === "KEY" ? `KEY · line ${(m.line ?? 0) + 1}` : m.kind === "section" ? `section ${m.name}` : m.kind === "DEFINE" ? `DEFINE: ${m.term}` : `${m.kind} · line ${(m.line ?? 0) + 1}`;
    const cells = cmp.takes_info.map((_, i) => {
      const st = m.statuses[i];
      const v = m.values[i];
      const val = v === null || v === undefined ? "" : m.kind === "KEY" ? ` ${v > 0 ? "+" : ""}${Math.round(v)}%` : m.kind === "section" ? ` ${v > 0 ? "+" : ""}${Math.round(v)} s` : ` ${v.toFixed(2)} s`;
      return h("td", {}, st ? statusChip(st, statusWord(st) + val, { word: statusWord(st) }) : h("span", { class: "muted" }, "–"));
    });
    return h("tr", {}, h("td", { class: "cmp-name" }, name, h("div", { class: "muted small" }, m.text ?? "")), ...cells);
  });
  return h("section", { class: "card" },
    h("h3", {}, `Across ${cmp.takes} take${cmp.takes === 1 ? "" : "s"} of this script`),
    cmp.summary.length ? h("ul", {}, ...cmp.summary.map((s) => h("li", {}, s))) : h("p", { class: "muted small" }, cmp.takes < 2 ? "Record another take of the same script to compare." : "No mark diverged in two or more takes."),
    h("div", { class: "cmp-wrap" }, h("table", { class: "cmp" }, h("thead", {}, h("tr", {}, h("th", {}, "Mark"), ...takesHead)), h("tbody", {}, ...rows))),
    h("p", { class: "muted small" }, "Percentages are the key line's rate against that take's own median; seconds are measured silences, or the section's time over (+) or under (−) its budget."));
}

/** A button that copies the shipped example take into a new take and opens its report. */
export function exampleButton(openReport: () => void, onError: (msg: string) => void): HTMLButtonElement {
  const btn = h("button", { class: "ghost-btn", type: "button", onClick: async () => {
    btn.setAttribute("disabled", "");
    btn.textContent = "Loading the example…";
    try {
      state.setAnalysis(await api.loadExample(state.effectiveSettings()));
      if (btn.isConnected) openReport();
    } catch (err) {
      onError(`Could not load the example take: ${(err as Error).message}`);
      btn.removeAttribute("disabled");
      btn.textContent = "Load example take";
    }
  } }, "Load example take") as HTMLButtonElement;
  btn.title = "A synthetic-voice take of the coral reef script. Needs no microphone and no speech model.";
  return btn;
}

function takeTitle(t: TakeSummary): string {
  if (t.mode === "improv") return `${t.topic ?? "Improvise"}${t.label ? ` · ${t.label}` : ""}`;
  return t.label || t.take_id;
}

/** An upload that was never analyzed: say why, and offer Retry and Delete. */
function unfinishedItem(t: TakeSummary, root: HTMLElement, openReport: () => void): HTMLElement {
  const note = h("p", { class: "small", role: "status" }, t.status === "processing" ? `Being analyzed (${t.stage ?? "queued"})…` : (t.error ?? ""));
  const retry = h("button", { class: "ghost-btn small", type: "button", onClick: async () => {
    let script: string | undefined;
    if (t.needs_script) {
      if (!state.scriptText.trim()) {
        note.textContent = "This take saved no script. Write or load the script it was recorded with on the Script tab, then retry.";
        return;
      }
      if (!confirm("This take saved no script. Retry it with the script currently on your Script tab?")) return;
      script = state.scriptText;
    }
    retry.setAttribute("disabled", "");
    del.setAttribute("disabled", "");
    note.textContent = "Analyzing the saved recording…";
    try {
      let job = await api.startRetryJob(t.take_id, { script, settings: state.effectiveSettings() });
      while (job.status === "queued" || job.status === "running") {
        const text = `Analyzing the saved recording (${job.stage && job.stage !== "starting" ? job.stage : "starting"})…`;
        if (note.textContent !== text) note.textContent = text;
        await new Promise((r) => setTimeout(r, 500));
        job = await api.job(t.take_id);
      }
      if (job.status === "failed" || !job.result) throw new Error(job.error ?? "the analysis did not finish");
      state.setTake(job.result);
      if (note.isConnected) openReport();
    } catch (err) {
      note.textContent = `Retry failed: ${(err as Error).message}`;
      retry.removeAttribute("disabled");
      del.removeAttribute("disabled");
    }
  } }, "Retry") as HTMLButtonElement;
  const del = h("button", { class: "ghost-btn small", type: "button", onClick: async () => {
    if (!confirm(`Delete the unfinished take from ${new Date(t.created_at).toLocaleString()}? Its recording will be removed from disk.`)) return;
    try {
      await api.deleteTake(t.take_id);
      void renderTakes(root, openReport);
    } catch (err) {
      note.textContent = `Delete failed: ${(err as Error).message}`;
    }
  } }, "Delete") as HTMLButtonElement;
  if (!t.retryable) retry.hidden = true;
  return h("li", { class: "unfinished" },
    h("span", { class: "mode-badge warn-badge" }, t.status === "processing" ? "Analyzing" : "Not analyzed"),
    t.mode === "improv" ? h("span", { class: "mode-badge" }, "Improvise") : null,
    h("span", { class: "take-title" }, takeTitle(t)),
    h("span", { class: "muted small" }, ` ${new Date(t.created_at).toLocaleString()}`),
    note,
    t.status === "failed" ? h("div", { class: "take-actions" }, retry, del) : null);
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
  const errLine = h("p", { class: "small warn", role: "status" });
  const head = h("div", { class: "takes-head" },
    h("p", { class: "muted small" }, "Each take keeps its audio, transcript and analysis under takes/<id>/. Open one to see its report, or re-analyze it against an edited script."),
    exampleButton(openReport, (msg) => { errLine.textContent = msg; }));
  if (!takes.length) {
    root.append(head, errLine, h("p", { class: "muted" }, "No takes yet. Record one in Rehearse, or load the example take."));
    return;
  }
  const cmpHolder = h("div", {});
  if (state.analysis && state.current === "script") {
    if ((state.analysis.kind ?? "take") === "take") {
      api.compare(state.analysis.take_id).then((cmp) => cmpHolder.replaceChildren(compareCard(cmp))).catch(() => undefined);
    } else {
      cmpHolder.replaceChildren(h("p", { class: "muted small" }, "The take you have open is the example (a synthetic voice), so it is not compared with your own takes. Record the script yourself to start a comparison."));
    }
  }
  const currentId = state.current === "improv" ? state.improv?.take_id : state.analysis?.take_id;
  root.append(
    cmpHolder,
    head,
    errLine,
    h("ul", { class: "take-list" }, ...takes.map((t) => (t.status ?? "done") !== "done" ? unfinishedItem(t, root, openReport) : h("li", { class: currentId === t.take_id ? "current" : "" },
      t.mode === "improv" ? h("span", { class: "mode-badge" }, "Improvise") : null,
      t.kind === "example" ? h("span", { class: "mode-badge" }, "Example") : null,
      h("button", { class: "linklike", type: "button", onClick: async () => {
        state.setTake(await api.getAnyTake(t.take_id));
        openReport();
      } }, takeTitle(t)),
      h("span", { class: "muted small" }, ` ${new Date(t.created_at).toLocaleString()} · ${fmtTime(t.duration_s)}${t.stt?.model ? ` · ${t.stt.model}` : ""}`),
      h("ul", { class: "small" }, ...(t.summary ?? []).map((s) => h("li", {}, s)))))),
  );
}
