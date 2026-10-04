import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type CSSProperties, type MutableRefObject } from "react";
import { Link, Outlet, useLocation, useNavigate, useSearchParams } from "react-router";
import { ApiError, api, call } from "../api/client";
import { hasRole, queryKeys, setSignedIn, useMe, type Me } from "../api/queries";
import { Loading, Notice } from "../app/Status";
import { Brand } from "../shared/Brand";
import { Button } from "../shared/Button";
import { SignInForm } from "../shared/SignInForm";
import "./install";
import { useHelperMode } from "./api";
import { HELPER_TABS, TABS, tabOf } from "./tabs";

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

/** Everything cached but the config and who's signed in: reset (data dropped, active queries
 * fetched again), so a refused refetch can't leave the last user's figures on screen. */
function forgetPrivate(qc: QueryClient) {
  const kept = new Set<unknown>([queryKeys.config[0], queryKeys.me[0]]);
  return qc.resetQueries({ predicate: (q) => !kept.has(q.queryKey[0]) });
}

/** Who the provider app last saw signed in: undefined until known, null when signed out. */
type LastUser = MutableRefObject<string | null | undefined>;

/** Whoever signs in or out (the sign-in form after a session ran out, switching user), the
 * provider app drops what it cached for the last user. Not on the first load. */
function useForgetOnUserChange(userId: string | null | undefined, lastRef: LastUser) {
  const qc = useQueryClient();
  useEffect(() => {
    if (userId === undefined) return;
    if (lastRef.current !== undefined && lastRef.current !== userId) void forgetPrivate(qc);
    lastRef.current = userId;
  }, [userId, lastRef, qc]);
}

/** Job-alert links carry ?t=<token>: sign in with it once, then drop it from the address bar. */
function useMagicLink(lastRef: LastUser): { pending: boolean; error: string | null } {
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
        const before = qc.getQueryData<Me>(queryKeys.me)?.user_id ?? null;
        await setSignedIn(qc, res.me);
        if (before === res.me.user_id) {
          await qc.invalidateQueries();
        } else {
          // Someone else: nothing cached for the last user may show, even if a refetch is refused.
          lastRef.current = res.me.user_id;
          await forgetPrivate(qc);
        }
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
  }, [token, params, location.pathname, navigate, qc, lastRef]);

  return { pending: !!token && done.token !== token, error: done.error };
}

/** Pages whose link carries its own single-use token as the authority: no sign-in needed. */
const TOKEN_PAGES = ["/p/plan-change/"];

function Body({ signup, open }: { signup: boolean; open: boolean }) {
  const lastUserRef = useRef<string | null | undefined>(undefined);
  const magic = useMagicLink(lastUserRef);
  const { data: me, isLoading } = useMe();
  useForgetOnUserChange(isLoading ? undefined : (me?.user_id ?? null), lastUserRef);
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
  const { helper, known } = useHelperMode();
  const signup = pathname.startsWith("/p/signup");
  const open = TOKEN_PAGES.some((prefix) => pathname.startsWith(prefix));
  const current = tabOf(pathname);
  const tabs = helper ? HELPER_TABS : TABS;
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
        {!signup && me && known && (
          <nav className="p-nav" aria-label="Provider">
            {tabs.map(({ id, label, icon: I, to }) => (
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
