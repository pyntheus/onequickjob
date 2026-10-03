import { useQueryClient } from "@tanstack/react-query";
import { ChevronRight, MessageCircle } from "lucide-react";
import { useState, type CSSProperties } from "react";
import { Link, useSearchParams } from "react-router";
import { api, call } from "../../api/client";
import { useCategories, useMe } from "../../api/queries";
import { Button } from "../../shared/Button";
import { CatIcon } from "../../shared/CatIcon";
import { firstName, fmt } from "../../shared/format";
import { SignInForm } from "../../shared/SignInForm";
import { Tabs } from "../../shared/Tabs";
import { useToast } from "../../shared/toast-context";
import { Loading } from "../../app/Status";
import { errorText, useBookings, usePlans, useProfile, useRequests, useThreads, useVisits, type CustomerVisit } from "../api";
import { MessagesTab } from "../account/MessagesTab";
import { PlansTab } from "../account/PlansTab";
import { VisitsTab } from "../account/VisitsTab";
import { dateText } from "../text";

const g = (px: number) => ({ "--g": `${px}px` }) as CSSProperties;
type Tab = "visits" | "plan" | "messages";
const TABS: { id: Tab; label: string }[] = [
  { id: "visits", label: "Visits" },
  { id: "plan", label: "Plan" },
  { id: "messages", label: "Messages" },
];
const WINDOW: Record<string, string> = { morning: "morning", afternoon: "afternoon", either: "time confirmed the day before" };

function ChangeDate({ visit, onDone }: { visit: CustomerVisit; onDone: () => void }) {
  const notify = useToast();
  const [dates, setDates] = useState(["", ""]);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const chosen = dates.filter(Boolean);
  const send = async () => {
    setBusy(true);
    try {
      await call(
        api.POST("/api/c/visits/{visit_id}/change-date", {
          params: { path: { visit_id: visit.id } },
          body: { preferred: chosen, note },
        }),
      );
      notify(`We've asked ${visit.provider_first_name}. They'll reply in your messages.`);
      onDone();
    } catch (e) {
      notify(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="soft stack" style={g(10)}>
      <span className="label">Pick a new date and we'll check with {visit.provider_first_name}</span>
      <div className="row wrap" style={g(10)}>
        {dates.map((d, i) => (
          <label key={i} className="field">
            <span className="small">{i === 0 ? "Best date" : "Another that suits"}</span>
            <input
              className="input"
              type="date"
              value={d}
              onChange={(e) => setDates((ds) => ds.map((x, j) => (j === i ? e.target.value : x)))}
            />
          </label>
        ))}
      </div>
      <input className="input" value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} placeholder="Anything else? (optional)" aria-label="A note for your provider" />
      <button type="button" className="btn btn-primary btn-sm" style={{ alignSelf: "flex-start" }} onClick={send} disabled={busy || !chosen.length}>
        Ask {visit.provider_first_name}
      </button>
    </div>
  );
}

function NextVisit({ v, onMessage }: { v: CustomerVisit; onMessage: () => void }) {
  const qc = useQueryClient();
  const notify = useToast();
  const { data: catalogue } = useCategories();
  const [changing, setChanging] = useState(false);
  const cat = catalogue?.categories.find((c) => c.id === v.category_id);
  const skip = async () => {
    try {
      await call(api.POST("/api/c/visits/{visit_id}/skip", { params: { path: { visit_id: v.id } } }));
      notify(`Visit skipped. We've let ${v.provider_first_name} know.`);
      await qc.invalidateQueries({ queryKey: ["c"] });
    } catch (e) {
      notify(errorText(e));
    }
  };
  return (
    <div className="card stack" style={g(14)}>
      <div className="row top" style={g(14)}>
        <span className="cat-ico lg" aria-hidden="true">
          <CatIcon icon={cat?.icon} id={v.category_id} size={24} />
        </span>
        <div className="grow stack" style={g(2)}>
          <span className="small muted">{v.recurring ? "Next visit" : "Booked"}</span>
          <h2 className="h2">
            {dateText(v.local_date)}, {WINDOW[v.window]}
          </h2>
          <span className="muted">
            {v.category_name} with {v.provider_short}, {fmt(v.price_pence)}
          </span>
        </div>
      </div>
      <div className="row wrap" style={g(8)}>
        {v.can_skip && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={skip}>
            Skip this visit
          </button>
        )}
        {v.can_change_date && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setChanging((c) => !c)} aria-expanded={changing}>
            Change the date
          </button>
        )}
        <button type="button" className="btn btn-ghost btn-sm" onClick={onMessage}>
          <MessageCircle size={15} aria-hidden="true" /> Message {v.provider_first_name}
        </button>
      </div>
      {changing && <ChangeDate visit={v} onDone={() => setChanging(false)} />}
    </div>
  );
}

/** My account: next visit, visits, plans (pause, cover, how often, cancel) and messages. */
export default function Account() {
  const { data: me, isLoading: meLoading } = useMe();
  const signedIn = !!me;
  const [params, setParams] = useSearchParams();
  const tab = (TABS.find((t) => t.id === params.get("tab"))?.id ?? "visits") as Tab;
  const thread = params.get("thread");
  const profile = useProfile(signedIn);
  const visits = useVisits(signedIn);
  const plans = usePlans(signedIn);
  const bookings = useBookings(signedIn);
  const threads = useThreads(signedIn);
  const requests = useRequests(signedIn);

  const setTab = (t: Tab, extra: Record<string, string> = {}) => setParams({ tab: t, ...extra }, { replace: true });

  if (meLoading) return <Loading />;
  if (!me) {
    return (
      <div className="c-flow">
        <SignInForm title="Sign in to your account" intro="No password: we text you a code whenever you sign in." />
      </div>
    );
  }
  if (profile.isLoading || visits.isLoading) return <Loading />;
  if (profile.data === null) {
    return (
      <div className="c-flow">
        <div className="stack" style={g(4)}>
          <span className="muted">Welcome</span>
          <h1 className="h1">Hi {firstName(me.name) || "there"}</h1>
        </div>
        <div className="card stack" style={g(12)}>
          <h2 className="h3">You haven't booked anything yet</h2>
          <p className="small muted">Get a guide price in under a minute. No account needed to see it.</p>
          <Button to="/" variant="cta">
            Get a price
          </Button>
        </div>
      </div>
    );
  }
  const open = (requests.data ?? []).filter((r) => r.status === "open");
  const next = visits.data?.next_visit ?? null;
  const unread = (threads.data ?? []).reduce((n, t) => n + t.unread, 0);
  const nextThread = next?.thread_id ?? undefined;

  return (
    <div className="c-flow wide">
      <div className="stack" style={g(4)}>
        <span className="muted">Welcome back</span>
        <h1 className="h1">Hi {firstName(profile.data?.name ?? me.name)}</h1>
      </div>
      {open.map((r) => (
        <Link key={r.id} to={`/requests/${r.ref}`} className="card link-card row" style={g(14)}>
          <span className="pulse" aria-hidden="true" />
          <span className="grow stack" style={g(2)}>
            <b>Finding someone local for your {r.category_name.toLowerCase()}</b>
            <span className="small muted">
              {r.ref}, guide price {fmt(r.guide_pence)} {r.unit}
            </span>
          </span>
          <ChevronRight size={18} aria-hidden="true" />
        </Link>
      ))}
      {next && <NextVisit v={next} onMessage={() => setTab("messages", nextThread ? { thread: nextThread } : {})} />}
      <Tabs
        items={TABS.map((t) => ({ ...t, label: t.id === "messages" && unread ? `Messages (${unread})` : t.label }))}
        value={tab}
        onChange={(t) => setTab(t)}
        label="My account"
      />
      <div role="tabpanel" aria-label={TABS.find((t) => t.id === tab)?.label}>
        {tab === "visits" && <VisitsTab upcoming={visits.data?.upcoming ?? []} done={visits.data?.done ?? []} />}
        {tab === "plan" && <PlansTab plans={plans.data ?? []} bookings={bookings.data ?? []} />}
        {tab === "messages" && (
          <MessagesTab threads={threads.data ?? []} selected={thread} onSelect={(id) => setTab("messages", { thread: id })} />
        )}
      </div>
    </div>
  );
}
