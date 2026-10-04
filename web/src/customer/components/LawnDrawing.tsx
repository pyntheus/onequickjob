/**
 * Top-down lawn drawings for the size step (decisions.md A26), hand-drawn in the Village style:
 * striped lawns, a car (4.5 × 1.8 m) and a standing person at the same scale, and a house beside
 * Large and Very large. The geometry, and why every drawing shares one scale, is lawn-scene.ts.
 */
import { useId } from "react";
import { CAR, HOUSE, LABEL, SCENE_W, layoutScene, type LawnRect } from "./lawn-scene";

const INK_LINE = { stroke: "var(--ink)", strokeWidth: 1.25, vectorEffect: "non-scaling-stroke" as const };

/** A car from above, 4.5 × 1.8 m, front to the left: mirrors, windscreen, rear window. */
function Car({ x, y, f }: { x: number; y: number; f: number }) {
  return (
    <g transform={`translate(${x} ${y}) scale(${f})`}>
      <rect x={1.05} y={-0.14} width={0.28} height={2.08} rx={0.08} style={{ fill: "var(--ink)" }} />
      <rect width={CAR.l} height={CAR.w} rx={0.5} style={{ fill: "var(--surface)", ...INK_LINE }} />
      <path d="M1.3 0.25 L1.85 0.36 L1.85 1.44 L1.3 1.55 Z" style={{ fill: "var(--sky)", ...INK_LINE }} />
      <path d="M3.78 0.32 L3.45 0.4 L3.45 1.4 L3.78 1.48 Z" style={{ fill: "var(--sky)", ...INK_LINE }} />
    </g>
  );
}

/** A standing figure, side on, 1.75 m from heel to the top of the head; (x, base) is at the feet. */
function Person({ x, base, f }: { x: number; base: number; f: number }) {
  return (
    <g transform={`translate(${x} ${base}) scale(${f})`} style={{ fill: "var(--roof)" }}>
      <circle cy={-1.62} r={0.13} />
      <path
        d="M-0.23 -1.44 L0.23 -1.44 L0.19 -0.86 L0.16 0 L0.04 0 L0 -0.72 L-0.04 0 L-0.16 0 L-0.19 -0.86 Z"
        style={{ stroke: "var(--roof)", strokeWidth: 1, strokeLinejoin: "round", vectorEffect: "non-scaling-stroke" }}
      />
    </g>
  );
}

function House({ x, y }: { x: number; y: number }) {
  const line = { stroke: "var(--roof)", strokeWidth: 1.5, vectorEffect: "non-scaling-stroke" as const, fill: "none" };
  const inset = 2.2;
  return (
    <g>
      <rect x={x} y={y} width={HOUSE.w} height={HOUSE.d} rx={0.3} style={{ ...line, fill: "var(--house)" }} />
      {/* A hipped roof from above: the ridge and the four hips. */}
      <path
        d={`M${x} ${y} L${x + HOUSE.w / 2} ${y + inset} L${x + HOUSE.w} ${y} M${x} ${y + HOUSE.d} L${x + HOUSE.w / 2} ${y + HOUSE.d - inset} L${x + HOUSE.w} ${y + HOUSE.d} M${x + HOUSE.w / 2} ${y + inset} V${y + HOUSE.d - inset}`}
        style={line}
      />
      <text x={x + HOUSE.w / 2} y={y + HOUSE.d + 1.45} textAnchor="middle" className="lawn-label" fontSize={LABEL * 0.9}>
        A house,
      </text>
      <text x={x + HOUSE.w / 2} y={y + HOUSE.d + 2.75} textAnchor="middle" className="lawn-label" fontSize={LABEL * 0.9}>
        for scale
      </text>
    </g>
  );
}

/**
 * One drawing: the lawns, a car and a person below them, and a house beside the lawn if asked.
 * `label` is for screen readers; leave it out where the drawing only repeats the text beside it
 * (it's then hidden from them).
 */
export function LawnScene({ lawns, house = false, label, names = false }: { lawns: LawnRect[]; house?: boolean; label?: string; names?: boolean }) {
  const stripes = `lawn-stripes-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const scene = layoutScene(lawns, house, names);
  return (
    <svg
      viewBox={`0 0 ${SCENE_W} ${scene.height.toFixed(2)}`}
      className="lawn-fig"
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      focusable="false"
    >
      <defs>
        <pattern id={stripes} width="3" height="3" patternUnits="userSpaceOnUse">
          <rect width="1.5" height="3" style={{ fill: "var(--lawn-1)" }} />
          <rect x="1.5" width="1.5" height="3" style={{ fill: "var(--lawn-2)" }} />
        </pattern>
      </defs>
      {scene.lawns.map((l, i) => (
        <g key={i}>
          {l.name && (
            <text x={l.x} y={l.y - 0.45} className="lawn-label" fontSize={LABEL}>
              {l.name}
            </text>
          )}
          <rect
            x={l.x}
            y={l.y}
            width={l.across}
            height={l.down}
            rx={Math.min(0.5, l.down / 4)}
            style={{ fill: `url(#${stripes})`, stroke: "var(--hedge)", strokeWidth: 1.5, vectorEffect: "non-scaling-stroke" }}
          />
          {l.text && l.down >= 2.2 && l.across >= 7 && (
            <text x={l.x + l.across / 2} y={l.y + l.down / 2 + LABEL * 0.35} textAnchor="middle" className="lawn-label on-lawn" fontSize={LABEL}>
              {l.text}
            </text>
          )}
        </g>
      ))}
      {scene.house && <House x={scene.house.x} y={scene.house.y} />}
      <Car x={scene.car.x} y={scene.car.y} f={scene.f} />
      <Person x={scene.person.x} base={scene.person.base} f={scene.f} />
    </svg>
  );
}
