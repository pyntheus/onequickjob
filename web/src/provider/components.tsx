/** Pieces the provider screens share, lifted from the prototype (OfferCard, LimitStrip, ApproxMap,
 * PhotoCheck) plus the upload and note helpers the real app needs. */
import {
  ArrowLeft,
  Calendar,
  Camera,
  Check,
  ChevronRight,
  Clock,
  Lock,
  PiggyBank,
  Route as RouteIcon,
  Upload,
} from "lucide-react";
import { useId, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { Link } from "react-router";
import { CatIcon } from "../shared/CatIcon";
import { fmt, relativeTime } from "../shared/format";
import { uploadFile, type FileKind, type JobCard, type LimitView } from "./api";
import { css, dateText, errorText, periodWord } from "./util";

export function BackLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="btn btn-link back-link">
      <ArrowLeft size={18} aria-hidden="true" /> {children}
    </Link>
  );
}

export function Note({ tone = "soft", icon, children }: { tone?: "soft" | "warn" | "danger" | "ok"; icon?: ReactNode; children: ReactNode }) {
  return (
    <div className={`soft small row top note-${tone}`} style={css(10)}>
      {icon && <span className="note-icon">{icon}</span>}
      <span className="grow">{children}</span>
    </div>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <p className="soft small note-danger" role="alert">
      {errorText(error)}
    </p>
  );
}

export function LimitStrip({ limit, to = "/p/limit" }: { limit: LimitView; to?: string }) {
  return (
    <Link to={to} className="card flat stack limit-strip" style={css(8)}>
      <span className="row" style={css(10)}>
        <PiggyBank size={20} aria-hidden="true" />
        <span className="grow small">
          {limit.reached ? (
            <>
              <b>You've reached</b> your {fmt(limit.amount_pence)} {periodWord(limit.period)} limit
            </>
          ) : (
            <>
              <b>{fmt(limit.remaining_pence ?? 0)} left</b> of your {fmt(limit.amount_pence)} {periodWord(limit.period)} limit
            </>
          )}
        </span>
        <ChevronRight size={18} aria-hidden="true" />
      </span>
      <span className="progress" aria-hidden="true">
        <i style={{ width: `${limit.used_percent}%`, background: limit.used_percent >= 100 ? "var(--accent)" : undefined }} />
      </span>
    </Link>
  );
}

export function OfferCard({ job, limitPeriod }: { job: JobCard; limitPeriod: string }) {
  const done = job.state === "yours" || job.state === "taken";
  return (
    <Link
      to={`/p/j/${job.request_ref}`}
      className="offer-card"
      style={{ opacity: job.over_limit || job.state === "taken" ? 0.72 : 1 }}
      aria-label={`${job.category_name} in ${job.area}, guide price ${fmt(job.guide_pence)}`}
    >
      <div className="row top" style={{ width: "100%" }}>
        <span className="cat-ico" aria-hidden="true">
          <CatIcon id={job.category_id} />
        </span>
        <div className="grow stack" style={css(2)}>
          <b>{job.category_name}</b>
          <span className="small muted">
            {job.area}, {job.district}, {job.miles} {job.miles === 1 ? "mile" : "miles"} away
          </span>
        </div>
        <div className="stack" style={{ ...css(0), textAlign: "right" }}>
          <span className="big-num" style={{ fontSize: 24 }}>
            {fmt(job.guide_pence)}
          </span>
          <span className="xs muted">you get {fmt(job.provider_pence)}</span>
        </div>
      </div>
      <div className="row wrap" style={css(6)}>
        <span className="badge">
          <Clock size={13} aria-hidden="true" /> About {job.mins} min
        </span>
        <span className="badge">
          <Calendar size={13} aria-hidden="true" /> {job.frequency_label}
        </span>
        {job.state === "yours" && (
          <span className="badge ok">
            <Check size={13} aria-hidden="true" /> Yours
          </span>
        )}
        {job.state === "countered" && <span className="badge warn">Waiting on your price</span>}
        {job.state === "lapsed" && <span className="badge warn">Your price lapsed</span>}
        {job.state === "taken" && <span className="badge">Gone to someone else</span>}
        {job.over_limit && !done && (
          <span className="badge warn">
            <PiggyBank size={13} aria-hidden="true" /> Over your {periodWord(limitPeriod)} limit
          </span>
        )}
      </div>
      {job.route_hint && (
        <span className="route-tag">
          <RouteIcon size={15} aria-hidden="true" /> {job.route_hint}
        </span>
      )}
      <span className="xs muted">Posted {relativeTime(job.posted_at)}</span>
    </Link>
  );
}

/** Where the job is, roughly: a drawing, not a real map (no map service), and never the house. */
export function ApproxMap({ hint }: { hint?: string | null }) {
  const road = (w: number): CSSProperties => ({ fill: "none", stroke: "var(--surface)", strokeWidth: w, strokeLinecap: "round" });
  return (
    <div className="card flat" style={{ padding: 0, overflow: "hidden" }}>
      <svg viewBox="0 0 360 150" className="chart" role="img" aria-label="Approximate area of the job, about a kilometre across">
        <rect width="360" height="150" style={{ fill: "var(--soft)" }} />
        <path d="M-10 112 C 80 92, 140 132, 220 98 S 330 62, 380 72" style={road(14)} />
        <path d="M120 -10 C 130 40, 110 90, 150 160" style={road(10)} />
        <path d="M252 -10 L 272 160" style={road(8)} />
        <circle cx="198" cy="82" r="42" style={{ fill: "var(--primary)", opacity: 0.14 }} />
        <circle cx="198" cy="82" r="42" style={{ fill: "none", stroke: "var(--primary)", strokeWidth: 2, strokeDasharray: "5 5" }} />
        {hint && <circle cx="262" cy="44" r="7" style={{ fill: "var(--accent)", stroke: "var(--ink)", strokeWidth: 1.5 }} />}
      </svg>
      <div className="row xs muted" style={{ ...css(6), padding: "10px 14px" }}>
        <Lock size={13} aria-hidden="true" /> Exact address shown once the job is yours
      </div>
    </div>
  );
}

/** A big tap target that opens the camera (or files) and uploads what's chosen. */
export function UploadButton({
  kind,
  label,
  onUploaded,
  visitId,
  accept = "image/*",
  capture,
  variant = "ghost",
  disabled,
}: {
  kind: FileKind;
  label: ReactNode;
  onUploaded: (fileId: string, url: string) => void | Promise<void>;
  visitId?: string;
  accept?: string;
  capture?: "environment" | "user";
  variant?: "ghost" | "primary";
  disabled?: boolean;
}) {
  const input = useRef<HTMLInputElement>(null);
  const id = useId();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pick = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const f = await uploadFile(file, kind, visitId);
      await onUploaded(f.id, f.url);
    } catch (e) {
      setError(errorText(e, "That upload didn't work. Please try again."));
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  };
  return (
    <div className="stack" style={css(6)}>
      <label htmlFor={id} className={`btn btn-${variant} btn-block${busy || disabled ? " is-busy" : ""}`} aria-disabled={busy || disabled}>
        <Upload size={17} aria-hidden="true" /> {busy ? "Uploading…" : label}
      </label>
      <input
        ref={input}
        id={id}
        className="sr-only"
        type="file"
        accept={accept}
        capture={capture}
        disabled={busy || disabled}
        onChange={(e) => void pick(e.target.files?.[0])}
      />
      {error && (
        <span className="field-error" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}

export function PhotoCheck({
  label,
  hint,
  done,
  kind,
  visitId,
  onUploaded,
  disabled,
}: {
  label: string;
  hint?: string;
  done: boolean;
  kind: "visit_before" | "visit_after";
  visitId: string;
  onUploaded: (fileId: string) => Promise<void>;
  disabled?: boolean;
}) {
  const id = useId();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pick = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const f = await uploadFile(file, kind, visitId);
      await onUploaded(f.id);
    } catch (e) {
      setError(errorText(e, "That photo didn't upload. Please try again."));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="stack" style={css(4)}>
      <label htmlFor={id} className="toggle-row photo-check" aria-disabled={disabled}>
        <span className={"box" + (done ? " on" : "")} aria-hidden="true">
          {done && <Check size={15} strokeWidth={3} />}
        </span>
        <span className="grow stack" style={css(0)}>
          <span style={{ fontWeight: 600 }}>
            {label}
            {done ? " added" : ""}
          </span>
          {hint && <span className="xs muted">{busy ? "Uploading…" : hint}</span>}
          {!hint && busy && <span className="xs muted">Uploading…</span>}
        </span>
        <Camera size={20} aria-hidden="true" />
      </label>
      <input
        id={id}
        className="sr-only"
        type="file"
        accept="image/*"
        capture="environment"
        disabled={disabled || busy}
        onChange={(e) => void pick(e.target.files?.[0])}
      />
      {error && (
        <span className="field-error" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}

export function DateChip({ iso }: { iso: string }) {
  return (
    <div className="date-chip" aria-hidden="true">
      <span>{dateText(iso, { weekday: "short" })}</span>
      <b>{Number(iso.slice(8, 10))}</b>
    </div>
  );
}

export function Section({ title, children, right }: { title: string; children: ReactNode; right?: ReactNode }) {
  return (
    <section className="stack" style={css(12)}>
      <div className="row between">
        <h2 className="h2">{title}</h2>
        {right}
      </div>
      {children}
    </section>
  );
}
