import { Placeholder } from "../../shared/Placeholder";

/** Tax and records: placeholder until lane L2 builds it. Owned by L2. */
export default function Tax() {
  return (
    <Placeholder
      title="Tax and records"
      lane="L2"
      prototype="TaxScreen"
      endpoints={[
        "GET /api/p/tax",
        "GET /api/p/tax/pack.csv",
        "GET /api/p/tax/pack.html",
        "GET /api/p/mileage",
        "GET /api/p/expenses",
        "POST /api/p/expenses",
        "DELETE /api/p/expenses/{expense_id}",
      ]}
    />
  );
}
