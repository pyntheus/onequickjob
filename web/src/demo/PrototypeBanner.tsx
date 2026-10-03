import { useConfig } from "../api/queries";

/** DEMO_MODE only: a thin bar across the top of every page. */
export function PrototypeBanner() {
  const { data: config } = useConfig();
  if (!config?.demo_mode) return null;
  return (
    <div className="demo-banner" role="note">
      Prototype: test payments only
    </div>
  );
}
