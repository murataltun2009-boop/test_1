/*
 * Service worker — PWA ("Ana ekrana ekle") icin.
 *
 * TASARIM KARARI: bu bir CANLI ISLEM uygulamasi. Bozuk veri gostermek
 * kotu, eski veri gostermek daha kotu. Bu yuzden:
 *
 *   * /api/*  ve /ws  ASLA cache'lenmez. Her zaman agdan gelir.
 *   * index.html      network-first (sunucu yeni surumse aninda gelir)
 *   * statik varliklar stale-while-revalidate (hizli acilis + arka planda
 *                     yenilenir; ECharts 1 MB oldugu icin onemli)
 *
 * YANLISLIKLA YAPILMAMASI GEREKEN: skipWaiting() + clients.claim()
 * burada kullanilMIYOR. Aksi halde kullanici canli islem yaparken
 * sayfa yarida guncellenip mum/gosterge durumu kaybolur. Yeni surum
 * bir sonraki acilista devreye girer.
 */
// VERSION degistirildiginde tarayici yeni surumu yukler.
// app.js'teki fiyat bicimlendirme duzeltmesi icin yukseltildi.
// VERSION degistirildiginde tarayici yeni surumu yukler.
// v4: PWA geri donusunde otomatik yenilenme (visibilitychange/pageshow)
// v5: MURO modu + 1g dilimi + yeni kaldirac paneli ayarlari
// v6: yon titremesi duzeltmesi (kapali bar sinyali + 5 dk bekleme)
//     + trend modunda kar kilitleme
// v7: 1m dilimi, stop sonrasi reclaim, optimum nokta giris filtresi
const VERSION = "ta-v18";
const SHELL = "shell-" + VERSION;

const PRECACHE = [
  "/",
  "/static/style.css",
  "/static/app.js",
  "/static/vendor/echarts.min.js",
  "/static/icon-192.png",
  "/static/icon-512.png",
  "/static/manifest.webmanifest",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL)
      // Tek bir dosya 404 olursa kurulumun tamami basarisiz olmasin.
      .then((c) => Promise.allSettled(PRECACHE.map((u) => c.add(u))))
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => k !== SHELL).map((k) => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;

  if (req.method !== "GET") return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // Canli veri hicbir zaman cache'ten gelmez.
  if (url.pathname.startsWith("/api/")) return;
  if (url.pathname === "/ws") return;

  // Sayfa gezinmesi: once ag. Sunucu yoksa son bilinen kabuk.
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(SHELL).then((c) => c.put("/", copy));
          return res;
        })
        .catch(() => caches.match("/").then((r) => r || offline()))
    );
    return;
  }

  // Statik varlik: once cache (hizli), arka planda tazele.
  event.respondWith(
    caches.match(req).then((hit) => {
      const net = fetch(req)
        .then((res) => {
          if (res && res.status === 200 && res.type === "basic") {
            const copy = res.clone();
            caches.open(SHELL).then((c) => c.put(req, copy));
          }
          return res;
        })
        .catch(() => hit);
      return hit || net;
    })
  );
});

function offline() {
  return new Response(
    "<!doctype html><meta charset=utf-8>" +
    "<body style='background:#0b121c;color:#8fa3b8;font:15px system-ui;" +
    "padding:32px;text-align:center'>" +
    "<h2 style='color:#dfe8f1'>Sunucuya ulaşılamıyor</h2>" +
    "<p>Termux'ta Python sunucusunun çalıştığından emin olun.</p></body>",
    { headers: { "Content-Type": "text/html; charset=utf-8" },
      status: 503 }
  );
}