/** The one audio element every view plays through, so two takes can never play at once. */

export const player = () => document.getElementById("player") as HTMLAudioElement;

/** Play the current source from just before t (seconds). */
export function play(at: number | null | undefined): void {
  if (at === null || at === undefined) return;
  const p = player();
  p.currentTime = Math.max(0, at - 0.15);
  p.play().catch(() => undefined);  // a newer play() or a source change interrupts this one; that is fine
}
