import { api } from "./api";
import { clear, esc, h } from "./dom";
import { isSectionHeader, sections, wordCount } from "./scriptinfo";
import { state } from "./state";
import { openSuggest } from "./suggest";
import { scriptTour, type Tour } from "./tour";
import type { Settings } from "./types";

const CHEATSHEET: [string, string][] = [
  ["<!-- take-two: short_pause_s=0.9 -->", "first line only: thresholds for this script, over the Settings dialog"],
  ["## Methods [1:30]", "section with a time budget (m:ss)"],
  ["[KEY] at line start", "a key line: say it slower than your median, then pause"],
  ["word / word", "short pause (target ≥ 0.7 s)"],
  ["word // word", "long pause (target ≥ 1.5 s)"],
  ["[DEFINE: term]", "a term your audience may not know (technical word, in-joke, reference): explain it aloud at or before its first use"],
  ["*word*", "emphasis (experimental)"],
];

export const SETTINGS_LINE = /^\s*<!--\s*(?:take-two|taketwo|marked)\s*:/i;

function highlightLine(line: string): string {
  if (!line.trim()) return "&nbsp;";
  if (SETTINGS_LINE.test(line)) return `<span class="hl-settings">${esc(line)}</span>`;
  if (isSectionHeader(line)) return `<span class="hl-section">${esc(line)}</span>`;
  let out = "";
  const keyMatch = /^(\s*)(\[KEY\])(\s*)/i.exec(line);
  let rest = line;
  if (keyMatch) {
    out += esc(keyMatch[1]) + `<span class="hl-key">${esc(keyMatch[2])}</span>` + esc(keyMatch[3]);
    rest = line.slice(keyMatch[0].length);
  }
  const parts = rest.split(/(\s+)/);
  for (const p of parts) {
    if (/^\s+$/.test(p)) {
      out += p;
      continue;
    }
    if (p === "/" || p === "//") out += `<span class="hl-pause">${p}</span>`;
    else if (/^\*[^\s*]+\*[^\w\s*]*$/.test(p)) out += `<span class="hl-emph">${esc(p)}</span>`;
    else out += esc(p);
  }
  // [DEFINE: multi word term] spans whitespace; colour it after the fact.
  out = out.replace(/\[DEFINE:\s*([^\]]+?)\s*\]/gi, (m) => `<span class="hl-define">${m}</span>`);
  return out;
}

export function renderEditor(root: HTMLElement): void {
  clear(root);
  const pre = h("pre", { class: "hl", "aria-hidden": "true" });
  const code = h("code");
  pre.append(code);
  const ta = h("textarea", { class: "script-input", spellcheck: "false", placeholder: "Paste or type your script here." }) as HTMLTextAreaElement;
  ta.value = state.scriptText;

  const stats = h("div", { class: "stats" });
  const settingsNote = h("p", { class: "small", role: "status" });
  let checkTimer = 0;
  let checked = "";
  const checkSettings = () => {
    window.clearTimeout(checkTimer);
    checkTimer = window.setTimeout(async () => {
      const text = ta.value;
      if (text === checked) return;
      checked = text;
      // Only a script that starts with a settings line needs the server's opinion.
      const first = text.split(/\r?\n/).find((l) => l.trim()) ?? "";
      if (!SETTINGS_LINE.test(first)) {
        settingsNote.textContent = "";
        settingsNote.className = "small";
        return;
      }
      try {
        const r = await api.scriptSettings(text, state.effectiveSettings());
        if (checked !== text) return;
        settingsNote.className = r.error ? "small warn" : "small muted";
        settingsNote.textContent = r.error
          ? `Settings line: ${r.error}. Takes of this script will be refused until it is fixed.`
          : `Settings line: ${describeOverrides(r.from_script)}. These win over the Settings dialog for takes of this script.`;
      } catch {
        settingsNote.textContent = "";
      }
    }, 300);
  };
  let tour: Tour | null = null;
  const refresh = () => {
    // One span per line, so the tour can point at a line.
    code.innerHTML = ta.value.split(/\r?\n/).map((l, i) => `<span class="hl-ln" data-ln="${i}">${highlightLine(l)}</span>`).join("\n") + "\n";
    const secs = sections(ta.value);
    const words = wordCount(ta.value);
    const budget = secs.reduce((a, s) => a + (s.budget_s ?? 0), 0);
    const rate = state.analysis?.baseline.median_wpm ?? null;
    const est = rate ? words / rate : words / 140;
    const m = Math.floor(est);
    const parts = [
      `${words} words`,
      `${secs.filter((s) => s.name).length} sections`,
      budget ? `budget ${Math.floor(budget / 60)}:${String(budget % 60).padStart(2, "0")}` : "no budgets yet",
      `≈ ${m}:${String(Math.round((est - m) * 60)).padStart(2, "0")} at ${rate ? `your median ${Math.round(rate)} wpm` : "140 wpm (estimate until you record a take)"}`,
    ];
    stats.textContent = parts.join("  ·  ");
    checkSettings();
    tour?.apply();
  };
  ta.addEventListener("input", () => {
    state.setScript(ta.value);
    refresh();
  });
  ta.addEventListener("scroll", () => {
    pre.scrollTop = ta.scrollTop;
    pre.scrollLeft = ta.scrollLeft;
  });
  const loadSample = async (name = "talk") => {
    const ex = await api.sample(name);
    if (ta.value.trim() && !confirm(`Replace the current script with the example (${ex.label})?`)) return;
    ta.value = ex.text;
    state.setScript(ex.text);
    refresh();
  };
  // "Start from an example": the science talk, plus a toast and a poem written for the demo.
  const examplePick = h("select", { class: "label-input", "aria-label": "Start from an example" },
    h("option", { value: "" }, "Start from an example…")) as HTMLSelectElement;
  api.samples().then((list) => list.forEach((x) => examplePick.append(h("option", { value: x.id }, x.label)))).catch(() => undefined);
  examplePick.addEventListener("change", async () => {
    const name = examplePick.value;
    examplePick.value = "";
    if (name) await loadSample(name);
  });
  tour = scriptTour(ta, code, () => loadSample("talk"));
  refresh();

  const importStatus = h("p", { class: "small warn", role: "status" });
  const pptxInput = h("input", { type: "file", accept: ".pptx,application/vnd.openxmlformats-officedocument.presentationml.presentation", hidden: "" }) as HTMLInputElement;
  pptxInput.addEventListener("change", async () => {
    const f = pptxInput.files?.[0];
    pptxInput.value = "";
    if (!f) return;
    importStatus.textContent = `Reading the speaker notes in ${f.name}…`;
    try {
      const { text, slides } = await api.importPptx(f);
      importStatus.textContent = "";
      if (ta.value.trim() && !confirm(`Replace the current script with the speaker notes from ${f.name} (${slides} slide${slides === 1 ? "" : "s"})?`)) return;
      ta.value = text;
      state.setScript(text);
      refresh();
      importStatus.textContent = `Imported ${slides} slide${slides === 1 ? "" : "s"} as sections. Add a [m:ss] budget to each heading and your marks.`;
      importStatus.className = "small muted";
    } catch (err) {
      importStatus.className = "small warn";
      importStatus.textContent = `Could not import ${f.name}: ${(err as Error).message}`;
    }
  });

  const suggestBtn = h("button", { class: "primary", type: "button", onClick: () => openSuggest(root, ta.value, () => renderEditor(root)) }, "Suggest marks…");
  const llm = state.health?.llm;
  const suggestNote = h("p", { class: "muted small" },
    llm?.available
      ? `Suggestions use ${llm.provider} (${llm.model}). The model only reads the script text; it never hears audio.`
      : (llm?.reason ?? "Suggestions need an ANTHROPIC_API_KEY on the server."));
  if (!llm?.available) suggestBtn.setAttribute("disabled", "");

  root.append(
    h("div", { class: "editor-layout" },
      h("div", { class: "editor-main" },
        h("div", { class: "toolbar" },
          examplePick,
          h("button", { class: "ghost-btn", type: "button", onClick: () => { ta.value = ""; state.setScript(""); refresh(); } }, "Clear"),
          h("button", { class: "ghost-btn", type: "button", title: "Each slide becomes a section; its speaker notes become the lines. Nothing is uploaded anywhere but this app.", onClick: () => pptxInput.click() }, "Import from PowerPoint notes"),
          pptxInput,
          h("span", { class: "spacer" }),
          suggestBtn,
        ),
        importStatus,
        h("div", { class: "editor" }, pre, ta),
        stats,
        settingsNote,
        suggestNote,
      ),
      h("aside", { class: "cheatsheet" },
        tour.el,
        h("h3", {}, "Marks"),
        h("p", { class: "muted small" }, "You set the targets. Nothing is judged against a universal norm unless you switch a preset on in Settings."),
        h("dl", {}, ...CHEATSHEET.flatMap(([mark, meaning]) => [h("dt", {}, h("code", {}, mark)), h("dd", {}, meaning)])),
        h("p", { class: "muted small" }, "Put spaces around / and // so km/h stays a word. Blank lines are ignored; every other line is a script line."),
        h("button", { class: "linklike small", type: "button", onClick: () => tour?.restart() }, "Show the one-minute tour"),
      ),
    ),
  );
}

/** "short_pause_s 0.9, conventions_enabled on" */
export function describeOverrides(over: Partial<Settings>): string {
  const parts = Object.entries(over).map(([k, v]) => `${k} ${typeof v === "boolean" ? (v ? "on" : "off") : v}`);
  return parts.length ? parts.join(", ") : "sets nothing";
}
