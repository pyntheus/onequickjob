import { useConfig } from "../api/queries";
import { OutboxDrawer } from "./OutboxDrawer";
import { SwitchUser } from "./SwitchUser";

/** The floating demo controls, bottom-left so they never cover the provider bottom nav. */
export function DemoTools() {
  const { data: config } = useConfig();
  if (!config?.demo_mode) return null;
  return (
    <div className="demo-fabs">
      <OutboxDrawer />
      <SwitchUser />
    </div>
  );
}
