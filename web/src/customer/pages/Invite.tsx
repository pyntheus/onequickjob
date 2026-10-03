import { useQueryClient } from "@tanstack/react-query";
import { Bell, Camera, Check, CreditCard, Receipt, Users } from "lucide-react";
import { useState, type CSSProperties } from "react";
import { useParams } from "react-router";
import { api, call, type Schemas } from "../../api/client";
import { useMe } from "../../api/queries";
import { CardCapture, type SavedCard } from "../../payments/CardCapture";
import { Avatar } from "../../shared/Avatar";
import { Button } from "../../shared/Button";
import { CheckRow } from "../../shared/CheckRow";
import { fmt } from "../../shared/format";
import { Loading, Notice } from "../../app/Status";
import { errorText, useInvite, useProfile, type Address } from "../api";
import { AddressSearch } from "../components/AddressSearch";
import { InlineSignIn } from "../components/InlineSignIn";

const g = (px: number) => ({ "--g": `${px}px` }) as CSSProperties;

/** A provider's invite to an existing customer: their price, not ours; the fee isn't added. */
export default function Invite() {
  const { token = "" } = useParams();
  const qc = useQueryClient();
  const { data: me } = useMe();
  const { data: inv, isLoading, error } = useInvite(token);
  const { data: profile, isFetched: profileLoaded } = useProfile(!!me);
  const [card, setCard] = useState<SavedCard | null>(null);
  const [address, setAddress] = useState<Address | null>(null);
  const [addressText, setAddressText] = useState("");
  const [agree, setAgree] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState<Schemas["BookingCard"] | null>(null);

  if (isLoading) return <Loading />;
  if (error || !inv) {
    return (
      <div className="c-flow">
        <Notice title="We can't find that invite">
          <p className="muted">The link may be mistyped. Ask your provider to send it again.</p>
        </Notice>
      </div>
    );
  }
  const who = inv.provider.first_name;
  const name = inv.customer_first_name;
  if (done) {
    return (
      <div className="c-flow">
        <div className="stack center" style={{ ...g(14), alignItems: "center", paddingTop: 24 }}>
          <span className="success-mark" aria-hidden="true">
            <Check size={32} strokeWidth={3} />
          </span>
          <h1 className="h1">You're all set, {name}</h1>
          <p className="muted">
            {who}'s next visit is {done.first_visit_text.split(",")[0]}. You'll pay by card after each visit.
          </p>
          <Button to="/account" variant="primary" size="lg">
            Done
          </Button>
        </div>
      </div>
    );
  }
  if (inv.status !== "invited") {
    return (
      <div className="c-flow">
        <Notice title={inv.status === "accepted" ? "You've already accepted this invite" : "This invite has closed"}>
          <p className="muted">
            {inv.status === "accepted"
              ? `Your visits with ${who} are in your account.`
              : `Ask ${who} to send you a new one if you'd like to arrange visits through OneQuickJob.`}
          </p>
          {inv.status === "accepted" && (
            <Button to="/account" variant="primary">
              Go to my account
            </Button>
          )}
        </Notice>
      </div>
    );
  }

  const perks = [
    { icon: CreditCard, title: "Pay by card after each visit", text: "No more cash or bank transfers." },
    { icon: Bell, title: "A text the day before", text: `So you know when ${who}'s coming.` },
    { icon: Camera, title: "A photo when it's done", text: "Handy if you're out." },
    { icon: Receipt, title: "A receipt for every visit", text: "All in one place." },
    { icon: Users, title: `Cover if ${who}'s away`, text: `Only if you want it. ${who} carries on afterwards.` },
  ];
  const savedCard = card ?? profile?.card ?? null;
  const hasAddress = !!address || !!profile?.addresses.length;
  const ready = !!me && !!savedCard && hasAddress && agree;

  const accept = async () => {
    setBusy(true);
    setErr(null);
    try {
      const booking = await call(
        api.POST("/api/c/invites/{token}/accept", { params: { path: { token } }, body: { agree_terms: true, address } }),
      );
      await qc.invalidateQueries({ queryKey: ["c"] });
      setDone(booking);
    } catch (e) {
      setErr(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="c-flow">
      <div className="card stack center" style={{ ...g(12), alignItems: "center" }}>
        <Avatar initials={inv.provider.initials} size={64} />
        <h1 className="h1">{who} has invited you to OneQuickJob</h1>
        <p className="muted">
          Hi {name}. {who} would like to arrange your visits through OneQuickJob from now on.
        </p>
      </div>
      <div className="card flat">
        <dl className="kv">
          <dt>Job</dt>
          <dd>
            {inv.category_name}, {inv.frequency_label}
          </dd>
          <dt>Price</dt>
          <dd>
            {fmt(inv.price_pence)} a visit, set by {who}
          </dd>
          {inv.next_visit_text && (
            <>
              <dt>Next visit</dt>
              <dd>{inv.next_visit_text}</dd>
            </>
          )}
        </dl>
      </div>
      <div className="card flat stack" style={g(14)}>
        <h2 className="h3">What changes for you</h2>
        {perks.map(({ icon: I, title, text }) => (
          <div key={title} className="check-row">
            <span className="ci">
              <I size={18} aria-hidden="true" />
            </span>
            <div className="stack" style={g(1)}>
              <b>{title}</b>
              <span className="small muted">{text}</span>
            </div>
          </div>
        ))}
        <p className="small muted">Nothing else changes. Same {who}, same price.</p>
      </div>
      <div className="soft small">
        Your agreement is still with {who}. OneQuickJob handles bookings and payments on {who}'s behalf, and {who} pays us a
        small fee of {fmt(inv.provider_fee_pence)} a visit. It isn't added to your price.
      </div>
      {!me ? (
        <div className="card stack" style={g(12)}>
          <h2 className="h3">First, confirm it's you</h2>
          <InlineSignIn
            phone=""
            name={name}
            phoneLabel="Your mobile number"
            phoneHint={`The number ${who} texted: ${inv.phone_hint}`}
            onSignedIn={() => undefined}
          />
        </div>
      ) : (
        <>
          {!profile?.addresses.length && (
            <AddressSearch
              label="Your address"
              value={addressText}
              onText={(t) => {
                setAddressText(t);
                if (address && address.label !== t) setAddress(null);
              }}
              onResolved={(a) => {
                setAddress(a);
                setAddressText(a.label);
              }}
            />
          )}
          {profileLoaded && <CardCapture key={savedCard?.last4 ?? "none"} saved={savedCard} onSaved={setCard} />}
        </>
      )}
      <CheckRow on={agree} onChange={setAgree}>
        I agree to the customer terms. My agreement for the work is with {who}, and OneQuickJob acts as {who}'s booking and
        payment agent.
      </CheckRow>
      {err && (
        <p className="field-error" role="alert">
          {err}
        </p>
      )}
      <button type="button" className="btn btn-cta btn-lg btn-block" disabled={!ready || busy} onClick={accept}>
        Accept {who}'s invite
      </button>
      <p className="xs muted center">You can stop using OneQuickJob at any time and arrange things with {who} directly again.</p>
    </div>
  );
}
