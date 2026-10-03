import { Placeholder } from "../../shared/Placeholder";

/** Providers: placeholder until lane L3 builds it. Owned by L3. */
export default function Providers() {
  return (
    <Placeholder
      title="Providers"
      lane="L3"
      prototype="AdminProviders"
      endpoints={[
        "GET /api/admin/providers?filter=",
        "GET /api/admin/hmrc-export.csv?year=",
      ]}
    />
  );
}
