"""
YENI ALGORITMA: Supertrend trend takibi.

Bu modul, arastirma sonucu secilen kurali tek yerde toplar; hem canli
sinyal (`service._signal_for_mode`) hem de geriye donuk test
(`paper._build_signal_series`) ayni kodu kullanir. Boylece "testte
baska, canlida baska" hata riski kalmaz.

KURAL
-----
  * Supertrend(10, 3) yonu belirler:
        +1 -> AL,  -1 -> SAT,  0 (isinma) -> NOTR
  * Giris: yon degistigi bar.
  * Cikis: yon NOTR'e donerse veya ters yon sinyali gelirse pozisyon
    kapanir; ters yon sinyali AYNI anda yeni pozisyon acar (diger
    sinyal modlariyla ayni davranis).
  * Risk: giris stopu 4 x ATR(14), kapanista 6 x ATR takip stopu.
    Pozisyon boyutu stop mesafesine gore hesaplanir (risk bazli).

NEDEN 4x / 6x?
--------------
Arastirmada 4x/6x, 25 coin ve iki bagimsiz kumede de pozitif kalan
tek "knife-edge olmayan" bolgede yer aliyordu (komsu degerler de
pozitif). Ayrintilar: ALGORITMA_ARASTIRMASI.md
"""
from __future__ import annotations

from typing import Optional

import numpy as np

import config
from core import indicators as ind
from core import fib as fib_mod

AL = "AL"
SAT = "SAT"
NOTR = "NÖTR"

# AUTO FIB RETRACEMENT (kullanici isteği: "nokta atişi dönüş yerlerini
# yakalasın, hibrit çalışsin"). Parametreler config'ten okunur.
FIB_ON = bool(config.PAPER_FIB_ON)
FIB_WINDOW = int(config.PAPER_FIB_WINDOW)
FIB_GATE = float(config.PAPER_FIB_GATE)   # ucun bu payindan yakini engel


def numeric_series(high, low, close,
                   period: Optional[int] = None,
                   multiplier: Optional[float] = None) -> np.ndarray:
    """Bar basina +1 / -1 / 0 dizisi. Gelecege bakmaz."""
    p = int(period if period is not None else config.PAPER_TREND_PERIOD)
    m = float(multiplier if multiplier is not None else config.PAPER_TREND_MULT)
    _, direction = ind.supertrend(high, low, close, p, m)
    return direction.astype(np.float64)


def signal_series(high, low, close,
                  period: Optional[int] = None,
                  multiplier: Optional[float] = None) -> list[str]:
    """Bar basina "AL" / "SAT" / "NÖTR" metin dizisi."""
    d = numeric_series(high, low, close, period, multiplier)
    return [AL if x > 0 else SAT if x < 0 else NOTR for x in d]


def last_signal(high, low, close,
                period: Optional[int] = None,
                multiplier: Optional[float] = None) -> str:
    """Son KAPANMIS bar icin sinyal."""
    if len(close) == 0:
        return NOTR
    return signal_series(high, low, close, period, multiplier)[-1]


def atr_value(high, low, close, n: int = 14) -> float:
    """Son barin ATR degeri (gecersizse 0)."""
    a = ind.atr(high, low, close, n)
    if a.size == 0:
        return 0.0
    v = float(a[-1])
    return v if np.isfinite(v) and v > 0 else 0.0


def is_trend_mode(mode: Optional[str]) -> bool:
    return mode == "trend"

# --------------------------------------------------------------------------
# KARAR SERISI (canlı akış ve geriye dönük test ORTAK kullanır)
# --------------------------------------------------------------------------
def decide_series(high, low, close, strong=None, period: int = 10,
                  mult: float = 3.0, pull_atr: float = 0.0,
                  pull_bars: int = 20) -> list[str]:
    """
    Bar başına karar dizisi.

    Çıktı: "AL" · "SAT" · "NÖTR" · "GÜÇLÜ AL" · "GÜÇLÜ SAT" · "" (bekle)

    KURALLAR
    --------
    1. YÖN: Supertrend(period, mult).
    2. OPTIMUM NOKTA (pull_atr > 0):
       * LONG  : fiyat son pull_bars barın zirvesine çok yakınsa GİRİLMEZ
                 (tepede alıp hemen düşmek en sık zarar sebebi).
       * SHORT : fiyat son pull_bars barın dibine çok yakınsa GİRİLMEZ.
       Ölçü ATR cinsinden mesafe.
    3. AUTO FIB (fib=True): son salınıma göre fibonacci geri çekilme
       derinliği (core/fib.py) hesaplanır:
       * GÜÇLÜ BYPASS: fiyat ALTIN CEBE geldi mi (0.5-0.618)? Yön uygunsa
         optimum nokta filtresini bile ATLAYARAK GÜÇLÜ girilir (dönüş
         yakalama — kullanıcı isteği: "nokta atışı dönüş yerleri").
       * UÇA YAKIN DEVAM ENGELİ: salınımin ucuna (%15'ten az mesafe her
         iki yonde) devam girişi engellenir.
    4. GÜÇLÜ SİNYAL (strong dizisi: +1 GÜÇLÜ AL, −1 GÜÇLÜ SAT, 0 yok):
       optimum nokta beklense bile GÜÇLÜ AL/GÜÇLÜ SAT gelirse HEMEN girilir.

    strong dizisi verilmemişse sadece yön + optimum nokta + fib uygulanır.
    """
    h = np.asarray(high, dtype=float)
    l = np.asarray(low, dtype=float)
    c = np.asarray(close, dtype=float)
    n = c.size
    out: list[str] = [""] * n
    if n == 0:
        return out

    _, dirn = ind.supertrend(h, l, c, period, mult)

    # Zon filtresi icin ATR ve donen zirve/dip
    atr_v = None
    roll_hi = roll_lo = None
    if pull_atr > 0 and n > 1:
        atr_v = ind.atr(h, l, c, 14)
        w = max(2, int(pull_bars))
        roll_hi = np.empty(n)
        roll_lo = np.empty(n)
        for i in range(n):
            j0 = max(0, i - w + 1)
            seg_h = h[j0:i + 1]
            seg_l = l[j0:i + 1]
            roll_hi[i] = float(seg_h.max())
            roll_lo[i] = float(seg_l.min())

    # AUTO FIB retracement (causal)
    fib_leg, _, _, fib_theta = (None, None, None, None)
    if FIB_ON:
        fib_leg, _, _, fib_theta = fib_mod.retrace_series(
            h, l, c, FIB_WINDOW)

    for i in range(n):
        d = int(dirn[i])
        if d == 0:
            out[i] = "NÖTR"
            continue
        if strong is not None and i < len(strong):
            st = int(strong[i])
        else:
            st = 0
        theta = (float(fib_theta[i])
                 if fib_theta is not None and np.isfinite(fib_theta[i])
                 else np.nan)

        if d > 0:
            # AUTO FIB: altin cebe geldiyse "dönüş yakalandı" -> GÜÇLÜ
            if fib_mod.at_golden_pocket(theta):
                out[i] = "GÜÇLÜ AL"
                continue
            # Uga yakin devam girişi: tepe almaya biçilmez.
            if fib_mod.at_extreme(theta, FIB_GATE) and st <= 0:
                continue
            if st > 0:
                out[i] = "GÜÇLÜ AL"
                continue
            if atr_v is not None and np.isfinite(atr_v[i]) and atr_v[i] > 0:
                if (roll_hi[i] - c[i]) < pull_atr * atr_v[i]:
                    continue          # tepede: bekle
            out[i] = "AL"
        else:
            if fib_mod.at_golden_pocket(theta):
                out[i] = "GÜÇLÜ SAT"
                continue
            if fib_mod.at_extreme(theta, FIB_GATE) and st <= 0:
                continue
            if st < 0:
                out[i] = "GÜÇLÜ SAT"
                continue
            if atr_v is not None and np.isfinite(atr_v[i]) and atr_v[i] > 0:
                if (c[i] - roll_lo[i]) < pull_atr * atr_v[i]:
                    continue          # dipte: bekle
            out[i] = "SAT"
    return out


def strong_series(signals) -> list[int]:
    """core.analysis.Signal listesinden guclu sinyal dizisi (+1 / -1 / 0)."""
    from core.analysis import Signal
    out = []
    for s in signals or []:
        v = getattr(s, "value", s)
        if v == "GÜÇLÜ AL":
            out.append(1)
        elif v == "GÜÇLÜ SAT":
            out.append(-1)
        else:
            out.append(0)
    return out
