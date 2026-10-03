// @vitest-environment node
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { matchRoutes } from "react-router";
import { describe, expect, it } from "vitest";
import { ADMIN_SCREENS } from "../admin/routes";
import { routes } from "../App";
import { CUSTOMER_SCREENS } from "../customer/routes";
import { PROVIDER_SCREENS } from "../provider/routes";

/** The SCREENS map from the prototype, read from the design file itself. */
function prototypeScreens(): Record<string, string[]> {
  const src = readFileSync(resolve(process.cwd(), "../docs/design/prototype.jsx"), "utf8");
  const block = src.slice(src.indexOf("const SCREENS = {"), src.indexOf("};", src.indexOf("const SCREENS = {")));
  const out: Record<string, string[]> = {};
  for (const surface of ["customer", "provider", "admin"]) {
    const part = block.slice(block.indexOf(`${surface}:`));
    const end = part.indexOf("]],");
    const body = end >= 0 ? part.slice(0, end + 2) : part;
    out[surface] = [...body.matchAll(/\["([a-z]+)",/g)].map((m) => m[1]);
  }
  return out;
}

const INDEX = { customer: CUSTOMER_SCREENS, provider: PROVIDER_SCREENS, admin: ADMIN_SCREENS };

describe("every prototype screen has a route", () => {
  const screens = prototypeScreens();
  it("reads the prototype's SCREENS", () => {
    expect(screens.customer).toHaveLength(10);
    expect(screens.provider).toHaveLength(12);
    expect(screens.admin).toHaveLength(5);
  });
  for (const surface of ["customer", "provider", "admin"] as const) {
    it(`${surface}: each screen id is indexed and its path matches a route`, () => {
      for (const id of screens[surface]) {
        const entry = INDEX[surface].find((s) => s.id === id);
        expect(entry, `${surface}/${id} missing from the screen index`).toBeDefined();
        const concrete = entry!.path.replace(/:([A-Za-z]+)/g, "x1");
        const matches = matchRoutes(routes, concrete);
        expect(matches, `${entry!.path} has no route`).not.toBeNull();
        expect(matches!.at(-1)!.route.path).not.toBe("*");
      }
    });
  }
});
