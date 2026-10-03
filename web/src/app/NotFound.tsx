import type { CSSProperties } from "react";
import { Brand } from "../shared/Brand";
import { Button } from "../shared/Button";

export default function NotFound() {
  return (
    <>
      <header className="c-header">
        <Brand />
      </header>
      <main id="main" className="c-flow">
        <div className="card stack" style={{ "--g": "12px" } as CSSProperties}>
          <h1 className="h2">We can't find that page</h1>
          <p className="muted">The link may be old, or the page may have moved.</p>
          <Button to="/" variant="primary">
            Go to the home page
          </Button>
        </div>
      </main>
    </>
  );
}
