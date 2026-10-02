/**
 * Saving a customer's card through the PaymentGateway. Owned by L3 after F: the fake
 * gateway works today; L3 adds Stripe Elements for PAYMENT_GATEWAY=stripe here, so L1's
 * contact screen and invite screen never change.
 */
import { CreditCard, Lock } from "lucide-react";
import { useState, type CSSProperties } from "react";
import { ApiError, api, call, type Schemas } from "../api/client";
import { useConfig } from "../api/queries";
import { Button } from "../shared/Button";

export type SavedCard = Schemas["SavedCardInfo"];

type Props = { onSaved: (card: SavedCard) => void; saved?: SavedCard | null };

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

export function CardCapture({ onSaved, saved }: Props) {
  const { data: config } = useConfig();
  const [card, setCard] = useState<SavedCard | null>(saved ?? null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const addFakeCard = async () => {
    setBusy(true);
    setError(null);
    try {
      const setup = await call(api.POST("/api/c/payment/setup"));
      const confirmed = await call(
        api.POST("/api/c/payment/setup/{setup_id}/confirm", { params: { path: { setup_id: setup.setup_id } } }),
      );
      setCard(confirmed.card);
      onSaved(confirmed.card);
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 501
          ? "Card saving isn't built yet (lane L1 adds the endpoint)."
          : e instanceof ApiError
            ? e.message
            : "We couldn't save your card. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="field">
      <span className="label">Payment card</span>
      {card ? (
        <CardRow card={card} />
      ) : config?.payments.gateway === "stripe" ? (
        <p className="soft small">Stripe card entry is added here by lane L3 (Stripe Elements).</p>
      ) : (
        <div className="stack" style={{ "--g": "8px" } as CSSProperties}>
          <div className="card-mock">
            <CreditCard size={18} aria-hidden="true" />
            <span className="grow muted">Add your card</span>
            <Button variant="link" onClick={addFakeCard} disabled={busy}>
              {busy ? "Saving…" : "Use test card 4242"}
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
