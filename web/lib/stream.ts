/**
 * Client-side SSE frame parser.
 *
 * Deliberately not `EventSource`: that only does GET, and the query endpoint is
 * a POST with a JSON body. Reading the fetch body stream also lets us keep the
 * request on the same-origin proxy route, so the JWT stays server-side.
 */

import type { StreamEvent } from "./types";

export async function* readEventStream(
  response: Response,
): AsyncGenerator<StreamEvent> {
  if (!response.body) return;

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // Frames are separated by a blank line. A frame can arrive split across
      // several chunks, so only complete ones are consumed.
      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);

        if (frame.startsWith("data: ")) {
          const payload = frame.slice(6);
          try {
            yield JSON.parse(payload) as StreamEvent;
          } catch {
            // A malformed frame should not kill the stream.
            yield { type: "error", message: `Malformed frame: ${payload.slice(0, 120)}` };
          }
        }
        boundary = buffer.indexOf("\n\n");
      }
    }
  } finally {
    reader.releaseLock();
  }
}
