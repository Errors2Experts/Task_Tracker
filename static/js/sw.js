// Service worker for Task Tracker push notifications.
// Only fires its own notification (OS default sound) when NO tab of this
// site is open at all — if a tab is open (even minimized/background), the
// page itself already shows a notification with the actual mixkit sound
// via notifications.js, so this skips to avoid a duplicate popup.

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (err) {
    data = { title: "Task Tracker", body: event.data ? event.data.text() : "" };
  }

  const title = data.title || "Task Tracker";
  const options = {
    body: data.body || "You have a new update.",
    icon: "/static/image/logo.jpeg",
    badge: "/static/image/logo.jpeg",
    data: {
      url: data.url || "/dashboard/",
      priority: data.priority || "MEDIUM",
    },
  };

  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clientList) => {
      // Any window of this site open at all (visible or just minimized/
      // background) — the open tab's own notifications.js will handle the
      // popup + custom sound instead, so don't show a second one here.
      if (clientList.length > 0) return;
      return self.registration.showNotification(title, options);
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/dashboard/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      for (const client of clients) {
        if (client.url.includes(url) && "focus" in client) {
          return client.focus();
        }
      }
      if (self.clients.openWindow) {
        return self.clients.openWindow(url);
      }
    })
  );
});