import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { FLOW_KEY, FlowCtx, INITIAL_FLOW, loadFlow, type FlowCtxValue, type FlowState } from "./flow";

/** Holds the quote flow's state for every customer route (see flow.ts). */
export function FlowProvider({ children, initial }: { children: ReactNode; initial?: FlowState }) {
  const [flow, setFlow] = useState<FlowState>(() => initial ?? loadFlow());
  const [photos, setAllPhotos] = useState<Record<string, File[]>>({});

  useEffect(() => {
    try {
      sessionStorage.setItem(FLOW_KEY, JSON.stringify(flow));
    } catch {
      // Storage can be blocked: the flow still works, it just won't survive a reload.
    }
  }, [flow]);

  const update = useCallback<FlowCtxValue["update"]>((patch) => {
    setFlow((f) => ({ ...f, ...(typeof patch === "function" ? patch(f) : patch) }));
  }, []);
  const setPhotos = useCallback((key: string, files: File[]) => setAllPhotos((p) => ({ ...p, [key]: files })), []);
  const reset = useCallback(() => {
    setFlow((f) => ({ ...INITIAL_FLOW, address: f.address, addressText: f.addressText, contact: f.contact }));
    setAllPhotos({});
  }, []);

  const value = useMemo(() => ({ flow, update, photos, setPhotos, reset }), [flow, update, photos, setPhotos, reset]);
  return <FlowCtx.Provider value={value}>{children}</FlowCtx.Provider>;
}
