/** Messages with customers: the list of conversations, and one conversation. Owned by L2. The
 * prototype's "Message" button on the round opens a conversation here. */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router";
import { api, call } from "../../api/client";
import { Loading } from "../../app/Status";
import { Button } from "../../shared/Button";
import { relativeTime, timeText } from "../../shared/format";
import { pKeys, useMessages, useThreads } from "../api";
import { BackLink, ErrorNote } from "../components";
import { css } from "../util";

function Conversation({ id }: { id: string }) {
  const qc = useQueryClient();
  const { data: threads } = useThreads();
  const { data: msgs, isLoading, error } = useMessages(id);
  const [body, setBody] = useState("");
  const thread = threads?.find((t) => t.id === id);
  const send = useMutation({
    mutationFn: () => call(api.POST("/api/p/threads/{thread_id}/messages", { params: { path: { thread_id: id } }, body: { body: body.trim() } })),
    onSuccess: () => {
      setBody("");
      void qc.invalidateQueries({ queryKey: pKeys.messages(id) });
      void qc.invalidateQueries({ queryKey: pKeys.threads });
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (body.trim()) send.mutate();
  };
  return (
    <>
      <BackLink to="/p/messages">Messages</BackLink>
      <h1 className="h2">{thread?.title ?? "Messages"}</h1>
      {isLoading && <Loading />}
      {error && <ErrorNote error={error} />}
      <ol className="thread" aria-label="Messages">
        {msgs?.length === 0 && <li className="muted small">No messages yet.</li>}
        {msgs?.map((m) => (
          <li key={m.id} className={"bubble" + (m.mine ? " mine" : "")}>
            <span className="xs muted">
              {m.mine ? "You" : m.sender_name}, {relativeTime(m.created_at)} ({timeText(m.created_at)})
            </span>
            <span>{m.body}</span>
          </li>
        ))}
      </ol>
      <form className="stack" style={css(10)} onSubmit={submit}>
        <label className="field">
          <span className="label">Your message</span>
          <textarea className="input" value={body} maxLength={1000} onChange={(e) => setBody(e.target.value)} />
        </label>
        <ErrorNote error={send.error} />
        <Button type="submit" variant="primary" size="lg" block disabled={!body.trim() || send.isPending}>
          Send
        </Button>
        <p className="xs muted">They get a text to say you've written. Please keep arrangements for the job here.</p>
      </form>
    </>
  );
}

export default function Messages() {
  const { threadId } = useParams();
  const { data: threads, isLoading, error } = useThreads(!threadId);
  if (threadId) return <Conversation id={threadId} />;
  return (
    <>
      <BackLink to="/p/me">Me</BackLink>
      <h1 className="h1">Messages</h1>
      {isLoading && <Loading />}
      {error && <ErrorNote error={error} />}
      {threads?.length === 0 && <p className="muted">No conversations yet. They start when a job is booked.</p>}
      {threads && threads.length > 0 && (
        <div className="card flat" style={{ padding: "4px 16px" }}>
          {threads.map((t) => (
            <Link key={t.id} to={`/p/messages/${t.id}`} className="list-row link-plain">
              <div className="grow stack" style={css(0)}>
                <b>{t.title}</b>
                <span className="xs muted">{t.preview || "No messages yet"}</span>
              </div>
              {t.unread > 0 && <span className="badge accent">{t.unread} new</span>}
            </Link>
          ))}
        </div>
      )}
    </>
  );
}
