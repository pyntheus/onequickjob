// @vitest-environment node
/** The dev server's /basemap (vite.config.ts): files from var/basemap with HTTP range requests,
 * as Caddy serves them on the site, and nothing outside that folder. */
import { chmodSync, mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { PassThrough } from "node:stream";
import { describe, expect, it } from "vitest";
import { serveBasemap } from "../../vite.config.ts";

const root = mkdtempSync(path.join(tmpdir(), "basemap-"));
const dir = path.join(root, "basemap");
mkdirSync(path.join(dir, "fonts"), { recursive: true });
writeFileSync(path.join(dir, "oqj.pmtiles"), Buffer.from(Array.from({ length: 100 }, (_, i) => i)));
writeFileSync(path.join(dir, "fonts", "0-255.pbf"), "glyphs");
writeFileSync(path.join(root, "secret.txt"), "not for the map");

type Answer = { status: number; headers: Record<string, string>; body: Buffer; passed: boolean };

function get(url: string, headers: Record<string, string> = {}, method = "GET"): Promise<Answer> {
  return new Promise((resolve) => {
    const res = new PassThrough() as PassThrough & {
      statusCode: number;
      headersSent: boolean;
      setHeader: (k: string, v: string) => void;
      removeHeader: (k: string) => void;
    };
    const out: Answer = { status: 200, headers: {}, body: Buffer.alloc(0), passed: false };
    const chunks: Buffer[] = [];
    res.statusCode = 200;
    res.headersSent = false;
    res.setHeader = (k, v) => (out.headers[k.toLowerCase()] = v);
    res.removeHeader = (k) => delete out.headers[k.toLowerCase()];
    res.on("data", (c: Buffer) => chunks.push(c));
    res.on("finish", () => resolve({ ...out, status: res.statusCode, body: Buffer.concat(chunks) }));
    res.resume();
    const req = { url, method, headers: Object.fromEntries(Object.entries(headers).map(([k, v]) => [k.toLowerCase(), v])) };
    serveBasemap(dir)(req as never, res as never, () => resolve({ ...out, passed: true }));
  });
}

describe("the dev server's basemap", () => {
  it("answers range requests, as the map reads tiles", async () => {
    const part = await get("/oqj.pmtiles", { Range: "bytes=10-19" });
    expect(part.status).toBe(206);
    expect(part.headers["content-range"]).toBe("bytes 10-19/100");
    expect([...part.body]).toEqual([10, 11, 12, 13, 14, 15, 16, 17, 18, 19]);
    expect(part.headers["accept-ranges"]).toBe("bytes");

    expect([...(await get("/oqj.pmtiles", { Range: "bytes=-3" })).body]).toEqual([97, 98, 99]);
    expect([...(await get("/oqj.pmtiles", { Range: "bytes=98-" })).body]).toEqual([98, 99]);
    expect((await get("/oqj.pmtiles", { Range: "bytes=95-500" })).headers["content-range"]).toBe("bytes 95-99/100");
    const beyond = await get("/oqj.pmtiles", { Range: "bytes=200-300" });
    expect([beyond.status, beyond.headers["content-range"]]).toEqual([416, "bytes */100"]);

    const whole = await get("/oqj.pmtiles");
    expect([whole.status, whole.body.length, whole.headers["content-type"]]).toEqual([200, 100, "application/octet-stream"]);
    const glyphs = await get("/fonts/0-255.pbf");
    expect([glyphs.body.toString(), glyphs.headers["content-type"]]).toEqual(["glyphs", "application/x-protobuf"]);
  });

  it("answers 404, and keeps running, when a file goes between its stat and its read", async () => {
    // A file it can see but not open stands in for one removed in between (make basemap
    // replaces folders): the open fails after the stat, asynchronously.
    const gone = path.join(dir, "fonts", "gone.pbf");
    writeFileSync(gone, "x");
    chmodSync(gone, 0o000);
    try {
      if (process.getuid?.() === 0) return; // root opens anything: nothing to test
      const answer = await get("/fonts/gone.pbf", { Range: "bytes=0-0" });
      expect([answer.status, answer.body.toString(), answer.headers["content-range"]]).toEqual([404, "Not found", undefined]);
      expect((await get("/fonts/0-255.pbf")).status).toBe(200); // still serving
    } finally {
      chmodSync(gone, 0o644);
    }
  });

  it("serves nothing outside the basemap folder, and nothing that isn't there", async () => {
    for (const url of ["/../secret.txt", "/%2e%2e/secret.txt", "/fonts/../../secret.txt", "/missing.pbf", "/fonts", "/%E0%A4%A"]) {
      const answer = await get(url);
      expect([url, answer.status, answer.body.toString()]).toEqual([url, 404, "Not found"]);
    }
    expect((await get("/oqj.pmtiles", {}, "POST")).passed).toBe(true);
    const head = await get("/oqj.pmtiles", {}, "HEAD");
    expect([head.status, head.headers["content-length"], head.body.length]).toEqual([200, "100", 0]);
  });
});
