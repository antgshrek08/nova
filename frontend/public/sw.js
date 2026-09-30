// Nova's service worker, for the phone app: notifications, and opening even
// when the computer Nova runs on is off.
//
// Only the app itself is kept (the page and its files), never your data --
// that stays behind the access token on the computer, and the screens keep
// their own "last time" copy (remote.js). The page is always fetched fresh
// first, so an update to Nova reaches the phone on its next open; the saved
// copy is used only when the computer can't be reached.

const CACHE = "nova-app-v1";
const SHELL = "/app/";

self.addEventListener("install", () => {
  // Take over immediately rather than waiting for every existing tab to
  // close. Without this, the first push after setup can arrive before any
  // worker is active and is dropped silently.
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(Promise.all([
    self.clients.claim(),
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k.startsWith("nova-app-") && k !== CACHE).map((k) => caches.delete(k)))),
  ]));
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin || !url.pathname.startsWith("/app")) return; // API calls: never cached
  // Built files have a content hash in their name, so a saved copy is never stale.
  if (url.pathname.startsWith("/app/assets/")) {
    event.respondWith(caches.open(CACHE).then(async (cache) => {
      const hit = await cache.match(request);
      if (hit) return hit;
      const response = await fetch(request);
      if (response.ok) cache.put(request, response.clone());
      return response;
    }));
    return;
  }
  // The page (and icons, manifest): fresh when the computer answers, saved copy when it doesn't.
  if (request.mode === "navigate" || /\/app\/?(index\.html)?$/.test(url.pathname) || /\.(png|ico|webmanifest|svg)$/.test(url.pathname)) {
    event.respondWith(fetch(request).then((response) => {
      if (response.ok) {
        const copy = response.clone();
        caches.open(CACHE).then((cache) => cache.put(request.mode === "navigate" ? SHELL : request, copy));
      }
      return response;
    }).catch(async () => (await caches.match(request.mode === "navigate" ? SHELL : request)) || (await caches.match(SHELL)) || Response.error()));
  }
});

self.addEventListener("push", (event) => {
  // A push with no readable payload still deserves to surface. Some push
  // services deliver a wake-up with no data, and a notification the user can
  // tap beats silence -- on iOS, failing to show one at all can cost the
  // site its push permission.
  let payload = { title: "Nova", body: "Nova has something for you.", url: "/app/" };
  if (event.data) {
    try {
      payload = { ...payload, ...event.data.json() };
    } catch {
      payload.body = event.data.text() || payload.body;
    }
  }

  event.waitUntil(
    self.registration.showNotification(payload.title, {
      body: payload.body,
      icon: "/app/icon.png",
      badge: "/app/icon.png",
      // Same tag replaces an earlier notification instead of stacking a
      // second one. Three "2 things due tomorrow" banners in a row is how a
      // useful reminder turns into something the user switches off.
      tag: payload.tag || "nova",
      renotify: true,
      data: { url: payload.url || "/app/" },
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || "/app/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      // Focus a tab that already has Nova open rather than opening a second
      // one. Two copies of the app on a phone is a real annoyance, and the
      // open one may already have unsent text in the composer.
      for (const client of clients) {
        if (client.url.includes("/app") && "focus" in client) return client.focus();
      }
      return self.clients.openWindow(target);
    })
  );
});
