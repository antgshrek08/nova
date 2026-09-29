/** Turning on "Nova can text me", from the browser's side.
 *
 * The whole flow is four steps that each fail differently, and the reason
 * this is its own module is that each failure needs its own sentence. "Push
 * notifications aren't available" is the answer to none of them: on an iPhone
 * the real answer is almost always "open this from the Home Screen icon, not
 * Safari", and a user who is told the generic thing will conclude the feature
 * is broken and stop.
 */
import { BACKEND_URL } from "../api.js";

/** iOS only grants Web Push to a Home Screen install (iOS 16.4+). */
export function isStandalone() {
  return (
    window.matchMedia?.("(display-mode: standalone)").matches ||
    window.navigator.standalone === true
  );
}

export function isIOS() {
  return (
    /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    // iPadOS 13+ reports as a Mac; the touch-point check separates them.
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1)
  );
}

/** Why notifications can't be turned on here, or null when they can. */
export function blocker() {
  if (!window.isSecureContext) {
    return "Notifications need a secure connection. Open Nova over its https:// address.";
  }
  if (!("serviceWorker" in navigator)) {
    return "This browser has no service worker support, which notifications need.";
  }
  if (!("PushManager" in window)) {
    if (isIOS() && !isStandalone()) {
      return "On iPhone, add Nova to your Home Screen first (Share → Add to Home Screen), then open it from that icon. Safari itself can't receive notifications.";
    }
    return "This browser can't receive push notifications.";
  }
  if (Notification.permission === "denied") {
    return "Notifications are blocked for this site. You'll need to re-allow them in your browser or iPhone settings.";
  }
  if (isIOS() && !isStandalone()) {
    return "On iPhone, add Nova to your Home Screen first (Share → Add to Home Screen), then open it from that icon.";
  }
  return null;
}

function urlBase64ToUint8Array(base64) {
  // PushManager wants the key as bytes. The server sends standard base64url
  // with the padding stripped, which atob does not accept.
  const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), "=");
  const raw = atob(padded.replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}

export async function currentSubscription() {
  if (!("serviceWorker" in navigator)) return null;
  const registration = await navigator.serviceWorker.getRegistration("/app/");
  if (!registration) return null;
  return registration.pushManager.getSubscription();
}

/** Register the worker, ask permission, subscribe, tell the backend.
 *  Throws with a sentence worth showing the user. */
export async function enable(label) {
  const why = blocker();
  if (why) throw new Error(why);

  const registration = await navigator.serviceWorker.register("/app/sw.js", { scope: "/app/" });
  await navigator.serviceWorker.ready;

  const permission = await Notification.requestPermission();
  if (permission !== "granted") {
    throw new Error("Notifications weren't allowed, so Nova can't reach this device.");
  }

  const { public_key: key } = await fetch(`${BACKEND_URL}/push/key`).then((r) => r.json());

  // Reuse an existing subscription rather than creating a second one. A
  // browser will refuse subscribe() outright if one already exists under a
  // different key, and the error for that is not self-explanatory.
  let subscription = await registration.pushManager.getSubscription();
  if (!subscription) {
    subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(key),
    });
  }

  await fetch(`${BACKEND_URL}/push/subscribe`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      subscription: subscription.toJSON(),
      label: label || deviceLabel(),
    }),
  });
  return subscription;
}

export async function disable() {
  const subscription = await currentSubscription();
  if (!subscription) return;
  await fetch(`${BACKEND_URL}/push/unsubscribe`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ endpoint: subscription.endpoint }),
  });
  await subscription.unsubscribe();
}

/** A name the user will recognise in the device list. */
function deviceLabel() {
  if (isIOS()) return isStandalone() ? "iPhone (Home Screen)" : "iPhone";
  if (/Android/.test(navigator.userAgent)) return "Android";
  if (/Mac/.test(navigator.platform)) return "Mac";
  return "This computer";
}
