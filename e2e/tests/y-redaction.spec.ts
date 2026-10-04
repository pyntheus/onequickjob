// The reporters write a failed test's errors to disk (error-context.md, the HTML report), and
// Playwright's error for a failed API request lists its headers, the site's basic auth included.
// send() must take the password out. The assertions compare booleans, so a failure here never
// prints the secret either.
import { expect, test } from "@playwright/test";
import { send } from "./helpers";

test("a failed API request's error never carries the site password", async ({ page }) => {
  const pass = process.env.E2E_PASS!;
  const basic = Buffer.from(`${process.env.E2E_USER}:${pass}`).toString("base64");
  const leaks = (text: string) => text.includes(pass) || text.includes(basic);

  // The hazard is real: Playwright's own error for a request that fails (here a 404, made to
  // throw) lists the request's headers, Authorization included.
  const raw = await page.request.fetch("/api/no-such-endpoint", { failOnStatusCode: true }).then(() => null, (e: Error) => e);
  expect(raw, "a 404 with failOnStatusCode should throw").not.toBeNull();
  expect(leaks(`${raw!.message}\n${raw!.stack}`), "Playwright's raw error lists the Authorization header").toBe(true);

  const err = await send(page, "GET", "/api/no-such-endpoint", undefined, { failOnStatusCode: true }).then(() => null, (e: Error) => e);
  expect(err, "a 404 with failOnStatusCode should throw").not.toBeNull();
  expect(leaks(err!.message), "the password is in send()'s error message").toBe(false);
  expect(leaks(err!.stack ?? ""), "the password is in send()'s error stack").toBe(false);
  expect(err!.message).toContain("[redacted]");
});
