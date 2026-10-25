"""
Auto Fibonacci Retracement — MT5/TradingView "Otomatik Fib" benzeri,
nedensel (gelecege bakmayan) Python karşılığı.

Matematik:
  * Her bar Icin son `window` barbaki en yuksek/en dusuk deger ve
    HANGISININ ONCE OLDUGU bulunur (salınım yönü).
  * Yukari salınım (dip once, tepe sonra): fiyat tepeden geri cekemismi?
        theta = (tepe - close) / (tepe - dip)     0..1
      theta = 0    -> ucun uzerinde/yakini (salinim hala tazeliyor)
      theta = 0.5  -> %50 geri cekilme (golden pocket siniri)
      theta = 0.618-> altin oran geri cekilmesi
      theta >= 0.786 -> salinim bozuldu derin geri cekilme
  * Asagi salınim (tepe once, dip sonra): theta = (close - dip) / aralık;
      yukari yönlü geri çekılmeyi ölçün; SHORT icindir dönüş bölgeleri.

Altin cebe: seviye bantlari 0.5-0.618 arası ("golden pocket"): salınımın
dönüş bölgesi buradaki fiyatlarla güçlenir (tiktower reversal).

Karar entegrasyonu (trend.py / muro.py):
  * GÜÇLÜ BYPASS: yön uygun + fiyat altin cebede (0.5-0.618) -> GÜÇLÜ
    (optimum nokta filtresini bile atalar — "dönüş yerini yakala").
  * UCA YAKIN DEVAM ENGELI: fiyat salinimin ucuna (%12'den az mesafe
    her iki yonde) cok yakinsa DEVAM girisi engellenir (tepe almak).
"""
from __future__ import annotations

import numpy as np

FIB_LEVELS = (0.236, 0.382, 0.5, 0.618, 0.786)


def retrace_series(high, low, close, window: int = 160):
    """
    Bar başına salınım bilgisi. Dönüş: (leg, hitarr, lotarr, theta)

      leg   : bar başına salınım yönü (+1 yukari, -1 asagi, 0 bilinmiyor)
      hitarr: bar başına salınım tepe fiyati (leg != 0); yoksa NaN
      lotarr: bar başına salınım dip fiyati  (leg != 0); yoksa NaN
      theta : bar başına geri çekilme derinliği (leg != 0 ve aralık > 0);
              yoksa NaN. 0 = uca dokunmuş, 0.618 = altin oran geri cekilmesi.

    NEDENSELLIK: pencere yalnizca gecmis + simdiki barlari gorur.
    """
    h = np.asarray(high, dtype=float)
    l = np.asarray(low, dtype=float)
    c = np.asarray(close, dtype=float)
    n = c.size
    leg = np.zeros(n, dtype=np.int8)
    hi_arr = np.full(n, np.nan)
    lo_arr = np.full(n, np.nan)
    theta = np.full(n, np.nan)
    if n == 0:
        return leg, hi_arr, lo_arr, theta
    w = max(3, int(window))
    for i in range(n):
        j0 = max(0, i - w + 1)
        sha = h[j0:i + 1]
        sla = l[j0:i + 1]
        hi_off = int(np.argmax(sha))
        lo_off = int(np.argmin(sla))
        hi = float(sha[hi_off])
        lo = float(sla[lo_off])
        rng = hi - lo
        # Salınım yonu: dip mi tepe mi ONCE geldi?
        if hi_off < lo_off:
            leg[i] = -1                # tepe once -> asagi salinim
        elif lo_off < hi_off:
            leg[i] = 1                 # dip once -> yukari salinim
        else:
            leg[i] = 0                 # ayni bar (aralik yok)
            continue
        if rng <= 0:
            leg[i] = 0
            continue
        hi_arr[i] = hi
        lo_arr[i] = lo
        if leg[i] > 0:
            theta[i] = (hi - c[i]) / rng   # tepeden geri cekilme
        else:
            theta[i] = (c[i] - lo) / rng   # dipten tepeden geri cekilme
    return leg, hi_arr, lo_arr, theta


def fib_levels(leg: int, hi: float, lo: float) -> dict:
    """Salinim uclarindan fibonacci seviyeleri (izleme paneli icin)."""
    if leg == 0 or not np.isfinite(hi) or not np.isfinite(lo):
        return {}
    return {f"{x:g}": (hi - x * (hi - lo)) if leg > 0
            else (lo + x * (hi - lo))
            for x in FIB_LEVELS}


def at_golden_pocket(theta: float, tol: float = 0.06) -> bool:
    """theta 0.5-0.618 bandinda mi (genisletilmis altin cebe)."""
    return np.isfinite(theta) and (0.5 - tol) <= theta <= (0.618 + tol)


def at_extreme(theta: float, gate: float) -> bool:
    """Salinim ucuna cok yakin mi (devam girisi engellenir)."""
    return np.isfinite(theta) and (theta < gate or theta > 1.0 - gate)


# Altın cebe bandı (at_golden_pocket'in tol=0.06 ile aynı: 0.44..0.678).
GOLDEN_LO = 0.44
GOLDEN_HI = 0.678

_LABEL_TO_SIGNAL = None          # tembel: core.analysis döngüsünü kırar


def gate_labels(labels: list, high, low, close,
                on: bool = True, window: int = 160,
                gate: float = 0.15) -> list:
    """
    Skor tabanli karar serilerine AUTO FIB gate (ma_only / osc_only /
    signal / signal_long / signal_exit).

    labels: "AL" / "SAT" / "GÜÇLÜ AL" / "GÜÇLÜ SAT" / "NÖTR" / None ...
    Salinim uclari VE fiyatin araliktaki yeri (0 = taban, 1 = zirve)
    retrace_series'dan turetilir; yon kendini tasıyandan gelmez.

    KURALLAR (trend/muro ile ayni ruhta, skor tabanina cevrilmis):
      * AL aralgin ZIRVESINE yakinsa (yer > 1-gate) NÖTR'e iner —
        tepe alma. (Aralik tabani alimlari serbest: dip aldir.)
      * SAT aralin TABANINA yakinsa (yer < gate) NÖTR'e iner — dipe
        satma. (Aralik zirvesi satislari serbest: tepeden satis.)
      * ALTIN CEBE: AL, yukari salınimda (leg +1) altin cebede ise
        GÜÇLÜ AL; SAT, asagi salinimda (leg -1) altin cebede ise
        GÜÇLÜ SAT. Zaten GÜÇLÜ olanlar korunur.
    """
    if not on:
        return list(labels)
    leg, _, _, theta = retrace_series(high, low, close, window)
    out: list = []
    for i, lab in enumerate(labels):
        if lab not in ("AL", "SAT", "GÜÇLÜ AL", "GÜÇLÜ SAT") \
                or i >= leg.size:
            out.append(lab)
            continue
        lg = int(leg[i])
        th = float(theta[i])
        if lg == 0 or not np.isfinite(th):
            out.append(lab)
            continue
        if lg > 0:
            pos = 1.0 - th          # yukari salınım: theta = tepeden uzaklik
        else:
            pos = float(th)         # asagi salinim: theta = dibden uzaklik
        if lab in ("AL", "GÜÇLÜ AL"):
            if pos > 1.0 - gate:
                out.append("NÖTR")           # aralik zirvesinde AL
                continue
            if lab == "AL" and lg > 0 and \
                    GOLDEN_LO <= th <= GOLDEN_HI:
                out.append("GÜÇLÜ AL")
                continue
            out.append(lab)
        else:
            if pos < gate:
                out.append("NÖTR")           # aralik tabaninda SAT
                continue
            if lab == "SAT" and lg < 0 and \
                    GOLDEN_LO <= pos <= GOLDEN_HI:
                out.append("GÜÇLÜ SAT")
                continue
            out.append(lab)
    return out


def gate_signals(sigs: list, high, low, close,
                 on: bool = True, window: int = 160,
                 gate: float = 0.15) -> list:
    """Signal ENUM listesi uzerinde gate_labels. Donus: Signal listesi."""
    global _LABEL_TO_SIGNAL
    from core.analysis import Signal as _S
    if _LABEL_TO_SIGNAL is None:
        _LABEL_TO_SIGNAL = {
            "AL": _S.BUY, "SAT": _S.SELL, "NÖTR": _S.NEUTRAL,
            "GÜÇLÜ AL": _S.STRONG_BUY, "GÜÇLÜ SAT": _S.STRONG_SELL,
            None: _S.NEUTRAL,
        }
    if not on:
        return list(sigs)
    labels = [(s.value if hasattr(s, "value") else s) for s in sigs]
    gated = gate_labels(labels, high, low, close, on, window, gate)
    return [_LABEL_TO_SIGNAL.get(x, _S.NEUTRAL) for x in gated]
