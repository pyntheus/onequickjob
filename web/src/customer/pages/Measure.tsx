import { Placeholder } from "../../shared/Placeholder";

/** Lawn measurement: placeholder until lane L1 builds it. Owned by L1. */
export default function Measure() {
  return (
    <div className="c-flow">
      <Placeholder
        title="Lawn measurement"
        lane="L1"
        prototype="MeasureScreen"
        notes="v0 uses the manual size bands (Small, Medium, Large, Very large) plus Looks smaller / About right / Looks bigger, not the LIDAR plan."
        endpoints={[
          "GET /api/area/options",
        ]}
      />
    </div>
  );
}
