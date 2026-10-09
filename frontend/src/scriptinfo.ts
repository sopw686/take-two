/** Lightweight client-side reading of the script: sections, budgets, lines and their marks.
 *  The server's parser (take_two/marks.py) is the source of truth; this mirrors it closely enough to
 *  drive live UI (the teleprompter, the planned-section line, word counts). */

export interface SectionInfo { name: string; budget_s: number | null; words: number; lineNo: number }

export type Part =
  | { kind: "word"; text: string; emph: boolean }
  | { kind: "pause"; long: boolean }
  | { kind: "define"; term: string };

export interface ScriptLine {
  index: number;
  section: number;
  raw: string;
  rawLineNo: number;
  isKey: boolean;
  /** Words, pauses and [DEFINE] tags in the order they were written. */
  parts: Part[];
  words: number;
}

export interface ScriptSection { index: number; name: string; budget_s: number | null; lineNo: number; lines: ScriptLine[] }

export interface ParsedScript { sections: ScriptSection[]; lines: ScriptLine[] }

const SECTION_RE = /^\s*##\s*(.*?)\s*(?:\[(\d+):(\d{1,2})\])?\s*$/;
const KEY_RE = /^\s*\[KEY\]\s*/i;
const DEFINE_RE = /\[DEFINE:\s*[^\]]+?\s*\]/gi;
const DEFINE_SPLIT_RE = /(\[DEFINE:\s*[^\]]+?\s*\])/i;
const EMPH_RE = /^\*([^\s*]+)\*([^\w\s*]*)$/;
/** [SAY: word = respelling | ipa]: how the speaker says a word. Removed before anything is counted or shown. */
export const SAY_RE = /\[SAY:\s*([^\]=|]+?)\s*=\s*([^\]|]+?)\s*(?:\|\s*([^\]]+?)\s*)?\]/gi;
// The line breaks Python's str.splitlines() recognizes, so line numbers match the server's.
const LINE_BREAK_RE = new RegExp(`\\r\\n|[\\n\\r\\v\\f\\x1c-\\x1e${String.fromCharCode(0x85, 0x2028, 0x2029)}]`);

/** {lower-cased word: respelling} from the script's [SAY] marks. */
export function sayings(text: string): Map<string, string> {
  const out = new Map<string, string>();
  for (const m of blankComments(text).matchAll(SAY_RE)) out.set(m[1].trim().toLowerCase(), m[2].trim());
  return out;
}

export function isSectionHeader(line: string): boolean {
  return line.trimStart().startsWith("##") && SECTION_RE.test(line);
}

/** Remove <!-- comments --> but keep their newlines, as the server does, so line numbers stay stable. */
export function blankComments(text: string): string {
  return text.replace(/<!--[\s\S]*?-->/g, (m) => "\n".repeat(m.split("\n").length - 1));
}

export function stripLineMarks(line: string): string {
  return line
    .replace(KEY_RE, "")
    .replace(DEFINE_RE, " ")
    .replace(SAY_RE, " ")
    .replace(/<!--.*?-->/g, "")
    .split(/\s+/)
    .filter((w) => w && w !== "/" && w !== "//")
    .map((w) => w.replace(EMPH_RE, "$1$2"))
    .join(" ");
}

function lineParts(raw: string): { isKey: boolean; parts: Part[] } {
  const isKey = KEY_RE.test(raw);
  const body = (isKey ? raw.replace(KEY_RE, "") : raw).replace(SAY_RE, " ");
  const parts: Part[] = [];
  for (const seg of body.split(DEFINE_SPLIT_RE)) {
    const d = /^\[DEFINE:\s*([^\]]+?)\s*\]$/i.exec(seg);
    if (d) {
      parts.push({ kind: "define", term: d[1].trim() });
      continue;
    }
    for (const piece of seg.split(/\s+/)) {
      if (!piece) continue;
      if (piece === "/" || piece === "//") parts.push({ kind: "pause", long: piece === "//" });
      else {
        const e = EMPH_RE.exec(piece);
        parts.push(e ? { kind: "word", text: e[1] + e[2], emph: true } : { kind: "word", text: piece, emph: false });
      }
    }
  }
  return { isKey, parts };
}

export function parseScript(text: string): ParsedScript {
  const sections: ScriptSection[] = [];
  const lines: ScriptLine[] = [];
  blankComments(text).split(LINE_BREAK_RE).forEach((raw, rawNo) => {
    if (!raw.trim()) return;
    if (isSectionHeader(raw)) {
      const m = SECTION_RE.exec(raw) as RegExpExecArray;
      const last = sections[sections.length - 1];
      if (last && !last.lines.length && last.name === "") sections.pop();  // drop an empty implicit section
      sections.push({ index: sections.length, name: m[1].trim() || `Section ${sections.length + 1}`,
        budget_s: m[2] !== undefined ? parseInt(m[2], 10) * 60 + parseInt(m[3], 10) : null, lineNo: rawNo, lines: [] });
      return;
    }
    if (!sections.length) sections.push({ index: 0, name: "", budget_s: null, lineNo: rawNo, lines: [] });
    const sec = sections[sections.length - 1];
    const { isKey, parts } = lineParts(raw);
    const line: ScriptLine = { index: lines.length, section: sec.index, raw, rawLineNo: rawNo, isKey, parts,
      words: parts.filter((p) => p.kind === "word").length };
    lines.push(line);
    sec.lines.push(line);
  });
  return { sections, lines };
}

export function sections(text: string): SectionInfo[] {
  return parseScript(text).sections.map((s) => ({ name: s.name, budget_s: s.budget_s, lineNo: s.lineNo,
    words: s.lines.reduce((a, l) => a + l.words, 0) }));
}

export function wordCount(text: string): number {
  return sections(text).reduce((a, s) => a + s.words, 0);
}

/** Which section the plan says you should be in at elapsed time t (cumulative budgets). */
export function plannedSectionAt(secs: SectionInfo[], t: number): { section: SectionInfo | null; into: number; total: number } {
  let acc = 0;
  for (const s of secs) {
    if (s.budget_s === null) continue;
    if (t < acc + s.budget_s) return { section: s, into: t - acc, total: s.budget_s };
    acc += s.budget_s;
  }
  return { section: null, into: t - acc, total: acc };
}

/** Planned [t0, t1) for every line: each section's budget spread over its lines by word count, on the
 *  same running total as plannedSectionAt. Null when a section that has lines has no budget. */
export function planLines(script: ParsedScript): { t0: number; t1: number }[] | null {
  if (!script.lines.length || script.sections.some((s) => s.lines.length && s.budget_s === null)) return null;
  const out: { t0: number; t1: number }[] = [];
  let acc = 0;
  for (const s of script.sections) {
    if (s.budget_s === null) continue;
    // A line with no words (a lone "//" or "[DEFINE: x]") still gets a word's worth of time, so it can be highlighted.
    const weight = (l: ScriptLine) => Math.max(l.words, 1);
    const words = s.lines.reduce((a, l) => a + weight(l), 0);
    for (const l of s.lines) {
      const share = weight(l) / words;
      out[l.index] = { t0: acc, t1: acc + s.budget_s * share };
      acc += s.budget_s * share;
    }
    if (!s.lines.length) acc += s.budget_s;  // a header with a budget but no lines still takes its time
  }
  return out;
}
