import { Placeholder } from "../../shared/Placeholder";

/** Booking confirmed: placeholder until lane L1 builds it. Owned by L1. */
export default function Booked() {
  return (
    <div className="c-flow">
      <Placeholder
        title="Booking confirmed"
        lane="L1"
        prototype="BookedScreen"
        endpoints={[
          "GET /api/c/bookings/{booking_id}",
        ]}
      />
    </div>
  );
}
