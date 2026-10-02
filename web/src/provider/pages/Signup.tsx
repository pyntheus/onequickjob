import { Placeholder } from "../../shared/Placeholder";

/** Sign-up: placeholder until lane L2 builds it. Owned by L2. */
export default function Signup() {
  return (
    <Placeholder
      title="Sign-up"
      lane="L2"
      prototype="OnboardingScreen"
      endpoints={[
        "GET /api/p/signup",
        "POST /api/p/signup/start",
        "PUT /api/p/signup/tax",
        "POST /api/p/signup/payment-account",
        "POST /api/p/signup/callback",
      ]}
    />
  );
}
