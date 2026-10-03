/** Time off and helpers: a date range, each affected visit set to local cover, a helper or skip;
 * your helpers and adding one. Owned by L2. Lifted from the prototype's CoverScreen. */
import { useMutation } from "@tanstack/react-query";
import { BadgeCheck, Plane, Plus, UserPlus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { api, call, type Schemas } from "../../api/client";
import { Loading } from "../../app/Status";
import { Avatar } from "../../shared/Avatar";
import { Badge } from "../../shared/Badge";
import { Button } from "../../shared/Button";
import { Chip } from "../../shared/Chip";
import { TextField } from "../../shared/Field";
import { useToast } from "../../shared/toast-context";
import { useHelpers, useInvalidateProvider, useTimeOff, type AffectedVisit, type HelperOut, type TimeOffOut } from "../api";
import { BackLink, ErrorNote } from "../components";
import { css, dateText, londonToday } from "../util";

type Choice = { action: "cover" | "helper" | "skip"; helper_user_id?: string };

function addDays(iso: string, n: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10);
}

function Plan({ helpers }: { helpers: HelperOut[] }) {
  const notify = useToast();
  const refresh = useInvalidateProvider();
  const tomorrow = addDays(londonToday(), 1);
  const [from, setFrom] = useState(tomorrow);
  const [to, setTo] = useState(addDays(tomorrow, 6));
  const [visits, setVisits] = useState<AffectedVisit[] | null>(null);
  const [plan, setPlan] = useState<Record<string, Choice>>({});
  const ready = helpers.filter((h) => h.status === "ready");
  const preview = useMutation({
    mutationFn: () => call(api.POST("/api/p/time-off/preview", { body: { from_date: from, to_date: to } })),
    onSuccess: (vs) => {
      setVisits(vs);
      setPlan(Object.fromEntries(vs.map((v) => [v.visit_id, v.cover_allowed ? { action: "cover" } : { action: "skip" }])));
    },
  });
  const book = useMutation({
    mutationFn: () =>
      call(
        api.POST("/api/p/time-off", {
          body: {
            from_date: from,
            to_date: to,
            arrangements: (visits ?? []).map((v) => ({ visit_id: v.visit_id, ...plan[v.visit_id] })) as Schemas["ArrangementIn"][],
          },
        }),
      ),
    onSuccess: () => {
      notify("Arranged. Your customers have been told who's coming.");
      setVisits(null);
      void refresh();
    },
  });
  const look = (e: FormEvent) => {
    e.preventDefault();
    preview.mutate();
  };
  return (
    <div className="card stack" style={css(14)}>
      <div className="row" style={css(10)}>
        <Plane size={20} aria-hidden="true" />
        <h2 className="h3">Time off</h2>
      </div>
      <form className="stack" style={css(12)} onSubmit={look}>
        <div className="grid2 narrow-stack">
          <TextField label="Away from" type="date" min={tomorrow} value={from} onChange={(e) => { setFrom(e.target.value); setVisits(null); }} />
          <TextField label="Back on" type="date" min={from} value={to} onChange={(e) => { setTo(e.target.value); setVisits(null); }} />
        </div>
        {visits === null && (
          <Button type="submit" variant="ghost" block disabled={preview.isPending || !from || !to}>
            See my visits in those days
          </Button>
        )}
      </form>
      <ErrorNote error={preview.error} />
      {visits !== null && (
        <>
          <span className="label">Your visits while you're away</span>
          {visits.length === 0 && <p className="small muted">Nothing booked in those days.</p>}
          {visits.map((v) => {
            const c = plan[v.visit_id];
            return (
              <div key={v.visit_id} className="stack" style={{ ...css(8), paddingBottom: 6 }}>
                <div className="stack" style={css(0)}>
                  <b>{v.customer_name}</b>
                  <span className="xs muted">
                    {v.category_name}, {dateText(v.local_date, { weekday: "short", day: "numeric", month: "short" })} at {v.start_time},{" "}
                    {v.area}
                  </span>
                </div>
                <div className="chips" role="group" aria-label={`What happens to ${v.customer_name}'s visit`}>
                  {v.cover_allowed && (
                    <Chip on={c?.action === "cover"} onClick={() => setPlan((p) => ({ ...p, [v.visit_id]: { action: "cover" } }))}>
                      Local cover
                    </Chip>
                  )}
                  {ready.map((h) => (
                    <Chip
                      key={h.user_id}
                      on={c?.action === "helper" && c.helper_user_id === h.user_id}
                      onClick={() => setPlan((p) => ({ ...p, [v.visit_id]: { action: "helper", helper_user_id: h.user_id } }))}
                    >
                      Send {h.name.split(" ")[0]}
                    </Chip>
                  ))}
                  <Chip on={c?.action === "skip"} onClick={() => setPlan((p) => ({ ...p, [v.visit_id]: { action: "skip" } }))}>
                    Skip it
                  </Chip>
                </div>
                {!v.cover_allowed && <span className="xs muted">This customer would rather not have cover.</span>}
              </div>
            );
          })}
          <div className="soft small stack" style={css(4)}>
            <b>Your customers stay yours.</b>
            <span>
              Whoever covers gets the visit, not the customer. Your regulars come straight back to you afterwards, and covers
              can't take them on privately.
            </span>
          </div>
          <ErrorNote error={book.error} />
          <Button variant="primary" size="lg" block disabled={book.isPending} onClick={() => book.mutate()}>
            {visits.length ? "Arrange cover" : "Book the time off"}
          </Button>
        </>
      )}
    </div>
  );
}

function ArrangeLater({ t, helpers }: { t: TimeOffOut; helpers: HelperOut[] }) {
  const notify = useToast();
  const refresh = useInvalidateProvider();
  const ready = helpers.filter((h) => h.status === "ready");
  const [plan, setPlan] = useState<Record<string, Choice>>(() =>
    Object.fromEntries(t.unarranged.map((v) => [v.visit_id, v.cover_allowed ? { action: "cover" } : { action: "skip" }])),
  );
  const save = useMutation({
    mutationFn: () =>
      call(
        api.POST("/api/p/time-off/{time_off_id}/arrange", {
          params: { path: { time_off_id: t.id } },
          body: { arrangements: t.unarranged.map((v) => ({ visit_id: v.visit_id, ...plan[v.visit_id] })) as Schemas["ArrangementIn"][] },
        }),
      ),
    onSuccess: () => {
      notify("Arranged. Your customers have been told who's coming.");
      void refresh();
    },
  });
  return (
    <div className="stack note-warn-card soft" style={css(10)}>
      <b>Booked in since you arranged this</b>
      {t.unarranged.map((v) => {
        const c = plan[v.visit_id];
        return (
          <div key={v.visit_id} className="stack" style={css(6)}>
            <span className="small">
              {v.customer_name}: {v.category_name}, {dateText(v.local_date, { weekday: "short", day: "numeric", month: "short" })} at {v.start_time}
            </span>
            <div className="chips" role="group" aria-label={`What happens to ${v.customer_name}'s visit`}>
              {v.cover_allowed && (
                <Chip on={c?.action === "cover"} onClick={() => setPlan((p) => ({ ...p, [v.visit_id]: { action: "cover" } }))}>
                  Local cover
                </Chip>
              )}
              {ready.map((h) => (
                <Chip
                  key={h.user_id}
                  on={c?.action === "helper" && c.helper_user_id === h.user_id}
                  onClick={() => setPlan((p) => ({ ...p, [v.visit_id]: { action: "helper", helper_user_id: h.user_id } }))}
                >
                  Send {h.name.split(" ")[0]}
                </Chip>
              ))}
              <Chip on={c?.action === "skip"} onClick={() => setPlan((p) => ({ ...p, [v.visit_id]: { action: "skip" } }))}>
                Skip it
              </Chip>
            </div>
          </div>
        );
      })}
      <ErrorNote error={save.error} />
      <Button variant="primary" block disabled={save.isPending} onClick={() => save.mutate()}>
        Arrange {t.unarranged.length === 1 ? "it" : "them"}
      </Button>
    </div>
  );
}

function Booked({ helpers }: { helpers: HelperOut[] }) {
  const { data } = useTimeOff();
  const refresh = useInvalidateProvider();
  const cancel = useMutation({
    mutationFn: (id: string) => call(api.DELETE("/api/p/time-off/{time_off_id}", { params: { path: { time_off_id: id } } })),
    onSuccess: () => void refresh(),
  });
  if (!data?.length) return null;
  return (
    <div className="stack" style={css(10)}>
      <h2 className="h3">Booked</h2>
      {data.map((t) => (
        <div key={t.id} className="card flat stack" style={css(8)}>
          <div className="row between">
            <b>
              {dateText(t.from_date, { day: "numeric", month: "short" })} to {dateText(t.to_date, { day: "numeric", month: "short" })}
            </b>
            <Badge tone={t.status === "cancelled" ? "plain" : "ok"}>
              {{ planned: "Coming up", active: "Away now", done: "Done", cancelled: "Cancelled" }[t.status]}
            </Badge>
          </div>
          {t.arrangements.map((a) => (
            <span key={a.visit_id} className="small">
              {a.detail}
            </span>
          ))}
          {t.unarranged.length > 0 && <ArrangeLater t={t} helpers={helpers} />}
          {t.status === "planned" && (
            <Button variant="link" disabled={cancel.isPending} onClick={() => cancel.mutate(t.id)}>
              Cancel this time off
            </Button>
          )}
        </div>
      ))}
      <ErrorNote error={cancel.error} />
    </div>
  );
}

function AddHelper({ onDone }: { onDone: () => void }) {
  const notify = useToast();
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [relationship, setRelationship] = useState("");
  const add = useMutation({
    mutationFn: () => call(api.POST("/api/p/helpers", { body: { name: name.trim(), phone: phone.trim(), relationship: relationship.trim() } })),
    onSuccess: () => {
      notify("We've texted them a sign-up link. It takes about 10 minutes.");
      onDone();
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    add.mutate();
  };
  return (
    <form className="stack" style={css(12)} onSubmit={submit}>
      <TextField label="Their name" value={name} onChange={(e) => setName(e.target.value)} autoComplete="off" required />
      <TextField label="Their mobile" value={phone} inputMode="tel" onChange={(e) => setPhone(e.target.value)} required />
      <TextField label="Who are they to you?" optional value={relationship} onChange={(e) => setRelationship(e.target.value)} placeholder="Son, neighbour, friend" />
      <ErrorNote error={add.error} />
      <Button type="submit" variant="primary" block disabled={add.isPending || !name.trim() || phone.replace(/\D/g, "").length < 10}>
        Text them a sign-up link
      </Button>
    </form>
  );
}

export default function TimeOff() {
  const { data: helpers, isLoading, error } = useHelpers();
  const refresh = useInvalidateProvider();
  const [adding, setAdding] = useState(false);
  return (
    <>
      <BackLink to="/p/me">Me</BackLink>
      <h1 className="h1">Time off and helpers</h1>
      {isLoading && <Loading />}
      {error && <ErrorNote error={error} />}
      {helpers && <Plan helpers={helpers} />}
      <Booked helpers={helpers ?? []} />
      <div className="card stack" style={css(14)}>
        <div className="row" style={css(10)}>
          <UserPlus size={20} aria-hidden="true" />
          <h2 className="h3">Your helpers</h2>
        </div>
        <p className="small muted">
          You can send a helper in your place. They do the job, you get paid, and you pay them however you've agreed. The
          customer is always told who's coming.
        </p>
        {helpers?.map((h) => (
          <div key={h.user_id} className="row top" style={css(12)}>
            <Avatar initials={h.initials} size={48} />
            <div className="grow stack" style={css(6)}>
              <div className="stack" style={css(0)}>
                <b>{h.name}</b>
                <span className="xs muted">{h.status_text}</span>
              </div>
              {h.badges.length > 0 && (
                <div className="row wrap" style={css(6)}>
                  {h.badges.map((b) => (
                    <span key={b} className="badge ok">
                      <BadgeCheck size={12} aria-hidden="true" /> {b}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
        {adding ? (
          <AddHelper onDone={() => { setAdding(false); void refresh(); }} />
        ) : (
          <Button variant="ghost" block onClick={() => setAdding(true)}>
            <Plus size={17} aria-hidden="true" /> Add a helper
          </Button>
        )}
        <p className="xs muted">Helpers go through the same ID, DBS and insurance checks as you before they can do a job.</p>
      </div>
    </>
  );
}
