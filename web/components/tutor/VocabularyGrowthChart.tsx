"use client";

/**
 * Vocabulary growth sparkline.
 *
 * The source used `recharts`. This is an inline SVG instead — one fewer
 * dependency for a chart this small, and it inherits the theme through
 * currentColor rather than needing hard-coded hex values that would break in
 * light mode.
 */

import type { VocabularyGrowthPoint } from "./lib/types";
import { TrendIcon } from "./Icons";

const W = 280;
const H = 78;
const PAD = 6;

export function VocabularyGrowthChart({
  chartData,
}: {
  chartData: VocabularyGrowthPoint[];
}) {
  const hasShape = chartData.length > 1;
  const maxTerms = Math.max(1, ...chartData.map((p) => p.terms));

  const points = chartData.map((point, index) => {
    const x =
      PAD +
      (index / Math.max(1, chartData.length - 1)) * (W - PAD * 2);
    const y = H - PAD - (point.terms / maxTerms) * (H - PAD * 2);
    return { x, y, ...point };
  });

  const line = points.map((p) => `${p.x},${p.y}`).join(" ");
  const area = hasShape
    ? `${PAD},${H - PAD} ${line} ${points[points.length - 1].x},${H - PAD}`
    : "";

  return (
    <div className="panel">
      <h2>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <TrendIcon size={13} /> Vocabulary growth
        </span>
      </h2>

      {chartData.length === 0 ? (
        <p className="empty">Ask something to start the chart.</p>
      ) : (
        <>
          <svg
            className="spark"
            viewBox={`0 0 ${W} ${H}`}
            preserveAspectRatio="none"
            role="img"
            aria-label={`Key terms per session across ${chartData.length} sessions, peaking at ${maxTerms}`}
          >
            {hasShape && <polygon className="area" points={area} />}
            {hasShape && <polyline className="line" points={line} />}
            {points.map((p) => (
              <circle key={p.session} className="pt" cx={p.x} cy={p.y} r={2.5} />
            ))}
          </svg>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <span className="hint">session {points[0]?.session}</span>
            <span className="hint">
              peak {maxTerms} term{maxTerms === 1 ? "" : "s"}
            </span>
            <span className="hint">
              session {points[points.length - 1]?.session}
            </span>
          </div>
        </>
      )}
    </div>
  );
}
