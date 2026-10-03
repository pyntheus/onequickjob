import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2 } from "lucide-react";
import { useEffect, useState, type CSSProperties } from "react";
import { useNavigate } from "react-router";
import { api, call } from "../../api/client";
import { useMe } from "../../api/queries";
import { CardCapture, type SavedCard } from "../../payments/CardCapture";
import { CatIcon } from "../../shared/CatIcon";
import { CheckRow } from "../../shared/CheckRow";
import { TextField } from "../../shared/Field";
import { FlowTop } from "../../shared/FlowTop";
import { fmt } from "../../shared/format";
import { ck, errorText, useProfile } from "../api";
import { FlowGuard } from "../components/FlowGuard";
import { InlineSignIn } from "../components/InlineSignIn";
import { uploadPhotos } from "../upload";
import { useQuoteStep } from "../useQuoteStep";

const g = (px: number) => ({ "--g": `${px}px` }) as CSSProperties;

/** Contact details, sign-in by code, the card (through the PaymentGateway) and the agency terms. */
export default function Contact() {
  const step = useQuoteStep("contact");
  const { flow, update, cat, steps, back, go, photos, reset } = step;
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { data: me } = useMe();
  const signedIn = !!me;
  const { data: profile, isFetched: profileLoaded } = useProfile(signedIn);
  const quote = useQuery({
    queryKey: ["c", "quote-by-id", flow.quoteId],
    queryFn: () => call(api.GET("/api/quotes/{quote_id}", { params: { path: { quote_id: flow.quoteId ?? "" } } })),
    enabled: !!flow.quoteId,
    staleTime: Infinity,
  });
  const [card, setCard] = useState<SavedCard | null>(null);
  const [agree, setAgree] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const savedCard = card ?? profile?.card ?? null;
  const c = flow.contact;
  const setContact = (k: keyof typeof c, v: string) => update((f) => ({ contact: { ...f.contact, [k]: v } }));

  useEffect(() => {
    if (me && !c.name && me.name) setContact("name", me.name);
    if (me?.email && !c.email) setContact("email", me.email);
    // Prefill once when the user is known.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me?.user_id]);

  const valid = signedIn && !!savedCard && agree && c.name.trim().length > 0 && !!flow.quoteId && !!flow.address;

  const send = async () => {
    if (!cat || !flow.quoteId || !flow.address) return;
    setBusy(true);
    setError(null);
    try {
      const files = cat.intake.filter((f) => f.type === "photos").flatMap((f) => photos[`${cat.id ?? ""}.${f.key}`] ?? []);
      const ids = files.length ? await uploadPhotos(files, "request_photo") : [];
      const detail = await call(
        api.POST("/api/c/requests", {
          body: {
            quote_id: flow.quoteId,
            address: flow.address,
            notes: flow.notes,
            when: flow.when,
            contact: { name: c.name.trim(), email: c.email.trim() || null },
            agree_terms: true,
            photos: ids,
          },
        }),
      );
      qc.setQueryData(ck.request(detail.ref), detail);
      await qc.invalidateQueries({ queryKey: ["c"] });
      reset();
      navigate(`/requests/${detail.ref}`);
    } catch (e) {
      setError(errorText(e, "We couldn't send your request. Please try again."));
    } finally {
      setBusy(false);
    }
  };

  const q = quote.data;
  return (
    <FlowGuard loading={step.loading} unknown={step.unknown} needsAddress={!flow.address}>
      <div className="c-flow">
        <FlowTop steps={steps} current="contact" onBack={back} />
        {!flow.quoteId ? (
          <div className="card stack" style={g(12)}>
            <h1 className="h2">Let's get your price first</h1>
            <button type="button" className="btn btn-primary" onClick={() => go("price")}>
              See my price
            </button>
          </div>
        ) : (
          <>
            {q && cat && (
              <div className="soft row between small">
                <span className="row" style={g(8)}>
                  <CatIcon icon={cat.icon} id={cat.id} size={18} /> {cat.name}
                </span>
                <b>
                  {fmt(q.result.price_pence)} {q.result.unit}
                </b>
              </div>
            )}
            <div className="stack" style={g(8)}>
              <h1 className="h1">Where should we send updates?</h1>
              <p className="muted">
                We'll text you when someone local picks up your job. No password: we send a code whenever you sign in.
              </p>
            </div>
            <TextField label="Your name" value={c.name} onChange={(e) => setContact("name", e.target.value)} autoComplete="name" maxLength={80} />
            {signedIn ? (
              <div className="field">
                <span className="label">Mobile number</span>
                <span className="row small" style={g(8)}>
                  <CheckCircle2 size={18} aria-hidden="true" style={{ color: "var(--ok)" }} />
                  {me?.phone ?? me?.email} <span className="muted">(confirmed)</span>
                </span>
              </div>
            ) : (
              <InlineSignIn
                phone={c.phone}
                onPhone={(v) => setContact("phone", v)}
                name={c.name}
                onSignedIn={() => undefined}
                phoneHint="We text you a code to confirm it."
              />
            )}
            <TextField
              label="Email"
              optional
              hint="For receipts"
              value={c.email}
              onChange={(e) => setContact("email", e.target.value)}
              inputMode="email"
              autoComplete="email"
              maxLength={254}
            />
            {signedIn && profileLoaded ? (
              // CardCapture reads `saved` when it mounts, so mount it once the profile is known.
              <CardCapture key={savedCard?.last4 ?? "none"} saved={savedCard} onSaved={(saved) => setCard(saved)} />
            ) : signedIn ? null : (
              <div className="field">
                <span className="label">Payment card</span>
                <p className="small muted">Confirm your number first, then add your card. It's charged only after each visit is done.</p>
              </div>
            )}
            <div className="card flat stack" style={g(12)}>
              <CheckRow on={agree} onChange={setAgree}>
                I agree to the customer terms. My agreement for the work is with the provider who takes the job, and
                OneQuickJob acts as their booking and payment agent.
              </CheckRow>
            </div>
            <p className="small muted">
              Your number isn't shared with providers. You message each other through OneQuickJob, so there's a record if
              anything needs sorting out.
            </p>
            {error && (
              <p className="field-error" role="alert">
                {error}
              </p>
            )}
            <button type="button" className="btn btn-cta btn-lg btn-block" disabled={!valid || busy} onClick={send}>
              {busy ? "Sending…" : "Send my request"}
            </button>
            {!agree && <p className="xs muted center">Tick the box above to send your request.</p>}
          </>
        )}
      </div>
    </FlowGuard>
  );
}
