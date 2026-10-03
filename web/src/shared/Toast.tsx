import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { ToastCtx } from "./toast-context";

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const notify = useCallback((msg: string) => {
    setToast(msg);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setToast(null), 2800);
  }, []);
  useEffect(() => () => clearTimeout(timer.current), []);
  return (
    <ToastCtx.Provider value={notify}>
      {children}
      <div aria-live="polite" role="status">
        {toast && <div className="toast">{toast}</div>}
      </div>
    </ToastCtx.Provider>
  );
}
