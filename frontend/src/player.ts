/** The one audio element every view plays through, so two takes can never play at once. */

export const player = () => document.getElementById("player") as HTMLAudioElement;

/** Play from just before t (seconds). With url, switch to that recording first if another one is loaded
 *  (a drill's "Hear this try" or a comparison cell may have left a different take in the player). */
export function play(at: number | null | undefined, url?: string): void {
  if (at === null || at === undefined) return;
  const p = player();
  const go = () => {
    p.currentTime = Math.max(0, at - 0.15);
    p.play().catch(() => undefined);  // a newer play() or a source change interrupts this one; that is fine
  };
  if (url && !p.src.endsWith(url)) {
    segment++;
    p.src = url;
    p.addEventListener("loadedmetadata", go, { once: true });
  } else go();
}

let segment = 0;

/** Play url from `from` to `to` seconds on the shared element, then stop. Starting another segment (or
 *  stopSegment) cancels this one, so two takes can never play over each other. */
export function playSegment(url: string, from: number, to: number, onEnd?: () => void): void {
  const p = player();
  const mine = ++segment;
  const start = () => {
    if (mine !== segment) return;
    p.currentTime = Math.max(0, from);
    p.play().catch(() => undefined);
    // A timer rather than timeupdate, which fires only every ~250 ms and would run past a short pause window.
    const iv = window.setInterval(() => {
      if (mine !== segment) { window.clearInterval(iv); return; }
      if (p.currentTime >= to || p.ended || p.paused) {
        window.clearInterval(iv);
        if (p.currentTime >= to) p.pause();
        onEnd?.();
      }
    }, 40);
  };
  if (!p.src.endsWith(url)) {
    p.pause();
    p.src = url;
    p.addEventListener("loadedmetadata", start, { once: true });
  } else start();
}

export function stopSegment(): void {
  segment++;
  player().pause();
}
