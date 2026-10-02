import { Gauge, Inbox, Layers, LayoutDashboard, Scale, Users, type LucideIcon } from "lucide-react";
import { NavLink, Outlet } from "react-router";
import { hasRole, useMe } from "../api/queries";
import { Loading, Notice } from "../app/Status";
import { Brand } from "../shared/Brand";
import { SignInForm } from "../shared/SignInForm";

const NAV: [string, string, LucideIcon, boolean][] = [
  ["/admin", "Overview", LayoutDashboard, true],
  ["/admin/providers", "Providers", Users, false],
  ["/admin/pricing", "Pricing", Gauge, false],
  ["/admin/disputes", "Disputes", Scale, false],
  ["/admin/categories", "Categories", Layers, false],
  ["/admin/outbox", "Outbox", Inbox, false],
];

function Guarded() {
  const { data: me, isLoading } = useMe();
  if (isLoading) return <Loading />;
  if (!me) return <SignInForm title="Sign in to OneQuickJob ops" />;
  if (!hasRole(me, "admin")) {
    return (
      <Notice title="This is for the OneQuickJob team only.">
        <p className="muted">You're signed in as {me.name || "someone"} without admin access.</p>
      </Notice>
    );
  }
  return <Outlet />;
}

/** Admin console: sidebar navigation and the main area. */
export function AdminLayout() {
  return (
    <div className="a-shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <nav className="a-side" aria-label="Admin">
        <div className="a-brand">
          <Brand to="/admin" small suffix="ops" />
        </div>
        {NAV.map(([to, label, I, end]) => (
          <NavLink key={to} to={to} end={end} className={({ isActive }) => "a-nav" + (isActive ? " on" : "")}>
            <I size={18} aria-hidden="true" /> {label}
          </NavLink>
        ))}
        <div className="a-side-foot">Manual dispatch mode. Providers are sent jobs by hand until Phase 2.</div>
      </nav>
      <main id="main" className="a-main" tabIndex={-1}>
        <Guarded />
      </main>
    </div>
  );
}

export default AdminLayout;
