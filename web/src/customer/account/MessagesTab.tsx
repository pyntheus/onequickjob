import { useQueryClient } from "@tanstack/react-query";
import { Send } from "lucide-react";
import { useEffect, useRef, useState, type CSSProperties } from "react";
import { api, call } from "../../api/client";
import { Avatar } from "../../shared/Avatar";
import { initialsOf } from "../../shared/format";
import { ck, errorText, useMessages, type ThreadSummary } from "../api";

const g = (px: number) => ({ "--g": `${px}px` }) as CSSProperties;

function Thread({ thread }: { thread: ThreadSummary }) {
  const qc = useQueryClient();
  const { data: messages = [], isLoading } = useMessages(thread.id);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);
  const first = thread.other_party.split(" ")[0];

  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "nearest" });
  }, [messages.length]);

  useEffect(() => {
    // Reading marks the thread read: refresh the unread counts.
    if (!isLoading) void qc.invalidateQueries({ queryKey: ck.threads });
  }, [isLoading, qc, thread.id]);

  const send = async () => {
    const body = draft.trim();
    if (!body) return;
    setBusy(true);
    setError(null);
    try {
      await call(api.POST("/api/c/threads/{thread_id}/messages", { params: { path: { thread_id: thread.id } }, body: { body } }));
      setDraft("");
      await qc.invalidateQueries({ queryKey: ck.messages(thread.id) });
      await qc.invalidateQueries({ queryKey: ck.threads });
    } catch (e) {
      setError(errorText(e, "Your message didn't send. Please try again."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card stack" style={g(10)}>
      <div className="row" style={{ ...g(10), paddingBottom: 6 }}>
        <Avatar initials={initialsOf(thread.other_party)} size={36} />
        <div className="stack" style={g(0)}>
          <b>{thread.other_party}</b>
          <span className="xs muted">{thread.title}</span>
        </div>
      </div>
      <div className="stack thread-msgs" style={g(8)} aria-live="polite">
        {messages.length === 0 && !isLoading && <p className="small muted">No messages yet. Say hello.</p>}
        {messages.map((m) =>
          m.sender_role === "system" ? (
            <p key={m.id} className="xs muted center">
              {m.body}
            </p>
          ) : (
            <div key={m.id} className={"bubble-row" + (m.mine ? " me" : "")}>
              <div className="msg">
                {!m.mine && <span className="sr-only">{m.sender_name}: </span>}
                {m.body}
              </div>
            </div>
          ),
        )}
        <div ref={end} />
      </div>
      <form
        className="row"
        style={{ ...g(8), paddingTop: 6 }}
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
      >
        <input
          className="input grow"
          value={draft}
          maxLength={1000}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={`Message ${first}`}
          aria-label={`Message ${first}`}
        />
        <button type="submit" className="btn btn-primary" aria-label="Send" disabled={busy || !draft.trim()}>
          <Send size={18} aria-hidden="true" />
        </button>
      </form>
      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
      <p className="xs muted">Messages stay in OneQuickJob, so there's a record if anything needs sorting out.</p>
    </div>
  );
}

export function MessagesTab({
  threads,
  selected,
  onSelect,
}: {
  threads: ThreadSummary[];
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  if (!threads.length) {
    return (
      <div className="card stack" style={g(8)}>
        <h2 className="h3">No messages yet</h2>
        <p className="small muted">Once you're booked, you can message your provider here.</p>
      </div>
    );
  }
  const current = threads.find((t) => t.id === selected) ?? threads[0];
  return (
    <div className="stack" style={g(14)}>
      {threads.length > 1 && (
        <div className="card flat" style={{ padding: "4px 18px" }}>
          {threads.map((t) => (
            <button
              key={t.id}
              type="button"
              className={"link-row thread-row" + (t.id === current.id ? " on" : "")}
              aria-current={t.id === current.id ? "true" : undefined}
              onClick={() => onSelect(t.id)}
            >
              <span className="grow stack" style={g(0)}>
                <b>{t.title}</b>
                <span className="xs muted">{t.preview || "No messages yet"}</span>
              </span>
              {t.unread > 0 && <span className="badge accent">{t.unread} new</span>}
            </button>
          ))}
        </div>
      )}
      <Thread key={current.id} thread={current} />
    </div>
  );
}
