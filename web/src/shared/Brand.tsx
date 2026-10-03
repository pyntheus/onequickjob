import { Sprout } from "lucide-react";
import { Link } from "react-router";

export const BRAND = "OneQuickJob";

export function Brand({ to = "/", small, suffix }: { to?: string; small?: boolean; suffix?: string }) {
  return (
    <Link to={to} className={"brand" + (small ? " sm" : "")} aria-label={`${BRAND}${suffix ? ` ${suffix}` : ""} home`}>
      <span className="brand-mark" aria-hidden="true">
        <Sprout size={small ? 14 : 18} strokeWidth={2.2} />
      </span>
      {BRAND}
      {suffix ? ` ${suffix}` : ""}
    </Link>
  );
}
