/** Turn an Improvise take into a script to refine on the Script tab (import-free, tested under Node).
 *
 *  One line per spoken sentence. Every pause the report noted is kept where it fell, as / or // by the
 *  long-pause setting: deliberate pauses between sentences as plain marks, hesitations as marks tagged with
 *  an inline comment so the speaker can keep, move or delete them. Fillers and restarts are left out (the
 *  report already counted them); hedges are kept, because whether to say "I think" is a choice of wording. */

export interface ImprovSource {
  topic: string;
  goal_s: number | null;
  words: { text: string }[];
  sentences: [number, number][];
  fillers: { i: number; j: number }[];
  restarts: { i: number; j: number; kind: string }[];
  /** Pauses between sentences that let a line land. */
  deliberate: { after_i: number; duration_s: number }[];
  /** Long silences inside (or far too long between) sentences. */
  hesitations: { after_i: number; duration_s: number }[];
}

export interface ImprovScript {
  text: string;
  lines: number;
  deliberate: number;
  hesitations: number;
  fillersRemoved: number;
  restartsRemoved: number;
}

type Piece = { kind: "word"; text: string } | { kind: "mark"; long: boolean; hesitation: number | null };

const TERMINAL_RE = /[.!?…]+["”’)]*$/;

/** "## Topic [1:00]": the topic as the section name, the time goal as its budget. */
function header(topic: string, goal_s: number | null): string {
  const name = topic.replace(/<!--|-->/g, "").replace(/\s+/g, " ").trim() || "Improvise";
  if (!goal_s || goal_s <= 0) return `## ${name}`;
  const s = Math.round(goal_s);
  return `## ${name} [${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}]`;
}

export function improvToScript(src: ImprovSource, opts: { longPauseS: number; when?: string }): ImprovScript {
  const n = src.words.length;
  const drop = new Set<number>();
  for (const f of src.fillers) for (let k = f.i; k <= f.j; k++) drop.add(k);
  let restartsRemoved = 0;
  for (const r of src.restarts) {
    // "I I" keeps the second word; a cut-off "th-" goes entirely.
    const k = r.kind === "repeat" ? r.i : r.j;
    if (k >= 0 && k < n && !drop.has(k)) {
      drop.add(k);
      restartsRemoved++;
    }
  }
  const pauseAfter = new Map<number, { duration_s: number; hesitation: boolean }>();
  const addPause = (after_i: number, duration_s: number, hesitation: boolean) => {
    const had = pauseAfter.get(after_i);
    if (!had || duration_s > had.duration_s) pauseAfter.set(after_i, { duration_s, hesitation });
  };
  src.deliberate.forEach((p) => addPause(p.after_i, p.duration_s, false));
  src.hesitations.forEach((p) => addPause(p.after_i, p.duration_s, true));

  const sentences = src.sentences.length ? src.sentences : (n ? [[0, n] as [number, number]] : []);
  const lines: Piece[][] = [];
  let deliberate = 0;
  let hesitations = 0;
  for (const [a, b] of sentences) {
    const line: Piece[] = [];
    for (let k = a; k < b && k < n; k++) {
      const text = src.words[k].text.trim();
      if (!drop.has(k) && text) line.push({ kind: "word", text });
      else if (drop.has(k) && k === b - 1) {
        // The sentence's last word was a filler: keep its full stop on the last word that stays.
        const end = TERMINAL_RE.exec(text)?.[0].replace(/["”’)]+$/, "");
        const last = [...line].reverse().find((x) => x.kind === "word") as { kind: "word"; text: string } | undefined;
        if (end && last && !TERMINAL_RE.test(last.text)) last.text = last.text.replace(/[,;:]+$/, "") + end;
      }
      const p = pauseAfter.get(k);
      if (!p) continue;
      const mark: Piece = { kind: "mark", long: p.duration_s >= opts.longPauseS, hesitation: p.hesitation ? p.duration_s : null };
      const prev = line[line.length - 1];
      if (prev?.kind === "mark") {
        // Two pauses with only left-out words between them read as one.
        prev.long ||= mark.long;
        prev.hesitation = prev.hesitation !== null || mark.hesitation !== null
          ? Math.max(prev.hesitation ?? 0, mark.hesitation ?? 0) : null;
      } else line.push(mark);
    }
    if (line.some((x) => x.kind === "word")) {
      const first = line.find((x) => x.kind === "word") as { kind: "word"; text: string };
      first.text = first.text.charAt(0).toUpperCase() + first.text.slice(1);
      lines.push(line);
    } else if (lines.length) {
      // Only left-out words and a pause: the pause belongs after the line before.
      for (const x of line) if (x.kind === "mark") lines[lines.length - 1].push(x);
    }
  }

  const rendered = lines.map((line) => line.map((x) => {
    if (x.kind === "word") return x.text;
    if (x.hesitation !== null) hesitations++;
    else deliberate++;
    const mark = x.long ? "//" : "/";
    return x.hesitation !== null ? `${mark} <!-- hesitation ${x.hesitation.toFixed(1)} s -->` : mark;
  }).join(" "));
  const intro = `<!-- From your Improvise take${opts.when ? ` of ${opts.when}` : ""}. Pauses you made are marked / and //; `
    + `the ones tagged "hesitation" were unplanned: keep, move or delete them. Fillers and restarts were left out. -->`;
  return {
    text: [intro, header(src.topic, src.goal_s), ...rendered].join("\n") + "\n",
    lines: rendered.length,
    deliberate,
    hesitations,
    fillersRemoved: src.fillers.length,
    restartsRemoved,
  };
}
