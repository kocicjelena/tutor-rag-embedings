"use client";

/**
 * Keep a growing answer in view while it streams.
 *
 * Without this the answer renders below the fold and the reader has to chase it
 * down the page with the scrollbar, which is the one thing streaming was
 * supposed to make pleasant.
 *
 * Two details do most of the work:
 *
 * **Instant, not smooth, while streaming.** `behavior: "smooth"` looks better
 * on a single jump, but tokens arrive faster than a smooth scroll completes and
 * each new one restarts the animation, so the view falls steadily further
 * behind the text. Smooth is kept for the settled state, where there is only
 * one jump to make.
 *
 * **The reader wins.** Scrolling up during a stream — to re-read something, or
 * to look at the sources — turns following off. Coming back to the bottom turns
 * it on again. An auto-scroll that fights the reader is worse than none.
 */

import { useEffect, useRef } from "react";

/** How close to the bottom still counts as "following". */
const STICK_THRESHOLD_PX = 80;

export function useStickToBottom(
  /** Changes whenever there is new content — the streamed text itself. */
  content: unknown,
  /** True while tokens are arriving. */
  streaming: boolean,
) {
  const endRef = useRef<HTMLDivElement | null>(null);
  const following = useRef(true);

  useEffect(() => {
    function onScroll() {
      const fromBottom =
        document.documentElement.scrollHeight -
        window.innerHeight -
        window.scrollY;
      following.current = fromBottom < STICK_THRESHOLD_PX;
    }
    // Our own scrolling also fires this, and lands at the bottom, so following
    // stays on — only the reader can turn it off.
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    if (!following.current) return;
    endRef.current?.scrollIntoView({
      block: "end",
      behavior: streaming ? "auto" : "smooth",
    });
  }, [content, streaming]);

  return endRef;
}
