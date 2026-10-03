import { Placeholder } from "../../shared/Placeholder";

/** Waiting for providers: placeholder until lane L1 builds it. Owned by L1. */
export default function Offers() {
  return (
    <div className="c-flow">
      <Placeholder
        title="Waiting for providers"
        lane="L1"
        prototype="OffersScreen"
        endpoints={[
          "GET /api/c/requests/{ref}",
          "POST /api/c/offers/{offer_id}/accept",
          "POST /api/c/offers/{offer_id}/decline",
          "POST /api/c/requests/{ref}/cancel",
          "POST /api/c/requests/{ref}/demo/simulate (DEMO_MODE only)",
        ]}
      />
    </div>
  );
}
