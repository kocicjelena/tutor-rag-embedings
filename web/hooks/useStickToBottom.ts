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
import { useContextState } from "@/context/GlobalContext";

/** How close to the bottom still counts as "following". */
const STICK_THRESHOLD_PX = 80;

/**
 * ## Why this stayed a hook rather than moving into the provider
 *
 * Jelena asked whether both hooks should be folded into `GlobalContext`. `useLearningTutor`
 * should and now is. This one should not, and the reason is structural rather than a
 * preference: what it returns is a **ref to one DOM element**, and refs are per-element. `/`
 * and `/tutor` each have their own scroll container, and a store can hold one ref or a map
 * of refs — the first is wrong and the second is a registry pretending to be state.
 *
 * What *did* move is the part that is genuinely shared: whether a stream is running. Callers
 * no longer pass it, because the store already knows.
 */
export function useStickToBottom(
  /** Changes whenever there is new content — the streamed text itself. */
  content: unknown,
  /**
   * True while tokens are arriving. Omit it and the store answers: any stream anywhere in
   * the app counts, which is right, because there is only ever one at a time.
   */
  streaming?: boolean,
) {
  const streamStatus = useContextState().stream.status;
  const isStreaming = streaming ?? streamStatus === "streaming";
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
      behavior: isStreaming ? "auto" : "smooth",
    });
  }, [content, isStreaming]);

  return endRef;
}
