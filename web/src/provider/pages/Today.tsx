import { Placeholder } from "../../shared/Placeholder";

/** Today's round: placeholder until lane L2 builds it. Owned by L2. */
export default function Today() {
  return (
    <Placeholder
      title="Today's round"
      lane="L2"
      prototype="TodayScreen"
      endpoints={[
        "GET /api/p/today",
        "GET /api/p/visits/{visit_id}",
        "POST /api/p/visits/{visit_id}/start",
        "POST /api/p/visits/{visit_id}/photos",
        "POST /api/files",
        "POST /api/p/visits/{visit_id}/send-helper",
        "POST /api/p/visits/{visit_id}/cover",
      ]}
    />
  );
}
