// Vite dev server for all three surfaces (/, /p, /admin).
// In Docker (infra/compose.app.yml) API_UPSTREAM points at this worktree's API container;
// on the host it defaults to the API on 127.0.0.1:8000. /api and /files are proxied so the
// browser only ever talks to one origin (cookies stay same-site).
import { createReadStream, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig, type Connect, type Plugin } from "vite";

const apiUpstream = process.env.API_UPSTREAM || "http://127.0.0.1:8000";
const siteHost = process.env.SITE_HOST || "dev.onequickjob.co.uk";
// The admin map's basemap (make basemap writes var/basemap; decisions.md A31). On the site Caddy
// serves it; a dev server reached through a tunnel serves it here, the same way.
const basemapDir = process.env.BASEMAP_DIR || fileURLToPath(new URL("../var/basemap", import.meta.url));
const BASEMAP_TYPES: Record<string, string> = {
  ".json": "application/json",
  ".png": "image/png",
  ".pbf": "application/x-protobuf",
  ".txt": "text/plain; charset=utf-8",
};

/** Files under var/basemap at /basemap, answering HTTP range requests: the map reads its tiles
 * out of the one .pmtiles file by range, as Caddy's file_server lets it on the site. */
export function serveBasemap(dir = basemapDir): Connect.NextHandleFunction {
  return (req, res, next) => {
    if (req.method !== "GET" && req.method !== "HEAD") return next();
    const notFound = () => {
      res.statusCode = 404;
      res.end("Not found");
    };
    let file: string;
    try {
      file = path.join(dir, path.normalize(decodeURIComponent((req.url ?? "/").split("?")[0])));
    } catch {
      return notFound();
    }
    if (!file.startsWith(dir + path.sep)) return notFound();
    let size: number;
    try {
      const stat = statSync(file);
      if (!stat.isFile()) return notFound();
      size = stat.size;
    } catch {
      return notFound();
    }
    res.setHeader("Content-Type", BASEMAP_TYPES[path.extname(file)] ?? "application/octet-stream");
    res.setHeader("Accept-Ranges", "bytes");
    res.setHeader("Cache-Control", "no-cache");
    let start = 0;
    let end = size - 1;
    const range = /^bytes=(\d*)-(\d*)$/.exec(String(req.headers.range ?? ""));
    if (range && (range[1] || range[2])) {
      if (range[1]) {
        start = Number(range[1]);
        if (range[2]) end = Math.min(Number(range[2]), size - 1);
      } else {
        start = Math.max(0, size - Number(range[2]));
      }
      if (start > end) {
        res.statusCode = 416;
        res.setHeader("Content-Range", `bytes */${size}`);
        return res.end();
      }
      res.statusCode = 206;
      res.setHeader("Content-Range", `bytes ${start}-${end}/${size}`);
    }
    res.setHeader("Content-Length", String(end - start + 1));
    if (req.method === "HEAD" || size === 0) return res.end();
    createReadStream(file, { start, end }).pipe(res);
  };
}

function basemap(): Plugin {
  return {
    name: "oqj-basemap",
    configureServer(server) {
      server.middlewares.use("/basemap", serveBasemap());
    },
    configurePreviewServer(server) {
      server.middlewares.use("/basemap", serveBasemap());
    },
  };
}

export default defineConfig({
  plugins: [react(), basemap()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    // Behind Caddy the Host header is the public name; via an SSH tunnel it's localhost.
    allowedHosts: [siteHost, "localhost", "127.0.0.1"],
    proxy: {
      "/api": { target: apiUpstream, changeOrigin: false, xfwd: true },
      "/files": { target: apiUpstream, changeOrigin: false },
    },
    // HMR connects back on whatever host and port served the page (443 via Caddy,
    // 517N via a tunnel), so no clientPort is set here.
  },
  // MapLibre's worker (admin map) is an ES module importing its shared code: bundle it as one.
  worker: { format: "es" },
  build: {
    sourcemap: true,
    // MapLibre GL is about 1.1 MB minified (300 kB gzipped), in the admin map's own chunk, which
    // only /admin/map loads.
    chunkSizeWarningLimit: 1200,
  },
});
