import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Camera, Check } from "lucide-react";
import { useId, useState, type CSSProperties } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { api, call, type Schemas } from "../../api/client";
import { useCategories, useMe } from "../../api/queries";
import { Badge } from "../../shared/Badge";
import { Button } from "../../shared/Button";
import { Chip } from "../../shared/Chip";
import { fmt, fmtDuration } from "../../shared/format";
import { SignInForm } from "../../shared/SignInForm";
import { Stars } from "../../shared/Stars";
import { useToast } from "../../shared/toast-context";
import { Loading, Notice } from "../../app/Status";
import { errorText, useVisit, type CustomerVisit } from "../api";
import { AfterPhotoArt, RoomPhotoArt } from "../components/Art";
import { PhotoPicker } from "../components/PhotoPicker";
import { dateText } from "../text";
import { uploadPhotos } from "../upload";

const g = (px: number) => ({ "--g": `${px}px` }) as CSSProperties;
const WORDS = ["", "Poor", "Not great", "OK", "Good", "Excellent"];
const GOOD = ["On time", "Thorough", "Friendly", "Left it tidy"];
const BAD = ["Missed bits", "Late", "Left a mess", "Rushed"];
const TIPS = [0, 200, 500, 1000];

function Problem({ v, onReported }: { v: CustomerVisit; onReported: (ref: string) => void }) {
  const who = v.provider_first_name;
  const id = useId();
  const notify = useToast();
  const [text, setText] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!v.can_report) {
    return (
      <div className="card flat stack" style={g(10)}>
        <h2 className="h3">Something not right?</h2>
        <p className="small muted">
          {v.dispute_ref
            ? `You've told us about this visit (${v.dispute_ref}). We'll keep you posted by text.`
            : `It's more than 48 hours since the visit, so please message ${who} about it instead.`}
        </p>
        {!v.dispute_ref && (
          <Button variant="ghost" size="sm" to={`/account?tab=messages${v.thread_id ? `&thread=${v.thread_id}` : ""}`}>
            Message {who}
          </Button>
        )}
      </div>
    );
  }
  const report = async () => {
    setBusy(true);
    setError(null);
    try {
      const photos = files.length ? await uploadPhotos(files, "dispute_photo", { visit_id: v.id }) : [];
      const out = await call(
        api.POST("/api/c/visits/{visit_id}/problem", {
          params: { path: { visit_id: v.id } },
          body: { description: text.trim(), photos },
        }),
      );
      notify(`Reported. We've let ${who} know and will text you within a day.`);
      onReported(out.ref);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="card flat stack" style={g(12)}>
      <h2 className="h3">Tell us what happened</h2>
      <p className="small muted">
        We'll share it with {who} and help you agree a fix, usually a free return visit. Please let us know within 48 hours
        of the visit.
      </p>
      <label className="sr-only" htmlFor={id}>
        What happened
      </label>
      <textarea
        id={id}
        className="input"
        value={text}
        maxLength={2000}
        onChange={(e) => setText(e.target.value)}
        placeholder="For example: the bathroom floor wasn't done."
      />
      <PhotoPicker files={files} onChange={setFiles} onReject={notify} />
      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
      <button type="button" className="btn btn-primary btn-block" onClick={report} disabled={busy || text.trim().length < 3}>
        Report the problem
      </button>
    </div>
  );
}

/** "How did Dave do?": stars, tags, a tip (no fee: all of it goes to them), report a problem. */
export default function Rate() {
  const { visitId = "" } = useParams();
  const [params] = useSearchParams();
  const qc = useQueryClient();
  const { data: me, isLoading: meLoading } = useMe();
  const { data: catalogue } = useCategories();
  const { data: v, isLoading, error } = useVisit(visitId, !!me);
  const [stars, setStars] = useState(0);
  const [tags, setTags] = useState<string[]>([]);
  const [tip, setTip] = useState(0);
  const [problem, setProblem] = useState(params.get("problem") === "1");
  const [done, setDone] = useState<Schemas["RatingOut"] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  if (meLoading || (me && isLoading)) return <Loading />;
  if (!me) {
    return (
      <div className="c-flow">
        <SignInForm title="Sign in to rate your visit" />
      </div>
    );
  }
  if (error || !v) {
    return (
      <div className="c-flow">
        <Notice title="We can't find that visit">
          <Button to="/account" variant="primary">
            Back to my account
          </Button>
        </Notice>
      </div>
    );
  }
  const who = v.provider_first_name;
  const group = catalogue?.categories.find((c) => c.id === v.category_id)?.group;

  if (done) {
    return (
      <div className="c-flow">
        <div className="stack center" style={{ ...g(14), alignItems: "center", paddingTop: 24 }}>
          <span className="success-mark" aria-hidden="true">
            <Check size={32} strokeWidth={3} />
          </span>
          <h1 className="h1">Thanks for rating {who}</h1>
          <p className="muted">
            {done.tip_status === "charged"
              ? `Your ${fmt(done.tip_pence)} tip goes straight to ${who}.`
              : done.tip_status === "failed"
                ? done.tip_message
                : `${who} will see your rating.`}
          </p>
          <Button to="/account" variant="primary" size="lg">
            Back to my account
          </Button>
        </div>
      </div>
    );
  }

  const send = async () => {
    setBusy(true);
    setErr(null);
    try {
      const out = await call(
        api.POST("/api/c/visits/{visit_id}/rating", {
          params: { path: { visit_id: v.id } },
          body: { stars, tags, tip_pence: tip, comment: "" },
        }),
      );
      await qc.invalidateQueries({ queryKey: ["c"] });
      setDone(out);
    } catch (e) {
      setErr(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const toggleTag = (t: string) => setTags((x) => (x.includes(t) ? x.filter((y) => y !== t) : [...x, t]));

  return (
    <div className="c-flow">
      <Link className="btn btn-link" style={{ alignSelf: "flex-start" }} to="/account">
        <ArrowLeft size={18} aria-hidden="true" /> My account
      </Link>
      <h1 className="h1">How did {who} do?</h1>
      <div className="card flat" style={{ padding: 0, overflow: "hidden" }}>
        {v.after_photo_url ? (
          <img className="after-photo" src={v.after_photo_url} alt={`The finished job, from ${who}`} />
        ) : group === "outside" ? (
          <AfterPhotoArt />
        ) : group === "inside" ? (
          <RoomPhotoArt />
        ) : null}
        <div className="row between wrap small" style={{ padding: "12px 16px" }}>
          <span>
            <b>
              {v.category_name}, {dateText(v.local_date)}.
            </b>{" "}
            {v.minutes_actual ? <span className="muted">Took {fmtDuration(v.minutes_actual)}.</span> : null}
          </span>
          {v.after_photo_url && (
            <Badge tone="ok">
              <Camera size={12} aria-hidden="true" /> After photo
            </Badge>
          )}
        </div>
      </div>
      {v.can_rate ? (
        <>
          <div className="stack center" style={{ ...g(4), alignItems: "center" }}>
            <Stars value={stars} onChange={setStars} size={38} />
            <span className="small muted" aria-live="polite">
              {WORDS[stars] || "Tap a star"}
            </span>
          </div>
          {stars > 0 && (
            <div className="stack" style={g(10)}>
              <span className="label" id="tags-label">
                {stars >= 4 ? "What went well?" : "What went wrong?"}
              </span>
              <div className="chips" role="group" aria-labelledby="tags-label">
                {(stars >= 4 ? GOOD : BAD).map((t) => (
                  <Chip key={t} on={tags.includes(t)} onClick={() => toggleTag(t)}>
                    {t}
                  </Chip>
                ))}
              </div>
            </div>
          )}
          <div className="stack" style={g(10)}>
            <span className="label" id="tip-label">
              Add a tip?{" "}
              <span className="muted" style={{ fontWeight: 400 }}>
                All of it goes to {who}.
              </span>
            </span>
            <div className="chips" role="group" aria-labelledby="tip-label">
              {TIPS.map((t) => (
                <Chip key={t} on={tip === t} onClick={() => setTip(t)}>
                  {t ? fmt(t) : "No tip"}
                </Chip>
              ))}
            </div>
          </div>
          {err && (
            <p className="field-error" role="alert">
              {err}
            </p>
          )}
          <button type="button" className="btn btn-cta btn-lg btn-block" disabled={!stars || busy} onClick={send}>
            Send rating
          </button>
        </>
      ) : (
        <p className="small muted center">
          {v.rating_stars ? `You rated this visit ${v.rating_stars} ${v.rating_stars === 1 ? "star" : "stars"}.` : "This visit can't be rated yet."}
        </p>
      )}
      <button type="button" className="btn btn-link" style={{ alignSelf: "center" }} onClick={() => setProblem((p) => !p)} aria-expanded={problem}>
        Something not right?
      </button>
      {problem && (
        <Problem
          v={v}
          onReported={() => void qc.invalidateQueries({ queryKey: ["c"] })}
        />
      )}
    </div>
  );
}
