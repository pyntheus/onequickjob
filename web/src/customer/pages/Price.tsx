import { Placeholder } from "../../shared/Placeholder";

/** Guide price: placeholder until lane L1 builds it. Owned by L1. */
export default function Price() {
  return (
    <div className="c-flow">
      <Placeholder
        title="Guide price"
        lane="L1"
        prototype="PriceScreen"
        endpoints={[
          "POST /api/quotes",
        ]}
      />
    </div>
  );
}
