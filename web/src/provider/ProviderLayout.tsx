import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type CSSProperties } from "react";
import { Link, Outlet, useLocation, useNavigate, useSearchParams } from "react-router";
import { ApiError, api, call } from "../api/client";
import { hasRole, queryKeys, useMe } from "../api/queries";
import { Loading, Notice } from "../app/Status";
import { Brand } from "../shared/Brand";
import { Button } from "../shared/Button";
import { SignInForm } from "../shared/SignInForm";
import "./install";
import { useHelperMode } from "./api";
import { TABS, tabOf } from "./tabs";

/** The service worker caches the app shell only (public/p/sw.js), in built apps: never in the
 * Vite dev server, where it would fight hot reloading. */
function useServiceWorker() {
  useEffect(() => {
    if (import.meta.env.PROD && "serviceWorker" in navigator) {
      navigator.serviceWorker.register("/p/sw.js", { scope: "/p/" }).catch(() => undefined);
    }
  }, []);
}

/** Adds the PWA manifest and theme colour only while the provider app is open. */
function useProviderManifest() {
  useEffect(() => {
    const link = document.createElement("link");
    link.rel = "manifest";
    link.href = "/p/manifest.webmanifest";
    const theme = document.createElement("meta");
    theme.name = "theme-color";
    theme.content = "#1E4B38";
    const apple = document.createElement("link");
    apple.rel = "apple-touch-icon";
    apple.href = "/p/icon-192.png";
    document.head.append(link, theme, apple);
    return () => {
      link.remove();
      theme.remove();
      apple.remove();
    };
  }, []);
}

/** Job-alert links carry ?t=<token>: sign in with it once, then drop it from the address bar. */
function useMagicLink(): { pending: boolean; error: string | null } {
  const [params] = useSearchParams();
  const token = params.get("t");
  const location = useLocation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const inFlight = useRef<string | null>(null);
  const [done, setDone] = useState<{ token: string | null; error: string | null }>({ token: null, error: null });

  useEffect(() => {
    if (!token || inFlight.current === token) return;
    inFlight.current = token;
    call(api.POST("/api/auth/magic", { body: { token } }))
      .then(async (res) => {
        qc.setQueryData(queryKeys.me, res.me);
        await qc.invalidateQueries();
        setDone({ token, error: null });
      })
      .catch((e: unknown) => {
        setDone({ token, error: e instanceof ApiError ? e.message : "That link didn't work. Sign in with a code." });
      })
      .finally(() => {
        const rest = new URLSearchParams(params);
        rest.delete("t");
        const q = rest.toString();
        navigate({ pathname: location.pathname, search: q ? `?${q}` : "" }, { replace: true });
      });
  }, [token, params, location.pathname, navigate, qc]);

  return { pending: !!token && done.token !== token, error: done.error };
}

/** Pages whose link carries its own single-use token as the authority: no sign-in needed. */
const TOKEN_PAGES = ["/p/plan-change/"];

function Body({ signup, open }: { signup: boolean; open: boolean }) {
  const magic = useMagicLink();
  const { data: me, isLoading } = useMe();
  const { helper, known } = useHelperMode();
  if (open) return <Outlet />;
  if (magic.pending || isLoading) return <Loading label={magic.pending ? "Signing you in…" : "Loading…"} />;
  if (!me) {
    return (
      <div className="stack" style={{ "--g": "14px" } as CSSProperties}>
        {magic.error && (
          <p className="soft small" role="alert">
            {magic.error}
          </p>
        )}
        <SignInForm
          title={signup ? "Earn with OneQuickJob" : "Sign in"}
          intro={signup ? "First, confirm your mobile number. We'll text you a code." : "We'll text you a code. No password to remember."}
        />
      </div>
    );
  }
  if (!signup && !hasRole(me, "provider") && !me.helper_of && !known) return <Loading />;
  if (!signup && !hasRole(me, "provider") && !me.helper_of && !helper) {
    return (
      <Notice title="This is for providers">
        <p className="muted">Want to take local jobs? Signing up takes about 10 minutes.</p>
        <Button to="/p/signup" variant="cta" size="lg" block>
          Earn with OneQuickJob
        </Button>
      </Notice>
    );
  }
  return <Outlet />;
}

/** Phone-width provider app: top bar, the screen, and the bottom nav (not on sign-up). */
export function ProviderLayout() {
  useProviderManifest();
  useServiceWorker();
  const { pathname } = useLocation();
  const { data: me } = useMe();
  const signup = pathname.startsWith("/p/signup");
  const open = TOKEN_PAGES.some((prefix) => pathname.startsWith(prefix));
  const current = tabOf(pathname);
  return (
    <div className="p-app">
      <div className="p-col">
        <a className="skip-link" href="#main">
          Skip to content
        </a>
        <header className="p-top">
          <Brand to="/p" small />
          <span className="xs muted">{signup ? "Sign up" : me?.name || ""}</span>
        </header>
        <main id="main" className="p-body" tabIndex={-1}>
          <Body signup={signup} open={open} />
        </main>
        {!signup && me && (
          <nav className="p-nav" aria-label="Provider">
            {TABS.map(({ id, label, icon: I, to }) => (
              <Link key={id} to={to} className={current === id ? "on" : ""} aria-current={current === id ? "page" : undefined}>
                <I size={22} strokeWidth={current === id ? 2.5 : 2} aria-hidden="true" />
                {label}
              </Link>
            ))}
          </nav>
        )}
      </div>
    </div>
  );
}

export default ProviderLayout;
