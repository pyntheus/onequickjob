import { Placeholder } from "../../shared/Placeholder";

/** Outbox: placeholder until lane L3 builds it. Owned by L3. */
export default function Outbox() {
  return (
    <Placeholder
      title="Outbox"
      lane="L3"
      prototype="(new) the full, searchable outbox"
      endpoints={[
        "GET /api/admin/outbox?q=&channel=&template_id=&before=",
        "GET /api/admin/audit",
      ]}
    />
  );
}
