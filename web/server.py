"""
Web arayuzunun arka plan servisi (FastAPI/Starlette uyumu olmadan, saf
Starlette + uvicorn).

Görevleri:
  * Static dosyalari sunmak (index.html, app.js, style.css, vendor/echarts)
  * Tarayiciya anlik veri akisi (WebSocket)
      - ``tick`` : her islemde fiyat (anlik, ~4,5 msg/sn)
      - ``snapshot``: mum gecmisi + gostergeler + sinyal yildizlari (~1 sn)
      - ``log``   : log satirlari
      - ``signal``: sinyal degisimleri
  * Ayar degisikligi (esikler) ve veritabani sifirlama

Onceden olusturulmus MarketService kullanilir; is mantigi (gostergeler,
sinyaller, DB) orada yasar, burada sadece WebSocket'e tasinir.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

import config
import core.analysis as analysis_mod
from core.analysis import Signal
from core.service import MarketService
from core.store import SignalStore

logger = logging.getLogger("ta.web")

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


# --------------------------------------------------------------------------
# JSON'a cevirme yardimcilari
# --------------------------------------------------------------------------
def _num(x) -> float | None:
    """NaN/Inf -> None (JSON'da gecersiz)."""
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def _fmt_ts(ms: int) -> str:
    """Epoch ms -> yerel saat damgasi (ISO, saniye)."""
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc) \
        .astimezone().isoformat(timespec="seconds")


def candle_payload(res, price: float, signals=None) -> dict[str, Any]:
    """Bir TimeframeAnalysis'i tarayiciya gonderilecek JSON'a cevirir.

    signals: MOD BAZLI sinyal serisi (list[Signal]). Verilirse yildizlar
    bu seriden uretilir; verilmezse bilesik skor serisi kullanilir.
    """
    n = int(res.c.size)
    # Tarayiciye tum gecmisi gondermek yerine son N mum + yeterli indikator
    # gecmisi: gosterge hesabinda kullanilan tum bar sonucu zaten hesaplandi.
    # Grafikte gorunecek miktar: en az 400 bar (indikator isinma + yildizlar).
    lo = max(0, n - 400)
    idx = list(range(lo, n))

    candles = [
        [int(res.open_times[i]) // 1000, float(res.o[i]), float(res.h[i]),
         float(res.l[i]), float(res.c[i]), float(res.v[i])]
        for i in idx
    ]

    def series(key: str) -> list:
        s = res.ma_series.get(key)
        if s is None:
            return []
        return [_num(s[i]) for i in idx]

    mas = {
        "ema20": series("ema20"), "ema50": series("ema50"),
        "ema200": series("ema200"), "sma200": series("sma200"),
        "hma": series("hma"), "vwma": series("vwma"),
    }

    # Sinyal yildizlari: sinyalin ilk ortaya ciktigi barlar.
    # Secilen algoritma (ma_only/osc_only/trend/1m/muro) bir sinyal serisi
    # verildiyse YILDIZLAR o seriden uretilir.
    if signals is None:
        marc = res.marker_indices()
    else:
        marc = analysis_mod.marker_indices_from(signals)
    markers = []
    for i in marc:
        if i < lo:
            continue
        sig = res.signals[i] if signals is None else signals[i]
        markers.append({
            "t": int(res.open_times[i]) // 1000,
            "signal": sig.value,
            "price": _num(res.c[i]),
            "strong": abs(sig.strength) >= 2,
        })

    # Bilesik skor serisi (grafik altinda mini panel icin)
    composite = [_num(res.composite[i]) for i in idx]

    # Gosterge tablolari (anlik degerler)
    osc = [{"ad": r.label, "deger": r.value_text, "v": r.verdict.value,
            "vad": r.verdict.label} for r in res.oscillator_rows]
    ma = [{"ad": r.label, "deger": r.value_text, "v": r.verdict.value,
           "vad": r.verdict.label} for r in res.ma_rows]

    counts = {
        "osc": _count(res.oscillator_rows), "ma": _count(res.ma_rows),
    }

    return {
        "type": "snapshot",
        "symbol": res.symbol,
        "timeframe": res.timeframe,
        # mum sirasi: [zaman, acilis, enYuksek, enDusuk, kapanis, hacim]
        "candles": candles,
        "ma": mas,
        "markers": markers,
        "composite": composite,
        "indicators": {"osc": osc, "ma": ma},
        "counts": counts,
        "signal": res.signal.value,
        "price": _num(price) if price == price else _num(res.c[-1]),
        "composite_score": round(float(res.composite_value), 4),
        "osc_score": round(float(res.oscillator_scores[-1]), 4),
        "ma_score": round(float(res.ma_scores[-1]), 4),
        "strong_threshold": 0.0,   # UI dolduracak
        "ts": int(datetime.now(timezone.utc).timestamp()),
    }


def _count(rows) -> dict:
    out = {"buy": 0, "sell": 0, "neutral": 0}
    for r in rows:
        out[{1: "buy", -1: "sell", 0: "neutral"}[r.verdict.value]] += 1
    return out


# --------------------------------------------------------------------------
# Baglanti yoneticisi
# --------------------------------------------------------------------------
class Hub:
    """
    Acik WebSocket baglantilarini yonetir, olaylari yayar.

    Her istemcinin bir "secili zaman dilimi" vardir. Bu sayede:
      * snapshot (76 KB) yalnizca istemcinin baktigi dilim icin uretilir
      * tikler yalnizca o dilimin istemcisine gonderilir
    Uc dilim de acilca bulunsaydi saniyede 3x76 KB gereksiz trafik olurdu.
    """

    def __init__(self, default_tf: str) -> None:
        self._clients: dict[WebSocket, str] = {}
        self._default_tf = default_tf
        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def register(self, ws: WebSocket, tf: str | None = None) -> None:
        async with self._lock:
            self._clients[ws] = tf or self._default_tf

    async def unregister(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.pop(ws, None)

    async def set_timeframe(self, ws: WebSocket, tf: str) -> str:
        """Istemcinin secili dilimini degistirir; yeni degeri dondurur."""
        async with self._lock:
            self._clients[ws] = tf
        return tf

    def timeframe_of(self, ws: WebSocket) -> str:
        return self._clients.get(ws, self._default_tf)

    def clients_for(self, tf: str) -> list[WebSocket]:
        return [ws for ws, t in self._clients.items() if t == tf]

    def used_timeframes(self) -> set[str]:
        return set(self._clients.values())

    async def broadcast(self, payload: dict) -> None:
        """Herkese ayni mesaj (log, durum vb.)."""
        data = json.dumps(payload, ensure_ascii=False, default=str)
        async with self._lock:
            targets = list(self._clients)
        dead = []
        for ws in targets:
            try:
                await ws.send_text(data)
            except Exception:      # noqa: BLE001
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._clients.pop(ws, None)

    async def send_to_timeframe(self, tf: str, payload: dict) -> None:
        """Yalnizca o dilimi gosteren istemcilere gonder."""
        async with self._lock:
            targets = [ws for ws, t in self._clients.items() if t == tf]
        if not targets:
            return
        data = json.dumps(payload, ensure_ascii=False, default=str)
        dead = []
        for ws in targets:
            try:
                await ws.send_text(data)
            except Exception:      # noqa: BLE001
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._clients.pop(ws, None)

    # Servis (worker thread) icinden cagrilir: loop'a atip planla.
    def broadcast_threadsafe(self, payload: dict) -> None:
        self._schedule(self.broadcast(payload))

    def send_to_timeframe_threadsafe(self, tf: str, payload: dict) -> None:
        self._schedule(self.send_to_timeframe(tf, payload))

    def _schedule(self, coro) -> None:
        if self._loop is None or self._loop.is_closed():
            return
        try:
            asyncio.run_coroutine_threadsafe(coro, self._loop)
        except RuntimeError:
            pass


# --------------------------------------------------------------------------
# Uygulama
# --------------------------------------------------------------------------
def create_app(service: MarketService, store: SignalStore,
               paper=None) -> Starlette:
    hub = Hub(service.settings.active_timeframe)
    app_state = {"service": service, "store": store, "hub": hub,
                 "started": False}

    # ------------------------------------------------------------------
    async def index(request: Request) -> Response:
        return FileResponse(os.path.join(STATIC_DIR, "index.html"),
                            headers=dict(NO_CACHE))

    async def api_state(request: Request) -> Response:
        return JSONResponse({
            "symbol": service.settings.symbol,
            "symbols": list(config.SYMBOLS),
            "timeframe": service.settings.active_timeframe,
            "timeframes": list(service.settings.timeframes),
            "tf_labels": {tf: config.TF_LABELS.get(tf, tf)
                          for tf in service.settings.timeframes},
            "thresholds": {
                "strong": service.settings.strong_threshold,
                "base": service.settings.base_threshold,
            },
            "running": app_state["started"],
        })

    def _payload_for(tf: str, price: float) -> dict[str, Any] | None:
        """Bir dilimin tarayiciya gidecek anlik goruntusu."""
        snap = service.snapshot()
        res = snap["analyses"].get(tf)
        if res is None:
            return None
        sigs = service.mode_signal_series(tf)
        payload = candle_payload(res, price, sigs or None)
        payload["strong_threshold"] = service.settings.strong_threshold
        payload["base_threshold"] = service.settings.base_threshold
        return payload

    async def api_thresholds(request: Request) -> Response:
        data = await request.json()
        try:
            strong = float(data.get("strong", service.settings.strong_threshold))
            base = float(data.get("base", service.settings.base_threshold))
        except (TypeError, ValueError):
            return JSONResponse({"ok": False, "error": "sayı gerekli"}, status_code=400)
        if not (0 < base < 1) or not (base <= strong <= 1):
            return JSONResponse(
                {"ok": False, "error": "0 < AL/SAT <= GÜÇLÜ <= 1 olmalı"},
                status_code=400)
        service.update_thresholds(strong, base)
        return JSONResponse({"ok": True, "strong": strong, "base": base})

    async def api_reset_db(request: Request) -> Response:
        removed = store.reset()
        hub.broadcast_threadsafe({
            "type": "log", "ts": datetime.now().strftime("%H:%M:%S"),
            "level": "warning",
            "text": f"VERİTABANI SIFIRLANDI — {sum(removed.values())} kayıt silindi",
        })
        return JSONResponse({"ok": True, "removed": removed})

    async def api_refresh(request: Request) -> Response:
        service.request_full_refresh()
        return JSONResponse({"ok": True})

    # ------------------------------------------------------------------
    # Kaldirac simulasyonu uclari
    # ------------------------------------------------------------------
    def _paper_price() -> float:
        snap = service.snapshot()
        p = snap.get("price")
        if p is None or p != p:            # NaN
            return 0.0
        return float(p)

    def _need_paper() -> JSONResponse | None:
        if paper is None:
            return JSONResponse({"ok": False, "error": "simülatör yok"},
                                status_code=503)
        return None

    async def api_paper_start(request: Request) -> Response:
        err = _need_paper()
        if err:
            return err
        data = {}
        try:
            data = await request.json()
        except Exception:      # noqa: BLE001
            pass
        paper.configure(
            balance=_num(data.get("balance")),
            leverage=_num(data.get("leverage")),
            fee_rate=_num(data.get("fee_rate")),
            wallet_fraction=_num(data.get("wallet_fraction")),
            lookback=int(_num(data.get("lookback")) or 0) or None,
            confirm=data.get("confirm"),
            short_rule=data.get("short_rule"),
            mode=data.get("mode"),
            min_hold=int(_num(data.get("min_hold")) or 0),
            risk_pct=_num(data.get("risk_pct")),
            lock_pct=_num(data.get("lock_pct")),
            pull_atr=_num(data.get("pull_atr")),
        )
        # Mod degisince grafik yildizlarini yeni algoritmaya gore
        # hemen yeniden uretip gonder.
        service.force_mode_refresh()

        # "Gecmisten baslat": once grafikteki tum mumlar tekrar edilir,
        # boylece "simdiye kadar ne kadar kazanirdi" olculmus olur;
        # ardindan canli akis AYNI hesapla devam eder.
        want_bt = data.get("backtest", True)
        bt = None
        if not want_bt:
            # ---- "Trade Basla": YALNIZCA CANLI -----------------------------
            # Hesap verilen USDT ile sifirlanir; gecmis oynatilmaz.
            # Boylece kullanici yalnizca o andan sonraki kâr/zarari izler.
            paper.start_live()
            service._emit_log(
                "info", "simulator",
                f"CANLI İŞLEM BAŞLADI · {paper.leverage:g}x · teminat "
                f"%{paper.wallet_fraction*100:.0f} · komisyon "
                f"%{paper.fee_rate*100:.3f} · bakiye {paper.balance:,.2f} · "
                f"{paper.mode} modu")
        elif want_bt:
            # Dilimi ISTEMCIDEN al. Sunucudaki active_timeframe'e güvenmek
            # riskli: dilim degisimi WebSocket, baslatma REST ile gelir;
            # ikisi araya girerse yanlis dilimin gecmisi test edilir
            # (tarayicida bir adim geriden gittiği ölçüldü).
            tf = str(data.get("timeframe") or "")
            if tf not in service.settings.timeframes:
                tf = service.settings.active_timeframe
            candles = service.paper_candles(tf)
            if len(candles) > (paper.lookback + 1):
                # Sinyal bakan modlar gecmise ait sinyal dizisine ihtiyac duyar.
                # ("signal", "signal_long", "signal_exit" — aralik modu fiyatla
                #  calisir, sinyal dizisi gerekmez.)
                sig = service.paper_signals(tf) \
                    if paper.mode in ("signal", "signal_long",
                                      "signal_exit") else None
                bt = await asyncio.to_thread(paper.backtest, candles, tf, sig)
                service._emit_log(
                    "info", "simulator",
                    f"Geriye dönük test ({len(candles)} {tf} mum, "
                    f"{paper.mode} modu, {bt['elapsed_ms']} ms): "
                    f"{bt['trades']} işlem "
                    f"({bt['wins']} kazanç / {bt['losses']} kayıp) · "
                    f"net {bt['profit']:+,.2f} ({bt['return_pct']:+.2f}%)")
                service._emit_log(
                    "info", "simulator",
                    f"Hesap bugünkü durumda: bakiye {bt['balance']:,.2f} · "
                    f"equity {bt['equity']:,.2f}. Artık CANLI devam ediyor.")
            else:
                service._emit_log(
                    "warning", "simulator",
                    f"Geriye dönük test atlandı: {tf} için yalnızca "
                    f"{len(candles)} mum hazır (coin yeni yükleniyor olabilir).")
        paper.running = True

        if not want_bt:
            return JSONResponse({"ok": True,
                                 "state": paper.state(_paper_price()),
                                 "backtest": None, "mode": "live"})
        service._emit_log("info", "simulator",
                          f"Kaldıraç simülatörü BAŞLADI · "
                          f"{paper.leverage:g}x · teminat %{paper.wallet_fraction*100:.0f} · "
                          f"komisyon %{paper.fee_rate*100:.3f}")
        return JSONResponse({"ok": True, "state": paper.state(_paper_price()),
                             "backtest": bt})

    async def api_paper_stop(request: Request) -> Response:
        err = _need_paper()
        if err:
            return err
        paper.running = False
        service._emit_log("info", "simulator",
                          "Kaldıraç simülatörü duraklatıldı "
                          "(açık pozisyon korunuyor).")
        return JSONResponse({"ok": True, "state": paper.state(_paper_price())})

    async def api_paper_reset(request: Request) -> Response:
        err = _need_paper()
        if err:
            return err
        was_running = paper.running
        paper.reset(service.settings.symbol)
        paper.running = was_running
        service._emit_log("info", "simulator", "Simülatör sıfırlandı.")
        return JSONResponse({"ok": True, "state": paper.state(_paper_price())})

    async def api_paper_config(request: Request) -> Response:
        err = _need_paper()
        if err:
            return err
        data = await request.json()
        paper.configure(
            balance=_num(data.get("balance")),
            leverage=_num(data.get("leverage")),
            fee_rate=_num(data.get("fee_rate")),
            wallet_fraction=_num(data.get("wallet_fraction")),
            lookback=int(_num(data.get("lookback")) or 0) or None,
            confirm=data.get("confirm"),
            short_rule=data.get("short_rule"),
            mode=data.get("mode"),
            min_hold=int(_num(data.get("min_hold")) or 0),
            risk_pct=_num(data.get("risk_pct")),
            lock_pct=_num(data.get("lock_pct")),
            pull_atr=_num(data.get("pull_atr")),
        )
        service.force_mode_refresh()
        return JSONResponse({"ok": True, "state": paper.state(_paper_price())})

    # ------------------------------------------------------------------
    # Coin (sembol) degisimi
    # ------------------------------------------------------------------
    async def api_symbol(request: Request) -> Response:
        data = await request.json()
        symbol = str(data.get("symbol", "")).upper().strip()
        if not symbol:
            return JSONResponse({"ok": False, "error": "sembol boş"},
                                status_code=400)
        if symbol == service.settings.symbol:
            return JSONResponse({"ok": True, "symbol": symbol,
                                 "note": "zaten seçili"})

        hub.broadcast_threadsafe({
            "type": "log", "ts": datetime.now().strftime("%H:%M:%S"),
            "level": "warning",
            "text": f"{symbol} yükleniyor, mum geçmişi çekiliyor..."})

        ok, msg = await asyncio.to_thread(service.switch_symbol, symbol)
        if not ok:
            hub.broadcast_threadsafe({
                "type": "log", "ts": datetime.now().strftime("%H:%M:%S"),
                "level": "error", "text": f"Sembol değiştirilemedi: {msg}"})
            return JSONResponse({"ok": False, "error": msg}, status_code=400)

        hub.broadcast_threadsafe({
            "type": "symbol_changed", "symbol": symbol})
        hub.broadcast_threadsafe({
            "type": "log", "ts": datetime.now().strftime("%H:%M:%S"),
            "level": "ok", "text": f"Sembol değiştirildi → {symbol}"})
        return JSONResponse({"ok": True, "symbol": symbol})

    # ------------------------------------------------------------------
    async def ws_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        hub.bind_loop(asyncio.get_running_loop())
        await hub.register(ws, service.settings.active_timeframe)

        try:
            snap = service.snapshot()
            start_tf = hub.timeframe_of(ws)
            payload = _payload_for(start_tf, snap["price"])
            if payload is not None:
                await ws.send_text(json.dumps(payload, ensure_ascii=False,
                                              default=str))

            await ws.send_text(json.dumps({
                "type": "hello",
                "symbol": service.settings.symbol,
                "symbols": list(config.SYMBOLS),
                "timeframe": start_tf,
                "timeframes": list(service.settings.timeframes),
                "tf_labels": {tf: config.TF_LABELS.get(tf, tf)
                              for tf in service.settings.timeframes},
                "db_signals": store.count_signals(),
                "db_logs": store.count_logs(),
                "db_kb": store.disk_size_kb(),
            }, ensure_ascii=False))

            if paper is not None:
                await ws.send_text(json.dumps(
                    paper.state(_paper_price()), ensure_ascii=False,
                    default=str))

            # Son log satirlari: sayfa her acildiginda log paneli bos
            # kalmasin, kullanici son durumu gorebilsin.
            for row in store.recent_logs(40):
                await ws.send_text(json.dumps({
                    "type": "log",
                    "ts": str(row["created_at"])[-8:],
                    "level": row["level"],
                    "text": row["message"],
                }, ensure_ascii=False))

            while True:
                # Tarayicidan gelen mesajlar (dilim degisimi, esikler)
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                kind = msg.get("type")

                if kind == "set_thresholds":
                    await api_thresholds_from_msg(msg, service)

                elif kind == "set_timeframe":
                    tf = str(msg.get("tf", ""))
                    if tf not in service.settings.timeframes:
                        continue
                    await hub.set_timeframe(ws, tf)
                    # Yeni dilimin analizi henuz hazir olmayabilir;
                    # set_focus hemen yeniden hesaplama tetikler.
                    service.set_focus(tf)
                    snap = service.snapshot()
                    payload = _payload_for(tf, snap["price"])
                    if payload is not None:
                        await ws.send_text(json.dumps(payload, ensure_ascii=False,
                                                      default=str))
                    await ws.send_text(json.dumps({
                        "type": "timeframe_ack", "timeframe": tf,
                    }, ensure_ascii=False))

                elif kind == "refresh":
                    service.request_full_refresh()

                elif kind == "set_symbol":
                    symbol = str(msg.get("symbol", "")).upper().strip()
                    if not symbol or symbol == service.settings.symbol:
                        continue
                    ok, note = await asyncio.to_thread(
                        service.switch_symbol, symbol)
                    if ok:
                        hub.broadcast_threadsafe({
                            "type": "symbol_changed", "symbol": symbol})

        except WebSocketDisconnect:
            pass
        except Exception as exc:      # noqa: BLE001
            logger.info("ws kapandi: %s", exc)
        finally:
            await hub.unregister(ws)

    async def api_thresholds_from_msg(msg: dict, service: MarketService) -> None:
        try:
            strong = float(msg.get("strong"))
            base = float(msg.get("base"))
        except (TypeError, ValueError):
            return
        if 0 < base < 1 and base <= strong <= 1:
            service.update_thresholds(strong, base)

    # ------------------------------------------------------------------
    NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache"}

    # Uygulama dosyalari NO-CACHE: gelistirme sirasinda tarayici bayat
    # surumu gosterip "duzeltmeyi uyguladim ama degismiyor" durumu
    # yasatiyordu. Vendor (echarts) uzun sure onbelleklenebilir.
    async def static_file(request: Request) -> Response:
        name = request.path_params["name"]
        path = os.path.join(STATIC_DIR, name)
        if not os.path.isfile(path):
            return JSONResponse({"error": "bulunamadı"}, status_code=404)
        return FileResponse(path, headers=dict(NO_CACHE))

    # Service worker KOKTEN servis edilmek zorunda.
    #
    # Tarayici bir service worker'in kapsamini (scope) dosyanin bulundugu
    # dizinden turetir. /static/sw.js kovasi "/static/" olurdu; boylece
    # ana sayfayi (/ ) denetleyemez ve PWA calismazdi. Ayni dosyayi
    # /sw.js adresinden de sunuyoruz; boylece kapsam "/" olur.
    async def service_worker(request: Request) -> Response:
        return FileResponse(os.path.join(STATIC_DIR, "sw.js"),
                            headers=dict(NO_CACHE))

    # Manifest de PWA kurulum akisinda fetch ediliyor; yine kokservis.
    async def manifest(request: Request) -> Response:
        return FileResponse(
            os.path.join(STATIC_DIR, "manifest.webmanifest"),
            headers={**NO_CACHE,
                     "Content-Type": "application/manifest+json; charset=utf-8"})

    routes = [
        Route("/", index),
        Route("/api/state", api_state),
        Route("/api/thresholds", api_thresholds, methods=["POST"]),
        Route("/api/reset-db", api_reset_db, methods=["POST"]),
        Route("/api/refresh", api_refresh, methods=["POST"]),
        Route("/api/paper/start", api_paper_start, methods=["POST"]),
        Route("/api/paper/stop", api_paper_stop, methods=["POST"]),
        Route("/api/paper/reset", api_paper_reset, methods=["POST"]),
        Route("/api/paper/config", api_paper_config, methods=["POST"]),
        Route("/api/symbol", api_symbol, methods=["POST"]),
        Route("/static/{name}", static_file),
        Route("/sw.js", service_worker),
        Route("/manifest.webmanifest", manifest),
        WebSocketRoute("/ws", ws_endpoint),
    ]

    app = Starlette(routes=routes)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    # ------------------------------------------------------------------
    # Servis olaylarini (log/sinyal) tarayiciya yonlendir
    # ------------------------------------------------------------------
    async def pump_events() -> None:
        """MarketService kuyrugunu bosaltip tarayiciya yayar."""
        # surum -> tf haritasi: ayni dilim surumu degismedikce paket
        # yeniden uretilmez (76 KB x 3 x 2 Hz gereksiz trafik olurdu)
        sent: dict[str, int] = {}
        while True:
            try:
                event = service.events.get_nowait()
            except Exception:      # noqa: BLE001  (kuyruk bos)
                await asyncio.sleep(0.05)
                continue

            kind = event[0]
            if kind == "log":
                _, stamp, level, _cat, msg = event
                hub.broadcast_threadsafe({
                    "type": "log", "ts": stamp[-8:], "level": level,
                    "text": msg})
            elif kind == "status":
                _, level, msg = event
                hub.broadcast_threadsafe({
                    "type": "log", "ts": datetime.now().strftime("%H:%M:%S"),
                    "level": level, "text": msg})
            elif kind == "signal_log":
                _, stamp, sig, _tf, text = event
                hub.broadcast_threadsafe({
                    "type": "signal_log", "ts": stamp[-8:],
                    "signal": sig.value, "text": text})

            elif kind == "snapshot":
                snap = event[1]
                versions = snap.get("versions", {})
                price = snap.get("price", float("nan"))
                # Yalnizca su an bir istemcinin baktigi dilimler icin paket
                # uret; herkese gonderme.
                for tf in hub.used_timeframes():
                    res = snap.get("analyses", {}).get(tf)
                    if res is None:
                        continue
                    if sent.get(tf) == versions.get(tf):
                        continue
                    sent[tf] = versions.get(tf)
                    sigs = service.mode_signal_series(tf)
                    payload = candle_payload(res, price, sigs or None)
                    payload["strong_threshold"] = \
                        service.settings.strong_threshold
                    payload["base_threshold"] = \
                        service.settings.base_threshold
                    hub.send_to_timeframe_threadsafe(tf, payload)

    async def pump_ticks() -> None:
        """
        Fiyat tiklerini (HER ISLEM) tarayiciya yayar.

        Bu, "anlik" hissini veren asil kanal: tarayici fiyati mum yeniden
        cizilmeden aninda gosterir. (Masaustu matplotlib surumunde mum
        ancak ~1,5 Hz yenileniyordu; burada tik 4,5 msg/sn gelir.)

        Uc dilim de islenir ama yalnizca o dilimi gosteren istemciye gider.
        """
        while True:
            drained = False
            try:
                while True:
                    payload = service.ticks.get_nowait()
                    tf = payload.get("tf")
                    if not hub.clients_for(tf):
                        continue          # bu dilime bakan istemci yok
                    hub.send_to_timeframe_threadsafe(tf, payload)
                    drained = True
            except Exception:      # noqa: BLE001
                pass
            if not drained:
                await asyncio.sleep(0.02)

    async def pump_wallet() -> None:
        """
        Sanal cuzdan durumunu 1 Hz'de yayar.

        Kullanici cuzdani ANLIK izlemek istiyor: acik pozisyonun kâr/zarar
        degeri her islemle degisir. Bu yuzden durum ayri bir kanaldan,
        saniyede bir gonderilir; mum gecmisi (76 KB) tasinmaz.
        """
        while True:
            if paper is not None:
                try:
                    st = paper.state(_paper_price())
                    if not st["trades"] and st["position"] is None and \
                            not st["running"]:
                        pass                      # bos durum, gonderme
                    else:
                        hub.broadcast_threadsafe(st)
                except Exception:      # noqa: BLE001
                    pass
            await asyncio.sleep(1.0)

    # Starlette 1.x icinde on_startup/on_shutdown kaldirildi; lifespan.
    @contextlib.asynccontextmanager
    async def lifespan(_app):
        hub.bind_loop(asyncio.get_running_loop())
        tasks = [asyncio.create_task(pump_events()),
                 asyncio.create_task(pump_ticks()),
                 asyncio.create_task(pump_wallet())]
        # Servisi burada baslat: sayfa yuklenirken veri akisi hazir olsun
        if not service.running:
            service.start()
            app_state["started"] = True
        try:
            yield
        finally:
            for t in tasks:
                t.cancel()
            service.stop()

    app = Starlette(routes=routes, lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
