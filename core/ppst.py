"""
Pivot Point Supertrend (PP-Supertrend) — karar mekanizması, 5m modu.

TradingView'daki "PP SuperTrend" göstergesinin nedensel (geleceğe
bakmayan) Python karşılığı. Matematik:

  * Dönen dönem içinden pivot noktası: pp = (pivot_hi + pivot_lo + close)/3
  * Pivot temelli dayanma/direnç varyantları (R1..R3, S1..S3) seçilir
  * Temel bantlar = seçilen seviye -/+ multiplier x ATR
  * Bantlar klasik Supertrend mantığıyla kilitlenir (final band)
  * Yön: fiyat final dirence yukarı kırdı → +1 (AL),
         final dayanmayı aşağı kırdı → -1 (SAT)

Kararlar yalnızca KAPANMIŞ mumlardan verilmelidir (bkz.
service._signal_for_mode — `trend.decide_series` sözleşmesiyle AYNI).
"""
from __future__ import annotations

import numpy as np

AL = "AL"
SAT = "SAT"
NOTR = "NÖTR"


def ppsupertrend(high, low, close, period: int = 10,
                 multiplier: float = 3.0):
    """
    PP-Supertrend hesabı. Dönüş: (line, dirn)

      line : bar başına kilitli bant (yön +1 → support bandı,
             -1 → resistance bandı); ısınma barlarında NaN
      dirn : bar başına yön +1 / -1 / 0 (0 = ısınma=NÖTR)

    NEDENSELLİK: dönen min/max/ortalama penceresi merkezli DEĞİL
    (center=False) — pencere TAMAMEN geçmiş+şimdiki barları görür.
    Supertrend bant kilitlemesi de yalnızca önceki barın değerlerini
    kullanır. Yani dirn[i] yalnızca i. bar ve öncesinden hesaplanır.
    """
    h = np.asarray(high, dtype=float)
    l = np.asarray(low, dtype=float)
    c = np.asarray(close, dtype=float)
    n = c.size
    line = np.full(n, np.nan)
    dirn = np.zeros(n, dtype=np.int8)
    if n < max(3, int(period) + 1):
        return line, dirn

    # True Range (önceki kapanış ile) + dönen ATR
    tr = np.empty(n)
    tr[0] = h[0] - l[0]
    pc = c[:-1]
    tr[1:] = np.maximum(h[1:] - l[1:],
                        np.maximum(np.abs(h[1:] - pc),
                                   np.abs(l[1:] - pc)))
    atr = np.full(n, np.nan)
    for i in range(int(period) - 1, n):
        atr[i] = float(tr[i - period + 1:i + 1].mean())

    # Dönen pivot uçları (merkezli DEĞİL — geleceğe bakmaz)
    roll_hi = np.full(n, np.nan)
    roll_lo = np.full(n, np.nan)
    for i in range(int(period) - 1, n):
        roll_hi[i] = float(h[i - period + 1:i + 1].max())
        roll_lo[i] = float(l[i - period + 1:i + 1].min())

    pp = (roll_hi + roll_lo + c) / 3.0
    rng = h - l
    r1 = 2.0 * pp - roll_lo
    r2 = pp + rng
    r3 = roll_hi + 2.0 * (pp - roll_lo)
    s1 = 2.0 * pp - roll_hi
    s2 = pp - rng
    s3 = roll_lo - 2.0 * (roll_hi - pp)

    res = np.full(n, np.nan)
    sup = np.full(n, np.nan)
    for i in range(int(period) - 1, n):
        hi, lo, v = roll_hi[i], roll_lo[i], pp[i]
        m = np.isfinite(hi) and np.isfinite(lo) and np.isfinite(v)
        if not m or not np.isfinite(atr[i]):
            continue
        # Direnç varyantları: r3 > r1 > r2 önceliği; seviye derebedeğişirse
        # dönen en yükseğe çakılır (orijinal gösterge davranışı).
        if (r3[i] >= v and r3[i] <= hi) or hi < v:
            res[i] = r3[i]
        elif (r1[i] >= v and r1[i] <= hi) or hi < v:
            res[i] = r1[i]
        elif (r2[i] >= v and r2[i] <= hi) or hi < v:
            res[i] = r2[i]
        else:
            res[i] = hi
        # Dayanma varyantları: s3 > s1 > s2 önceliği.
        if (s3[i] <= v and s3[i] >= lo) or lo > v:
            sup[i] = s3[i]
        elif (s1[i] <= v and s1[i] >= lo) or lo > v:
            sup[i] = s1[i]
        elif (s2[i] <= v and s2[i] >= lo) or lo > v:
            sup[i] = s2[i]
        else:
            sup[i] = lo

    # Temel bantlar
    inter_res = res - float(multiplier) * atr
    inter_sup = sup + float(multiplier) * atr

    # Klasik Supertrend kilit döngüsü (yalnızca geçmişe bakar)
    prev_fr = np.nan
    prev_fs = np.nan
    prev_d = 0
    for i in range(n):
        if not (np.isfinite(inter_res[i]) and np.isfinite(inter_sup[i])):
            continue
        if i == 0 or not (np.isfinite(prev_fr) and np.isfinite(prev_fs)):
            fr = inter_res[i]
            fs = inter_sup[i]
            d = 0
        else:
            fr = inter_res[i] if (inter_res[i] < prev_fr or
                                  c[i - 1] > prev_fr) else prev_fr
            fs = inter_sup[i] if (inter_sup[i] > prev_fs or
                                  c[i - 1] < prev_fs) else prev_fs
            if c[i] > prev_fr:
                d = 1
            elif c[i] < prev_fs:
                d = -1
            else:
                d = prev_d
        prev_fr, prev_fs = fr, fs
        dirn[i] = d
        line[i] = fs if d > 0 else fr
        prev_d = d
    return line, dirn


def directions(high, low, close, period: int = 10,
               multiplier: float = 3.0) -> list[int]:
    """Bar başına +1 / -1 / 0 dizisi (AL / SAT / NÖTR)."""
    _, d = ppsupertrend(high, low, close, period, multiplier)
    return [int(x) for x in d]


def last_direction(high, low, close, period: int = 10,
                   multiplier: float = 3.0) -> int:
    d = directions(high, low, close, period, multiplier)
    return d[-1] if d else 0


# --------------------------------------------------------------------------
# KARAR SERİSİ (canlı akış ve geriye dönük test ORTAK kullanır)
# --------------------------------------------------------------------------
def decide_series(high, low, close, strong=None, period: int = 10,
                  mult: float = 3.0, pull_atr: float = 0.0,
                  pull_bars: int = 20) -> list[str]:
    """
    Bar başına karar dizisi ("AL"/"SAT"/"NÖTR"/"GÜÇLÜ AL"/"GÜÇLÜ SAT"/"").

    KURALLAR (core.trend.decide_series ile AYNI sözleşme):
    1. YÖN: PP-Supertrend(period, mult).
    2. OPTIMUM NOKTA (pull_atr > 0): tepeye/ dibe çok yakın giriş bekler
       (dönen zirve/dip karşılaştırması, ATR cinsinden mesafe).
    3. GÜÇLÜ SİNYAL bypass: optimum nokta beklense dahi, barın bilesik
       skoru GÜÇLÜ ise hemen girilir.
    """
    h = np.asarray(high, dtype=float)
    l = np.asarray(low, dtype=float)
    c = np.asarray(close, dtype=float)
    n = c.size
    out: list[str] = [""] * n
    if n == 0:
        return out

    _, dirn = ppsupertrend(h, l, c, int(period), float(mult))

    atr_v = None
    roll_hi = roll_lo = None
    if pull_atr > 0 and n > 1:
        # ATR: ppsupertrend icerisindeki tanimla ayni (donen pencere).
        tr = np.empty(n)
        tr[0] = h[0] - l[0]
        pc = c[:-1]
        tr[1:] = np.maximum(h[1:] - l[1:],
                            np.maximum(np.abs(h[1:] - pc),
                                       np.abs(l[1:] - pc)))
        atr_v = np.full(n, np.nan)
        for i in range(13, n):       # ATR(14) ile dizin aynı
            atr_v[i] = float(tr[i - 13:i + 1].mean())
        w = max(2, int(pull_bars))
        roll_hi = np.empty(n)
        roll_lo = np.empty(n)
        for i in range(n):
            j0 = max(0, i - w + 1)
            roll_hi[i] = float(h[j0:i + 1].max())
            roll_lo[i] = float(l[j0:i + 1].min())

    for i in range(n):
        d = int(dirn[i])
        if d == 0:
            out[i] = NOTR
            continue
        if strong is not None and i < len(strong):
            st = int(strong[i])
        else:
            st = 0
        if d > 0:
            if st > 0:
                out[i] = "GÜÇLÜ AL"
                continue
            if atr_v is not None and np.isfinite(atr_v[i]) and atr_v[i] > 0:
                if (roll_hi[i] - c[i]) < pull_atr * atr_v[i]:
                    continue          # tepede: bekle
            out[i] = AL
        else:
            if st < 0:
                out[i] = "GÜÇLÜ SAT"
                continue
            if atr_v is not None and np.isfinite(atr_v[i]) and atr_v[i] > 0:
                if (c[i] - roll_lo[i]) < pull_atr * atr_v[i]:
                    continue          # dipte: bekle
            out[i] = SAT
    return out
