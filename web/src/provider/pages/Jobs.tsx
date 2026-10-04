/** New jobs: greeting, this week, the limit strip, jobs near you and coming up. Owned by L2.
 * Lifted from the prototype's ProviderJobs, OfferCard and LimitStrip. The prototype's text-message
 * screen (SmsScreen) is the job alert in the Outbox drawer: its link opens /p/j/{ref} signed in. */
import { MessageCircle } from "lucide-react";
import { Link, Navigate } from "react-router";
import { Loading } from "../../app/Status";
import { fmt } from "../../shared/format";
import { useHome } from "../api";
import { DateChip, ErrorNote, LimitStrip, OfferCard } from "../components";
import { css } from "../util";

export default function Jobs() {
  const { data: home, isLoading, error } = useHome();
  if (isLoading) return <Loading />;
  if (error || !home) return <ErrorNote error={error ?? new Error()} />;
  if (home.status === "signing_up") return <Navigate to="/p/signup" replace />;

  const fresh = home.new_jobs.filter((j) => j.state === null || j.state === "countered");
  const mine = home.new_jobs.filter((j) => j.state !== null && j.state !== "countered");
  return (
    <>
      <div className="stack" style={css(2)}>
        <span className="small muted">{home.today_text}</span>
        <h1 className="h1">{home.greeting}</h1>
      </div>

      {home.helper ? (
        <p className="muted">These are the visits you've been sent to. Open Today for the round.</p>
      ) : (
        <>
          <div className="grid2">
            <div className="card flat stack" style={{ ...css(4), padding: 16 }}>
              <span className="xs muted">This week</span>
              <span className="big-num" style={{ fontSize: 30 }}>
                {fmt(home.week_earned_pence)}
              </span>
              <span className="xs muted">
                from {home.week_jobs} {home.week_jobs === 1 ? "job" : "jobs"}
              </span>
            </div>
            <div className="card flat stack" style={{ ...css(4), padding: 16 }}>
              <span className="xs muted">Your rating</span>
              <span className="big-num" style={{ fontSize: 30 }}>
                {home.rating_avg !== null ? home.rating_avg.toFixed(1) : "New"}
              </span>
              <span className="xs muted">
                from {home.rating_count} {home.rating_count === 1 ? "review" : "reviews"}
              </span>
            </div>
          </div>
          {home.unread_messages > 0 && (
            <Link to="/p/messages" className="card flat row link-card" style={css(10)}>
              <MessageCircle size={20} aria-hidden="true" />
              <b className="grow">
                {home.unread_messages} new {home.unread_messages === 1 ? "message" : "messages"}
              </b>
            </Link>
          )}
          {home.status === "suspended" && (
            <p className="soft small note-warn">Your account is paused, so you won't get new jobs for now. We'll be in touch.</p>
          )}
          {home.limit.on && <LimitStrip limit={home.limit} />}

          <div className="row between">
            <h2 className="h2">New jobs near you</h2>
            {fresh.length > 0 && <span className="badge accent">{fresh.length} new</span>}
          </div>
          {fresh.length === 0 && (
            <p className="muted">Nothing new near you just now. We'll text you as soon as a job comes in.</p>
          )}
          {fresh.map((j) => (
            <OfferCard key={j.request_ref} job={j} limitPeriod={home.limit.period} />
          ))}
          {mine.length > 0 && (
            <>
              <h2 className="h3">Recently</h2>
              {mine.map((j) => (
                <OfferCard key={j.request_ref} job={j} limitPeriod={home.limit.period} />
              ))}
            </>
          )}
        </>
      )}

      <h2 className="h2">Coming up</h2>
      {home.coming_up.length === 0 ? (
        <p className="muted">Nothing booked yet.</p>
      ) : (
        <div className="card flat" style={{ padding: "4px 16px" }}>
          {home.coming_up.map((u) => (
            <Link key={u.visit_id} to={`/p/today?date=${u.local_date}`} className="list-row link-plain">
              <DateChip iso={u.local_date} />
              <div className="grow stack" style={css(0)}>
                <b>
                  {u.start_time} in {u.area}
                </b>
                <span className="small muted">{u.category_name}</span>
              </div>
              <span>{fmt(u.price_pence)}</span>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}
