import { describe, expect, it } from "vitest";
import { tabOf } from "./tabs";

describe("provider bottom nav follows the prototype's tabOf", () => {
  it.each([
    ["/p", "jobs"],
    ["/p/j/R-2301", "jobs"],
    ["/p/today", "today"],
    ["/p/visits/abc/finish", "today"],
    ["/p/earnings", "earnings"],
    ["/p/tax", "earnings"],
    ["/p/limit", "earnings"],
    ["/p/me", "me"],
    ["/p/time-off", "me"],
    ["/p/own-customers", "me"],
    ["/p/signup", null],
  ])("%s -> %s", (path, tab) => {
    expect(tabOf(path)).toBe(tab);
  });
});
