import { Placeholder } from "../../shared/Placeholder";

/** Provider: placeholder until lane L3 builds it. Owned by L3. */
export default function ProviderDetail() {
  return (
    <Placeholder
      title="Provider"
      lane="L3"
      prototype="(new) provider detail, from the AdminProviders row"
      endpoints={[
        "GET /api/admin/providers/{provider_id}",
        "POST /api/admin/providers/{provider_id}/documents/{doc_type}/verify",
        "POST /api/admin/providers/{provider_id}/documents/{doc_type}/reject",
        "POST /api/admin/providers/{provider_id}/suspend",
        "POST /api/admin/providers/{provider_id}/reinstate",
        "POST /api/admin/providers/{provider_id}/nudge",
      ]}
    />
  );
}
