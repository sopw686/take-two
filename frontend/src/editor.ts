import { api } from "./api";
import { clear, esc, h } from "./dom";
import { openDrill } from "./drill";
import { hearButton, sayWord } from "./hearit";
import { isSectionHeader, parseScript, sections, wordCount } from "./scriptinfo";
import { state } from "./state";
import { openSuggest } from "./suggest";
import { scriptTour, type Tour } from "./tour";
import type { PronounceWord, Settings } from "./types";

const CHEATSHEET: [string, string][] = [
  ["<!-- take-two: short_pause_s=0.9 -->", "first line only: thresholds for this script, over the Settings dialog"],
  ["## Methods [1:30]", "section with a time budget (m:ss)"],
  ["[KEY] at line start", "a key line: say it slower than your median, then pause"],
  ["word / word", "short pause (target ≥ 0.7 s)"],
  ["word // word", "long pause (target ≥ 1.5 s)"],
  ["[DEFINE: term]", "a term your audience may not know (technical word, in-joke, reference): explain it aloud at or before its first use"],
  ["*word*", "emphasis (experimental)"],
  ["[SAY: word = KOH-ral]", "how you say a word, for Hear it (not checked in the report)"],
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
  out = out.replace(/\[SAY:[^\]]*\]/gi, (m) => `<span class="hl-say">${m}</span>`);
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

  const setText = (text: string) => {
    ta.value = text;
    state.setScript(text);
    refresh();
    hearLines.refresh();
  };
  const hearLines = hearYourLines(() => ta.value, setText);
  const wordsPanel = wordsWorthChecking(() => ta.value, setText);
  ta.addEventListener("input", () => hearLines.refresh());

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
        hearLines.el,
        wordsPanel.el,
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

/** Every script line with a Hear it button: the marks you wrote, said by a synthetic voice, or the coach's way. */
function hearYourLines(text: () => string, setText: (t: string) => void): { el: HTMLElement; refresh: () => void } {
  const body = h("div", { class: "hear-lines-body" });
  const el = h("details", { class: "card hear-lines" },
    h("summary", {}, "Hear your lines ", h("small", { class: "muted" }, "a synthetic voice says a line the way you marked it, or the coach's way")), body);
  let timer = 0;
  let shown = "";
  const build = () => {
    const t = text();
    if (!el.open || t === shown) return;
    shown = t;
    const parsed = parseScript(t);
    const take = state.analysis && (state.analysis.kind ?? "take") === "take" ? state.analysis : null;
    // Try it records a drill of the line, judged against a full take of this same script.
    const same = !!take && take.lines.length === parsed.lines.length
      && parsed.lines.every((l, i) => l.words === take.lines[i].word_count);
    body.replaceChildren(...(parsed.lines.length ? parsed.lines.map((ln) => {
      let row: HTMLElement = h("div");
      const words = ln.parts.map((p) => (p.kind === "word" ? p.text : p.kind === "pause" ? (p.long ? "//" : "/") : "")).filter(Boolean).join(" ");
      row = h("div", { class: `hear-line${ln.isKey ? " is-key" : ""}` },
        h("span", { class: "muted small" }, `${ln.index + 1}`), " ", ln.isKey ? h("code", {}, "KEY") : "", " ", words, " ",
        hearButton({ lineIndex: ln.index, script: text, takeId: same && take ? take.take_id : null,
          tryIt: same && take ? () => openDrill(take, "line", ln.index, `line ${ln.index + 1}`, row)
            : "Record a full take of this script first: a try is judged against that take's median.",
          onScriptChange: setText }, () => row));
      return row;
    }) : [h("p", { class: "muted small" }, "No script lines yet.")]));
  };
  el.addEventListener("toggle", build);
  return { el, refresh: () => { window.clearTimeout(timer); timer = window.setTimeout(build, 400); } };
}

/** Names, loanwords, acronyms and rare words, with a proposed pronunciation to confirm (with a key) or type. */
function wordsWorthChecking(text: () => string, setText: (t: string) => void): { el: HTMLElement } {
  const body = h("div", {});
  const status = h("p", { class: "small muted", role: "status" });
  const find = h("button", { class: "ghost-btn small", type: "button" }, "Find words worth checking") as HTMLButtonElement;
  const row = (w: PronounceWord): HTMLElement => {
    const inp = h("input", { type: "text", class: "label-input", value: w.respelling ?? "", placeholder: "how you say it, e.g. KOH-ral",
      "aria-label": `How you say ${w.word}`, style: "width:11em" }) as HTMLInputElement;
    const say = h("button", { class: "ghost-btn small", type: "button", onClick: () => sayWord(w.word, inp.value.trim() || null, (m) => { status.textContent = m; }) }, "Hear it slowly");
    const ok = h("button", { class: "ghost-btn small", type: "button", onClick: async () => {
      try {
        setText((await api.confirmSaying(text(), w.word, inp.value.trim(), w.ipa)).text);
        status.textContent = `Saved as [SAY: ${w.word} = ${inp.value.trim()}] in your script. Hear it uses it; the report does not check pronunciation.`;
      } catch (err) {
        status.textContent = `Not saved: ${(err as Error).message}`;
      }
    } }, w.confirmed ? "Update" : "Confirm");
    return h("li", {}, h("strong", {}, w.word), h("span", { class: "muted small" }, ` ${w.reasons.join(", ")}${w.count > 1 ? `, ${w.count}×` : ""} `),
      inp, w.ipa ? h("span", { class: "muted small" }, ` /${w.ipa}/ `) : " ", say, ok,
      w.source ? h("div", { class: "small muted" }, w.confirmed ? w.source : `Proposed pronunciation: confirm it. ${w.source.replace(/: confirm it$/, "")}.`) : null);
  };
  find.addEventListener("click", async () => {
    find.disabled = true;
    status.textContent = "Reading the script…";
    try {
      const r = await api.pronounce(text());
      status.textContent = "";
      body.replaceChildren(
        r.words.length ? h("ul", { class: "words-list" }, ...r.words.map(row)) : h("p", { class: "small muted" }, "Nothing flagged: no names, acronyms, loanwords or rare words found."),
        r.reason ? h("p", { class: "small muted" }, r.reason) : h("p", { class: "small muted" }, "A model can be wrong about names, and names vary by person and place. You know how yours are said: edit before you confirm."),
        r.note ? h("p", { class: "small muted" }, r.note) : "",
        r.dropped.length ? h("p", { class: "small muted" }, `Dropped by code: ${r.dropped.map((d) => `${d.count} ${d.reason}`).join("; ")}.`) : "");
    } catch (err) {
      status.textContent = `Failed: ${(err as Error).message}`;
    }
    find.disabled = false;
  });
  return { el: h("details", { class: "card words-check" },
    h("summary", {}, "Words worth checking ", h("small", { class: "muted" }, "names, loanwords, acronyms, rare words: how you say them")),
    h("p", {}, find), body, status) };
}

/** "short_pause_s 0.9, conventions_enabled on" */
export function describeOverrides(over: Partial<Settings>): string {
  const parts = Object.entries(over).map(([k, v]) => `${k} ${typeof v === "boolean" ? (v ? "on" : "off") : v}`);
  return parts.length ? parts.join(", ") : "sets nothing";
}
