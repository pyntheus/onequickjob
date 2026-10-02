import { Placeholder } from "../../shared/Placeholder";

/** My account: placeholder until lane L1 builds it. Owned by L1. */
export default function Account() {
  return (
    <div className="c-flow wide">
      <Placeholder
        title="My account"
        lane="L1"
        prototype="AccountScreen"
        endpoints={[
          "GET /api/c/visits",
          "GET /api/c/plans",
          "PATCH /api/c/plans/{series_id}",
          "POST /api/c/plans/{series_id}/cancel",
          "POST /api/c/visits/{visit_id}/skip",
          "POST /api/c/visits/{visit_id}/change-date",
          "POST /api/c/bookings/{booking_id}/rebook",
          "GET /api/c/threads",
          "GET /api/c/threads/{thread_id}/messages",
          "POST /api/c/threads/{thread_id}/messages",
          "GET /api/c/profile",
        ]}
      />
    </div>
  );
}
