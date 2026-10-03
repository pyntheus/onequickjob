/** Me: profile, documents (upload, expiry), jobs I do with the missing-document prompt, travel
 * radius, days, alert settings, add-to-home-screen help, and links to time off, helpers, the limit,
 * tax and your own customers. Owned by L2. Lifted from the prototype's MeScreen.
 * A helper sees their own name and documents only. */
import { FileText, HeartHandshake, MessageCircle, PiggyBank, Plane, Receipt, Smartphone, Wallet } from "lucide-react";
import { useEffect, useState } from "react";
import { useCategories, useMe } from "../../api/queries";
import { Loading } from "../../app/Status";
import { Avatar } from "../../shared/Avatar";
import { Badge } from "../../shared/Badge";
import { Button } from "../../shared/Button";
import { CatIcon } from "../../shared/CatIcon";
import { Chip } from "../../shared/Chip";
import { fmt } from "../../shared/format";
import { LinkRow } from "../../shared/LinkRow";
import { Stars } from "../../shared/Stars";
import { Stepper } from "../../shared/Stepper";
import { Toggle } from "../../shared/Toggle";
import { useToast } from "../../shared/toast-context";
import { useDebounced, useDocuments, useHelperMode, useLimit, usePatchProfile, useProfile, type ProviderProfile } from "../api";
import { ErrorNote } from "../components";
import { DocRow } from "../Documents";
import { isStandalone, useInstallPrompt } from "../install";
import { css, dateText } from "../util";

const DAYS = [
  ["mon", "Mon"],
  ["tue", "Tue"],
  ["wed", "Wed"],
  ["thu", "Thu"],
  ["fri", "Fri"],
  ["sat", "Sat"],
  ["sun", "Sun"],
] as const;
type Day = (typeof DAYS)[number][0];

function HomeScreenHelp() {
  const [open, setOpen] = useState(false);
  const { canInstall, install } = useInstallPrompt();
  if (isStandalone()) return null;
  return (
    <div className="soft stack" style={css(8)}>
      <b>Put OneQuickJob on your home screen</b>
      <span className="small">
        In your browser's menu, tap “Add to Home Screen”. It then opens like an app, with nothing to download.
      </span>
      {canInstall && (
        <Button variant="primary" onClick={() => void install()}>
          <Smartphone size={17} aria-hidden="true" /> Add it now
        </Button>
      )}
      <Button variant="link" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        {open ? "Hide the steps" : "Show me how"}
      </Button>
      {open && (
        <div className="stack small" style={css(8)}>
          <div>
            <b>iPhone (Safari):</b> tap the Share button (a square with an arrow pointing up) at the bottom of the screen,
            scroll down and tap “Add to Home Screen”, then “Add”.
          </div>
          <div>
            <b>Android (Chrome):</b> tap the three dots at the top right, then “Add to Home screen” or “Install app”, then
            “Install”.
          </div>
        </div>
      )}
    </div>
  );
}

function Settings({ p }: { p: ProviderProfile }) {
  const notify = useToast();
  const patch = usePatchProfile();
  const { data: cats } = useCategories();
  const [radius, setRadius] = useState(p.travel_radius_miles);
  const settledRadius = useDebounced(radius, 600);
  useEffect(() => {
    if (settledRadius !== p.travel_radius_miles) {
      patch.mutate({ travel_radius_miles: settledRadius }, { onSuccess: () => notify("Saved") });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- save only when the settled value changes
  }, [settledRadius]);
  const save = (body: Parameters<typeof patch.mutate>[0]) => patch.mutate(body, { onSuccess: () => notify("Saved") });
  const toggleSkill = (id: string) =>
    save({ skills: p.skills.includes(id) ? p.skills.filter((s) => s !== id) : [...p.skills, id] });
  const toggleDay = (d: Day) =>
    save({ working_days: p.working_days.includes(d) ? p.working_days.filter((x) => x !== d) : [...p.working_days, d] });
  const a = p.alert_settings;
  const missing = p.documents.filter((d) => p.missing_for_skills.includes(d.type));
  return (
    <>
      <div className="stack" style={css(12)}>
        <h2 className="h3">Jobs I do</h2>
        {cats?.groups.map((g) => (
          <div key={g.id} className="stack" style={css(8)}>
            <span className="small muted">{g.name}</span>
            <div className="chips">
              {cats.categories
                .filter((c) => c.group === g.id && c.status === "live")
                .map((c) => (
                  <Chip key={c.id} on={p.skills.includes(c.id ?? "")} onClick={() => toggleSkill(c.id ?? "")} disabled={patch.isPending}>
                    <CatIcon id={c.id ?? ""} size={16} /> {c.name}
                  </Chip>
                ))}
            </div>
          </div>
        ))}
        {missing.length > 0 && (
          <div className="soft small stack" style={css(6)}>
            <span>
              To take all of these, we'll also need: <b>{missing.map((d) => d.label).join(", ")}</b>. You can add them under
              your documents above.
            </span>
          </div>
        )}
      </div>
      <div className="stack" style={css(10)}>
        <h2 className="h3">How far I'll travel</h2>
        <div className="row wrap" style={css(12)}>
          <Stepper
            value={radius}
            onChange={setRadius}
            min={1}
            max={15}
            label="Travel distance"
            format={(v) => `${v} ${v === 1 ? "mile" : "miles"}`}
          />
          <span className="small muted">from {p.district}</span>
        </div>
      </div>
      <div className="stack" style={css(10)}>
        <h2 className="h3">Days I work</h2>
        <div className="chips" role="group" aria-label="Days I work">
          {DAYS.map(([d, label]) => (
            <Chip key={d} on={p.working_days.includes(d)} onClick={() => toggleDay(d)} disabled={patch.isPending}>
              {label}
            </Chip>
          ))}
        </div>
      </div>
      <div className="card flat" style={{ padding: "0 16px" }}>
        <Toggle on={a.sms} onChange={(v) => save({ alert_settings: { ...a, sms: v } })} label="New jobs by text" />
        <hr />
        <Toggle on={a.whatsapp} onChange={(v) => save({ alert_settings: { ...a, whatsapp: v } })} label="New jobs on WhatsApp" />
        <hr />
        <Toggle
          on={a.quiet_hours}
          onChange={(v) => save({ alert_settings: { ...a, quiet_hours: v } })}
          label="Quiet hours"
          hint={`No alerts between ${a.quiet_from} and ${a.quiet_to}`}
        />
      </div>
      <ErrorNote error={patch.error} />
    </>
  );
}

function HelperMe() {
  const { data: me } = useMe();
  const { data: docs, isLoading, error } = useDocuments();
  return (
    <>
      <div className="row" style={css(14)}>
        <Avatar initials={(me?.name ?? "").split(" ").map((w) => w[0]).join("").slice(0, 2)} size={64} />
        <div className="stack" style={css(4)}>
          <h1 className="h2">{me?.name}</h1>
          <span className="small muted">Helper. You do visits you've been sent to.</span>
        </div>
      </div>
      <p className="muted">
        Helpers go through the same ID, DBS and insurance checks before doing a job. Add yours here and we'll check them.
      </p>
      {isLoading && <Loading />}
      {error && <ErrorNote error={error} />}
      <div className="card flat" style={{ padding: "4px 16px" }}>
        {docs?.map((d) => <DocRow key={d.type} doc={d} />)}
      </div>
    </>
  );
}

export default function Me() {
  const { data: me } = useMe();
  const { helper } = useHelperMode();
  const { data: p, isLoading, error } = useProfile(!!me && !helper);
  const { data: limit } = useLimit();
  if (!me) return <Loading />;
  if (helper) return <HelperMe />;
  if (isLoading) return <Loading />;
  if (error || !p) return <ErrorNote error={error ?? new Error()} />;
  const since = p.joined_on ? dateText(p.joined_on, { month: "long", year: "numeric" }) : null;
  return (
    <>
      <div className="row" style={css(14)}>
        <Avatar initials={p.initials} size={64} />
        <div className="stack" style={css(4)}>
          <h1 className="h2">{p.name}</h1>
          {p.rating_avg !== null && (
            <span className="row small muted" style={css(6)}>
              <Stars value={p.rating_avg} size={14} /> {p.rating_avg.toFixed(1)} from {p.rating_count} jobs
            </span>
          )}
          <span className="xs muted">
            {p.area}
            {since ? `, with OneQuickJob since ${since}` : ""}
          </span>
        </div>
      </div>
      {p.status === "signing_up" && (
        <Button to="/p/signup" variant="cta" block>
          Finish setting up
        </Button>
      )}
      <div className="card flat" style={{ padding: "0 16px" }}>
        <LinkRow
          icon={Plane}
          title="Time off and helpers"
          sub={p.helpers.length ? `Cover for your regulars, and ${p.helpers.map((h) => h.name.split(" ")[0]).join(", ")} as your helper` : "Cover for your regulars, and a helper"}
          to="/p/time-off"
        />
        <LinkRow
          icon={PiggyBank}
          title="Earnings limit"
          sub={limit?.on ? `${fmt(limit.amount_pence)} a ${limit.period}` : "Off"}
          to="/p/limit"
        />
        <LinkRow icon={Receipt} title="Tax and records" sub="Your tax pack builds itself as you work" to="/p/tax" />
        <LinkRow icon={HeartHandshake} title="Your own customers" sub="Bring them on for a 5% fee instead of 15%" to="/p/own-customers" />
        <LinkRow icon={MessageCircle} title="Messages" sub="With your customers" to="/p/messages" />
      </div>
      <div className="card flat" style={{ padding: "4px 16px" }}>
        {p.documents.map((d) => (
          <DocRow key={d.type} doc={d} />
        ))}
        <div className="doc-row">
          <span className="cat-ico sm" aria-hidden="true">
            <FileText size={17} />
          </span>
          <div className="grow stack" style={css(0)}>
            <b>Tax details for HMRC</b>
            <span className="xs muted">National Insurance number and date of birth</span>
          </div>
          {p.tax_complete ? <Badge tone="ok">Done</Badge> : <Button to="/p/signup" variant="link">Add them</Button>}
        </div>
        <div className="doc-row">
          <span className="cat-ico sm" aria-hidden="true">
            <Wallet size={17} />
          </span>
          <div className="grow stack" style={css(0)}>
            <b>Bank account</b>
            <span className="xs muted">Paid out every Friday</span>
          </div>
          {p.payment_account_status === "enabled" ? (
            <Badge tone="ok">Done</Badge>
          ) : (
            <Button to="/p/signup" variant="link">
              Connect it
            </Button>
          )}
        </div>
      </div>
      <Settings p={p} />
      <HomeScreenHelp />
    </>
  );
}
