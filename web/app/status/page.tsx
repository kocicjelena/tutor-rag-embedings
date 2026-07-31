"use client";

/**
 * The status page — what this app can do, checked rather than claimed.
 *
 * Its own page rather than a panel on `/` because the content is a different
 * kind of thing: `/` and `/tutor` are the app being used, this is the app
 * describing itself. Cramming it into a sidebar would have made the refused
 * decisions look like footnotes, and those are the part worth reading.
 */

import Link from "next/link";
import { useEffect } from "react";
import StatusBoard from "@/components/StatusBoard";
import { useContextActions, useContextState } from "@/context/GlobalContext";

export default function StatusPage() {
  // The third page that asked `/api/auth` for itself. One store, one answer — and walking
  // here from `/` no longer shows "Loading…" for a session that was already known.
  const signedIn = useContextState().session.signedIn;
  const { checkSession } = useContextActions();

  useEffect(() => {
    if (signedIn === null) void checkSession();
  }, [signedIn, checkSession]);

  return (
    <div className="shell">
      <header className="masthead">
        <div>
          <h1>mcp-py</h1>
          <div className="sub">
            What is built, what is running, and what was deliberately not built
          </div>
        </div>
        <nav className="tutor-nav">
          <Link href="/">Documents</Link>
          <Link href="/tutor">Tutor</Link>
          <Link href="/status" className="active">
            Status
          </Link>
        </nav>
      </header>

      {signedIn === null ? (
        <p className="empty">Loading…</p>
      ) : (
        <>
          <StatusBoard signedIn={signedIn} />

          {signedIn && (
            <div className="panel">
              <h2>Why a fourth status</h2>
              <p className="hint" style={{ lineHeight: 1.65 }}>
                Most of a project is <em>built</em> or <em>not built yet</em>.
                This one keeps a third category: things that were examined
                closely and then refused, because building them would have made
                the rest mean less.
              </p>
              <p className="hint" style={{ lineHeight: 1.65 }}>
                A tool that generates its own text would have made the execution
                trace a story about something that did not happen. Merging
                results from two embedding models would have produced a
                perfectly ordered, meaningless ranking. Calling the browser’s
                progress bars “your model” would have been the easiest feature
                here and would have hollowed out the real one.
              </p>
              <p className="hint" style={{ lineHeight: 1.65 }}>
                Each of those would have left the app looking the same and being
                worth less — so they are listed beside the working parts rather
                than quietly left out.
              </p>
            </div>
          )}
        </>
      )}
    </div>
  );
}
