import { Placeholder } from "../../shared/Placeholder";

/** Earnings limit: placeholder until lane L2 builds it. Owned by L2. */
export default function Limit() {
  return (
    <Placeholder
      title="Earnings limit"
      lane="L2"
      prototype="LimitScreen"
      notes="The benefits answer is never sent or stored, only the limit."
      endpoints={[
        "GET /api/p/limit",
        "PUT /api/p/limit",
      ]}
    />
  );
}
