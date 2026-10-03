/** Documents with their status and expiry, and the upload that sends a new one for checks.
 * The expiry shown after an upload comes from the API's shared rule (decisions.md A3: a basic
 * DBS check runs 12 months from its issue date), never from sums in the browser. */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BadgeCheck, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { api, call } from "../api/client";
import { Badge, type BadgeTone } from "../shared/Badge";
import { Button } from "../shared/Button";
import { TextField } from "../shared/Field";
import { pKeys, type DocumentOut } from "./api";
import { ErrorNote, UploadButton } from "./components";
import { css, dateText, londonToday } from "./util";

const STATUS: Record<DocumentOut["status"], [string, BadgeTone]> = {
  verified: ["Checked", "ok"],
  pending: ["Being checked", "warn"],
  rejected: ["Not accepted", "danger"],
  expired: ["Run out", "danger"],
  missing: ["Needed", "warn"],
};

function longDate(iso: string): string {
  return dateText(iso, { day: "numeric", month: "long", year: "numeric" });
}

function detail(d: DocumentOut): string {
  if (d.renewal) {
    const until = d.renewal.expires_on ? `, valid to ${longDate(d.renewal.expires_on)}` : "";
    return `Your new copy is being checked${until}. Your current one counts until then.`;
  }
  if (d.status === "verified" && d.expires_on) {
    if (d.expiring_soon) return `Runs out on ${longDate(d.expires_on)}. Upload the new one so you can keep taking these jobs.`;
    return `Checked until ${longDate(d.expires_on)}. We'll remind you a month before.`;
  }
  if (d.status === "pending")
    return d.expires_on ? `We're checking it. Valid to ${longDate(d.expires_on)}.` : "We're checking it. It usually takes a day.";
  if (d.status === "expired" && d.expires_on) return `Ran out on ${longDate(d.expires_on)}. Upload the new one.`;
  if (d.status === "rejected") return d.note ?? "We couldn't accept it. Please upload it again.";
  if (d.status === "missing")
    return d.required_for.length ? `Needed for ${d.required_for.join(", ").toLowerCase()}.` : "Needed before you can take jobs.";
  return d.note ?? "";
}

function needsUpload(d: DocumentOut): boolean {
  if (d.renewal) return false;
  return d.status !== "pending" && (d.status !== "verified" || d.expiring_soon);
}

export function DocUpload({ doc, onDone }: { doc: DocumentOut; onDone?: (d: DocumentOut) => void }) {
  const qc = useQueryClient();
  const [date, setDate] = useState("");
  const [result, setResult] = useState<DocumentOut | null>(null);
  const attach = useMutation({
    mutationFn: (fileId: string) =>
      call(
        api.POST("/api/p/documents", {
          body: {
            type: doc.type,
            file_id: fileId,
            issued_on: doc.needs_issue_date ? date : null,
            expires_on: doc.needs_expiry_date ? date : null,
          },
        }),
      ),
    onSuccess: (d) => {
      setResult(d);
      void qc.invalidateQueries({ queryKey: pKeys.all });
      onDone?.(d);
    },
  });
  const needsDate = doc.needs_issue_date || doc.needs_expiry_date;
  if (result) {
    const until = result.renewal?.expires_on ?? result.expires_on;
    return (
      <p className="small soft note-ok" role="status">
        Thanks, we've got it and we'll check it soon.
        {until && (
          <>
            {" "}
            It's valid to <b>{longDate(until)}</b>
            {doc.needs_issue_date ? " (12 months from the issue date)" : ""}.
          </>
        )}
      </p>
    );
  }
  return (
    <div className="stack" style={css(10)}>
      {needsDate && (
        <TextField
          label={doc.needs_issue_date ? "Date of issue (on the certificate)" : "Runs out on"}
          type="date"
          value={date}
          max={doc.needs_issue_date ? londonToday() : undefined}
          min={doc.needs_expiry_date ? londonToday() : undefined}
          onChange={(e) => setDate(e.target.value)}
          hint={doc.needs_issue_date ? "A basic DBS check counts for 12 months from this date." : undefined}
        />
      )}
      <UploadButton
        kind="document"
        accept="image/*,application/pdf"
        label={`Photograph or upload your ${doc.label.toLowerCase()}`}
        disabled={needsDate && !date}
        onUploaded={(id) => attach.mutateAsync(id).then(() => undefined)}
      />
      <ErrorNote error={attach.error} />
    </div>
  );
}

export function DocRow({ doc }: { doc: DocumentOut }) {
  const [open, setOpen] = useState(false);
  const [label, tone] = STATUS[doc.status];
  const Icon = doc.type === "identity" ? BadgeCheck : ShieldCheck;
  return (
    <div className="doc-row stack-mobile">
      <div className="row top" style={{ ...css(12), width: "100%" }}>
        <span className="cat-ico sm" aria-hidden="true">
          <Icon size={17} />
        </span>
        <div className="grow stack" style={css(2)}>
          <b>{doc.label}</b>
          <span className="xs muted">{detail(doc)}</span>
        </div>
        <Badge tone={doc.expiring_soon ? "warn" : tone}>{doc.expiring_soon ? "Runs out soon" : label}</Badge>
      </div>
      {needsUpload(doc) &&
        (open ? (
          <div className="doc-upload">
            <DocUpload doc={doc} />
          </div>
        ) : (
          <Button variant="link" onClick={() => setOpen(true)}>
            {doc.status === "missing" ? "Add it" : "Upload the new one"}
          </Button>
        ))}
    </div>
  );
}
