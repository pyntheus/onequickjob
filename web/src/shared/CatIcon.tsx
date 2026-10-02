import { CATEGORY_ICONS } from "./category-icons";
import {
  AppWindow,
  CookingPot,
  Dog,
  Droplets,
  Frame,
  Home,
  Package,
  PaintRoller,
  Scissors,
  Sparkles,
  SprayCan,
  Sprout,
  TabletSmartphone,
  Trash2,
  Wrench,
  type LucideIcon,
} from "lucide-react";

/** By icon name ("Sprout") or, for convenience, by category id ("mowing"). */
const BY_CATEGORY: Record<string, LucideIcon> = {
  mowing: Sprout,
  hedges: Scissors,
  clearance: Trash2,
  jetwash: Droplets,
  gutters: Home,
  windows: AppWindow,
  cleaning: Sparkles,
  deepclean: SprayCan,
  oven: CookingPot,
  decorating: PaintRoller,
  flatpack: Package,
  mounting: Frame,
  repairs: Wrench,
  techhelp: TabletSmartphone,
  dogwalking: Dog,
};

export function CatIcon({ icon, id, size = 20 }: { icon?: string | null; id?: string; size?: number }) {
  const I = (icon && CATEGORY_ICONS[icon]) || (id && BY_CATEGORY[id]) || Sprout;
  return <I size={size} strokeWidth={2} aria-hidden="true" />;
}
