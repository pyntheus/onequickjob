import { useQueryClient } from "@tanstack/react-query";
import { Lock } from "lucide-react";
import { useState, type CSSProperties, type FormEvent } from "react";
import { ApiError, api, call } from "../api/client";
import { queryKeys, useConfig, type Me } from "../api/queries";
import { Button } from "./Button";
import { TextField } from "./Field";

type Props = {
  /** Called after a successful sign-in, with the signed-in user. */
  onSignedIn?: (me: Me) => void;
  title?: string;
  intro?: string;
  /** Used if the code creates a new account. */
  name?: string;
};

/** Sign in with a mobile number or email and a 6-digit code (no passwords). */
export function SignInForm({
  onSignedIn,
  title = "Sign in",
  intro = "No password: we send a code whenever you sign in.",
  name,
}: Props) {
  const qc = useQueryClient();
  const { data: config } = useConfig();
  const [identifier, setIdentifier] = useState("");
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sendCode = async (e?: FormEvent) => {
    e?.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const sent = await call(api.POST("/api/auth/code", { body: { identifier: identifier.trim() } }));
      setSentTo(sent.sent_to);
      setCode("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "We couldn't send a code. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  const verify = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const me = await call(
        api.POST("/api/auth/verify", { body: { identifier: identifier.trim(), code: code.trim(), name: name ?? null } }),
      );
      qc.setQueryData(queryKeys.me, me);
      await qc.invalidateQueries();
      onSignedIn?.(me);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That didn't work. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card stack" style={{ "--g": "16px" } as CSSProperties}>
      <div className="stack" style={{ "--g": "6px" } as CSSProperties}>
        <h1 className="h2">{title}</h1>
        <p className="muted">{intro}</p>
      </div>
      {sentTo === null ? (
        <form className="stack" style={{ "--g": "14px" } as CSSProperties} onSubmit={sendCode}>
          <TextField
            label="Mobile number or email"
            value={identifier}
            onChange={(e) => setIdentifier(e.target.value)}
            autoComplete="username"
            inputMode="email"
            required
            error={error}
          />
          <Button type="submit" variant="cta" size="lg" block disabled={busy || identifier.trim().length < 3}>
            Send me a code
          </Button>
        </form>
      ) : (
        <form className="stack" style={{ "--g": "14px" } as CSSProperties} onSubmit={verify}>
          <p className="small">
            We've sent a 6-digit code to <b>{sentTo}</b>. It lasts 10 minutes.
          </p>
          {config?.demo_mode && <p className="small muted">Prototype: your code is in the Outbox.</p>}
          <TextField
            label="Your code"
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
            autoComplete="one-time-code"
            inputMode="numeric"
            pattern="[0-9]{6}"
            required
            error={error}
          />
          <Button type="submit" variant="cta" size="lg" block disabled={busy || code.length !== 6}>
            Sign in
          </Button>
          <div className="row wrap" style={{ "--g": "16px" } as CSSProperties}>
            <Button variant="link" onClick={() => sendCode()} disabled={busy}>
              Send a new code
            </Button>
            <Button variant="link" onClick={() => { setSentTo(null); setError(null); }}>
              Use a different number
            </Button>
          </div>
        </form>
      )}
      <p className="xs muted row" style={{ "--g": "6px" } as CSSProperties}>
        <Lock size={13} aria-hidden="true" /> We don't pass your details on.
      </p>
    </div>
  );
}
