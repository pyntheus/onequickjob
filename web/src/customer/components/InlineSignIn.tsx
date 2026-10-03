import { useQueryClient } from "@tanstack/react-query";
import { useState, type CSSProperties, type FormEvent } from "react";
import { api, call } from "../../api/client";
import { queryKeys, useConfig, type Me } from "../../api/queries";
import { Button } from "../../shared/Button";
import { TextField } from "../../shared/Field";
import { errorText } from "../api";

type Props = {
  phone: string;
  onPhone?: (v: string) => void;
  name?: string;
  onSignedIn: (me: Me) => void;
  phoneLabel?: string;
  phoneHint?: string;
  sendLabel?: string;
};

/** The contact and invite screens' sign-in: the mobile number, then the 6-digit code. */
export function InlineSignIn({
  phone,
  onPhone,
  name,
  onSignedIn,
  phoneLabel = "Mobile number",
  phoneHint,
  sendLabel = "Text me a code",
}: Props) {
  const qc = useQueryClient();
  const { data: config } = useConfig();
  const [local, setLocal] = useState(phone);
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const number = onPhone ? phone : local;

  const send = async (e?: FormEvent) => {
    e?.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const sent = await call(api.POST("/api/auth/code", { body: { identifier: number.trim() } }));
      setSentTo(sent.sent_to);
      setCode("");
    } catch (err) {
      setError(errorText(err, "We couldn't send a code. Please try again."));
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
        api.POST("/api/auth/verify", {
          body: { identifier: number.trim(), code: code.trim(), name: name?.trim() || null },
        }),
      );
      qc.setQueryData(queryKeys.me, me);
      await qc.invalidateQueries({ queryKey: ["c"] });
      onSignedIn(me);
    } catch (err) {
      setError(errorText(err, "That didn't work. Please try again."));
    } finally {
      setBusy(false);
    }
  };

  if (sentTo === null) {
    return (
      <form className="stack" style={{ "--g": "12px" } as CSSProperties} onSubmit={send}>
        <TextField
          label={phoneLabel}
          hint={phoneHint}
          value={number}
          onChange={(e) => (onPhone ? onPhone(e.target.value) : setLocal(e.target.value))}
          inputMode="tel"
          autoComplete="tel"
          required
          error={error}
        />
        <Button type="submit" variant="primary" disabled={busy || number.trim().length < 10}>
          {sendLabel}
        </Button>
      </form>
    );
  }
  return (
    <form className="stack" style={{ "--g": "12px" } as CSSProperties} onSubmit={verify}>
      <p className="small">
        We've sent a 6-digit code to <b>{sentTo}</b>. It lasts 10 minutes. No password: we send a code whenever you
        sign in.
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
      <div className="row wrap" style={{ "--g": "16px" } as CSSProperties}>
        <Button type="submit" variant="primary" disabled={busy || code.length !== 6}>
          Confirm my number
        </Button>
        <Button variant="link" onClick={() => send()} disabled={busy}>
          Send a new code
        </Button>
        <Button
          variant="link"
          onClick={() => {
            setSentTo(null);
            setError(null);
          }}
        >
          Change the number
        </Button>
      </div>
    </form>
  );
}
