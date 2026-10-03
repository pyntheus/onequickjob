/** Sign-up: the checklist with the benefits notice and "Set an earnings limit", your details and
 * home, ID, tax details (stored sealed, shown masked), insurance, jobs and area, and the
 * payment-account link from the PaymentGateway. Owned by L2. Lifted from the prototype's
 * OnboardingScreen. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Phone, PiggyBank, TriangleAlert } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { api, call } from "../../api/client";
import { queryKeys, useCategories, useConfig, useMe } from "../../api/queries";
import { Loading } from "../../app/Status";
import { Button } from "../../shared/Button";
import { CatIcon } from "../../shared/CatIcon";
import { Chip } from "../../shared/Chip";
import { TextField } from "../../shared/Field";
import { useToast } from "../../shared/toast-context";
import { pKeys, useDebounced, useDocuments, usePatchProfile, useProfile, useSignup, type DocumentOut, type SignupChecklist } from "../api";
import { ErrorNote, Note } from "../components";
import { DocUpload } from "../Documents";
import { appPath, css, dateText } from "../util";

function Details({ onDone }: { onDone: () => void }) {
  const { data: me } = useMe();
  const [name, setName] = useState(me?.name ?? "");
  const [postcode, setPostcode] = useState("");
  const [addressId, setAddressId] = useState<string | null>(null);
  const q = useDebounced(postcode.trim(), 300);
  const found = useQuery({
    queryKey: ["address", "search", q],
    queryFn: () => call(api.GET("/api/address/search", { params: { query: { q } } })),
    enabled: q.length >= 5,
  });
  const start = useMutation({
    mutationFn: () =>
      call(api.POST("/api/p/signup/start", { body: { name: name.trim(), postcode: postcode.trim(), address_id: addressId } })),
    onSuccess: onDone,
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    start.mutate();
  };
  return (
    <form className="stack" style={css(12)} onSubmit={submit}>
      <TextField label="Your full name" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" required />
      <TextField
        label="Your home postcode"
        hint="We use it to find jobs near you. Customers only ever see your village."
        value={postcode}
        onChange={(e) => {
          setPostcode(e.target.value.toUpperCase());
          setAddressId(null);
        }}
        autoComplete="postal-code"
        required
      />
      {found.data && found.data.length > 0 && (
        <div className="stack" style={css(6)} role="radiogroup" aria-label="Your address">
          <span className="label">Choose your address</span>
          {found.data.map((a) => (
            <button
              key={a.id}
              type="button"
              role="radio"
              aria-checked={addressId === a.id}
              className={"choice" + (addressId === a.id ? " on" : "")}
              onClick={() => setAddressId(a.id)}
            >
              <span className="tick" aria-hidden="true">
                {addressId === a.id && <Check size={14} strokeWidth={3} />}
              </span>
              <span>{a.label}</span>
            </button>
          ))}
        </div>
      )}
      {found.data && found.data.length === 0 && q.length >= 5 && <p className="small muted">We couldn't find that postcode.</p>}
      <ErrorNote error={start.error} />
      <Button type="submit" variant="primary" size="lg" block disabled={!name.trim() || !addressId || start.isPending}>
        Save my details
      </Button>
    </form>
  );
}

function TaxForm({ onDone }: { onDone: () => void }) {
  const [ni, setNi] = useState("");
  const [dob, setDob] = useState("");
  const save = useMutation({
    mutationFn: () => call(api.PUT("/api/p/signup/tax", { body: { ni_number: ni.trim(), date_of_birth: dob } })),
    onSuccess: onDone,
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };
  return (
    <form className="stack" style={css(12)} onSubmit={submit}>
      <p className="small muted">
        The law requires us to collect these because we report earnings to HMRC. We don't use them for anything else, and we
        only ever show them to you partly hidden.
      </p>
      <TextField label="National Insurance number" value={ni} onChange={(e) => setNi(e.target.value.toUpperCase())} placeholder="QQ 12 34 56 C" autoComplete="off" />
      <TextField label="Date of birth" type="date" value={dob} onChange={(e) => setDob(e.target.value)} autoComplete="bday" />
      <ErrorNote error={save.error} />
      <Button type="submit" variant="primary" size="lg" block disabled={!ni.trim() || !dob || save.isPending}>
        Save tax details
      </Button>
    </form>
  );
}

function DocStep({ type }: { type: "identity" | "insurance" }) {
  const notify = useToast();
  const { data: docs } = useDocuments();
  const doc = docs?.find((d) => d.type === type);
  if (!docs) return <Loading />;
  if (!doc) return <Note>Choose the jobs you do first, then add this.</Note>;
  const done = (d: DocumentOut) => {
    const until = d.renewal?.expires_on ?? d.expires_on;
    notify(`Thanks, we've got your ${d.label.toLowerCase()}${until ? `, valid to ${dateText(until, { day: "numeric", month: "long", year: "numeric" })}` : ""}. We'll check it soon.`);
  };
  return <DocUpload doc={doc} onDone={done} />;
}

function Work({ onDone }: { onDone: () => void }) {
  const { data: p } = useProfile();
  const { data: cats } = useCategories();
  const patch = usePatchProfile();
  const [skills, setSkills] = useState<string[] | null>(null);
  const chosen = skills ?? p?.skills ?? [];
  if (!p || !cats) return <Loading />;
  const toggle = (id: string) => setSkills(chosen.includes(id) ? chosen.filter((s) => s !== id) : [...chosen, id]);
  return (
    <div className="stack" style={css(12)}>
      {cats.groups.map((g) => (
        <div key={g.id} className="stack" style={css(8)}>
          <span className="small muted">{g.name}</span>
          <div className="chips">
            {cats.categories
              .filter((c) => c.group === g.id && c.status === "live")
              .map((c) => (
                <Chip key={c.id} on={chosen.includes(c.id ?? "")} onClick={() => toggle(c.id ?? "")}>
                  <CatIcon id={c.id ?? ""} size={16} /> {c.name}
                </Chip>
              ))}
          </div>
        </div>
      ))}
      <p className="small muted">You can change these, your travel distance and your days any time on the Me tab.</p>
      <ErrorNote error={patch.error} />
      <Button
        variant="primary"
        size="lg"
        block
        disabled={chosen.length === 0 || patch.isPending}
        onClick={() => patch.mutate({ skills: chosen }, { onSuccess: onDone })}
      >
        Save the jobs I do
      </Button>
    </div>
  );
}

function Payouts() {
  const navigate = useNavigate();
  const { data: config } = useConfig();
  const link = useMutation({
    mutationFn: () => call(api.POST("/api/p/signup/payment-account")),
    onSuccess: ({ url }) => {
      const path = config ? appPath(url, config.public_base_url) : null;
      if (path) navigate(path);
      else window.location.assign(url);
    },
  });
  return (
    <div className="stack" style={css(10)}>
      <p className="small muted">
        You'll be paid every Friday for the week's jobs. Our payment provider checks your bank details; we never see them.
      </p>
      <ErrorNote error={link.error} />
      <Button variant="primary" size="lg" block disabled={link.isPending} onClick={() => link.mutate()}>
        Connect your bank account
      </Button>
    </div>
  );
}

function StepBody({ step, list, done }: { step: SignupChecklist["steps"][number]; list: SignupChecklist; done: () => void }) {
  switch (step.key) {
    case "details":
      return <Details onDone={done} />;
    case "identity":
      return <DocStep type="identity" />;
    case "tax":
      return <TaxForm onDone={done} />;
    case "insurance":
      return <DocStep type="insurance" />;
    case "work":
      return <Work onDone={done} />;
    case "payouts":
      return list.provider_id ? <Payouts /> : null;
  }
}

export default function Signup() {
  const qc = useQueryClient();
  const notify = useToast();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const { data: me } = useMe();
  const { data: list, isLoading, error } = useSignup(!!me);
  const [guide, setGuide] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const callMe = useMutation({
    mutationFn: (step: string) => call(api.POST("/api/p/signup/callback", { body: { step } })),
    onSuccess: (ack) => notify(ack.message),
  });
  const onboarding = params.get("onboarding");
  useEffect(() => {
    if (onboarding === "done" || onboarding === "again") {
      // Back from the payment provider: the checklist asks it how the account stands.
      void qc.invalidateQueries({ queryKey: pKeys.signup });
      if (onboarding === "done") notify("Thanks. We'll check your bank details with our payment provider.");
      navigate("/p/signup", { replace: true });
    }
  }, [onboarding, notify, navigate, qc]);
  const refresh = () => {
    setOpen(null);
    void qc.invalidateQueries({ queryKey: pKeys.all });
    void qc.invalidateQueries({ queryKey: queryKeys.me });
  };
  if (isLoading || !list) return error ? <ErrorNote error={error} /> : <Loading />;
  const now = list.steps.find((s) => s.state === "now");
  const current = open ?? now?.key ?? null;
  const all = list.done_count === list.steps.length;
  return (
    <>
      <div className="stack" style={css(6)}>
        <h1 className="h1">{all ? "You're all set up" : "Let's get you set up"}</h1>
        <p className="muted">
          {all
            ? list.status === "active"
              ? "Everything's done. New jobs near you will come through by text."
              : "Thanks. We're checking your documents and we'll text you as soon as you can take jobs."
            : "About 10 minutes. You can stop and come back any time."}
        </p>
      </div>
      <div className="stack" style={css(6)}>
        <span className="small muted">
          {list.done_count} of {list.steps.length} done
        </span>
        <div className="progress" aria-hidden="true">
          <i style={{ width: `${(list.done_count / list.steps.length) * 100}%` }} />
        </div>
      </div>
      <div className="card flat stack note-warn-card" style={css(8)}>
        <div className="row" style={css(10)}>
          <TriangleAlert size={20} aria-hidden="true" />
          <b>Before you start</b>
        </div>
        <p className="small">
          If you get Pension Credit, Universal Credit or other means-tested support, earnings from jobs can affect it. You can
          set a limit, and we'll stop offering you jobs once you reach it.
        </p>
        <div className="row wrap" style={css(16)}>
          {list.provider_id ? (
            <Button to="/p/limit" variant="primary" size="sm">
              <PiggyBank size={15} aria-hidden="true" /> {list.limit_on ? "Change your earnings limit" : "Set an earnings limit"}
            </Button>
          ) : (
            <span className="xs muted">You can set a limit as soon as your details are saved.</span>
          )}
          <Button variant="link" aria-expanded={guide} onClick={() => setGuide((v) => !v)}>
            Read the guide
          </Button>
        </div>
        {guide && (
          <p className="small">
            Pension Credit is worked out weekly and Universal Credit monthly, so choose a weekly or monthly limit to match.
            The earnings limit page explains more. It isn't benefits advice: Citizens Advice or the Turn2us benefits
            calculator can help.
          </p>
        )}
      </div>
      <div className="stack" style={css(10)}>
        {list.steps.map((s, i) => {
          const expanded = current === s.key && (s.state !== "done" || open === s.key);
          return (
            <div key={s.key} className={expanded ? "card stack" : "card flat stack"} style={{ ...css(12), padding: 16, opacity: s.state === "todo" ? 0.6 : 1 }}>
              <div className="row" style={css(12)}>
                <span className={"box step-num" + (s.state === "done" ? " on" : "")} aria-hidden="true">
                  {s.state === "done" ? <Check size={15} strokeWidth={3} /> : <span className="xs" style={{ fontWeight: 700 }}>{i + 1}</span>}
                </span>
                <div className="grow stack" style={css(0)}>
                  <b>
                    {s.title}
                    <span className="sr-only">{s.state === "done" ? " (done)" : s.state === "now" ? " (next)" : ""}</span>
                  </b>
                  <span className="xs muted">{s.detail}</span>
                </div>
                {s.state === "done" && s.key !== "details" && s.key !== "payouts" && current !== s.key && (
                  <Button variant="link" onClick={() => setOpen(s.key)}>
                    Change
                  </Button>
                )}
              </div>
              {expanded && <StepBody step={s} list={list} done={refresh} />}
            </div>
          );
        })}
      </div>
      {list.status === "active" && (
        <Button to="/p" variant="cta" size="lg" block>
          See jobs near you
        </Button>
      )}
      <div className="card flat row" style={css(12)}>
        <Phone size={20} aria-hidden="true" style={{ flex: "none" }} />
        <div className="grow small">Stuck on anything? Our local team will ring you back.</div>
        <Button variant="ghost" size="sm" disabled={callMe.isPending || callMe.isSuccess} onClick={() => callMe.mutate(now?.title ?? "")}>
          {callMe.isSuccess ? "Asked" : "Call me"}
        </Button>
      </div>
      {callMe.isError && <Note tone="danger">We couldn't ask for a call just now. Please try again.</Note>}
    </>
  );
}
