/** Your own customers: the fee comparison, the list, and the invite form, with the invite-only
 * rule (numbers that belong to platform customers stay on the standard fee). Owned by L2. Lifted
 * from the prototype's OwnCustomersScreen. What the provider keeps comes from the API. */
import { useMutation } from "@tanstack/react-query";
import { Info } from "lucide-react";
import { useState, type FormEvent } from "react";
import { ApiError, api, call } from "../../api/client";
import { useCategories, useConfig } from "../../api/queries";
import { Loading } from "../../app/Status";
import { Avatar } from "../../shared/Avatar";
import { Button } from "../../shared/Button";
import { CatIcon } from "../../shared/CatIcon";
import { Chip } from "../../shared/Chip";
import { TextField } from "../../shared/Field";
import { fmt, initialsOf } from "../../shared/format";
import { Stepper } from "../../shared/Stepper";
import { useToast } from "../../shared/toast-context";
import { useInvalidateProvider, useOwnCustomers, useOwnPreview } from "../api";
import { BackLink, ErrorNote, Note } from "../components";
import { css } from "../util";

const FREQS = [
  ["fortnightly", "Every 2 weeks"],
  ["weekly", "Every week"],
  ["monthly", "Monthly"],
  ["threemonthly", "Every 3 months"],
  ["oneoff", "Just once"],
] as const;
type Freq = (typeof FREQS)[number][0];

function InviteForm({ skills }: { skills: string[] }) {
  const notify = useToast();
  const refresh = useInvalidateProvider();
  const { data: config } = useConfig();
  const { data: cats } = useCategories();
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [cat, setCat] = useState(skills[0] ?? "");
  const [pounds, setPounds] = useState(30);
  const [freq, setFreq] = useState<Freq>("fortnightly");
  const keep = useOwnPreview(pounds * 100);
  const send = useMutation({
    mutationFn: () =>
      call(
        api.POST("/api/p/own-customers/invites", {
          body: { name: name.trim(), phone: phone.trim(), category_id: cat, price_pence: pounds * 100, frequency: freq },
        }),
      ),
    onSuccess: (out) => {
      notify(`Invite sent to ${out.name.split(" ")[0]} by text`);
      setName("");
      setPhone("");
      void refresh();
    },
  });
  const blocked = send.error instanceof ApiError && send.error.code === "platform_customer";
  const valid = name.trim().length > 0 && phone.replace(/\D/g, "").length >= 10 && !!cat;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (valid) send.mutate();
  };
  const reset = () => send.reset();
  return (
    <form className="card stack" style={css(14)} onSubmit={submit}>
      <h2 className="h3">Invite a customer</h2>
      <TextField label="Their name" value={name} onChange={(e) => { reset(); setName(e.target.value); }} autoComplete="off" />
      <TextField label="Their mobile" value={phone} inputMode="tel" onChange={(e) => { reset(); setPhone(e.target.value); }} />
      {config?.demo_mode && (
        <span className="xs muted">Prototype: try 07700 900123 to see what happens with someone who's already a OneQuickJob customer.</span>
      )}
      <div className="stack" style={css(8)}>
        <span className="label" id="job-label">
          The job
        </span>
        <div className="chips" role="group" aria-labelledby="job-label">
          {skills.map((id) => (
            <Chip key={id} on={cat === id} onClick={() => { reset(); setCat(id); }}>
              <CatIcon id={id} size={16} /> {cats?.categories.find((c) => c.id === id)?.name ?? id}
            </Chip>
          ))}
        </div>
      </div>
      <div className="stack" style={css(8)}>
        <span className="label">Your price</span>
        <div className="row wrap between" style={css(12)}>
          <Stepper value={pounds} onChange={(v) => { reset(); setPounds(v); }} min={5} max={500} step={1} format={(v) => fmt(v * 100)} label="Your price" />
          <div className="stack" style={{ ...css(0), textAlign: "right" }} aria-live="polite">
            <span className="xs muted">You'd keep</span>
            <b>{keep.data && keep.data.price_pence === pounds * 100 ? fmt(keep.data.provider_pence) : "…"}</b>
          </div>
        </div>
        <span className="hint">For your own customers, the price is entirely yours. There's no guide price.</span>
      </div>
      <div className="stack" style={css(8)}>
        <span className="label" id="freq-label">
          How often
        </span>
        <div className="chips" role="group" aria-labelledby="freq-label">
          {FREQS.map(([v, l]) => (
            <Chip key={v} on={freq === v} onClick={() => setFreq(v)}>
              {l}
            </Chip>
          ))}
        </div>
      </div>
      {blocked ? (
        <Note tone="warn" icon={<Info size={18} aria-hidden="true" />}>
          {send.error instanceof ApiError ? send.error.message : ""}
        </Note>
      ) : (
        <ErrorNote error={send.error} />
      )}
      <Button type="submit" variant="primary" size="lg" block disabled={!valid || send.isPending}>
        Send invite
      </Button>
      <p className="xs muted">They get a text from you, sent through OneQuickJob, and agree to the same customer terms as everyone else.</p>
    </form>
  );
}

export default function OwnCustomers() {
  const { data, isLoading, error } = useOwnCustomers();
  const { data: config } = useConfig();
  return (
    <>
      <BackLink to="/p/me">Me</BackLink>
      <div className="stack" style={css(6)}>
        <h1 className="h1">Your own customers</h1>
        <p className="muted">
          Bring the customers you already have. We handle reminders, card payments, receipts and your tax records, for a much
          smaller fee.
        </p>
      </div>
      {isLoading && <Loading />}
      {error && <ErrorNote error={error} />}
      {data && (
        <>
          <div className="card stack" style={css(12)}>
            <span className="small muted">On a {fmt(data.comparison.example_price_pence)} job, you keep</span>
            <div className="grid2">
              <div className="cmp win" style={{ flexDirection: "column", alignItems: "flex-start", gap: 2 }}>
                <span className="xs muted">Your own customer</span>
                <span className="big-num" style={{ fontSize: 28 }}>
                  {fmt(data.comparison.own_customer.provider_pence)}
                </span>
                <span className="xs muted">
                  {data.comparison.own_customer.rate_percent}% fee
                  {config ? `, ${fmt(config.fees.own_customer_min_pence)} minimum` : ""}
                </span>
              </div>
              <div className="cmp" style={{ flexDirection: "column", alignItems: "flex-start", gap: 2 }}>
                <span className="xs muted">A customer we found</span>
                <span className="big-num" style={{ fontSize: 28 }}>
                  {fmt(data.comparison.standard.provider_pence)}
                </span>
                <span className="xs muted">{data.comparison.standard.rate_percent}% fee</span>
              </div>
            </div>
          </div>
          {data.customers.length > 0 && (
            <div className="card flat" style={{ padding: "4px 16px" }}>
              {data.customers.map((c) => (
                <div key={c.id} className="list-row">
                  <Avatar initials={initialsOf(c.name)} size={40} />
                  <div className="grow stack" style={css(0)}>
                    <b>{c.name}</b>
                    <span className="xs muted">
                      {c.category_name}, {c.frequency_label.toLowerCase()}, {fmt(c.price_pence)}
                    </span>
                  </div>
                  {c.status === "active" ? <span className="badge ok">Active</span> : <span className="badge warn">Invite sent</span>}
                </div>
              ))}
            </div>
          )}
          <InviteForm skills={data.skills} />
          <div className="soft small stack" style={css(4)}>
            <b>Who counts as your own customer</b>
            <span>
              Someone you invite who hasn't booked through OneQuickJob before. Customers who found you through OneQuickJob stay
              on the standard fee, even if they later book you directly.
            </span>
          </div>
        </>
      )}
    </>
  );
}
