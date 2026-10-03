import { Placeholder } from "../../shared/Placeholder";

/** Earnings: placeholder until lane L2 builds it. Owned by L2. */
export default function Earnings() {
  return (
    <Placeholder
      title="Earnings"
      lane="L2"
      prototype="EarningsScreen"
      endpoints={[
        "GET /api/p/earnings",
      ]}
    />
  );
}
