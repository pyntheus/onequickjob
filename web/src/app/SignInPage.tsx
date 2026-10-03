import { useNavigate, useSearchParams } from "react-router";
import { Brand } from "../shared/Brand";
import { SignInForm } from "../shared/SignInForm";
import { safeNext } from "./routing";

/** /signin?next=/p/today: sign in, then go to next or the user's home. */
export default function SignInPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const next = safeNext(params.get("next"));
  return (
    <>
      <header className="c-header">
        <Brand />
      </header>
      <main id="main" className="c-flow">
        <SignInForm onSignedIn={(me) => navigate(next ?? me.home_path, { replace: true })} />
      </main>
    </>
  );
}
