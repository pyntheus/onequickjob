import { describe, expect, it } from "vitest";
import { toAppPath } from "./links";

describe("outbox links open in-app on any host", () => {
  const base = "https://dev.onequickjob.co.uk";
  it("rewrites our links to relative paths", () => {
    expect(toAppPath("https://dev.onequickjob.co.uk/p/j/R-2301?t=abc", base)).toBe("/p/j/R-2301?t=abc");
    expect(toAppPath("https://dev.onequickjob.co.uk/requests/R-2301", base + "/")).toBe("/requests/R-2301");
  });
  it("leaves other sites alone", () => {
    expect(toAppPath("https://example.com/p/j/R-1", base)).toBeNull();
    expect(toAppPath("https://dev.onequickjob.co.uk.evil.test/p", base)).toBeNull();
  });
});
