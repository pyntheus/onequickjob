import { Outlet, ScrollRestoration } from "react-router";
import { DemoTools } from "../demo/DemoTools";
import { PrototypeBanner } from "../demo/PrototypeBanner";
import { ToastProvider } from "../shared/Toast";

/** Wraps every surface: the .pt root (the prototype's scoping), demo controls, toasts. */
export function RootLayout() {
  return (
    <ToastProvider>
      <div className="pt">
        <PrototypeBanner />
        <Outlet />
        <DemoTools />
      </div>
      <ScrollRestoration />
    </ToastProvider>
  );
}
