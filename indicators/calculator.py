"""
Teknik indikator hesaplayici.
TradingView 1dk "Technicals" sayfasindaki indikatorlerin Python karsiligi.

pandas-ta yoksa saf pandas/numpy fallback implementasyonu kullanilir.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Dict, Any, Optional

try:  # pragma: no cover
    import pandas_ta as ta

    HAS_PANDAS_TA = True
except Exception:  # pragma: no cover
    ta = None
    HAS_PANDAS_TA = False


# --------------------------------------------------------------------------
# Temel yardimci fonksiyonlar
# --------------------------------------------------------------------------

def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def sma(series: pd.Series, length: int) -> pd.Series:
    return series.rolling(length).mean()


def rma(series: pd.Series, length: int) -> pd.Series:
    """Wilder's smoothing (ADX/RSI icin)."""
    return series.ewm(alpha=1.0 / length, adjust=False).mean()


def wma(series: pd.Series, length: int) -> pd.Series:
    weights = np.arange(1, length + 1, dtype=float)
    return series.rolling(length).apply(lambda x: np.dot(x, weights) / weights.sum(), raw=True)


# --------------------------------------------------------------------------
# Osilatorler
# --------------------------------------------------------------------------

def rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = rma(gain, length)
    avg_loss = rma(loss, length)
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - (100.0 / (1.0 + rs))
    out = out.where(avg_loss != 0.0, 100.0)
    return out


def stoch(high: pd.Series, low: pd.Series, close: pd.Series,
          k_len: int = 14, k_smooth: int = 3, d_len: int = 3) -> tuple[pd.Series, pd.Series]:
    lowest = low.rolling(k_len).min()
    highest = high.rolling(k_len).max()
    raw_k = 100.0 * (close - lowest) / (highest - lowest).replace(0.0, np.nan)
    raw_k = raw_k.fillna(50.0)
    k = raw_k.rolling(k_smooth).mean()
    d = k.rolling(d_len).mean()
    return k, d


def cci(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 20) -> pd.Series:
    tp = (high + low + close) / 3.0
    ma = tp.rolling(length).mean()
    md = tp.rolling(length).apply(lambda x: np.mean(np.abs(x - np.mean(x))), raw=True)
    out = (tp - ma) / (0.015 * md.replace(0.0, np.nan))
    return out.replace([np.inf, -np.inf], np.nan)


def adx(high: pd.Series, low: pd.Series, close: pd.Series,
        length: int = 14) -> tuple[pd.Series, pd.Series, pd.Series]:
    up = high.diff()
    down = -low.diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=high.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=high.index)

    atr = rma(pd.concat([(high - low).abs(), (high - close.shift(1)).abs(),
                         (low - close.shift(1)).abs()], axis=1).max(axis=1), length)

    plus_di = 100.0 * rma(plus_dm, length) / atr.replace(0.0, np.nan)
    minus_di = 100.0 * rma(minus_dm, length) / atr.replace(0.0, np.nan)

    denom = (plus_di + minus_di).replace(0.0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / denom
    adx_line = rma(dx.fillna(0.0), length)
    # Wilder ADX ilk `2*length` bardan itibaren gecerli
    warmup = min(2 * length, len(adx_line))
    adx_line = adx_line.copy()
    adx_line.iloc[:warmup] = np.nan
    return adx_line, plus_di, minus_di


def awesome_oscillator(high: pd.Series, low: pd.Series, fast: int = 5, slow: int = 34) -> pd.Series:
    hl2 = (high + low) / 2.0
    return sma(hl2, fast) - sma(hl2, slow)


def momentum(close: pd.Series, length: int = 10) -> pd.Series:
    return close - close.shift(length)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def stoch_rsi(close: pd.Series, rsi_len: int = 14, stoch_len: int = 14,
              k: int = 3, d: int = 3) -> tuple[pd.Series, pd.Series]:
    r = rsi(close, rsi_len)
    lowest = r.rolling(stoch_len).min()
    highest = r.rolling(stoch_len).max()
    raw = 100.0 * (r - lowest) / (highest - lowest).replace(0.0, np.nan)
    raw = raw.fillna(50.0)
    k_line = raw.rolling(k).mean()
    d_line = k_line.rolling(d).mean()
    return k_line, d_line


def williams_r(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    highest = high.rolling(length).max()
    lowest = low.rolling(length).min()
    return -100.0 * (highest - close) / (highest - lowest).replace(0.0, np.nan)


def bull_bear_power(high: pd.Series, low: pd.Series, close: pd.Series,
                     length: int = 13) -> tuple[pd.Series, pd.Series]:
    basis = ema(close, length)
    return high - basis, low - basis


def ultimate_oscillator(high: pd.Series, low: pd.Series, close: pd.Series,
                        fast: int = 7, medium: int = 14, slow: int = 28) -> pd.Series:
    prev_close = close.shift(1)
    bp = close - np.minimum(low, prev_close)
    tr = np.maximum(high, prev_close) - np.minimum(low, prev_close)
    tr = tr.replace(0.0, np.nan)

    def avg(n: int) -> pd.Series:
        return pd.Series(bp).rolling(n).sum() / pd.Series(tr).rolling(n).sum()

    f, m, s = avg(fast), avg(medium), avg(slow)
    return 100.0 * (4.0 * f + 2.0 * m + 1.0 * s) / 7.0


# --------------------------------------------------------------------------
# Hareketli ortalamalar
# --------------------------------------------------------------------------

def vwma(close: pd.Series, volume: pd.Series, length: int = 20) -> pd.Series:
    pv = (close * volume).rolling(length).sum()
    v = volume.rolling(length).sum().replace(0.0, np.nan)
    return pv / v


def hma(close: pd.Series, length: int = 9) -> pd.Series:
    half = max(1, length // 2)
    sqrt_len = int(np.sqrt(length))
    return wma(2.0 * wma(close, half) - wma(close, length), sqrt_len)


def ichimoku(high: pd.Series, low: pd.Series,
             tenkan_len: int = 9, kijun_len: int = 26, senkou_b_len: int = 52):
    def midpoint(n: int) -> pd.Series:
        return (high.rolling(n).max() + low.rolling(n).min()) / 2.0

    tenkan = midpoint(tenkan_len)
    kijun = midpoint(kijun_len)
    senkou_a = ((tenkan + kijun) / 2.0).shift(kijun_len)
    senkou_b = midpoint(senkou_b_len).shift(kijun_len)
    return tenkan, kijun, senkou_a, senkou_b


# --------------------------------------------------------------------------
# Pivot hesaplama (gunluk)
# --------------------------------------------------------------------------

def classic_pivots(high: float, low: float, close: float) -> Dict[str, float]:
    """Classic pivot points (onceki gun OHLC'ten)."""
    if any(pd.isna(v) for v in (high, low, close)):
        return {}
    p = (high + low + close) / 3.0
    return {
        "pivot": p,
        "r1": 2 * p - low,
        "s1": 2 * p - high,
        "r2": p + (high - low),
        "s2": p - (high - low),
        "r3": high + 2 * (p - low),
        "s3": low - 2 * (high - p),
    }


# --------------------------------------------------------------------------
# Ana hesaplayici
# --------------------------------------------------------------------------

class IndicatorsCalculator:
    """OHLCV DataFrame'ine tum teknik indikatorleri ekler."""

    MA_PERIODS = [10, 20, 30, 50, 100, 200]

    def __init__(self, config=None):
        self.config = config

    # ------------------------------------------------------------------
    def calculate_all(self, df: pd.DataFrame) -> pd.DataFrame:
        cfg = self.config
        rsi_len = getattr(cfg, "rsi_period", 14) if cfg else 14
        cci_len = getattr(cfg, "cci_period", 20) if cfg else 20
        adx_len = getattr(cfg, "adx_period", 14) if cfg else 14
        macd_fast = getattr(cfg, "macd_fast", 12) if cfg else 12
        macd_slow = getattr(cfg, "macd_slow", 26) if cfg else 26
        macd_sig = getattr(cfg, "macd_signal", 9) if cfg else 9

        if df is None or len(df) < 60:
            return df

        out = df.copy()
        high, low, close, volume = out["high"], out["low"], out["close"], out["volume"]

        # Osilatorler
        out["rsi"] = rsi(close, rsi_len)
        out["stoch_k"], out["stoch_d"] = stoch(high, low, close)
        out["cci"] = cci(high, low, close, cci_len)
        out["adx"], out["di_plus"], out["di_minus"] = adx(high, low, close, adx_len)
        out["ao"] = awesome_oscillator(high, low)
        out["momentum"] = momentum(close, 10)
        out["macd"], out["macd_signal"], out["macd_hist"] = macd(close, macd_fast, macd_slow, macd_sig)
        out["stoch_rsi_k"], out["stoch_rsi_d"] = stoch_rsi(close)
        out["williams_r"] = williams_r(high, low, close)
        out["bull_power"], out["bear_power"] = bull_bear_power(high, low, close)
        out["uo"] = ultimate_oscillator(high, low, close)

        # Hareketli ortalamalar
        for period in self.MA_PERIODS:
            out[f"ema_{period}"] = ema(close, period)
            out[f"sma_{period}"] = sma(close, period)

        (out["ichimoku_tenkan"], out["ichimoku_kijun"],
         out["ichimoku_senkou_a"], out["ichimoku_senkou_b"]) = ichimoku(high, low)

        out["vwma"] = vwma(close, volume)
        out["hull_ma"] = hma(close)

        # Pivotlar (gunluk) - bilesik skora %20 agirlikla katilir
        self._add_pivots(out)

        return out

    # ------------------------------------------------------------------
    @staticmethod
    def _add_pivots(df: pd.DataFrame) -> None:
        """Gunluk pivotlari mevcut timeframe verisine ilerletir.

        Not: 4h'de gunlik pivot gunluk OHLC'ten hesaplanip ayni gune
        ait tum 4h barlarina uygulanir.
        """
        daily = df.resample("D").agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum",
        }).dropna()

        if len(daily) < 2:
            for col in ("pivot", "r1", "r2", "r3", "s1", "s2", "s3"):
                df[col] = np.nan
            return

        prev_h = daily["high"].shift(1)
        prev_l = daily["low"].shift(1)
        prev_c = daily["close"].shift(1)

        p = (prev_h + prev_l + prev_c) / 3.0
        levels = {
            "pivot": p,
            "r1": 2 * p - prev_l,
            "s1": 2 * p - prev_h,
            "r2": p + (prev_h - prev_l),
            "s2": p - (prev_h - prev_l),
            "r3": prev_h + 2 * (p - prev_l),
            "s3": prev_l - 2 * (prev_h - p),
        }

        day_index = df.index.normalize()
        for name, series in levels.items():
            df[name] = day_index.map(series)

    # ------------------------------------------------------------------
    def get_latest(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Son satirdaki tum indikator degerlerini sozluk olarak dondurur."""
        if df is None or len(df) == 0:
            return {}

        row = df.iloc[-1]
        values: Dict[str, Any] = {
            "timestamp": df.index[-1],
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
        }

        indicator_cols = [
            "rsi", "stoch_k", "stoch_d", "cci", "adx", "di_plus", "di_minus",
            "ao", "momentum", "macd", "macd_signal", "macd_hist",
            "stoch_rsi_k", "stoch_rsi_d", "williams_r",
            "bull_power", "bear_power", "uo",
            "ichimoku_tenkan", "ichimoku_kijun",
            "ichimoku_senkou_a", "ichimoku_senkou_b",
            "vwma", "hull_ma",
            "pivot", "r1", "r2", "r3", "s1", "s2", "s3",
        ]
        for period in self.MA_PERIODS:
            indicator_cols += [f"ema_{period}", f"sma_{period}"]

        for col in indicator_cols:
            if col in df.columns:
                v = row[col]
                values[col] = float(v) if pd.notna(v) else float("nan")

        return values


# --------------------------------------------------------------------------
# TradingView yorumlama kurallari
# --------------------------------------------------------------------------

def interpret_oscillator(name: str, value: float) -> str:
    """Tek bir osilator icin 'buy' / 'sell' / 'neutral' dondurur."""
    if value is None or pd.isna(value):
        return "neutral"

    if name == "rsi":
        if value >= 70:
            return "sell"          # asiri alim
        if value <= 30:
            return "buy"           # asiri satim
        return "neutral"

    if name in ("stoch_k", "stoch_rsi_k"):
        if value >= 80:
            return "sell"
        if value <= 20:
            return "buy"
        return "neutral"

    if name == "cci":
        if value >= 100:
            return "sell"
        if value <= -100:
            return "buy"
        return "neutral"

    if name == "adx":
        return "buy" if value >= 25 else "neutral"   # trend guclu

    if name == "ao":
        return "buy" if value > 0 else "sell"

    if name == "momentum":
        return "buy" if value > 0 else "sell"

    if name == "macd":
        return "buy" if value > 0 else "sell"

    if name == "macd_hist":
        return "buy" if value > 0 else "sell"

    if name == "williams_r":
        if value >= -20:
            return "sell"
        if value <= -80:
            return "buy"
        return "neutral"

    if name == "bull_power":
        return "buy" if value > 0 else "neutral"

    if name == "bear_power":
        return "sell" if value < 0 else "neutral"

    if name == "uo":
        if value >= 70:
            return "sell"
        if value <= 30:
            return "buy"
        return "neutral"

    if name == "di_plus":
        return "buy" if value > 20 else "neutral"

    if name == "di_minus":
        return "sell" if value > 20 else "neutral"

    return "neutral"


def interpret_ma(price: float, ma_value: float) -> str:
    """Fiyat MA'nin ustundeyse buy, altindaysa sell."""
    if ma_value is None or pd.isna(ma_value) or pd.isna(price):
        return "neutral"
    return "buy" if price > ma_value else "sell"


def interpret_pivot(price: float, levels: Dict[str, float]) -> str:
    """Fiyatin pivot seviyelerine gore konumu."""
    pivot = levels.get("pivot")
    if pivot is None or pd.isna(pivot) or pd.isna(price):
        return "neutral"
    if price > pivot:
        return "buy"
    if price < pivot:
        return "sell"
    return "neutral"
