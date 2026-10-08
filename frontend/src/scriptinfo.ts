/** Lightweight client-side reading of the script: section budgets and word counts.
 *  The server's parser is the source of truth; this only drives live UI hints. */

export interface SectionInfo { name: string; budget_s: number | null; words: number; lineNo: number }

const SECTION_RE = /^\s*##\s*(.*?)\s*(?:\[(\d+):(\d{1,2})\])?\s*$/;
const DEFINE_RE = /\[DEFINE:\s*[^\]]+?\s*\]/gi;

export function isSectionHeader(line: string): boolean {
  return line.trimStart().startsWith("##") && SECTION_RE.test(line);
}

export function stripLineMarks(line: string): string {
  return line
    .replace(/^\s*\[KEY\]\s*/i, "")
    .replace(DEFINE_RE, " ")
    .replace(/<!--.*?-->/g, "")
    .split(/\s+/)
    .filter((w) => w && w !== "/" && w !== "//")
    .map((w) => w.replace(/^\*([^\s*]+)\*$/, "$1"))
    .join(" ");
}

export function sections(text: string): SectionInfo[] {
  const out: SectionInfo[] = [];
  const cleaned = text.replace(/<!--[\s\S]*?-->/g, "");
  cleaned.split(/\r?\n/).forEach((line, i) => {
    if (!line.trim()) return;
    const m = line.trimStart().startsWith("##") ? SECTION_RE.exec(line) : null;
    if (m) {
      const budget = m[2] !== undefined ? parseInt(m[2], 10) * 60 + parseInt(m[3], 10) : null;
      out.push({ name: m[1] || `Section ${out.length + 1}`, budget_s: budget, words: 0, lineNo: i });
      return;
    }
    if (!out.length) out.push({ name: "", budget_s: null, words: 0, lineNo: i });
    out[out.length - 1].words += stripLineMarks(line).split(/\s+/).filter(Boolean).length;
  });
  return out;
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
