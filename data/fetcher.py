"""
Binance Futures'tan OHLCV veri cekme (CCXT).
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

import pandas as pd

from config import CACHE_DIR, TRADING_CONFIG

logger = logging.getLogger(__name__)

TF_MS = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}

COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


class DataFetcher:
    """CCXT uzerinden Binance USDT-M futures verisi."""

    def __init__(self, config: TRADING_CONFIG = None):
        self.config = config or TRADING_CONFIG
        self._exchange = None

    # ------------------------------------------------------------------
    @property
    def exchange(self):
        if self._exchange is None:
            self._connect()
        return self._exchange

    def _connect(self):
        import ccxt

        if self.config.exchange_id == "binance":
            self._exchange = ccxt.binance({
                "enableRateLimit": True,
                "options": {"defaultType": self.config.market_type},
            })
        else:
            exchange_cls = getattr(ccxt, self.config.exchange_id)
            self._exchange = exchange_cls({
                "enableRateLimit": True,
                "options": {"defaultType": self.config.market_type},
            })

        self._exchange.load_markets()
        logger.info("Borsaya baglanildi: %s (%s)", self.config.exchange_id, self.config.market_type)

    # ------------------------------------------------------------------
    def fetch_ohlcv(self, limit: Optional[int] = None,
                    symbol: Optional[str] = None,
                    timeframe: Optional[str] = None) -> pd.DataFrame:
        """Son N mumu getirir. Limit > 1500 ise otomatik sayfalar."""
        symbol = symbol or self.config.symbol
        timeframe = timeframe or self.config.timeframe
        limit = limit or self.config.lookback_candles

        step = TF_MS.get(timeframe, 60_000)
        max_per_request = 1500

        if limit <= max_per_request:
            return self._to_dataframe(
                self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit))

        # sayfalama: en eski mumun bulundugu zaman diliminden geriye dogru git
        end_ms = self._server_time_ms()
        start_ms = end_ms - limit * step

        frames: list[pd.DataFrame] = []
        cursor = start_ms
        guard = 0
        while cursor < end_ms and guard < 40:
            guard += 1
            batch = self.exchange.fetch_ohlcv(symbol, timeframe,
                                              since=cursor, limit=max_per_request)
            if not batch:
                break
            frames.append(self._to_dataframe(batch))
            last = int(batch[-1][0])
            if last <= cursor:
                break                       # ilerleme yok, cik
            cursor = last + step
            if len(batch) < 200:
                break                       # veri sonu

        if not frames:
            return pd.DataFrame(columns=COLUMNS[1:])

        out = pd.concat(frames)
        out = out[~out.index.duplicated(keep="last")].sort_index()
        return out.tail(limit)

    def fetch_since(self, since_ms: int, symbol: Optional[str] = None,
                    timeframe: Optional[str] = None) -> pd.DataFrame:
        """since (ms) sonrasindaki mumlari getirir."""
        symbol = symbol or self.config.symbol
        timeframe = timeframe or self.config.timeframe

        raw = self.exchange.fetch_ohlcv(symbol, timeframe, since=since_ms, limit=1500)
        return self._to_dataframe(raw)

    def fetch_range(self, start: str, end: str, symbol: Optional[str] = None,
                    timeframe: Optional[str] = None,
                    use_cache: bool = True) -> pd.DataFrame:
        """Tarih araligindaki tum mumlari toplar (backtest icin).

        use_cache=True ise sonuc CSV olarak saklanir; ayni aralik tekrar
        istenirse agdan yeniden cekilmez.
        """
        symbol = symbol or self.config.symbol
        timeframe = timeframe or self.config.timeframe
        step = TF_MS.get(timeframe, 60_000)

        cache_file = self._cache_path(symbol, timeframe, start, end)
        if use_cache and os.path.exists(cache_file):
            try:
                cached = pd.read_csv(cache_file, parse_dates=["timestamp"])
                cached.set_index("timestamp", inplace=True)
                logger.info("Onbellekten yuklendi: %s (%d mum)", cache_file, len(cached))
                return cached
            except Exception as exc:
                logger.warning("Onbellek okunamadi (%s), yeniden cekilecek", exc)

        start_ms = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
        end_ms = int(pd.Timestamp(end, tz="UTC").timestamp() * 1000)

        frames: list[pd.DataFrame] = []
        cursor = start_ms
        max_per_request = 1500
        guard = 0

        while cursor < end_ms and guard < 400:
            guard += 1
            batch = self.exchange.fetch_ohlcv(symbol, timeframe,
                                              since=cursor, limit=max_per_request)
            if not batch:
                break

            frames.append(self._to_dataframe(batch))
            last_ms = int(batch[-1][0])
            if last_ms <= cursor:
                break
            cursor = last_ms + step

            if len(batch) < 200:
                break
            time.sleep(self.exchange.rateLimit / 1000)

        if not frames:
            return pd.DataFrame(columns=COLUMNS[1:])

        out = pd.concat(frames)
        out = out[~out.index.duplicated(keep="last")].sort_index()
        out = out[out.index <= pd.Timestamp(end_ms, unit="ms", tz="UTC")]

        if use_cache and not out.empty:
            try:
                out.reset_index().to_csv(cache_file, index=False)
                logger.info("Onbellege yazildi: %s (%d mum)", cache_file, len(out))
            except Exception as exc:
                logger.warning("Onbellege yazilamadi: %s", exc)

        return out

    # ------------------------------------------------------------------
    @staticmethod
    def _cache_path(symbol: str, timeframe: str, start: str, end: str) -> str:
        safe = symbol.replace("/", "_").replace(":", "-")
        name = f"{safe}_{timeframe}_{start}_{end}.csv"
        return os.path.join(CACHE_DIR, name)

    # ------------------------------------------------------------------
    def _server_time_ms(self) -> int:
        """Borsa sunucu zamani (ms). Hata olursa yerel saat."""
        try:
            t = self.exchange.fetch_time()
            if isinstance(t, dict):
                return int(t["timestamp"])
            return int(t)
        except Exception:
            return int(time.time() * 1000)

    # ------------------------------------------------------------------
    # CANLI FIYAT (emir fiyatlari buradan gelir, mum kapanisindan DEGIL)
    # ------------------------------------------------------------------
    def get_last_price(self, symbol: Optional[str] = None) -> Optional[float]:
        """Anlik son islem fiyati. CCXT fetch_ticker yerine dogrusur
        REST ucu kullanilir: olcumde 0.27s (fetch_ticker ~0.28s, ikisi de
        hizli; ama ticker bazi durumlarda marketi yeniden tarar)."""
        symbol = symbol or self.config.symbol
        try:
            raw = self.exchange.fapiPublicGetTickerPrice(
                {"symbol": self.config.display_symbol})
            return float(raw["price"])
        except Exception:
            try:
                return float(self.exchange.fetch_ticker(symbol)["last"])
            except Exception as exc:
                logger.error("Fiyat alinamadi: %s", exc)
                return None

    def get_mark_price(self, symbol: Optional[str] = None) -> Optional[float]:
        """Vadeli islemde PnL ve likidasyon icin MARK PRICE.

        Son islem fiyati degil, borsanin likidasyonu hesapladigi fiyattir.
        Bot PnL'i bununla degerlendirmelidir."""
        return self.get_market_info(symbol)[0]

    def get_market_info(self, symbol: Optional[str] = None):
        """(mark_price, index_price, funding_rate) - tek istekte.

        premiumIndex ucu mark + index + fonlama oranini birlikte dondurur;
        ayri ticker cagrisi yapmaya gerek kalmaz.
        """
        try:
            raw = self.exchange.fapiPublicGetPremiumIndex(
                {"symbol": self.config.display_symbol})
            return (float(raw["markPrice"]),
                    float(raw.get("indexPrice", 0.0) or 0.0),
                    float(raw.get("lastFundingRate", 0.0) or 0.0))
        except Exception as exc:
            logger.debug("premiumIndex alinamadi (%s)", exc)
            p = self.get_last_price(symbol)
            return p, p, 0.0

    def get_bid_ask(self, symbol: Optional[str] = None):
        """(bid, ask) - gercek emir degerlendirmesi icin."""
        symbol = symbol or self.config.symbol
        try:
            t = self.exchange.fetch_ticker(symbol)
            return float(t["bid"]), float(t["ask"])
        except Exception:
            p = self.get_last_price(symbol)
            return p, p

    def fetch_new_candles(self, last_timestamp,
                          symbol: Optional[str] = None,
                          timeframe: Optional[str] = None) -> pd.DataFrame:
        """Yalnizca son zamandan sonraki YENI mumlari getirir.

        Canli modda her tur 5000 mum indirmek yerine sadece yeni bar
        alinir: tek istek, ~0.3s.
        """
        symbol = symbol or self.config.symbol
        timeframe = timeframe or self.config.timeframe
        step = TF_MS.get(timeframe, 60_000)

        since_ms = None
        if last_timestamp is not None:
            since_ms = int(pd.Timestamp(last_timestamp).timestamp() * 1000)

        raw = self.exchange.fetch_ohlcv(symbol, timeframe, since=since_ms,
                                        limit=500)
        df = self._to_dataframe(raw)
        if df.empty:
            return df

        # son mum yarim kalmis olabilir -> bar kapanisinda tekrar alinacak
        if last_timestamp is not None:
            df = df[df.index > pd.Timestamp(last_timestamp)]
        return df

    # ------------------------------------------------------------------
    @staticmethod
    def _to_dataframe(raw: list) -> pd.DataFrame:
        if not raw:
            return pd.DataFrame(columns=COLUMNS[1:])

        df = pd.DataFrame(raw, columns=COLUMNS)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("timestamp", inplace=True)
        for col in COLUMNS[1:]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df
