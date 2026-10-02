import { Placeholder } from "../../shared/Placeholder";

/** Time off and helpers: placeholder until lane L2 builds it. Owned by L2. */
export default function TimeOff() {
  return (
    <Placeholder
      title="Time off and helpers"
      lane="L2"
      prototype="CoverScreen"
      endpoints={[
        "POST /api/p/time-off/preview",
        "GET /api/p/time-off",
        "POST /api/p/time-off",
        "DELETE /api/p/time-off/{time_off_id}",
        "GET /api/p/helpers",
        "POST /api/p/helpers",
      ]}
    />
  );
}
