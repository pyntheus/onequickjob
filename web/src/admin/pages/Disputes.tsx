import { Placeholder } from "../../shared/Placeholder";

/** Disputes: placeholder until lane L3 builds it. Owned by L3. */
export default function Disputes() {
  return (
    <Placeholder
      title="Disputes"
      lane="L3"
      prototype="AdminDisputes"
      endpoints={[
        "GET /api/admin/disputes",
        "POST /api/admin/disputes/{ref}/message",
        "POST /api/admin/disputes/{ref}/propose",
        "POST /api/admin/disputes/{ref}/close",
        "POST /api/admin/visits/{visit_id}/refund",
      ]}
    />
  );
}
