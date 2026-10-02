import { Placeholder } from "../../shared/Placeholder";

/** Finish a job: placeholder until lane L2 builds it. Owned by L2. */
export default function Finish() {
  return (
    <Placeholder
      title="Finish a job"
      lane="L2"
      prototype="FinishScreen"
      endpoints={[
        "POST /api/p/visits/{visit_id}/finish",
      ]}
    />
  );
}
