import assert from "node:assert/strict";
import { test } from "node:test";
import { toUtterances, wordPlan, VOICE_WPM, type PlanSegment } from "../src/schedule.js";

const seg = (o: Partial<PlanSegment>): PlanSegment => ({ text: "a b", wpm: VOICE_WPM, pitch_st: 0, volume_db: 0, contour: "none", pause_after_s: 0, ...o });

test("pauses become timed gaps after the utterance, not punctuation", () => {
  const { leadMs, utterances } = toUtterances({ lead_pause_s: 0.5, segments: [seg({ text: "one two", pause_after_s: 0.7 }), seg({ text: "three", pause_after_s: 1.5 })] });
  assert.equal(leadMs, 500);
  assert.deepEqual(utterances.map((u) => [u.text, u.gapAfterMs]), [["one two", 700], ["three", 1500]]);
});

test("pace, pitch and loudness map to bounded browser values", () => {
  const [slow, loud, wild] = toUtterances({ lead_pause_s: 0, segments: [
    seg({ wpm: VOICE_WPM * 0.8 }), seg({ volume_db: 4, pitch_st: 2 }), seg({ wpm: 1000, pitch_st: -40, volume_db: 40 })] }).utterances;
  assert.equal(slow.rate, 0.8);
  assert.ok(loud.volume > 0.8 && loud.volume <= 1 && loud.pitch > 1);
  assert.deepEqual([wild.rate, wild.pitch, wild.volume], [2, 0.5, 1]);
});

test("a contour is the last word said on its own, pitched up or down, keeping the pause", () => {
  const u = toUtterances({ lead_pause_s: 0, segments: [seg({ text: "it was never broken.", contour: "fall", pause_after_s: 0.7 })] }).utterances;
  assert.deepEqual(u.map((x) => x.text), ["it was never", "broken."]);
  assert.ok(u[1].pitch < u[0].pitch && u[0].gapAfterMs === 0 && u[1].gapAfterMs === 700);
  const rise = toUtterances({ lead_pause_s: 0, segments: [seg({ text: "ready?", contour: "rise" })] }).utterances;
  assert.equal(rise.length, 1);
  assert.ok(rise[0].pitch > 1);
});

test("a respelling is spoken in place of the word, lower-cased so it is not spelled out", () => {
  const u = toUtterances({ lead_pause_s: 0, segments: [seg({ text: "Nguyen,", say_as: "WIN" }), seg({ text: "coral", say_as: "KOH-ral" })] }).utterances;
  assert.deepEqual(u.map((x) => x.text), ["win", "koh ral"]);
});

test("empty segments are skipped and keep their indexes", () => {
  const u = toUtterances({ lead_pause_s: 0, segments: [seg({ text: "  " }), seg({ text: "x" })] }).utterances;
  assert.deepEqual(u.map((x) => x.segment), [1]);
});

test("one word: syllables slowly, the stressed one lifted, then the whole word", () => {
  const p = wordPlan("coral", "KOH-ral");
  assert.deepEqual(p.segments.map((s) => s.say_as), ["KOH", "ral", "KOH-ral"]);
  assert.ok(p.segments[0].pitch_st > p.segments[1].pitch_st && p.segments[2].wpm > p.segments[0].wpm);
});
