/**
 * IX-2 — Service Worker de la Fábrica de Software (PWA).
 *
 * Estrategia de caché:
 *   - Activos estáticos (CSS, JS, fonts):  Cache-First (versión offline disponible)
 *   - API routes (/api/*):                 Network-Only (siempre datos frescos)
 *   - SSE streams:                         Network-Only (no cacheable)
 *   - Páginas HTML:                        Network-First con fallback offline
 *
 * Notificaciones push:
 *   - Escucha eventos "push" y muestra notificaciones del sistema operativo.
 *   - Al hacer clic, abre la URL incluida en el payload.
 */

const CACHE_VERSION = "fabrica-v1";
const CACHE_STATIC  = `${CACHE_VERSION}-static`;
const CACHE_PAGES   = `${CACHE_VERSION}-pages`;

// Recursos que se pre-cachean en la instalación
const PRECACHE_ASSETS = [
  "/static/app.js",
  "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css",
  "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css",
  "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js",
];

// Páginas que se cachean en la primera visita (Network-First)
const PAGE_ROUTES = ["/", "/new", "/config", "/skills", "/deploy", "/news"];

// ── Instalación ───────────────────────────────────────────────────────────────
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_STATIC).then((cache) => {
      return cache.addAll(PRECACHE_ASSETS).catch(() => {
        // Ignorar fallos de precache de CDN (sin conexión durante install)
      });
    }).then(() => self.skipWaiting())
  );
});

// ── Activación (limpia cachés viejos) ─────────────────────────────────────────
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => k.startsWith("fabrica-") && k !== CACHE_STATIC && k !== CACHE_PAGES)
          .map((k) => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

// ── Fetch interceptor ─────────────────────────────────────────────────────────
self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Solo interceptar mismo origen + CDNs conocidos
  const isSameOrigin = url.origin === self.location.origin;
  const isCDN = url.hostname.includes("cdn.jsdelivr.net");

  if (!isSameOrigin && !isCDN) return;

  // SSE streams — Network-Only, siempre
  if (url.pathname.includes("/stream") || url.pathname.includes("/api/sessions/")) {
    return; // sin interceptar
  }

  // API routes — Network-Only
  if (url.pathname.startsWith("/api/")) {
    event.respondWith(networkOnly(request));
    return;
  }

  // Auth routes — Network-Only
  if (url.pathname.startsWith("/auth/") || url.pathname === "/login" || url.pathname === "/logout") {
    event.respondWith(networkOnly(request));
    return;
  }

  // Activos estáticos (CSS/JS/fonts) — Cache-First
  if (
    isCDN ||
    url.pathname.startsWith("/static/") ||
    request.destination === "style" ||
    request.destination === "script" ||
    request.destination === "font"
  ) {
    event.respondWith(cacheFirst(request, CACHE_STATIC));
    return;
  }

  // Páginas HTML — Network-First con fallback
  if (request.mode === "navigate" || request.headers.get("accept")?.includes("text/html")) {
    event.respondWith(networkFirstWithFallback(request));
    return;
  }

  // Por defecto: Network-First
  event.respondWith(networkFirst(request, CACHE_PAGES));
});

// ── Estrategias de caché ──────────────────────────────────────────────────────

async function networkOnly(request) {
  try {
    return await fetch(request);
  } catch {
    return new Response("Offline — sin conexión", { status: 503 });
  }
}

async function cacheFirst(request, cacheName) {
  const cached = await caches.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(cacheName);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    return new Response("Recurso no disponible offline", { status: 503 });
  }
}

async function networkFirst(request, cacheName) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(cacheName);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    const cached = await caches.match(request);
    return cached || new Response("Sin conexión", { status: 503 });
  }
}

async function networkFirstWithFallback(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(CACHE_PAGES);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    // Intentar página cacheada
    const cached = await caches.match(request);
    if (cached) return cached;
    // Fallback a la raíz
    const root = await caches.match("/");
    if (root) return root;
    return new Response(
      `<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8">
       <title>Sin conexión — Fábrica de Software</title>
       <style>body{background:#0f0f13;color:#aaa;font-family:sans-serif;
         display:flex;align-items:center;justify-content:center;height:100vh;text-align:center}
         h1{font-size:2rem}p{color:#666}</style></head>
       <body><div><h1>🏭 Sin conexión</h1>
       <p>No hay conexión a Internet.<br>Reconéctate para usar la Fábrica de Software.</p></div></body></html>`,
      { headers: { "Content-Type": "text/html" } }
    );
  }
}

// ── Notificaciones Push ───────────────────────────────────────────────────────
self.addEventListener("push", (event) => {
  if (!event.data) return;

  let payload = {};
  try {
    payload = event.data.json();
  } catch {
    payload = { title: "Fábrica de Software", body: event.data.text() };
  }

  const title   = payload.title   || "🏭 Fábrica de Software";
  const body    = payload.body    || "Tienes una notificación pendiente.";
  const url     = payload.url     || "/";
  const icon    = payload.icon    || "/static/icons/icon-192.png";
  const badge   = payload.badge   || "/static/icons/icon-192.png";
  const tag     = payload.tag     || "fabrica-default";

  event.waitUntil(
    self.registration.showNotification(title, {
      body,
      icon,
      badge,
      tag,
      data: { url },
      vibrate: [200, 100, 200],
      requireInteraction: payload.requireInteraction || false,
      actions: payload.actions || [],
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = event.notification.data?.url || "/";
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((windowClients) => {
      // Si ya hay una ventana abierta, enfocarla
      for (const client of windowClients) {
        if (client.url.includes(self.location.origin)) {
          client.focus();
          client.navigate(url);
          return;
        }
      }
      // Si no, abrir una nueva
      return clients.openWindow(url);
    })
  );
});
