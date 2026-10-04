/**
 * Saving a customer's card through the PaymentGateway. Owned by L3: L1's contact and invite
 * screens render it and never change. With the fake gateway it saves test card 4242 at once;
 * with PAYMENT_GATEWAY=stripe it shows Stripe's Payment Element, confirms the SetupIntent in
 * the browser (the card never touches our servers) and then asks the API to record the card.
 */
import { Elements, PaymentElement, useElements, useStripe } from "@stripe/react-stripe-js";
import type { Appearance, Stripe } from "@stripe/stripe-js";
import { loadStripe } from "@stripe/stripe-js/pure";
import { CreditCard, Lock } from "lucide-react";
import { useState, type CSSProperties } from "react";
import { ApiError, api, call, type Schemas } from "../api/client";
import { useConfig } from "../api/queries";
import { Button } from "../shared/Button";

export type SavedCard = Schemas["SavedCardInfo"];
type Setup = Schemas["CardSetup"];

type Props = { onSaved: (card: SavedCard) => void; saved?: SavedCard | null };

const stripes = new Map<string, Promise<Stripe | null>>();
/** Stripe.js loads only when a card is being added with the Stripe gateway, once per key. */
function stripeFor(publishableKey: string): Promise<Stripe | null> {
  let p = stripes.get(publishableKey);
  if (!p) {
    p = loadStripe(publishableKey);
    stripes.set(publishableKey, p);
  }
  return p;
}

// The village theme's tokens, so Stripe's fields look like ours.
const APPEARANCE: Appearance = {
  theme: "stripe",
  variables: {
    colorPrimary: "#1e4b38",
    colorText: "#1d2420",
    colorDanger: "#b3261e",
    fontFamily: "Figtree, system-ui, sans-serif",
    fontSizeBase: "16px",
    borderRadius: "12px",
  },
};

function message(e: unknown): string {
  if (e instanceof ApiError && e.status === 501) return "Card saving isn't built yet (lane L1 adds the endpoint).";
  if (e instanceof ApiError) return e.message;
  return "We couldn't save your card. Please try again.";
}

function CardRow({ card }: { card: SavedCard }) {
  return (
    <div className="card-mock">
      <CreditCard size={18} aria-hidden="true" />
      <span className="grow">•••• •••• •••• {card.last4}</span>
      <span className="muted">
        {String(card.exp_month).padStart(2, "0")}/{String(card.exp_year).slice(-2)}
      </span>
    </div>
  );
}

async function confirmWithApi(setupId: string): Promise<SavedCard> {
  const confirmed = await call(api.POST("/api/c/payment/setup/{setup_id}/confirm", { params: { path: { setup_id: setupId } } }));
  return confirmed.card;
}

function StripeForm({ setup, onSaved }: { setup: Setup; onSaved: (card: SavedCard) => void }) {
  const stripe = useStripe();
  const elements = useElements();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    if (!stripe || !elements) return;
    setBusy(true);
    setError(null);
    try {
      const { error: stripeError } = await stripe.confirmSetup({
        elements,
        redirect: "if_required",
        confirmParams: { return_url: window.location.href },
      });
      if (stripeError) {
        setError(stripeError.message ?? "Your card wasn't accepted. Please check the details.");
        return;
      }
      onSaved(await confirmWithApi(setup.setup_id));
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="stack" style={{ "--g": "10px" } as CSSProperties}>
      <div className="stripe-box">
        <PaymentElement options={{ layout: "tabs", wallets: { applePay: "never", googlePay: "never" } }} />
      </div>
      {error && (
        <span className="field-error" role="alert">
          {error}
        </span>
      )}
      <Button variant="primary" onClick={save} disabled={!stripe || busy}>
        {busy ? "Saving…" : "Save card"}
      </Button>
    </div>
  );
}

const cardKey = (c?: SavedCard | null) => (c ? `${c.brand}-${c.last4}-${c.exp_month}-${c.exp_year}` : "");

export function CardCapture({ onSaved, saved }: Props) {
  const { data: config } = useConfig();
  const [card, setCard] = useState<SavedCard | null>(saved ?? null);
  // Follow `saved` when it changes (a returning customer's card loads after this mounts).
  const [shown, setShown] = useState(cardKey(saved));
  if (cardKey(saved) !== shown) {
    setShown(cardKey(saved));
    setCard(saved ?? null);
  }
  const [setup, setSetup] = useState<Setup | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const stripeGateway = config?.payments.gateway === "stripe";

  const done = (c: SavedCard) => {
    setCard(c);
    setSetup(null);
    onSaved(c);
  };

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      const s = await call(api.POST("/api/c/payment/setup"));
      if (s.status === "succeeded") {
        done(await confirmWithApi(s.setup_id)); // the fake: saved straight away
      } else if (!s.client_secret || !(s.publishable_key ?? config?.payments.publishable_key)) {
        setError("Card entry isn't set up on this server yet (the Stripe publishable key is missing).");
      } else {
        setSetup(s);
      }
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  };

  const publishable = setup?.publishable_key ?? config?.payments.publishable_key ?? "";
  return (
    <div className="field">
      <span className="label">Payment card</span>
      {card ? (
        <CardRow card={card} />
      ) : setup?.client_secret && publishable ? (
        <Elements stripe={stripeFor(publishable)} options={{ clientSecret: setup.client_secret, appearance: APPEARANCE }}>
          <StripeForm setup={setup} onSaved={done} />
        </Elements>
      ) : (
        <div className="stack" style={{ "--g": "8px" } as CSSProperties}>
          <div className="card-mock">
            <CreditCard size={18} aria-hidden="true" />
            <span className="grow muted">Add your card</span>
            <Button variant="link" onClick={start} disabled={busy}>
              {busy ? "Opening…" : stripeGateway ? "Add card" : "Use test card 4242"}
            </Button>
          </div>
          {error && (
            <span className="field-error" role="alert">
              {error}
            </span>
          )}
        </div>
      )}
      <span className="hint row" style={{ "--g": "6px" } as CSSProperties}>
        <Lock size={13} aria-hidden="true" /> Held securely by Stripe. Charged only after each visit is done.
      </span>
    </div>
  );
}
