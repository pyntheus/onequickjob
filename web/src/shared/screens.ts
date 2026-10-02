import type { Lane } from "./Placeholder";

/** One entry per prototype SCREENS item (and the extra admin screens), with its route. */
export type ScreenEntry = { id: string; label: string; path: string; lane: Lane };
