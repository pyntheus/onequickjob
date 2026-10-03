import { Check, MessageCircle } from "lucide-react";
import type { CSSProperties } from "react";
import { useParams } from "react-router";
import { useMe } from "../../api/queries";
import { Button } from "../../shared/Button";
import { fmt } from "../../shared/format";
import { SignInForm } from "../../shared/SignInForm";
import { Loading, Notice } from "../../app/Status";
import { errorText, useBooking } from "../api";
import { ProviderSummary } from "../components/ProviderSummary";

const g = (px: number) => ({ "--g": `${px}px` }) as CSSProperties;

/** "You're booked": the provider with their checks, the terms, the split and who it's with. */
export default function Booked() {
  const { bookingId = "" } = useParams();
  const { data: me, isLoading: meLoading } = useMe();
  const { data: b, isLoading, error } = useBooking(bookingId, !!me);

  if (meLoading || (me && isLoading)) return <Loading />;
  if (!me) {
    return (
      <div className="c-flow">
        <SignInForm title="Sign in to see your booking" />
      </div>
    );
  }
  if (error || !b) {
    return (
      <div className="c-flow">
        <Notice title="We can't find that booking">
          <p className="muted">{errorText(error)}</p>
          <Button to="/account" variant="primary">
            Go to my account
          </Button>
        </Notice>
      </div>
    );
  }
  const who = b.provider.first_name;
  const own = b.source === "own_customer";
  return (
    <div className="c-flow">
      <div className="stack center" style={{ ...g(12), alignItems: "center", paddingTop: 8 }}>
        <span className="success-mark" aria-hidden="true">
          <Check size={32} strokeWidth={3} />
        </span>
        <h1 className="h1">{b.status === "cancelled" ? "This booking is cancelled" : "You're booked"}</h1>
        {b.sms_sent_to && b.status !== "cancelled" && <p className="muted">We've texted the details to {b.sms_sent_to}.</p>}
      </div>
      <div className="card stack" style={g(16)}>
        <ProviderSummary p={b.provider} />
        <hr />
        <dl className="kv">
          <dt>Job</dt>
          <dd>
            {b.category_name}
            {b.recurring && b.frequency_label ? `, ${b.frequency_label}` : ""}
          </dd>
          <dt>{b.recurring ? "First visit" : "When"}</dt>
          <dd>{b.first_visit_text}</dd>
          <dt>Price</dt>
          <dd>
            {fmt(b.price_pence)} {b.unit}, charged after {b.charged_after}
            {b.first_price_pence ? ` (first visit ${fmt(b.first_price_pence)})` : ""}
          </dd>
          <dt>Split</dt>
          <dd>
            {fmt(b.split.provider_pence)} to {who}, {fmt(b.split.fee_pence)} OneQuickJob fee
            {own ? `, paid by ${who}` : ""}
          </dd>
        </dl>
      </div>
      <div className="soft small stack" style={g(6)}>
        <b>Who you're dealing with</b>
        <span>{b.agreement_text}</span>
      </div>
      <div className="grid2">
        <Button variant="ghost" to={`/account?tab=messages${b.thread_id ? `&thread=${b.thread_id}` : ""}`}>
          <MessageCircle size={17} aria-hidden="true" /> Message {who}
        </Button>
        <Button variant="primary" to="/account">
          My account
        </Button>
      </div>
    </div>
  );
}
