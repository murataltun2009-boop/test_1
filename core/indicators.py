"""
Teknik indikatorler - saf numpy.

Bilerek pandas kullanmam; boylece surum farkliliklarindan etkilenmez ve
kucuk veri kumesinde (500 bar) hizli calisir.

Butun fonksiyonlar girdiyle ayni uzunlukta float64 dizi dondurur; yeterli
veri olmayan baslangic barlari NaN ile doldurulur.
"""
from __future__ import annotations

import numpy as np

# NaN'i tamamen yaymayan kaydirma penceresi (strict) -------------------------------------
_SW = np.lib.stride_tricks.sliding_window_view


def _f(x) -> np.ndarray:
    """Girdiyi 1-D float64 diziye cevirir."""
    return np.asarray(x, dtype=np.float64).ravel()


# Diger modullerin kullanabilmesi icin acik isim.
to_float = _f


# --------------------------------------------------------------------------
# Temel yardimcilar
# --------------------------------------------------------------------------
def rolling_mean(x: np.ndarray, n: int) -> np.ndarray:
    """Basit hareketli ortalama. NaN tasiyorsa sonuc NaN kalir (strict)."""
    x = _f(x)
    out = np.full(x.size, np.nan)
    if x.size < n or n < 1:
        return out
    win = _SW(x, n)                      # (size-n+1, n)
    out[n - 1:] = win.mean(axis=1)
    return out


def rolling_sum(x: np.ndarray, n: int) -> np.ndarray:
    x = _f(x)
    out = np.full(x.size, np.nan)
    if x.size < n:
        return out
    win = _SW(x, n)
    out[n - 1:] = win.sum(axis=1)
    return out


def rolling_max(x: np.ndarray, n: int) -> np.ndarray:
    x = _f(x)
    out = np.full(x.size, np.nan)
    if x.size < n:
        return out
    out[n - 1:] = _SW(x, n).max(axis=1)
    return out


def rolling_min(x: np.ndarray, n: int) -> np.ndarray:
    x = _f(x)
    out = np.full(x.size, np.nan)
    if x.size < n:
        return out
    out[n - 1:] = _SW(x, n).min(axis=1)
    return out


def rolling_abs_deviation(x: np.ndarray, ma: np.ndarray, n: int) -> np.ndarray:
    """|x - ma| serisinin n barlik ortalamasi (CCI'nin mean deviation'i)."""
    d = np.abs(_f(x) - _f(ma))
    return rolling_mean(d, n)


def sma(x, n: int) -> np.ndarray:
    return rolling_mean(x, n)


def ema(x, n: int) -> np.ndarray:
    """Ustel hareketli ortalama, ilk deger(n) ortalamasi ile tohumlanir."""
    x = _f(x)
    out = np.full(x.size, np.nan)
    if x.size < n or n < 1:
        return out
    alpha = 2.0 / (n + 1.0)
    acc = x[:n].mean()
    out[n - 1] = acc
    for i in range(n, x.size):
        acc = alpha * x[i] + (1.0 - alpha) * acc
        out[i] = acc
    return out


def rma(x, n: int) -> np.ndarray:
    """Wilder yumusatmasi (RSI/ADX icin). alpha = 1/n."""
    x = _f(x)
    out = np.full(x.size, np.nan)
    if x.size < n or n < 1:
        return out
    alpha = 1.0 / n
    acc = x[:n].mean()
    out[n - 1] = acc
    for i in range(n, x.size):
        acc = alpha * x[i] + (1.0 - alpha) * acc
        out[i] = acc
    return out


def wma(x, n: int) -> np.ndarray:
    """Agirlikli hareketli ortalama (Hull MA icin)."""
    x = _f(x)
    out = np.full(x.size, np.nan)
    if x.size < n or n < 1:
        return out
    w = np.arange(1.0, n + 1.0)
    win = _SW(x, n)                      # (size-n+1, n)
    out[n - 1:] = win @ w / w.sum()
    return out


def shift(x, n: int) -> np.ndarray:
    x = _f(x)
    out = np.full(x.size, np.nan)
    if n <= 0:
        return x.copy()
    if x.size > n:
        out[n:] = x[:-n]
    return out


def _nan_safe(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.divide(a, b, out=np.full(np.broadcast(a, b).shape, np.nan),
                     where=(b != 0) & np.isfinite(b))


# --------------------------------------------------------------------------
# Osilatorler
# --------------------------------------------------------------------------
def rsi(close, n: int = 14) -> np.ndarray:
    """Goreceli Guc Endeksi - Wilder yumusatmasi."""
    c = _f(close)
    out = np.full(c.size, np.nan)
    if c.size < n + 1:
        return out
    d = np.diff(c)                                   # ilk bari haric
    g = np.clip(d, 0.0, None)
    loss = np.clip(-d, 0.0, None)
    ag = rma(g, n)
    al = rma(loss, n)
    rs = _nan_safe(ag, al)
    out[1:] = np.where(al == 0.0, 100.0, 100.0 - 100.0 / (1.0 + rs))
    return out


def stochastic_k(high, low, close, k_len: int = 14,
                 smooth: int = 3) -> np.ndarray:
    """Stokastik %K (14, 3, 3) - %K isicisi 3 barla yumusatilir."""
    hh = rolling_max(high, k_len)
    ll = rolling_min(low, k_len)
    span = hh - ll
    raw = np.where(span > 0, 100.0 * (_f(close) - ll) / np.where(span > 0, span, 1.0), np.nan)
    return rolling_mean(raw, smooth)


def cci(high, low, close, n: int = 20) -> np.ndarray:
    """Emtia Kanal Endeksi."""
    h, l, c = _f(high), _f(low), _f(close)
    tp = (h + l + c) / 3.0
    ma = rolling_mean(tp, n)
    md = rolling_abs_deviation(tp, ma, n)
    return _nan_safe(tp - ma, 0.015 * md)


def adx(high, low, close, n: int = 14):
    """Ortalama Yonsel Endeks -> (adx, +DI, -DI)"""
    h, l, c = _f(high), _f(low), _f(close)
    if h.size < 2 * n + 2:
        nan = np.full(h.size, np.nan)
        return nan, nan.copy(), nan.copy()

    prev_c = shift(c, 1)
    up = h - shift(h, 1)
    dn = shift(l, 1) - l

    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    plus_dm[0] = 0.0
    minus_dm[0] = 0.0
    plus_dm[~np.isfinite(plus_dm)] = 0.0
    minus_dm[~np.isfinite(minus_dm)] = 0.0

    tr = np.maximum.reduce([h - l, np.abs(h - prev_c), np.abs(l - prev_c)])
    tr = np.nan_to_num(tr, nan=0.0, posinf=0.0, neginf=0.0)
    tr[0] = h[0] - l[0]

    atr = rma(tr, n)
    pdi = 100.0 * _nan_safe(rma(plus_dm, n), atr)
    mdi = 100.0 * _nan_safe(rma(minus_dm, n), atr)

    denom = pdi + mdi
    dx = np.where(denom > 0, 100.0 * np.abs(pdi - mdi) / np.where(denom > 0, denom, 1.0), np.nan)
    adx_line = rma(np.nan_to_num(dx, nan=0.0), n)
    adx_line[denom <= 0] = np.nan
    return adx_line, pdi, mdi


def awesome_oscillator(high, low, fast: int = 5, slow: int = 34) -> np.ndarray:
    hl2 = (_f(high) + _f(low)) / 2.0
    return rolling_mean(hl2, fast) - rolling_mean(hl2, slow)


def momentum(close, n: int = 10) -> np.ndarray:
    return _f(close) - shift(close, n)


def macd(close, fast: int = 12, slow: int = 26, signal: int = 9):
    """MACD -> (macd, sinyal, histogram)"""
    c = _f(close)
    line = ema(c, fast) - ema(c, slow)
    sig = ema(np.nan_to_num(line, nan=0.0), signal)
    # NaN bolgesinde sinyal de NaN kalmali
    sig[~np.isfinite(line)] = np.nan
    return line, sig, line - sig


def stoch_rsi_fast(close, rsi_len: int = 14, stoch_len: int = 14,
                   k: int = 3, d: int = 3) -> np.ndarray:
    """Stokastik RSI Hizli (3, 3, 14, 14) -> %K"""
    r = rsi(close, rsi_len)
    hh = rolling_max(r, stoch_len)
    ll = rolling_min(r, stoch_len)
    span = hh - ll
    raw = np.where(span > 0, 100.0 * (r - ll) / np.where(span > 0, span, 1.0), np.nan)
    return rolling_mean(raw, k)


def williams_r(high, low, close, n: int = 14) -> np.ndarray:
    hh = rolling_max(high, n)
    ll = rolling_min(low, n)
    span = hh - ll
    return np.where(span > 0, -100.0 * (hh - _f(close)) / np.where(span > 0, span, 1.0), np.nan)


def bull_bear_power(high, low, close, n: int = 13):
    """Boga Ayi Gucu -> (bogalar, ayilar); farklari deger olarak gosterilir."""
    basis = ema(close, n)
    return _f(high) - basis, _f(low) - basis


def ultimate_oscillator(high, low, close, fast: int = 7,
                       medium: int = 14, slow: int = 28) -> np.ndarray:
    h, l, c = _f(high), _f(low), _f(close)
    prev_c = shift(c, 1)
    bp = c - np.minimum(l, prev_c)
    tr = np.maximum(h, prev_c) - np.minimum(l, prev_c)
    tr = np.nan_to_num(tr, nan=0.0, posinf=0.0, neginf=0.0)

    def avg(n: int) -> np.ndarray:
        return _nan_safe(rolling_sum(bp, n), rolling_sum(tr, n))

    return 100.0 * (4.0 * avg(fast) + 2.0 * avg(medium) + 1.0 * avg(slow)) / 7.0


# --------------------------------------------------------------------------
# Hareketli ortalamalar / ek bantlar
# --------------------------------------------------------------------------
def vwma(close, volume, n: int = 20) -> np.ndarray:
    c, v = _f(close), _f(volume)
    return _nan_safe(rolling_sum(c * v, n), rolling_sum(v, n))


def hma(close, n: int = 9) -> np.ndarray:
    """Hull Hareketli Ortalama."""
    half = max(1, n // 2)
    root = max(1, int(np.sqrt(n)))
    raw = 2.0 * wma(close, half) - wma(close, n)
    return wma(np.nan_to_num(raw, nan=0.0), root)


def ichimoku_base_line(high, low, kijun: int = 26) -> np.ndarray:
    """
    Ichimoku Ana Hatti.

    TradingView parametresi (9, 26, 52, 26) olsa da "Ana Hat" 9 ve 26
    periyotlarinin ortalamasidir, yani Tenkan ile Kijun'un basit ortalamasi.
    Grafikte 26 bar ileriye kaydirilir; burada ANIN gorunumu (karsilastirma
    icin kaydirilmamis deger) dondurulur.
    """
    hh = rolling_max(high, kijun)
    ll = rolling_min(low, kijun)
    return (hh + ll) / 2.0