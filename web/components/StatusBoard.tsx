"use client";

/**
 * What this app can do, as the app reports it about itself.
 *
 * Two things make this different from a feature list in a README:
 *
 * 1. **`running` is measured.** The backend opened a real MCP session, embedded
 *    a string, and read `vec_version()` out of SQLite before this rendered.
 *    Each measured row shows what was observed, so the claim can be checked
 *    rather than believed.
 *
 * 2. **`exploring` is a first-class status.** Those are not a backlog and not
 *    failures — they are things the project came near to building and refused,
 *    because building them would have made everything else mean less. On a
 *    project about retrieval and model protocols, the refusals are as much of
 *    the demonstration as the code, so they are shown, not hidden.
 */

import { useCallback, useEffect, useState } from "react";
import type {
  Capability,
  CapabilityArea,
  CapabilityReport,
  CapabilityStatus,
} from "@/lib/types";

const STATUS_META: Record<
  CapabilityStatus,
  { label: string; className: string; blurb: string }
> = {
  running: {
    label: "running",
    className: "ok",
    blurb: "Checked just now, in this process. The evidence is what was observed.",
  },
  built: {
    label: "built",
    className: "",
    blurb:
      "Committed and tested, but not verified here — either it cannot be probed from inside, or it is not switched on.",
  },
  building: {
    label: "building",
    className: "warn",
    blurb: "Started and unfinished. Listed on purpose rather than left out.",
  },
  exploring: {
    label: "explored, refused",
    className: "err",
    blurb:
      "Examined closely and deliberately not built — because it would have made the rest of the app mean less.",
  },
};

const AREA_LABEL: Record<CapabilityArea, string> = {
  llm: "Language models",
  rag: "Retrieval",
  mcp: "Model Context Protocol",
  identity: "Identity and keys",
  deploy: "Deployment",
};

const AREA_ORDER: CapabilityArea[] = ["rag", "llm", "mcp", "identity", "deploy"];

// `exploring` last within an area: the working parts answer "does it work",
// and the refusals answer "why is it shaped like this" — which only makes
// sense once you have seen the shape.
const STATUS_ORDER: CapabilityStatus[] = [
  "running",
  "built",
  "building",
  "exploring",
];

export default function StatusBoard({ signedIn }: { signedIn: boolean }) {
  const [report, setReport] = useState<CapabilityReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!signedIn) return;
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/api/status", { cache: "no-store" });
      if (!response.ok) {
        const body = (await response.json().catch(() => ({}))) as {
          detail?: unknown;
        };
        setError(
          typeof body.detail === "string"
            ? body.detail
            : `Could not read status (${response.status})`,
        );
        return;
      }
      setReport((await response.json()) as CapabilityReport);
    } catch {
      setError("Could not reach the app.");
    } finally {
      setBusy(false);
    }
  }, [signedIn]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  if (!signedIn) {
    return (
      <div className="panel">
        <h2>What works</h2>
        <p className="empty">Sign in to see what this app can currently do.</p>
      </div>
    );
  }

  const byArea = (area: CapabilityArea) =>
    (report?.data ?? [])
      .filter((c) => c.area === area)
      .sort(
        (a, b) =>
          STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status),
      );

  return (
    <div className="panel">
      <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
        <h2 style={{ flex: 1 }}>What works</h2>
        <button
          className="ghost"
          onClick={() => void refresh()}
          disabled={busy}
          style={{ fontSize: 12 }}
        >
          {busy ? "checking…" : "re-check"}
        </button>
      </div>

      <p className="hint" style={{ marginTop: 0 }}>
        Measured, not claimed. Every <em>running</em> row below was verified a
        moment ago — an MCP session was opened, a string was embedded, the
        vector extension was asked its version.
      </p>

      {error && <div className="error-box">{error}</div>}

      {report && (
        <div className="status-totals">
          {STATUS_ORDER.map((status) => {
            const count = report.totals[status] ?? 0;
            if (!count) return null;
            return (
              <span key={status} className={`badge ${STATUS_META[status].className}`}>
                {count} {STATUS_META[status].label}
              </span>
            );
          })}
        </div>
      )}

      {!report && !error && <p className="empty">Checking…</p>}

      {report &&
        AREA_ORDER.map((area) => {
          const items = byArea(area);
          if (items.length === 0) return null;
          return (
            <section key={area} className="status-area">
              <h3>{AREA_LABEL[area]}</h3>
              {items.map((item) => (
                <Row
                  key={item.key}
                  item={item}
                  expanded={open === item.key}
                  onToggle={() =>
                    setOpen((current) => (current === item.key ? null : item.key))
                  }
                />
              ))}
            </section>
          );
        })}

      {report && (
        <p className="hint" style={{ marginTop: 12 }}>
          Checked{" "}
          {new Date(report.generated_at).toLocaleTimeString(undefined, {
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
          })}
          . Rows without evidence were declared, not measured — there is no way
          to ask this process about them from inside it.
        </p>
      )}
    </div>
  );
}

function Row({
  item,
  expanded,
  onToggle,
}: {
  item: Capability;
  expanded: boolean;
  onToggle: () => void;
}) {
  const meta = STATUS_META[item.status];
  const hasMore = Boolean(item.detail || item.evidence || item.doc);

  return (
    <div className={`status-row ${item.status === "exploring" ? "refused" : ""}`}>
      <button
        className="status-head"
        onClick={onToggle}
        aria-expanded={expanded}
        disabled={!hasMore}
        title={meta.blurb}
      >
        <span className={`badge ${meta.className}`}>{meta.label}</span>
        <span className="status-name">{item.name}</span>
        <span className="status-summary">{item.summary}</span>
        {hasMore && <span className="status-chevron">{expanded ? "−" : "+"}</span>}
      </button>

      {expanded && (
        <div className="status-detail">
          {item.detail && <p>{item.detail}</p>}

          {item.evidence && (
            <p className="status-evidence">
              <strong>{item.probed ? "Observed:" : "Note:"}</strong>{" "}
              <code>{item.evidence}</code>
            </p>
          )}

          {/* Said out loud rather than implied by a missing line: an
              unprobed row is someone's assertion, and should not borrow the
              credibility of the rows that were actually checked. */}
          {!item.probed && item.status !== "exploring" && (
            <p className="status-evidence">
              <em>Not probed — this status is declared, not measured.</em>
            </p>
          )}

          {item.doc && (
            <p className="status-evidence">
              Written up in <code>{item.doc}</code>
            </p>
          )}
        </div>
      )}
    </div>
  );
}
