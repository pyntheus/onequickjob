import type { CSSProperties, ReactNode } from "react";
import { Button } from "../../shared/Button";
import { Loading, Notice } from "../../app/Status";

/** Loading and "start again" states shared by the quote flow's screens. */
export function FlowGuard({
  loading,
  unknown,
  needsAddress,
  children,
}: {
  loading: boolean;
  unknown: boolean;
  needsAddress: boolean;
  children: ReactNode;
}) {
  if (loading) return <Loading />;
  if (unknown) {
    return (
      <div className="c-flow">
        <Notice title="We don't know that kind of job">
          <Button to="/" variant="primary">
            See the jobs we do
          </Button>
        </Notice>
      </div>
    );
  }
  if (needsAddress) {
    return (
      <div className="c-flow">
        <Notice title="Start with your address">
          <p className="muted">We need to know where the job is to work out a guide price.</p>
          <div className="row" style={{ "--g": "10px" } as CSSProperties}>
            <Button to="/" variant="primary">
              Add my address
            </Button>
          </div>
        </Notice>
      </div>
    );
  }
  return <>{children}</>;
}
