import { Placeholder } from "../../shared/Placeholder";

/** Overview and dispatch: placeholder until lane L3 builds it. Owned by L3. */
export default function Overview() {
  return (
    <Placeholder
      title="Overview and dispatch"
      lane="L3"
      prototype="AdminOverview"
      endpoints={[
        "GET /api/admin/overview",
        "GET /api/admin/requests/{ref}/whatsapp",
        "POST /api/admin/requests/{ref}/raise-guide",
      ]}
    />
  );
}
