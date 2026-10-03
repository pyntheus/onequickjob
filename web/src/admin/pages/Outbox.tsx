/** Outbox: every message the product would have sent, searchable (the demo drawer shows only
 * the latest). Outside DEMO_MODE the API masks sign-in codes. Owned by L3. */
import { Search } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { useConfig } from "../../api/queries";
import { linkify } from "../../demo/links";
import { Chip } from "../../shared/Chip";
import { relativeTime, ukPhone } from "../../shared/format";
import { useOutboxPage, type OutboxItem, type OutboxQuery } from "../api";
import { AdminHeader, QueryState } from "../components";
import { gap } from "../util";

const CHANNELS: [OutboxQuery["channel"], string][] = [
  [undefined, "Everything"],
  ["sms", "Texts"],
  ["whatsapp", "WhatsApp"],
  ["email", "Emails"],
];
const CHANNEL_WORD: Record<OutboxItem["channel"], string> = { sms: "Text", whatsapp: "WhatsApp", email: "Email" };

function when(iso: string): string {
  return new Date(iso).toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Europe/London",
  });
}

function Row({ m, base }: { m: OutboxItem; base: string }) {
  const to = m.recipient.phone ? ukPhone(m.recipient.phone) : (m.recipient.email ?? "");
  return (
    <li className="a-msg">
      <div className="a-msg-meta">
        <span className="badge">{CHANNEL_WORD[m.channel]}</span>
        <span>
          To <b>{m.recipient.name || to}</b>
          {m.recipient.name && to ? `, ${to}` : ""}
        </span>
        <time dateTime={m.created_at} title={relativeTime(m.created_at)}>
          {when(m.created_at)}
        </time>
        <span className="ident">{m.template_id}</span>
      </div>
      <div className={"a-msg-body" + (m.channel === "email" ? " email" : "")}>
        {m.subject && <div className="subject">{m.subject}</div>}
        {linkify(m.body, base)}
      </div>
      {m.not_before && <span className="xs muted">Held for quiet hours until {when(m.not_before)}</span>}
    </li>
  );
}

export default function Outbox() {
  const searchId = useId();
  const { data: config } = useConfig();
  const [typed, setTyped] = useState("");
  const [q, setQ] = useState("");
  const [channel, setChannel] = useState<OutboxQuery["channel"]>(undefined);
  // The "before" cursor of each older page shown, for the search it was shown for.
  const [cursor, setCursor] = useState<{ key: string; pages: string[] }>({ key: "", pages: [] });
  useEffect(() => {
    const t = setTimeout(() => setQ(typed.trim()), 300);
    return () => clearTimeout(t);
  }, [typed]);
  const key = `${q}|${channel ?? ""}`;
  const pages = cursor.key === key ? cursor.pages : [];
  const setPages = (f: (p: string[]) => string[]) => setCursor({ key, pages: f(pages) });
  const before = pages.at(-1);
  const { data, isLoading, error, isFetching } = useOutboxPage({ q, channel, before });
  const base = config?.public_base_url ?? "";
  return (
    <>
      <AdminHeader title="Outbox" sub="Every text, WhatsApp and email the product would have sent. Nothing is really sent." />
      <div className="stack" style={gap("12px")}>
        <div className="field">
          <label className="label" htmlFor={searchId}>
            Search messages
          </label>
          <div className="input-icon">
            <Search size={18} aria-hidden="true" />
            <input
              id={searchId}
              className="input"
              type="search"
              placeholder="A name, number, email, words in the message, or a template like job_alert"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
            />
          </div>
        </div>
        <div className="chips">
          {CHANNELS.map(([v, l]) => (
            <Chip key={l} on={channel === v} onClick={() => setChannel(v)}>
              {l}
            </Chip>
          ))}
        </div>
      </div>
      <QueryState isLoading={isLoading} error={error}>
        <div className="card stack" style={gap("10px")} aria-busy={isFetching}>
          {data?.items.length === 0 ? (
            <p className="small muted">No messages match.</p>
          ) : (
            <ol className="a-msgs" aria-label="Messages, newest first">
              {data?.items.map((m) => (
                <Row key={m.id} m={m} base={base} />
              ))}
            </ol>
          )}
          <div className="row wrap" style={gap("8px")}>
            {pages.length > 0 && (
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setPages((p) => p.slice(0, -1))}>
                Newer messages
              </button>
            )}
            {data?.next_before && (
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setPages((p) => [...p, data.next_before as string])}>
                Older messages
              </button>
            )}
          </div>
        </div>
      </QueryState>
    </>
  );
}
