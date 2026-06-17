// OneSignal v16 service worker for World Cup 2026 web-push.
// Hosted in its own /worldcup-2026/onesignal/ scope so it never collides with the
// app's own sw.js (the scores PWA / self-update worker, which controls /worldcup-2026/).
importScripts("https://cdn.onesignal.com/sdks/web/v16/OneSignalSDK.sw.js");
