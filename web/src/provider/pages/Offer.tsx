import { Placeholder } from "../../shared/Placeholder";

/** Job offer: placeholder until lane L2 builds it. Owned by L2. */
export default function Offer() {
  return (
    <Placeholder
      title="Job offer"
      lane="L2"
      prototype="OfferDetail and ApproxMap"
      notes="Opening a job-alert link signs the provider in with its single-use token (POST /api/auth/magic, done by the layout)."
      endpoints={[
        "GET /api/p/requests/{ref}",
        "POST /api/p/requests/{ref}/accept",
        "POST /api/p/requests/{ref}/counter",
      ]}
    />
  );
}
