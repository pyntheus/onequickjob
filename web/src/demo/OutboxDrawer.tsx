import { useQuery } from "@tanstack/react-query";
import { Copy, Inbox, X } from "lucide-react";
import { useEffect, useRef, useState, type CSSProperties } from "react";
import { api, call, type Schemas } from "../api/client";
import { queryKeys, useConfig } from "../api/queries";
import { relativeTime, ukPhone } from "../shared/format";
import { linkify } from "./links";

type Item = Schemas["OutboxItem"];

const CHANNEL: Record<Item["channel"], string> = { sms: "Text", whatsapp: "WhatsApp", email: "Email" };
const SEEN_KEY = "oqj.outbox.seenAt";

function readSeen(): number {
  try {
    const v = sessionStorage.getItem(SEEN_KEY);
    return v ? Number(v) : Date.now();
  } catch {
    return Date.now();
  }
}

function writeSeen(t: number) {
  try {
    sessionStorage.setItem(SEEN_KEY, String(t));
  } catch {
    // Storage can be blocked; the count just resets on reload.
  }
}

function CodeBox({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };
  return (
    <div className="code-box">
      <span className="code-digits" aria-label={`Sign-in code ${code.split("").join(" ")}`}>
        {code}
      </span>
      <button type="button" className="btn btn-ghost btn-sm" onClick={copy}>
        <Copy size={15} aria-hidden="true" /> {copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}

function Message({ m, base, onNavigate }: { m: Item; base: string; onNavigate: () => void }) {
  const to = m.recipient.phone ? ukPhone(m.recipient.phone) : m.recipient.email ?? "";
  const code = m.template_id === "login_code" ? /\b(\d{6})\b/.exec(m.body)?.[1] : undefined;
  return (
    <li className="outbox-item">
      <div className="outbox-meta">
        <span className="badge">{CHANNEL[m.channel]}</span>
        <span>
          To <b>{m.recipient.name || to}</b>
          {m.recipient.name && to ? `, ${to}` : ""}
        </span>
        <time dateTime={m.created_at}>{relativeTime(m.created_at)}</time>
        <span className="ident">{m.template_id}</span>
      </div>
      {code && <CodeBox code={code} />}
      {m.channel === "email" ? (
        <div className="email-card">
          {m.subject && <div className="subject">{m.subject}</div>}
          {linkify(m.body, base, onNavigate)}
        </div>
      ) : (
        <div className={"sms-bubble" + (m.channel === "whatsapp" ? " whatsapp" : "")}>{linkify(m.body, base, onNavigate)}</div>
      )}
      {m.not_before && <span className="xs muted">Held for quiet hours until {relativeTime(m.not_before)}</span>}
    </li>
  );
}

/**
 * DEMO_MODE only. Every message the product "sends" lands in the outbox; this drawer shows
 * the latest, including login codes and job alerts (the prototype's text-message screen).
 */
export function OutboxDrawer() {
  const { data: config } = useConfig();
  const enabled = !!config?.demo_mode;
  const [open, setOpen] = useState(false);
  const [seenAt, setSeenAt] = useState(readSeen);
  const fab = useRef<HTMLButtonElement>(null);
  const closeBtn = useRef<HTMLButtonElement>(null);
  const wasOpen = useRef(false);

  const { data: items = [] } = useQuery({
    queryKey: queryKeys.demoOutbox,
    queryFn: () => call(api.GET("/api/demo/outbox", { params: { query: { limit: 30 } } })),
    enabled,
    refetchInterval: open ? 3000 : 15000,
  });

  useEffect(() => {
    if (open) {
      closeBtn.current?.focus();
    } else if (wasOpen.current) {
      fab.current?.focus();
    }
    wasOpen.current = open;
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  if (!enabled) return null;
  const unread = open ? 0 : items.filter((m) => new Date(m.created_at).getTime() > seenAt).length;

  return (
    <>
      <button
        ref={fab}
        type="button"
        className="demo-fab"
        aria-expanded={open}
        aria-controls="outbox-panel"
        onClick={() => {
          if (!open) {
            const now = Date.now();
            setSeenAt(now);
            writeSeen(now);
          }
          setOpen(!open);
        }}
      >
        <Inbox size={17} aria-hidden="true" /> Outbox
        {unread > 0 && (
          <span className="count" aria-label={`${unread} new`}>
            {unread}
          </span>
        )}
      </button>
      {open && (
        <aside id="outbox-panel" className="outbox-panel" role="dialog" aria-modal="false" aria-labelledby="outbox-title">
          <div className="outbox-head">
            <div className="stack" style={{ "--g": "0px" } as CSSProperties}>
              <h2 id="outbox-title" className="h3">
                Outbox
              </h2>
              <span className="xs muted">Nothing is really sent. Texts, WhatsApps and emails land here.</span>
            </div>
            <button ref={closeBtn} type="button" className="icon-btn" aria-label="Close the outbox" onClick={() => setOpen(false)}>
              <X size={20} aria-hidden="true" />
            </button>
          </div>
          {items.length === 0 ? (
            <p className="small muted" style={{ padding: 16 }}>
              No messages yet. Ask for a sign-in code to see one arrive.
            </p>
          ) : (
            <ol className="outbox-list" aria-label="Latest messages, newest first" style={{ listStyle: "none", margin: 0 }}>
              {items.map((m) => (
                <Message key={m.id} m={m} base={config.public_base_url} onNavigate={() => setOpen(false)} />
              ))}
            </ol>
          )}
        </aside>
      )}
    </>
  );
}
