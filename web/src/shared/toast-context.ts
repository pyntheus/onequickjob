import { createContext, useContext } from "react";

export const ToastCtx = createContext<(message: string) => void>(() => {});

/** notify("Saved") shows the prototype's toast for 2.8 seconds. */
export function useToast(): (message: string) => void {
  return useContext(ToastCtx);
}
