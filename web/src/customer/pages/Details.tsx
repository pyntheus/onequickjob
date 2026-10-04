import { useId, type CSSProperties } from "react";
import { FlowTop } from "../../shared/FlowTop";
import { useToast } from "../../shared/toast-context";
import { FlowGuard } from "../components/FlowGuard";
import { IntakeField } from "../components/IntakeField";
import { answersFor, emptyCounts, lawnFilled } from "../flow";
import { useQuoteStep } from "../useQuoteStep";

/** "A few quick questions": every question comes from the category's intake schema. */
export default function Details() {
  const step = useQuoteStep("details");
  const { flow, update, cat, steps, go, back, photos, setPhotos } = step;
  const notify = useToast();
  const notesId = useId();
  const needsLawn = !!cat?.measure && !lawnFilled(flow.lawn);

  return (
    <FlowGuard loading={step.loading} unknown={step.unknown} needsAddress={!flow.address}>
      {cat && (() => {
        const answers = answersFor(cat, flow);
        const empty = emptyCounts(cat, answers);
        const cid = cat.id ?? "";
        const setAnswer = (key: string, value: unknown) =>
          update((f) => ({ answers: { ...f.answers, [cid]: { ...(f.answers[cid] ?? {}), [key]: value } }, quoteId: null }));
        return (
          <div className="c-flow">
            <FlowTop steps={steps} current="details" onBack={back} />
            <div className="stack" style={{ "--g": "8px" } as CSSProperties}>
              <span className="kicker">{cat.name}</span>
              <h1 className="h1">A few quick questions</h1>
              <p className="muted">So the price reflects the real job, and nobody turns up surprised.</p>
            </div>
            {cat.intake.map((f) => (
              <IntakeField
                key={f.key}
                field={f}
                value={answers[f.key]}
                onChange={(v) => setAnswer(f.key, v)}
                files={photos[`${cid}.${f.key}`] ?? []}
                onFiles={(files) => setPhotos(`${cid}.${f.key}`, files)}
              />
            ))}
            <div className="field">
              <label className="label" htmlFor={notesId}>
                Anything else they should know?{" "}
                <span className="muted" style={{ fontWeight: 400 }}>
                  (optional)
                </span>
              </label>
              <textarea
                id={notesId}
                className="input"
                value={flow.notes}
                maxLength={1000}
                onChange={(e) => update({ notes: e.target.value })}
                placeholder={
                  cat.group === "outside"
                    ? "For example: the side gate sticks, so please close it behind you."
                    : "For example: parking is on the drive, and the cat mustn't get out."
                }
              />
            </div>
            <button
              type="button"
              className="btn btn-cta btn-lg btn-block"
              disabled={empty}
              onClick={() => {
                if (needsLawn) {
                  notify("Tell us how big your lawn is first.");
                  go("size");
                } else go("price");
              }}
            >
              See my price
            </button>
            {empty && (
              <p className="small center" style={{ color: "var(--danger)" }}>
                Add at least one item to see a price.
              </p>
            )}
          </div>
        );
      })()}
    </FlowGuard>
  );
}
