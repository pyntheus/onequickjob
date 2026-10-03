/** The prototype's illustrations: the hero garden and the placeholder "after" pictures. */
import type { CSSProperties } from "react";

const f = (v: string): CSSProperties => ({ fill: `var(${v})` });

export function GardenArt() {
  return (
    <svg viewBox="0 0 440 380" className="garden-art" aria-hidden="true">
      <defs>
        <clipPath id="pt-lawn-clip">
          <rect x="30" y="200" width="380" height="150" rx="18" />
        </clipPath>
      </defs>
      <rect width="440" height="380" rx="28" style={f("--sky")} />
      <rect x="250" y="72" width="150" height="120" rx="6" style={{ ...f("--house"), stroke: "var(--roof)", strokeWidth: 2 }} />
      <path d="M238 80 L325 22 L412 80 Z" style={f("--roof")} />
      <rect x="273" y="108" width="34" height="34" rx="4" style={f("--sky")} />
      <rect x="343" y="108" width="34" height="34" rx="4" style={f("--sky")} />
      <rect x="311" y="150" width="30" height="42" rx="3" style={f("--roof")} />
      <g clipPath="url(#pt-lawn-clip)">
        {Array.from({ length: 10 }).map((_, i) => (
          <rect key={i} x={30 + i * 38} y="200" width="38" height="150" style={f(i % 2 ? "--lawn-1" : "--lawn-2")} />
        ))}
      </g>
      {[42, 80, 118, 156, 194].map((cx, i) => (
        <circle key={i} cx={cx} cy={182 + (i % 2) * 4} r={30} style={f("--hedge")} />
      ))}
      <path d="M306 192 C 306 250, 256 282, 246 350 L 296 350 C 306 292, 342 252, 346 192 Z" style={f("--path")} />
      <g transform="translate(98 262)">
        <rect width="56" height="26" rx="8" style={f("--accent")} />
        <circle cx="11" cy="28" r="7" style={f("--ink")} />
        <circle cx="45" cy="28" r="7" style={f("--ink")} />
        <path d="M52 4 L80 -30" style={{ stroke: "var(--ink)", strokeWidth: 5, strokeLinecap: "round" }} />
      </g>
    </svg>
  );
}

export function AfterPhotoArt() {
  return (
    <svg viewBox="0 0 400 170" className="chart" role="img" aria-label="Illustration of a mown lawn">
      <rect width="400" height="170" style={f("--sky")} />
      {Array.from({ length: 12 }).map((_, i) => (
        <rect key={i} x={i * 34 - 10} y="52" width="34" height="118" style={f(i % 2 ? "--lawn-1" : "--lawn-2")} />
      ))}
      {[20, 70, 120, 170, 220, 270, 320, 370].map((cx, i) => (
        <circle key={i} cx={cx} cy={40 + (i % 2) * 6} r={32} style={f("--hedge")} />
      ))}
      <rect x="0" y="150" width="400" height="20" style={f("--path")} />
    </svg>
  );
}

export function RoomPhotoArt() {
  return (
    <svg viewBox="0 0 400 170" className="chart" role="img" aria-label="Illustration of a clean living room">
      <rect width="400" height="118" style={f("--sky")} />
      <rect y="118" width="400" height="52" style={f("--path")} />
      <rect x="40" y="26" width="92" height="66" rx="4" style={{ ...f("--surface"), stroke: "var(--hedge)", strokeWidth: 4 }} />
      <line x1="86" y1="26" x2="86" y2="92" style={{ stroke: "var(--hedge)", strokeWidth: 3 }} />
      <rect x="190" y="78" width="160" height="50" rx="12" style={f("--primary")} />
      <rect x="182" y="66" width="26" height="62" rx="10" style={f("--primary")} />
      <rect x="332" y="66" width="26" height="62" rx="10" style={f("--primary")} />
      <rect x="214" y="70" width="44" height="24" rx="8" style={f("--accent")} />
      <rect x="150" y="96" width="18" height="30" rx="3" style={f("--hedge")} />
      <circle cx="159" cy="86" r="16" style={f("--lawn-1")} />
    </svg>
  );
}
