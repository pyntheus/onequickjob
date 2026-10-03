import { Placeholder } from "../../shared/Placeholder";

/** Contact and card: placeholder until lane L1 builds it. Owned by L1. */
export default function Contact() {
  return (
    <div className="c-flow">
      <Placeholder
        title="Contact and card"
        lane="L1"
        prototype="ContactScreen (card capture: web/src/payments/CardCapture)"
        endpoints={[
          "POST /api/auth/code",
          "POST /api/auth/verify",
          "POST /api/c/payment/setup",
          "POST /api/c/payment/setup/{setup_id}/confirm",
          "POST /api/c/requests",
        ]}
      />
    </div>
  );
}
