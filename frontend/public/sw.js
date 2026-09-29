// Nova's service worker. Its only job is to receive pushes and open the app
// when one is tapped.
//
// Deliberately not a caching/offline worker. Nova's frontend is served by the
// backend it talks to, so a cached shell that outlives its API is worse than
// no cache at all: the app would load, look fine, and fail every request.
// Adding offline support later means versioning that cache carefully, and
// that is a separate piece of work from "let Nova reach the phone".

self.addEventListener("install", () => {
  // Take over immediately rather than waiting for every existing tab to
  // close. Without this, the first push after setup can arrive before any
  // worker is active and is dropped silently.
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
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
