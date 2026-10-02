import { Placeholder } from "../../shared/Placeholder";

/** Rate a visit: placeholder until lane L1 builds it. Owned by L1. */
export default function Rate() {
  return (
    <div className="c-flow">
      <Placeholder
        title="Rate a visit"
        lane="L1"
        prototype="RateScreen"
        endpoints={[
          "POST /api/c/visits/{visit_id}/rating",
          "POST /api/c/visits/{visit_id}/problem",
          "POST /api/files",
        ]}
      />
    </div>
  );
}
