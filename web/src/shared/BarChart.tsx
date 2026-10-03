import { fmt } from "./format";

/** The earnings bar chart: last bar highlighted with its value. Values are pence. */
export function BarChart({ data, labels, format = fmt, label }: { data: number[]; labels: string[]; format?: (v: number) => string; label: string }) {
  const W = 340;
  const H = 140;
  const max = Math.max(1, ...data) * 1.18;
  const bw = (W - 8) / Math.max(1, data.length);
  return (
    <svg viewBox={`0 0 ${W} ${H + 22}`} className="chart" role="img" aria-label={label}>
      {data.map((v, i) => {
        const h = (v / max) * H;
        const x = 4 + i * bw + bw * 0.17;
        const w = bw * 0.66;
        const last = i === data.length - 1;
        return (
          <g key={i}>
            <rect x={x} y={H - h} width={w} height={h} rx="5" style={{ fill: last ? "var(--accent)" : "var(--primary)", opacity: last ? 1 : 0.55 }} />
            {last && (
              <text x={x + w / 2} y={H - h - 7} textAnchor="middle" className="chart-val">
                {format(v)}
              </text>
            )}
            <text x={x + w / 2} y={H + 16} textAnchor="middle" className="chart-lbl">
              {labels[i]}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
