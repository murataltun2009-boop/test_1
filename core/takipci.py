# -*- coding: utf-8 -*-
"""TAKİPÇİ — PEMBE (HULL 9) çizgi sıralamasına dayanan 5 dk algoritması.

KULLANICI KURALI (2026-11-25, 5 dk periyot)

Grafik çizgileri ve renkleri (ALGO-GRAF ile aynı eşleme):
    TURUNCU = EMA20        #f7a35c
    MAVİ    = EMA50        #4fc3f7
    PEMBE   = HULL 9       #ff8fb1
    YEŞİL   = VWMA20       #7dd6a0

    EMA200 ve SMA200 grafikte yoktur ve hiçbir kuralda kullanılmaz.

Kurallar (yalnız PEMBE'nin konumu belirleyicidir):

  SHORT : PEMBE, EMA50 + VWMA20 + EMA20 ÜÇÜNÜN DE ALTINDA olduğu sürece
          SHORT aç ve pozisyonda kal.
  SHORT KAPAT: PEMBE dipten yükselip EMA20 / VWMA20 çizgilerine
          DEĞDİĞİNDE (ikisinden yakın olanına ulaştığında) kapat.
  LONG  : PEMBE, EMA50 + VWMA20 + EMA20 ÜÇÜNÜN DE ÜSTÜNDE olduğu sürece
          LONG aç ve pozisyonda kal.
  LONG KAPAT: PEMBE tepeden dönüp EMA20 / VWMA20 çizgilerine DEĞDİĞİNDE
          (ikisinden yakın olanına ulaştığında) kapat.
  NÖTR  : Çizgiler aynı seviyedeyken / PEMBE üçlünün dışında değilken
          bekle; yeni pozisyon açma.

Çıkış mantığı: PEMBE girişte EMA20 ve VWMA20'nin dışındadır. Geri
döndüğünde önce bu iki çizgiden YAKIN olanına değer:
    LONG  -> PEMBE <= max(EMA20, VWMA20)  (aşağı yönde ilk temas)
    SHORT -> PEMBE >= min(EMA20, VWMA20)  (yukarı yönde ilk temas)
`PAPER_TAKIPCI_TOUCH` (varsayılan 0) fiyatın oranı kadar ölü bant ekler.

ÜÇ VARYANT (ALGO-GRAF ile aynı desen):
    takipci       : iki yön — LONG ve SHORT birlikte (sırayla)
    takipci_long  : yalnız LONG
    takipci_short : yalnız SHORT

YÜRÜTME KATMANI (`paper._algograf`) bu modlarda da geçerlidir:
  * ZARAR FRENİ: net zarar `PAPER_ALGOGRAF_LOSS_USD` (varsayılan 5$) olunca
    pozisyon kapanır. Kapanış sonrası bekleme = arayüzdeki "Min. bekleme"
    (0 = bekleme yok).
  * KÂR BANKASI: açık kâr `PAPER_ALGOGRAF_BANK_USD` (varsayılan 10$) olunca
    pozisyon kapanır, net kâr cüzdana yazılır ve YENİ pozisyon beklenir
    (kural sıfırlanana kadar aynı yönde yeniden girilmez).
  * KORUYUCU STOP bu modlarda KAPALIDIR; çıkış kuraldan veya zarar
    freninden gelir.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np

import config
from core.algograf import LINE_KEYS

# Kullanıcı isteğindeki üç varyant.
MODES: tuple[str, ...] = ("takipci", "takipci_long", "takipci_short")

LABELS: tuple[str, ...] = ("AL", "SAT", "NÖTR", "AL-KAPAT", "SAT-KAPAT")


def is_takipci_mode(mode: object) -> bool:
    """Mod TAKİPÇİ ailesinden mi?"""
    return str(mode or "").strip() in MODES


def side_for_mode(mode: object) -> Optional[int]:
    """Varyantın izin verdiği yön: +1 long-only, -1 short-only, None iki yön."""
    m = str(mode or "").strip()
    if m == "takipci_long":
        return 1
    if m == "takipci_short":
        return -1
    return None


def touch_ratio() -> float:
    """Değme/aynı seviye toleransı (fiyat oranı). Varsayılan 0 = sıkı."""
    try:
        return max(0.0, float(getattr(config, "PAPER_TAKIPCI_TOUCH", 0.0)))
    except (TypeError, ValueError):
        return 0.0


def _above(a: float, b: float, eps: float) -> bool:
    return a > b + eps


def _below(a: float, b: float, eps: float) -> bool:
    return a < b - eps


def conditions(t: float, mavi: float, pembe: float, yesil: float,
               eps: float) -> dict[str, bool]:
    """Bir barın TAKİPÇİ koşulları.

    t=TURUNCU(EMA20), mavi=MAVİ(EMA50), pembe=HULL9, yesil=YEŞİL(VWMA20).
    """
    # PEMBE üçlünün TAMAMININ üstünde / altında mı?
    long_entry = (_above(pembe, t, eps) and _above(pembe, mavi, eps)
                  and _above(pembe, yesil, eps))
    short_entry = (_below(pembe, t, eps) and _below(pembe, mavi, eps)
                   and _below(pembe, yesil, eps))
    # Çıkış: PEMBE geri dönüp EMA20 / VWMA20 çizgilerinden yakınına değdi.
    long_exit = pembe <= max(t, yesil) + eps
    short_exit = pembe >= min(t, yesil) - eps
    return {"long_entry": long_entry, "short_entry": short_entry,
            "long_exit": long_exit, "short_exit": short_exit}


def _arrays(ma_series: dict) -> Optional[tuple]:
    try:
        return tuple(np.asarray(ma_series[k], dtype=float)
                     for k in (LINE_KEYS["TURUNCU"], LINE_KEYS["MAVİ"],
                               LINE_KEYS["PEMBE"], LINE_KEYS["YEŞİL"]))
    except (KeyError, TypeError):
        return None


def series(ma_series: dict, *, side: Optional[int] = None,
           touch: Optional[float] = None) -> list[str]:
    """Bar başına TAKİPÇİ kararı (pozisyona duyarlı).

    `ma_series`: analysis.TimeframeAnalysis.ma_series (ema20/ema50/hma/vwma
    okunur; ema200/sma200 kullanılmaz).

    `side`: +1 yalnız LONG, -1 yalnız SHORT, None iki yön. `paper.py` ve
    `service.py` AYNI fonksiyonu çağırır; canlı, geriye dönük test ve grafik
    yıldızları birebir aynı kararı gösterir.

    Seri NEDENSELDİR: i. bar yalnızca 0..i barlarına bakar.
    """
    arrs = _arrays(ma_series)
    if arrs is None:
        return []
    t_a, m_a, p_a, y_a = arrs
    n = min(len(t_a), len(m_a), len(p_a), len(y_a))
    if n <= 0:
        return []
    eps_oran = touch_ratio() if touch is None else max(0.0, float(touch))
    yon = 0 if side is None else (1 if int(side) > 0 else -1)

    out: list[str] = []
    state = 0              # +1 LONG, -1 SHORT, 0 düz

    for i in range(n):
        t = float(t_a[i])
        mavi = float(m_a[i])
        pembe = float(p_a[i])
        yesil = float(y_a[i])
        if not all(math.isfinite(x) for x in (t, mavi, pembe, yesil)) \
                or t <= 0:
            out.append("NÖTR")
            continue
        eps = abs(t) * eps_oran
        c = conditions(t, mavi, pembe, yesil, eps)

        if state > 0:
            # ---- AÇIK LONG ------------------------------------------
            if c["long_exit"]:
                out.append("AL-KAPAT")
                state = 0
            else:
                out.append("AL")
            continue

        if state < 0:
            # ---- AÇIK SHORT -----------------------------------------
            if c["short_exit"]:
                out.append("SAT-KAPAT")
                state = 0
            else:
                out.append("SAT")
            continue

        # ---- DÜZ: giriş ---------------------------------------------
        if yon > 0:
            if c["long_entry"]:
                out.append("AL")
                state = 1
            else:
                out.append("NÖTR")
        elif yon < 0:
            if c["short_entry"]:
                out.append("SAT")
                state = -1
            else:
                out.append("NÖTR")
        elif c["long_entry"]:
            out.append("AL")
            state = 1
        elif c["short_entry"]:
            out.append("SAT")
            state = -1
        else:
            # Çizgiler iç içe / aynı seviyede: nötr bekle.
            out.append("NÖTR")

    return out


def label_at(ma_series: dict, idx: int, *,
             side: Optional[int] = None) -> str:
    """Tek barın kararı (seri baştan üretilir; nedensel)."""
    s = series(ma_series, side=side)
    if 0 <= int(idx) < len(s):
        return s[int(idx)]
    return "NÖTR"


def summary() -> dict:
    """Test/araştırma için özet."""
    return {
        "modes": list(MODES),
        "labels": list(LABELS),
        "lines": {k: v for k, v in LINE_KEYS.items()},
        "touch": touch_ratio(),
    }
