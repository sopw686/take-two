import { api } from "./api";
import { clear, esc, h } from "./dom";
import { isSectionHeader, sections, wordCount } from "./scriptinfo";
import { state } from "./state";
import { openSuggest } from "./suggest";

const CHEATSHEET: [string, string][] = [
  ["## Methods [1:30]", "section with a time budget (m:ss)"],
  ["[KEY] at line start", "a key line: say it slower than your median, then pause"],
  ["word / word", "short pause (target ≥ 0.7 s)"],
  ["word // word", "long pause (target ≥ 1.5 s)"],
  ["[DEFINE: term]", "the term must be explained aloud at or before its first use"],
  ["*word*", "emphasis (experimental)"],
];

function highlightLine(line: string): string {
  if (!line.trim()) return "&nbsp;";
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
    else if (/^\*[^\s*]+\*$/.test(p)) out += `<span class="hl-emph">${esc(p)}</span>`;
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
  const refresh = () => {
    code.innerHTML = ta.value.split(/\r?\n/).map(highlightLine).join("\n") + "\n";
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
  };
  ta.addEventListener("input", () => {
    state.setScript(ta.value);
    refresh();
  });
  ta.addEventListener("scroll", () => {
    pre.scrollTop = ta.scrollTop;
    pre.scrollLeft = ta.scrollLeft;
  });
  refresh();

  const loadSample = async () => {
    if (ta.value.trim() && !confirm("Replace the current script with the sample?")) return;
    const { text } = await api.sample();
    ta.value = text;
    state.setScript(text);
    refresh();
  };

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
          h("button", { class: "ghost-btn", type: "button", onClick: loadSample }, "Load sample script"),
          h("button", { class: "ghost-btn", type: "button", onClick: () => { ta.value = ""; state.setScript(""); refresh(); } }, "Clear"),
          h("span", { class: "spacer" }),
          suggestBtn,
        ),
        h("div", { class: "editor" }, pre, ta),
        stats,
        suggestNote,
      ),
      h("aside", { class: "cheatsheet" },
        h("h3", {}, "Marks"),
        h("p", { class: "muted small" }, "You set the targets. Nothing is judged against a universal norm unless you switch a preset on in Settings."),
        h("dl", {}, ...CHEATSHEET.flatMap(([mark, meaning]) => [h("dt", {}, h("code", {}, mark)), h("dd", {}, meaning)])),
        h("p", { class: "muted small" }, "Put spaces around / and // so km/h stays a word. Blank lines are ignored; every other line is a script line."),
      ),
    ),
  );
}
