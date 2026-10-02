import { Placeholder } from "../../shared/Placeholder";

/** Your own customers: placeholder until lane L2 builds it. Owned by L2. */
export default function OwnCustomers() {
  return (
    <Placeholder
      title="Your own customers"
      lane="L2"
      prototype="OwnCustomersScreen"
      endpoints={[
        "GET /api/p/own-customers",
        "POST /api/p/own-customers/invites",
      ]}
    />
  );
}
