import type { CSSProperties } from "react";
import { Badge } from "./Badge";

export type Lane = "L1" | "L2" | "L3";

type Props = {
  title: string;
  lane: Lane;
  /** The prototype component(s) to lift, e.g. "MeasureScreen". */
  prototype: string;
  endpoints: string[];
  notes?: string;
};

const LANE_NAMES: Record<Lane, string> = { L1: "Customer", L2: "Provider", L3: "Admin and payments" };

/** Every screen starts as this: what it is, who builds it, what to lift and which API it uses. */
export function Placeholder({ title, lane, prototype, endpoints, notes }: Props) {
  return (
    <div className="card stack" style={{ "--g": "14px" } as CSSProperties}>
      <div className="row between wrap top" style={{ "--g": "10px" } as CSSProperties}>
        <h1 className="h2">{title}</h1>
        <Badge tone="accent">
          {lane}: {LANE_NAMES[lane]}
        </Badge>
      </div>
      <p className="muted">Lane {lane} builds this screen.</p>
      <p className="small">
        Lift <span className="ident">{prototype}</span> in docs/design/prototype.jsx.
      </p>
      {notes && <p className="small muted">{notes}</p>}
      {endpoints.length > 0 && (
        <div className="stack" style={{ "--g": "6px" } as CSSProperties}>
          <span className="label">API</span>
          <ul className="placeholder-endpoints">
            {endpoints.map((e) => (
              <li key={e}>
                <code>{e}</code>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
