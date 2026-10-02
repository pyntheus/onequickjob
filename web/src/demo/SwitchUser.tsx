import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronUp, UserRound } from "lucide-react";
import { Fragment, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { api, call, type Schemas } from "../api/client";
import { queryKeys, useConfig, useMe } from "../api/queries";

type DemoUser = Schemas["DemoUser"];
const GROUPS: DemoUser["group"][] = ["Customers", "Providers", "Helpers", "Admins"];

/** DEMO_MODE only: jump between seeded users without codes. */
export function SwitchUser() {
  const { data: config } = useConfig();
  const enabled = !!config?.demo_mode;
  const { data: me } = useMe();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);

  const { data: users = [] } = useQuery({
    queryKey: queryKeys.demoUsers,
    queryFn: () => call(api.GET("/api/demo/users")),
    enabled: enabled && open,
    staleTime: 60_000,
  });

  useEffect(() => {
    if (!open) return undefined;
    wrap.current?.querySelector<HTMLButtonElement>(".demo-menu button")?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        trigger.current?.focus();
      }
    };
    const onClick = (e: MouseEvent) => {
      if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onClick);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onClick);
    };
  }, [open, users.length]);

  if (!enabled) return null;

  const become = async (u: DemoUser) => {
    setBusy(true);
    try {
      await call(api.POST("/api/demo/switch", { body: { user_id: u.user_id } }));
      setOpen(false);
      await qc.resetQueries();
      navigate(u.home_path);
    } finally {
      setBusy(false);
    }
  };

  const signOut = async () => {
    setBusy(true);
    try {
      await call(api.POST("/api/auth/logout"));
      setOpen(false);
      await qc.resetQueries();
      navigate("/");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div ref={wrap} style={{ position: "relative" }}>
      <button
        ref={trigger}
        type="button"
        className="demo-fab"
        aria-haspopup="true"
        aria-label={me ? `Switch user, signed in as ${me.name || "someone"}` : "Switch user"}
        aria-expanded={open}
        aria-controls="switch-user-menu"
        onClick={() => setOpen((v) => !v)}
      >
        <UserRound size={17} aria-hidden="true" /> {me ? me.name || "Signed in" : "Switch user"}
        <ChevronUp size={15} aria-hidden="true" />
      </button>
      {open && (
        <div id="switch-user-menu" className="demo-menu" role="group" aria-label="Switch user">
          {users.length === 0 && <p className="small muted" style={{ padding: 10 }}>Loading people…</p>}
          {GROUPS.map((g) => {
            const list = users.filter((u) => u.group === g);
            if (!list.length) return null;
            return (
              <Fragment key={g}>
                <h2>{g}</h2>
                {list.map((u) => (
                  <button key={u.user_id} type="button" disabled={busy} aria-current={me?.user_id === u.user_id ? "true" : undefined} onClick={() => become(u)}>
                    <span className="who">
                      {u.name}
                      {me?.user_id === u.user_id ? " (you)" : ""}
                    </span>
                    <span className="what">{u.description}</span>
                  </button>
                ))}
              </Fragment>
            );
          })}
          {me && (
            <>
              <h2>Signed in as {me.name || "you"}</h2>
              <button type="button" disabled={busy} onClick={signOut}>
                <span className="who">Sign out</span>
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
