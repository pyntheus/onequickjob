/** A10: the provider's answer to a change of frequency lives in the provider app (L2), at
 * /p/plan-change/:token. Links in texts sent before it moved land here and go straight on. */
import { Navigate, useParams } from "react-router";

export default function PlanChangeMoved() {
  const { token = "" } = useParams();
  return <Navigate to={`/p/plan-change/${encodeURIComponent(token)}`} replace />;
}
