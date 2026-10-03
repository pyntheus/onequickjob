/** Finish a job: minutes taken (from the timer), what was different, a note; then the visit is
 * charged and the provider sees what's on its way. Owned by L2. Lifted from the prototype's
 * FinishScreen. The recorded times and flags are how guide prices get fixed. */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Info } from "lucide-react";
import { useState } from "react";
import { useLocation, useParams } from "react-router";
import { api, call } from "../../api/client";
import { Loading } from "../../app/Status";
import { Button } from "../../shared/Button";
import { Chip } from "../../shared/Chip";
import { fmt } from "../../shared/format";
import { Stepper } from "../../shared/Stepper";
import { pKeys, useHelperMode, useVisit, type FinishOut, type ProviderVisit } from "../api";
import { BackLink, ErrorNote } from "../components";
import { css } from "../util";

const NONE = "Nothing, it was as described";
const OUTSIDE = ["The job was bigger than described", "Access was harder", "More waste than expected", "Weather slowed me down"];
const FLAGS: Record<string, string[]> = {
  mowing: ["Grass was longer than described", "Access was harder", "More waste than expected", "Weather slowed me down"],
  hedges: ["Hedge was bigger than described", "Access was harder", "More waste than expected", "Weather slowed me down"],
  clearance: ["More waste than described", "Access was harder", "Extra trips to the tip"],
  jetwash: OUTSIDE,
  gutters: ["Gutters were fuller than expected", "Access was harder", "Weather slowed me down"],
  windows: OUTSIDE,
  dogwalking: ["The walk took longer", "Getting in took longer"],
  techhelp: ["It took longer than described"],
};
const INSIDE = ["The job was bigger than described", "Access was harder", "Needed extra materials"];

function Done({ out, helper }: { out: FinishOut; helper: boolean }) {
  const paid = out.charge_status === "succeeded";
  return (
    <div className="stack center" style={{ ...css(14), alignItems: "center", paddingTop: 36 }}>
      <span className="success-mark" aria-hidden="true">
        <Check size={32} strokeWidth={3} />
      </span>
      <h1 className="h1">
        {paid ? (helper ? "Done, thank you" : `${fmt(out.provider_pence)} is on its way`) : "Job recorded"}
      </h1>
      <p className="muted" role="status">
        {out.charge_message}
      </p>
      <Button to={helper ? "/p/today" : "/p"} variant="primary" size="lg" block>
        {helper ? "Back to today" : "Back to jobs"}
      </Button>
    </div>
  );
}

function FinishForm({ v, timerMinutes, onDone }: { v: ProviderVisit; timerMinutes: number | null; onDone: (o: FinishOut) => void }) {
  const qc = useQueryClient();
  const fromTimer = timerMinutes !== null && timerMinutes >= 1;
  const start = fromTimer ? timerMinutes : v.est_mins;
  const [mins, setMins] = useState(Math.min(720, Math.max(1, start)));
  const [flags, setFlags] = useState<string[]>([]);
  const [note, setNote] = useState("");
  const options = [...(FLAGS[v.category_id] ?? INSIDE), NONE];
  const toggle = (f: string) =>
    setFlags((x) => {
      if (f === NONE) return x.includes(NONE) ? [] : [NONE];
      const y = x.filter((z) => z !== NONE);
      return y.includes(f) ? y.filter((z) => z !== f) : [...y, f];
    });
  const finish = useMutation({
    mutationFn: () =>
      call(
        api.POST("/api/p/visits/{visit_id}/finish", {
          params: { path: { visit_id: v.id } },
          body: {
            minutes: mins,
            from_timer: fromTimer && mins === start,
            flags: flags.filter((f) => f !== NONE),
            nothing_different: flags.includes(NONE),
            note: note.trim(),
          },
        }),
      ),
    onSuccess: (out) => {
      void qc.invalidateQueries({ queryKey: pKeys.all });
      onDone(out);
    },
  });
  const diff = mins - v.est_mins;
  return (
    <>
      <BackLink to="/p/today">Today</BackLink>
      <h1 className="h1">Nice work. How did it go?</h1>
      <div className="card stack" style={css(12)}>
        <span className="label" id="mins-label">
          How long did it take?
        </span>
        <Stepper value={mins} onChange={setMins} min={1} max={720} step={5} label="Minutes taken" format={(x) => `${x} min`} />
        <span className="small muted">
          {fromTimer && mins === start ? "From your timer. " : ""}The estimate was {v.est_mins} minutes
          {diff === 0 ? ", spot on." : `, so ${Math.abs(diff)} minutes ${diff > 0 ? "over" : "under"}.`}
        </span>
      </div>
      <div className="stack" style={css(10)}>
        <span className="label">Was anything different from the description?</span>
        <div className="chips">
          {options.map((f) => (
            <Chip key={f} on={flags.includes(f)} onClick={() => toggle(f)}>
              {f}
            </Chip>
          ))}
        </div>
      </div>
      <label className="field">
        <span className="label">
          Anything else?{" "}
          <span className="muted" style={{ fontWeight: 400 }}>
            (optional)
          </span>
        </span>
        <textarea
          className="input"
          value={note}
          maxLength={1000}
          onChange={(e) => setNote(e.target.value)}
          placeholder="For example: there's a second lawn behind the shed that isn't on the plan."
        />
      </label>
      <div className="soft small row top" style={css(10)}>
        <Info size={18} aria-hidden="true" style={{ flex: "none", marginTop: 2 }} />
        <span>
          <b>Why we ask:</b> your real times are how guide prices get fixed. If jobs like this keep taking longer than we
          estimate, the guide price goes up.
        </span>
      </div>
      <ErrorNote error={finish.error} />
      <Button variant="cta" size="lg" block disabled={finish.isPending} onClick={() => finish.mutate()}>
        {finish.isPending ? "Sending…" : "Send and get paid"}
      </Button>
    </>
  );
}

export default function Finish() {
  const { visitId } = useParams();
  const location = useLocation();
  const { helper } = useHelperMode();
  const { data: v, isLoading, error } = useVisit(visitId);
  const [done, setDone] = useState<FinishOut | null>(null);
  const state = location.state as { minutes?: number } | null;
  if (done) return <Done out={done} helper={helper} />;
  if (isLoading) return <Loading />;
  if (error || !v) return <ErrorNote error={error ?? new Error()} />;
  if (v.status === "finished") {
    return (
      <>
        <BackLink to="/p/today">Today</BackLink>
        <h1 className="h1">Already finished</h1>
        <p className="muted">
          Done in {v.minutes_actual} minutes. Payment: {v.charge_status === "succeeded" ? "taken" : v.charge_status.replace("_", " ")}.
        </p>
      </>
    );
  }
  if (v.status !== "in_progress") {
    return (
      <>
        <BackLink to="/p/today">Today</BackLink>
        <h1 className="h1">Start the job first</h1>
        <p className="muted">Open it on Today and tap “I've arrived” when you get there.</p>
      </>
    );
  }
  const timer = state?.minutes ?? (v.elapsed_seconds !== null ? Math.round(v.elapsed_seconds / 60) : null);
  return <FinishForm v={v} timerMinutes={timer} onDone={setDone} />;
}
