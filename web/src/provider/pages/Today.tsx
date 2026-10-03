/** Today's round: the day's visits in time order and the on-the-job card (timer, photos,
 * directions, message, finish). Owned by L2. Lifted from the prototype's TodayScreen. */
import { useQueryClient } from "@tanstack/react-query";
import { MessageCircle, Navigation, Timer, UserPlus, Users } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { api, call } from "../../api/client";
import { useConfig } from "../../api/queries";
import { Loading } from "../../app/Status";
import { Button } from "../../shared/Button";
import { Chip } from "../../shared/Chip";
import { useToast } from "../../shared/toast-context";
import { pKeys, useHelperMode, useInvalidateProvider, useProviderMutation, useToday, useVisit, type RoundItem, type TodayRound } from "../api";
import { ErrorNote, Note, PhotoCheck } from "../components";
import { clock, css, dateText, errorText } from "../util";

const DEMO_EXTRA_KEY = "oqj.p.demoExtraMins";

function demoExtra(visitId: string): number {
  try {
    return Number(sessionStorage.getItem(`${DEMO_EXTRA_KEY}.${visitId}`) || 0);
  } catch {
    return 0;
  }
}

function setDemoExtra(visitId: string, mins: number) {
  try {
    sessionStorage.setItem(`${DEMO_EXTRA_KEY}.${visitId}`, String(mins));
  } catch {
    // storage blocked: the demo minutes just aren't kept
  }
}

function OnJob({ item, demo }: { item: RoundItem; demo: boolean }) {
  const { data: v, dataUpdatedAt, error } = useVisit(item.visit_id);
  const qc = useQueryClient();
  const refresh = useInvalidateProvider();
  const navigate = useNavigate();
  const [now, setNow] = useState(() => Date.now());
  const [extra, setExtra] = useState(() => demoExtra(item.visit_id));
  const running = v?.status === "in_progress";
  useEffect(() => {
    if (!running) return undefined;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [running]);
  const start = useProviderMutation({
    mutationFn: () => call(api.POST("/api/p/visits/{visit_id}/start", { params: { path: { visit_id: item.visit_id } } })),
    onSuccess: (data) => {
      qc.setQueryData(pKeys.visit(item.visit_id), data);
      setNow(Date.now());
      void refresh();
    },
  });
  const photo = async (kind: "before" | "after", fileId: string) => {
    const data = await call(
      api.POST("/api/p/visits/{visit_id}/photos", { params: { path: { visit_id: item.visit_id } }, body: { kind, file_id: fileId } }),
    );
    qc.setQueryData(pKeys.visit(item.visit_id), data);
  };
  if (error) return <ErrorNote error={error} />;
  if (!v) return <Loading />;

  // Demo minutes count only while DEMO_MODE is on: never in calibration data from a real round.
  const elapsed = (v.elapsed_seconds ?? 0) + (running ? Math.max(0, now - dataUpdatedAt) / 1000 : 0) + (demo ? extra * 60 : 0);
  const mins = elapsed / 60;
  const over = mins > v.est_mins * 1.1;
  const addTen = () => {
    setExtra((x) => {
      setDemoExtra(item.visit_id, x + 10);
      return x + 10;
    });
  };
  return (
    <div className="grow card stack" style={{ ...css(14), padding: 16 }}>
      <div className="stack" style={css(2)}>
        <b>{v.address_line}</b>
        <span className="small muted">
          {v.category_name} for {v.customer_name}
          {item.miles_from_previous !== null ? `, ${item.miles_from_previous} miles from your last stop` : ""}
        </span>
      </div>
      {(v.summary || v.note) && (
        <div className="soft small">
          {v.summary}
          {v.summary && v.note ? ". " : ""}
          {v.note && <>“{v.note}”</>}
        </div>
      )}
      <div className="grid2">
        <a className="btn btn-ghost" href={v.directions_url} target="_blank" rel="noreferrer noopener">
          <Navigation size={17} aria-hidden="true" /> Directions
        </a>
        {v.thread_id ? (
          <Link className="btn btn-ghost" to={`/p/messages/${v.thread_id}`}>
            <MessageCircle size={17} aria-hidden="true" /> Message
          </Link>
        ) : (
          <span />
        )}
      </div>
      {v.status === "scheduled" && (
        <>
          {v.can_start ? (
            <>
              <Button variant="cta" size="lg" block disabled={start.isPending} onClick={() => start.mutate()}>
                <Timer size={20} aria-hidden="true" /> {v.early_start_demo ? "Demo: start it now" : "I've arrived, start the job"}
              </Button>
              {v.early_start_demo && (
                <p className="xs muted">Prototype: this visit is booked for {dateText(v.local_date)}. Demo mode lets you start it now.</p>
              )}
            </>
          ) : (
            v.start_note && <Note>{v.start_note}</Note>
          )}
          <ErrorNote error={start.error} />
        </>
      )}
      {running && (
        <div className="stack" style={css(10)}>
          <div className="timer" role="timer" aria-label={`${Math.floor(mins)} minutes so far`}>
            {clock(elapsed)}
          </div>
          <div className="progress" aria-hidden="true">
            <i style={{ width: `${Math.min(100, (mins / v.est_mins) * 100)}%`, background: over ? "var(--accent)" : undefined }} />
          </div>
          <div className="row between xs muted">
            <span>{over ? "Running over the estimate, that's fine" : `Estimate ${v.est_mins} minutes`}</span>
            {demo && (
              <button type="button" className="btn btn-link xs" onClick={addTen}>
                Demo: add 10 min
              </button>
            )}
          </div>
        </div>
      )}
      <div className="stack" style={css(0)}>
        <PhotoCheck
          label="Before photo"
          done={v.before_photos.length > 0}
          kind="visit_before"
          visitId={v.id}
          onUploaded={(id) => photo("before", id)}
        />
        <PhotoCheck
          label="After photo"
          hint={`Sent to ${v.customer_first}. It also protects you if there's a disagreement.`}
          done={v.after_photos.length > 0}
          kind="visit_after"
          visitId={v.id}
          onUploaded={(id) => photo("after", id)}
        />
      </div>
      {running && (
        <Button
          variant="primary"
          size="lg"
          block
          onClick={() => navigate(`/p/visits/${v.id}/finish`, { state: { minutes: Math.max(1, Math.round(mins)) } })}
        >
          Finish job
        </Button>
      )}
    </div>
  );
}

function Row({ item }: { item: RoundItem }) {
  const what =
    item.status === "finished"
      ? `${item.category_name}, done in ${item.minutes_actual ?? item.est_mins} minutes`
      : item.status === "skipped"
        ? `${item.category_name}, skipped`
        : item.performer === "helper"
          ? `${item.category_name}, ${item.performer_name} is doing this`
          : item.cover_state === "offered"
            ? `${item.category_name}, out for local cover`
            : `${item.category_name}, about ${item.est_mins} minutes`;
  return (
    <div className="stack" style={{ ...css(0), paddingTop: 4 }}>
      <b>{item.area || item.address_line}</b>
      <span className="small muted">
        {what}
        {item.customer_name ? ` for ${item.customer_name}` : ""}
      </span>
    </div>
  );
}

function CantMakeIt({ round }: { round: TodayRound }) {
  const notify = useToast();
  const refresh = useInvalidateProvider();
  const options = round.items.filter((i) => i.status === "scheduled" && i.performer === "provider" && i.cover_state === "none");
  const [chosen, setChosen] = useState<string | null>(null);
  const visitId = chosen ?? options[0]?.visit_id ?? null;
  const item = options.find((i) => i.visit_id === visitId);
  const send = useProviderMutation({
    mutationFn: (helperId: string) =>
      call(api.POST("/api/p/visits/{visit_id}/send-helper", { params: { path: { visit_id: visitId ?? "" } }, body: { helper_user_id: helperId } })),
    onSuccess: (v) => {
      notify(`${item?.customer_name ?? "The customer"} has been told ${v.performer_name} is coming instead`);
      void refresh();
    },
  });
  const cover = useProviderMutation({
    mutationFn: () => call(api.POST("/api/p/visits/{visit_id}/cover", { params: { path: { visit_id: visitId ?? "" } } })),
    onSuccess: () => {
      notify("Sent out for local cover. We'll text you when someone takes it.");
      void refresh();
    },
  });
  if (options.length === 0) return null;
  return (
    <div className="card flat stack" style={css(10)}>
      <b>Can't make one of {round.is_today ? "today's" : "these"} jobs?</b>
      {options.length > 1 && (
        <div className="chips" role="group" aria-label="Which visit">
          {options.map((o) => (
            <Chip key={o.visit_id} on={o.visit_id === visitId} onClick={() => setChosen(o.visit_id)}>
              {o.start_time} {o.area}
            </Chip>
          ))}
        </div>
      )}
      <div className="grid2">
        {round.helpers.map((h) => (
          <Button key={h.user_id} variant="ghost" disabled={send.isPending} onClick={() => send.mutate(h.user_id)}>
            <UserPlus size={17} aria-hidden="true" /> Send {h.name.split(" ")[0]}
          </Button>
        ))}
        {item?.cover_allowed && !round.is_today ? (
          <Button variant="ghost" disabled={cover.isPending} onClick={() => cover.mutate()}>
            <Users size={17} aria-hidden="true" /> Get cover
          </Button>
        ) : (
          <Button to="/p/time-off" variant="ghost">
            <Users size={17} aria-hidden="true" /> Time off
          </Button>
        )}
      </div>
      {round.is_today && <p className="xs muted">Cover needs a day's notice. For today, send a helper or message the customer.</p>}
      {(send.error || cover.error) && <p className="field-error" role="alert">{errorText(send.error ?? cover.error)}</p>}
    </div>
  );
}

export default function Today() {
  const [params] = useSearchParams();
  const date = params.get("date");
  const { data: config } = useConfig();
  const { helper } = useHelperMode();
  const { data: round, isLoading, error } = useToday(date);
  const isToday = !date || round?.is_today;
  const heading = isToday ? "Today's round" : `${dateText(date ?? "", { weekday: "long" })}'s round`;
  return (
    <>
      <div className="stack" style={css(2)}>
        <span className="small muted">{round?.day_text ?? (date ? dateText(date) : "")}</span>
        <h1 className="h1">{heading}</h1>
      </div>
      {round && (round.upcoming_days.length > 0 || !isToday) && (
        <nav className="day-picker" aria-label="Other days">
          <Link to="/p/today" className={"chip" + (isToday ? " on" : "")} aria-current={isToday ? "page" : undefined}>
            Today
          </Link>
          {[...new Set([...(date && !isToday ? [date] : []), ...round.upcoming_days])].sort().map((d) => (
            <Link
              key={d}
              to={`/p/today?date=${d}`}
              className={"chip" + (d === date ? " on" : "")}
              aria-current={d === date ? "page" : undefined}
            >
              {dateText(d, { weekday: "short", day: "numeric" })}
            </Link>
          ))}
        </nav>
      )}
      {isLoading && <Loading />}
      {error && <ErrorNote error={error} />}
      {round && round.items.length === 0 && (
        <p className="muted">
          Nothing booked {isToday ? "today" : "that day"}.
          {round.upcoming_days.length > 0 && <> Your next visits are on the days above.</>}
        </p>
      )}
      {round && round.items.length > 0 && (
        <div>
          {round.items.map((item) => (
            <div
              key={item.visit_id}
              className={"round-item" + (item.status === "finished" ? " done" : item.is_now ? " now" : "")}
            >
              <span className="round-time">{item.start_time}</span>
              {item.is_now ? <OnJob item={item} demo={!!config?.demo_mode} /> : <Row item={item} />}
            </div>
          ))}
        </div>
      )}
      {round && !helper && <CantMakeIt round={round} />}
    </>
  );
}
