/** Suggested marks: goal picker → one structured LLM call → ghost marks the user accepts or rejects.
 *  Nothing is ever applied silently; "Done" writes only the accepted marks into the script. */

import { api } from "./api";
import { clear, h } from "./dom";
import { state } from "./state";
import type { Suggestion, SuggestResponse } from "./types";

const GOALS: { id: string; label: string; hint: string }[] = [
  { id: "clear", label: "Clear and informative", hint: "define terms, give sections budgets" },
  { id: "persuasive", label: "Persuasive / land the main point", hint: "a pause before and after the central claim" },
  { id: "somber", label: "Somber", hint: "slower key lines, more long pauses" },
  { id: "warm", label: "Warm / celebratory", hint: "fewer, shorter pauses" },
];
const HONESTY = "Marks can check your pace and pauses. They can't tell whether a take sounded sad or moving; that's your call.";

export function openSuggest(root: HTMLElement, script: string, onDone: () => void): void {
  const dlg = h("dialog", { class: "settings-dialog" }) as HTMLDialogElement;
  const notes = h("textarea", { rows: "2", placeholder: "Anything else? e.g. “the audience is clinicians”, “the room is mostly family”, “the ending must land”", class: "label-input", style: "width:100%" }) as HTMLTextAreaElement;
  const target = h("input", { type: "text", placeholder: "m:ss (optional)", class: "label-input", style: "width:120px" }) as HTMLInputElement;
  const goalInputs = GOALS.map((g, i) => {
    const inp = h("input", { type: "radio", name: "goal", value: g.id }) as HTMLInputElement;
    if (i === 0) inp.checked = true;
    return { g, inp };
  });
  const status = h("p", { class: "muted small", role: "status" }, "");
  const go = h("button", { class: "primary", type: "button" }, "Suggest marks") as HTMLButtonElement;
  go.addEventListener("click", async () => {
    const goal = goalInputs.find((x) => x.inp.checked)?.g.id ?? "clear";
    const m = /^(\d+):(\d{1,2})$/.exec(target.value.trim());
    const targetSeconds = m ? parseInt(m[1], 10) * 60 + parseInt(m[2], 10) : null;
    go.setAttribute("disabled", "");
    status.textContent = "Asking the model for a few marks with reasons…";
    try {
      const resp = await api.suggest(script, goal, notes.value, targetSeconds);
      dlg.close();
      renderReview(root, script, resp, onDone);
    } catch (err) {
      status.textContent = `Failed: ${(err as Error).message}`;
      go.removeAttribute("disabled");
    }
  });
  dlg.append(
    h("h2", {}, "Suggest marks"),
    h("p", { class: "muted small" }, "Pick what you want the speech to do. The model reads only the script text and proposes a small number of marks, each with a one-line reason. You accept or reject every one."),
    h("div", { class: "goal-grid" }, ...goalInputs.map(({ g, inp }) => h("label", {}, inp, h("span", {}, g.label, h("small", {}, g.hint))))),
    h("label", { class: "small" }, "Notes for the model (optional)", notes),
    h("label", { class: "small", style: "display:block;margin-top:8px" }, "Target total length ", target),
    h("p", { class: "honesty" }, HONESTY),
    status,
    h("div", { class: "dialog-actions" }, h("span", { class: "spacer" }), h("button", { class: "ghost-btn", type: "button", onClick: () => dlg.close() }, "Cancel"), go),
  );
  document.body.append(dlg);
  dlg.addEventListener("close", () => dlg.remove());
  dlg.showModal();
}

function ghost(s: Suggestion, decided: Map<number, boolean>, rerender: () => void): HTMLElement {
  const label = s.type === "key" ? "KEY" : s.type === "pause" ? "/" : s.type === "long_pause" ? "//" : s.type === "define" ? `DEFINE: ${s.term}` : `## ${s.name} [${s.budget_label}]`;
  const d = decided.get(s.id);
  const el = h("span", { class: `ghost ${d === true ? "accepted" : d === false ? "rejected" : ""} tip`, "data-tip": s.reason + (s.type === "section" && s.budget_estimated ? " (budget is an estimate at 140 wpm until you record a take)" : "") },
    h("span", {}, label),
    h("button", { type: "button", title: "Accept", onClick: (e) => { e.stopPropagation(); decided.set(s.id, true); rerender(); } }, "✓"),
    h("button", { type: "button", title: "Reject", onClick: (e) => { e.stopPropagation(); decided.set(s.id, false); rerender(); } }, "✗"),
  );
  el.addEventListener("click", () => {
    const why = el.querySelector(".why");
    if (why) why.remove();
    else el.append(h("span", { class: "why" }, ` ${s.reason}`));
  });
  return el;
}

function renderReview(root: HTMLElement, script: string, resp: SuggestResponse, onDone: () => void): void {
  const decided = new Map<number, boolean>();
  const draw = () => {
    clear(root);
    if (!resp.available) {
      root.append(h("p", { class: "muted" }, resp.reason ?? "Suggestions are unavailable."), h("button", { class: "ghost-btn", type: "button", onClick: onDone }, "Back to the editor"));
      return;
    }
    if (!resp.suggestions.length) {
      root.append(h("p", { class: "muted" }, resp.reason ?? "The model proposed nothing that survived validation. The script may already be well marked."),
        h("button", { class: "ghost-btn", type: "button", onClick: onDone }, "Back to the editor"));
      return;
    }
    const accepted = resp.suggestions.filter((s) => decided.get(s.id) === true);
    const undecided = resp.suggestions.filter((s) => decided.get(s.id) === undefined);
    const doneBtn = h("button", { class: "primary", type: "button", onClick: async () => {
      doneBtn.setAttribute("disabled", "");
      try {
        const { text } = await api.applySuggestions(script, accepted);
        state.setScript(text);
        onDone();
      } catch (err) {
        alert(`Could not apply marks: ${(err as Error).message}`);
        doneBtn.removeAttribute("disabled");
      }
    } }, accepted.length ? `Apply ${accepted.length} accepted mark${accepted.length === 1 ? "" : "s"}` : "Done (apply nothing)") as HTMLButtonElement;

    const byLine = new Map<number, Suggestion[]>();
    for (const s of resp.suggestions) byLine.set(s.line_index, [...(byLine.get(s.line_index) ?? []), s]);
    const lines = resp.lines.map((ln) => {
      const sugg = byLine.get(ln.index) ?? [];
      const words = ln.text.split(/\s+/).filter(Boolean);
      const parts: (HTMLElement | string)[] = [];
      for (const s of sugg.filter((x) => x.type === "key")) parts.push(ghost(s, decided, draw));
      for (const s of sugg.filter((x) => x.type === "define")) parts.push(ghost(s, decided, draw));
      words.forEach((w, i) => {
        for (const s of sugg.filter((x) => (x.type === "pause" || x.type === "long_pause") && x.word_index === i)) parts.push(ghost(s, decided, draw));
        parts.push(w + " ");
      });
      for (const s of sugg.filter((x) => (x.type === "pause" || x.type === "long_pause") && x.word_index === words.length)) parts.push(ghost(s, decided, draw));
      const secs = sugg.filter((x) => x.type === "section").map((s) => h("div", { class: "rhead" }, ghost(s, decided, draw)));
      return h("div", { class: "rline" }, ...secs, h("div", {}, ...parts));
    });

    root.append(
      h("div", { class: "review-actions" },
        h("strong", {}, `${resp.suggestions.length} suggested mark${resp.suggestions.length === 1 ? "" : "s"}`),
        h("span", { class: "muted" }, `· ${accepted.length} accepted · ${undecided.length} undecided`),
        h("span", { class: "spacer" }),
        h("button", { class: "ghost-btn", type: "button", onClick: () => { resp.suggestions.forEach((s) => decided.set(s.id, true)); draw(); } }, "Accept all"),
        h("button", { class: "ghost-btn", type: "button", onClick: () => { resp.suggestions.forEach((s) => decided.set(s.id, false)); draw(); } }, "Reject all"),
        h("button", { class: "ghost-btn", type: "button", onClick: onDone }, "Cancel"),
        doneBtn),
      h("p", { class: "muted small" }, "Dashed marks are proposals. Hover or click one for its reason, then ✓ or ✗. Section budgets are ", resp.rate_source || "estimates", ".",
        resp.dropped.length ? ` The model proposed more; ${resp.dropped.reduce((a, d) => a + d.count, 0)} were dropped by the caps (${resp.dropped.map((d) => `${d.reason} ×${d.count}`).join("; ")}).` : ""),
      h("div", { class: "review" }, ...lines),
      h("p", { class: "honesty" }, HONESTY),
    );
  };
  draw();
}
