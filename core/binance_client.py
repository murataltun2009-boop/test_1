"""
Binance Futures (fapi.binance.com) veri erisimi.

- REST  : mum gecmisi (klines) ve anlik fiyat
- WS    : secili zaman dilimleri icin canli mum akisi

Tum ag islemleri ayri thread'lerde yapilir; arayuz kuyruk uzerinden beslenir.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import requests

import config


# --------------------------------------------------------------------------
# Mum modeli
# --------------------------------------------------------------------------
@dataclass
class Candle:
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int
    closed: bool

    def to_dict(self) -> dict:
        return {
            "open_time": self.open_time,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "close_time": self.close_time,
            "closed": self.closed,
        }


@dataclass
class Trade:
    """Tek bir islem (Binance @trade akisi)."""

    time_ms: int
    price: float
    qty: float
    buyer_is_maker: bool


def candle_from_payload(k: list) -> Candle:
    """
    Binance klines dizisinden Candle uretir.

    ONEMLI - sifir deger onarimi:
    ----------------------------------------------
    Olcumde goruldu: yeni acilan oluşan mumda Binance arada bir
    ``low=0`` ve ``close=0`` gonderiyor (acilis ve zirve gercek):

        ac=82790.0  yis=82795.2  dus=0.0  kap=0.0

    Bu degerler oldugunda:
      * mum araliginin alt ucu 0'a cekilir,
      * Y ekseni 0'a dogru uzar,
      * RSI/CCI/MACD gibi gostergeler tamamen bozulur,
      * "fiyat pencerenin en tabaninda" testi her zaman tetiklenir
        (konum = (fiyat-0)/(zirve-0) ~ %100).

    Bu yuzden mum onarilir: gecersiz olan herhangi bir fiyat, acilisa
    sabitlenir ve yuksek/dusuk tutarliligi yeniden kurulur.
    """
    o = float(k[1]); h = float(k[2]); l = float(k[3]); c = float(k[4])

    def sane(x: float) -> bool:
        return x == x and x > 0 and x != float("inf") and x != float("-inf")

    if not sane(o):                      # acilis bile gecersizse mumu at
        o = h = l = c = 0.0
    if not sane(h):
        h = max(o, c if sane(c) else o)
    if not sane(l):
        l = min(o, c if sane(c) else o)
    if not sane(c):
        c = o

    # H/L tum mumu saracak sekilde duzelt (ECharts ve indikator bunu bekler)
    h = max(h, o, c)
    l = min(l, o, c)
    if l <= 0:
        l = min(o, c)

    return Candle(
        open_time=int(k[0]),
        open=o,
        high=h,
        low=l,
        close=c,
        volume=float(k[5]),
        close_time=int(k[6]),
        closed=True,
    )


class BinanceFuturesClient:
    """REST + WebSocket istemcisi. Thread-safe degildir; tek thread kullanir."""

    def __init__(self, symbol: str = config.SYMBOL, timeout: float = 15.0):
        self.symbol = symbol.upper()
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "btcusdt-ta-live/1.0"})
        self._ws = None

    # ------------------------------------------------------------------
    # REST
    # ------------------------------------------------------------------
    def fetch_klines(self, interval: str, limit: int = config.CANDLE_LIMIT) -> list[Candle]:
        url = f"{config.FAPI_REST}/fapi/v1/klines"
        params = {"symbol": self.symbol, "interval": interval, "limit": limit}
        last_error: Optional[Exception] = None

        for attempt in range(3):
            try:
                r = self.session.get(url, params=params, timeout=self.timeout)
                if r.status_code == 429:
                    raise RuntimeError("Binance hiz siniri (429), bekleniyor...")
                if r.status_code == 418:
                    raise RuntimeError("Binance IP bani (418). IP adresin gecici olarak engellendi.")
                r.raise_for_status()
                data = r.json()
                if not isinstance(data, list) or not data:
                    raise RuntimeError("Binance bos mum listesi döndü.")
                candles = [candle_from_payload(k) for k in data]
                # Ikinci savunma katmani: onarim sonrasi hala bozuk kalan
                # mum varsa dusur (gosterge zincirine 0 sizmasin).
                candles = [c for c in candles
                           if c.open > 0 and c.high > 0
                           and c.low > 0 and c.close > 0]
                if not candles:
                    raise RuntimeError("Binance bos mum listesi dondu.")
                # Son mum hâlâ oluşuyorsa isaretle
                now_ms = int(time.time() * 1000)
                if candles and candles[-1].close_time > now_ms:
                    candles[-1].closed = False
                return candles
            except Exception as exc:      # noqa: BLE001
                last_error = exc
                time.sleep(0.8 * (attempt + 1))

        raise RuntimeError(f"Mum verisi alınamadı ({interval}): {last_error}")

    def fetch_price(self) -> float:
        url = f"{config.FAPI_REST}/fapi/v1/ticker/price"
        r = self.session.get(url, params={"symbol": self.symbol}, timeout=self.timeout)
        r.raise_for_status()
        return float(r.json()["price"])

    def server_time_offset_ms(self) -> int:
        """Yerel saat ile Binance sunucu saati arasindaki fark (ms)."""
        try:
            t0 = int(time.time() * 1000)
            r = self.session.get(f"{config.FAPI_REST}/fapi/v1/time", timeout=self.timeout)
            t1 = int(time.time() * 1000)
            server = int(r.json()["serverTime"])
            return server - (t0 + (t1 - t0) // 2)
        except Exception:      # noqa: BLE001
            return 0

    # ------------------------------------------------------------------
    # WebSocket
    # ------------------------------------------------------------------
    def stream_trades(self,
                      on_trade: Callable[[Trade], None],
                      on_status: Callable[[str, str], None],
                      stop_event: threading.Event) -> None:
        """
        Canli ISLEM (trade) akisini dinler.

        NEDEN @kline DEGIL?
        --------------------
        Bu makinede olculdu:

            @kline_4h    30 sn  ->  0 mesaj
            @kline_1m    20 sn  ->  0 mesaj
            @aggTrade    20 sn  ->  0 mesaj
            @miniTicker  20 sn  ->  0 mesaj
            @trade       20 sn  ->  91 mesaj  (4,5 msg/sn)   <-- calisiyor

        Kline akisi bu ortamda tamamen sessiz kaliyor (WebSocket handshake
        basarili, sonra hic kare gelmiyor). Bu yuzden mumlar REST'ten
        aliniyor ve OLUSAN mum trade akisinden kendimiz kuruluyor: her
        islem fiyat/yuksek/dusuk/hacim degerlerini guncelleyerek son barin
        degerlerini birebir yeniden uretir.

        Bu yol her agda calisir ve kline akisindan daha kucuk gecikme verir.
        """
        try:
            import websocket  # websocket-client
        except ImportError:
            on_status("error",
                      "websocket-client kurulu degil; REST ile devam ediliyor.")
            return

        stream = f"{self.symbol.lower()}@trade"
        url = f"{config.FAPI_WS}{stream}"
        last_status = ""

        while not stop_event.is_set():
            try:
                on_status("connecting", f"WebSocket baglaniliyor: {stream}")
                self._ws = websocket.create_connection(
                    url, timeout=20, enable_multithread=False)
                on_status("connected", "Canli islem akisi baglandi.")

                while not stop_event.is_set():
                    try:
                        raw = self._ws.recv()
                    except Exception as exc:      # noqa: BLE001
                        raise ConnectionError(str(exc)) from exc

                    if raw is None:
                        continue
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8", errors="ignore")
                    if raw == "pong":
                        continue

                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    d = msg.get("data", {})
                    if d.get("e") != "trade":
                        continue

                    try:
                        on_trade(Trade(
                            time_ms=int(d["T"]),
                            price=float(d["p"]),
                            qty=float(d["q"]),
                            buyer_is_maker=bool(d["m"]),
                        ))
                    except (KeyError, TypeError, ValueError):
                        continue

            except Exception as exc:      # noqa: BLE001
                msg = str(exc)
                if last_status != msg:
                    on_status("error", f"WebSocket kesildi: {msg} - "
                                       f"{config.WS_RECONNECT_SECONDS}sn sonra tekrar denenecek")
                    last_status = msg
            finally:
                self._close_ws()

            stop_event.wait(config.WS_RECONNECT_SECONDS)

        on_status("closed", "WebSocket kapatildi.")

    def ping(self) -> bool:
        try:
            r = self.session.get(f"{config.FAPI_REST}/fapi/v1/ping", timeout=self.timeout)
            return r.status_code == 200
        except Exception:      # noqa: BLE001
            return False

    def _close_ws(self) -> None:
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:      # noqa: BLE001
                pass
            self._ws = None