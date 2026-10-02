// Vite dev server for all three surfaces (/, /p, /admin).
// In Docker (infra/compose.app.yml) API_UPSTREAM points at this worktree's API container;
// on the host it defaults to the API on 127.0.0.1:8000. /api and /files are proxied so the
// browser only ever talks to one origin (cookies stay same-site).
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const apiUpstream = process.env.API_UPSTREAM || "http://127.0.0.1:8000";
const siteHost = process.env.SITE_HOST || "dev.onequickjob.co.uk";

export default defineConfig({
  plugins: [react()],
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
  build: {
    sourcemap: true,
    chunkSizeWarningLimit: 900,
  },
});
