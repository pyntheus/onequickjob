import { User } from "lucide-react";
import type { CSSProperties } from "react";
import { Link, Outlet } from "react-router";
import { Brand } from "../shared/Brand";
import { FlowProvider } from "./FlowProvider";

/** The customer header from the prototype; every customer screen renders in <main>. */
export function CustomerLayout() {
  return (
    <FlowProvider>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="c-header">
        <Brand />
        <nav className="row" style={{ "--g": "16px" } as CSSProperties} aria-label="Account">
          <Link className="btn btn-link hide-sm" to="/p/signup">
            Earn with OneQuickJob
          </Link>
          <Link className="btn btn-ghost btn-sm" to="/account">
            <User size={16} aria-hidden="true" /> My account
          </Link>
        </nav>
      </header>
      <main id="main" tabIndex={-1}>
        <Outlet />
      </main>
    </FlowProvider>
  );
}

export default CustomerLayout;
