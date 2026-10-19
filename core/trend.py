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

AL = "AL"
SAT = "SAT"
NOTR = "NÖTR"


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
