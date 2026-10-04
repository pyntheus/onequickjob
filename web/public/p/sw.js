/* OneQuickJob for providers: a service worker for the app shell only (lane L2 ruling).
 * Pages under /p are fetched from the network first; if the network is down, the last shell
 * we saw is shown so the app still opens. The API, uploads and files are never cached:
 * jobs, money and messages always come fresh from the server.
 * The manifest starts the installed app at /p/, inside this worker's scope, so it opens offline
 * too; its own scope is /p, so the app's many links to /p never leave the installed app. */
const SHELL = "oqj-p-shell-v1";

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(caches.open(SHELL).then((c) => c.addAll(["/p"]).catch(() => undefined)));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith("oqj-p-") && k !== SHELL).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/files/")) return;
  if (req.mode === "navigate" && url.pathname.startsWith("/p")) {
    event.respondWith(
      fetch(req)
        .then((res) => {
          if (res.ok) {
            const copy = res.clone();
            caches.open(SHELL).then((c) => c.put("/p", copy));
          }
          return res;
        })
        .catch(() => caches.match("/p").then((hit) => hit || Response.error())),
    );
    return;
  }
  if (url.pathname.startsWith("/assets/")) {
    // Built assets have hashed names: once fetched they never change.
    event.respondWith(
      caches.match(req).then(
        (hit) =>
          hit ||
          fetch(req).then((res) => {
            if (res.ok) {
              const copy = res.clone();
              caches.open(SHELL).then((c) => c.put(req, copy));
            }
            return res;
          }),
      ),
    );
  }
});
