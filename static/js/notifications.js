(function () {
  "use strict";

  const root = document.body;
  if (!root || root.dataset.authenticated !== "true") return;

  const POLL_URL = "/notifications/poll/";
  const PUSH_KEY_URL = "/push/public-key/";
  const PUSH_SUBSCRIBE_URL = "/push/subscribe/";
  const POLL_INTERVAL_MS = 15000;
  const LAST_ID_KEY = "tt_last_notification_id";

  const SOUND_BY_PRIORITY = {
    LOW: "/static/sound/task-new-normal.wav",
    MEDIUM: "/static/sound/task-new-normal.wav",
    HIGH: "/static/sound/task-new-urgent.wav",
    URGENT: "/static/sound/task-new-urgent.wav",
  };

  const TITLE_BY_VERB = {
    CREATED: "New task assigned",
    COMPLETED: "Task completed",
  };
  const NOTIFY_VERBS = new Set(["CREATED", "COMPLETED"]);

  function getCsrfToken() {
    const match = document.cookie.match(/csrftoken=([^;]+)/);
    return match ? match[1] : "";
  }

  function playSoundForPriority(priority) {
    const src = SOUND_BY_PRIORITY[priority] || SOUND_BY_PRIORITY.MEDIUM;
    try {
      const audio = new Audio(src);
      audio.volume = 0.85;
      // Autoplay can be blocked until the person has interacted with the
      // page at least once — that's a browser policy, not a bug here.
      audio.play().catch(() => {});
    } catch (err) {
      /* no-op */
    }
  }

  function showTaskNotification(n) {
    if (!("Notification" in window)) return;
    if (Notification.permission !== "granted") return;

    const title = TITLE_BY_VERB[n.verb] || "Task Tracker";
    const priorityLabel = n.priority
      ? n.priority.charAt(0) + n.priority.slice(1).toLowerCase()
      : "";
    let body = n.message;
    if (n.assigned_to) body += ` — assigned to ${n.assigned_to}`;
    if (priorityLabel) body += ` (Priority: ${priorityLabel})`;

    const notification = new Notification(title, {
      body: body,
      icon: "/static/image/logo.jpeg",
      tag: "task-" + n.id, // same task ku rendu notification varadhu
    });

    notification.onclick = () => {
      window.focus();
      if (n.task_id) {
        window.location.href = "/tasks/" + n.task_id + "/";
      }
      notification.close();
    };
  }

  function updateBadge(count) {
    const badge = document.querySelector('[data-notification-badge]');
    if (!badge) return;
    if (count > 0) {
      badge.textContent = count;
      badge.style.display = "";
    } else {
      badge.style.display = "none";
    }
  }

  // Runs while this tab is open — foreground OR a background/minimized tab.
  // Plays the actual mixkit sound + shows a popup from right here on the
  // page, since a page that's open can control its own audio (a fully
  // closed browser cannot — that's handled by real push + sw.js instead,
  // which deliberately skips showing its own notification whenever it sees
  // this tab is open, so there's no duplicate popup).
  function poll() {
    const since = localStorage.getItem(LAST_ID_KEY) || "0";
    fetch(`${POLL_URL}?since=${encodeURIComponent(since)}`, { credentials: "same-origin" })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!data) return;
        if (data.notifications && data.notifications.length) {
          data.notifications.forEach((n) => {
            if (NOTIFY_VERBS.has(n.verb)) {
              playSoundForPriority(n.priority);
              showTaskNotification(n);
            }
          });
        }
        if (data.last_id) localStorage.setItem(LAST_ID_KEY, String(data.last_id));
        updateBadge(data.unread_count || 0);
      })
      .catch(() => {});
  }

  setInterval(poll, POLL_INTERVAL_MS);
  poll();

  function urlBase64ToUint8Array(base64String) {
    const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
    const rawData = window.atob(base64);
    const outputArray = new Uint8Array(rawData.length);
    for (let i = 0; i < rawData.length; ++i) outputArray[i] = rawData.charCodeAt(i);
    return outputArray;
  }

  function subscribeForPush() {
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) return;

    navigator.serviceWorker
      .register("/static/js/sw.js")
      .then((registration) => {
        console.log("[push] service worker registered, scope:", registration.scope);
        return registration.pushManager.getSubscription().then((existing) => {
          if (existing) return existing;
          return fetch(PUSH_KEY_URL, { credentials: "same-origin" })
            .then((res) => res.json())
            .then((data) =>
              registration.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: urlBase64ToUint8Array(data.publicKey),
              })
            );
        });
      })
      .then((subscription) => {
        if (!subscription) return;
        console.log("[push] subscription created:", subscription.endpoint);
        return fetch(PUSH_SUBSCRIBE_URL, {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json", "X-CSRFToken": getCsrfToken() },
          body: JSON.stringify(subscription.toJSON()),
        }).then((res) => {
          if (!res.ok) {
            console.error("[push] server rejected subscription:", res.status);
          } else {
            console.log("[push] subscription saved on server.");
          }
        });
      })
      .catch((err) => {
        console.error("[push] setup failed:", err);
      });
  }

  function requestPushPermissionOnce() {
    if (!("Notification" in window)) return;
    if (Notification.permission === "granted") {
      subscribeForPush();
      return;
    }
    if (Notification.permission === "denied") return;

    const ask = () => {
      document.removeEventListener("click", ask);
      Notification.requestPermission().then((permission) => {
        if (permission === "granted") subscribeForPush();
      });
    };
    document.addEventListener("click", ask, { once: true });
  }

  requestPushPermissionOnce();
})();