/** Cue plan -> browser utterances. Pure and import-free, so it runs under Node's test runner too.
 *  A browser voice has coarse control: rate, pitch and volume per utterance, nothing per syllable. So each
 *  segment is one utterance, a pause is a timed gap after it (never left to punctuation), and a rising or
 *  falling end is approximated by saying the segment's last word as its own utterance, pitched up or down. */

export interface PlanSegment {
  text: string; say_as?: string | null; wpm: number; pitch_st: number; volume_db: number;
  contour: string; pause_after_s: number;
}
export interface PlanLike { lead_pause_s: number; segments: PlanSegment[] }

export interface Utterance { text: string; rate: number; pitch: number; volume: number; gapAfterMs: number; segment: number }

/** A browser voice's own pace at rate 1 is not known; this is the usual neighbourhood. */
export const VOICE_WPM = 170;
export const CONTOUR_PITCH: Record<string, number> = { rise: 1.15, fall: 0.87 };

const clamp = (x: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, x));
const round = (x: number) => Math.round(x * 1000) / 1000;

/** "KOH-ral" -> "koh ral": capitals would be spelled out letter by letter. */
export function respellingToSpeech(r: string): string {
  return r.replace(/-/g, " ").toLowerCase().split(/\s+/).filter(Boolean).join(" ");
}

export function toUtterances(plan: PlanLike, voiceWpm = VOICE_WPM): { leadMs: number; utterances: Utterance[] } {
  const out: Utterance[] = [];
  plan.segments.forEach((seg, i) => {
    const text = seg.say_as ? respellingToSpeech(seg.say_as) : seg.text.trim();
    if (!text) return;
    const base = {
      rate: round(clamp((seg.wpm || voiceWpm) / voiceWpm, 0.5, 2)),
      pitch: round(clamp(2 ** ((seg.pitch_st || 0) / 12), 0.5, 1.6)),
      volume: round(clamp(0.8 * 10 ** ((seg.volume_db || 0) / 20), 0, 1)),
      segment: i,
    };
    const gap = Math.round(clamp(seg.pause_after_s || 0, 0, 10) * 1000);
    const shift = CONTOUR_PITCH[seg.contour];
    const words = text.split(/\s+/);
    if (shift && words.length > 1 && !seg.say_as) {
      out.push({ ...base, text: words.slice(0, -1).join(" "), gapAfterMs: 0 });
      out.push({ ...base, text: words[words.length - 1], pitch: round(clamp(base.pitch * shift, 0.5, 2)), gapAfterMs: gap });
    } else {
      out.push({ ...base, text, pitch: shift ? round(clamp(base.pitch * shift, 0.5, 2)) : base.pitch, gapAfterMs: gap });
    }
  });
  return { leadMs: Math.round(clamp(plan.lead_pause_s || 0, 0, 10) * 1000), utterances: out };
}

/** A word said syllable by syllable, slowly, then whole at an ordinary pace: for "hear one word". */
export function wordPlan(word: string, respelling: string | null): PlanLike {
  const sylls = respelling ? respelling.split(/[-\s]+/).filter(Boolean) : [];
  const segs: PlanSegment[] = sylls.length > 1
    ? sylls.map((s) => ({ text: s, say_as: s, wpm: 70, pitch_st: s === s.toUpperCase() ? 1.5 : 0, volume_db: s === s.toUpperCase() ? 2 : 0, contour: "none", pause_after_s: 0.3 }))
    : [{ text: word, say_as: respelling, wpm: 70, pitch_st: 0, volume_db: 0, contour: "none", pause_after_s: 0.6 }];
  if (segs.length > 1) segs[segs.length - 1].pause_after_s = 0.6;
  segs.push({ text: word, say_as: respelling, wpm: 150, pitch_st: 0, volume_db: 0, contour: "none", pause_after_s: 0 });
  return { lead_pause_s: 0, segments: segs };
}

/** Plain text at an ordinary pace: the examiner's questions. */
export function textPlan(text: string, wpm = VOICE_WPM): PlanLike {
  return { lead_pause_s: 0, segments: [{ text, wpm, pitch_st: 0, volume_db: 0, contour: "none", pause_after_s: 0 }] };
}
