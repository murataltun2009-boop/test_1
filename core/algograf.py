# -*- coding: utf-8 -*-
"""ALGO-GRAF — grafik çizgi sıralamasına dayanan LONG/SHORT algoritması.

KULLANICI KURALI (2026-11-13, 5 dk periyot)

Grafik panelindeki çizgiler ve renkleri:
    TURUNCU = EMA20   #f7a35c
    MAVİ    = EMA50   #4fc3f7  (açık mavi / turkuaz)
    MOR     = EMA200  #b07cff
    PEMBE   = HULL 9  #ff8fb1
    YEŞİL   = VWMA20  (açık yeşil / mint)
    GRİ     = SMA200  #8d9db0  -> kurallarda KULLANILMAZ

Kurallar (sıralama = fiyat değeri büyükten küçüğe, üstten alta):

  1) MAVİ en üstte, PEMBE en altta (TURUNCU ve YEŞİL arada) -> SHORT aç
     ve pozisyonda kal.
  2) PEMBE en alt sıradan çıktığında / YEŞİL veya TURUNCU ile çakıştığında
     ya da üstüne çıktığında -> SHORT kapat.
  3) PEMBE en üstte, MAVİ en altta -> LONG aç ve pozisyonda kal; YEŞİL
     PEMBE'nin üstüne çıktığında -> LONG kapat.
  4) YEŞİL en üstte, PEMBE en altta -> NÖTR.
  5) PEMBE->YEŞİL->TURUNCU->MAVİ dizilimi -> LONG kapat.
  6) PEMBE en üstte, YEŞİL en altta -> NÖTR.
  7) PEMBE en üstte, MAVİ en altta iken MOR, YEŞİL veya TURUNCU ile
     çakışırsa (aynı seviye) -> LONG kapat.
  8) PEMBE->TURUNCU->YEŞİL->MOR->MAVİ dizilimi -> SHORT aç; PEMBE,
     YEŞİL'in veya TURUNCU'nun altına inince -> SHORT kapat.
  9) MAVİ, MOR ile çakışıp MOR'un altında kalırken PEMBE de aynı anda en
     alta geçerse -> SHORT kapat.

  * Bu kuralların dışında kararsız kalınan her durumda pozisyon NÖTR'dür.
  * Yalnızca seçilen algoritma pozisyon belirler; gösterge hesapları ve
    grafik üretimi DEĞİŞMEZ.

ÜÇ VARYANT:
    algograf       : iki yön (tüm kurallar)
    algograf_short : yalnız SHORT (kural 1 giriş, kural 2 çıkış)
    algograf_long  : yalnız LONG (kural 3 giriş, YEŞİL>PEMBE çıkış)

Etiketler pozisyona duyarlıdır:
    AL / SAT / AL-KAPAT / SAT-KAPAT / NÖTR

"Çakışma" (aynı seviye) toleransı fiyatın `PAPER_ALGOGRAF_TOUCH` kadarıdır
(varsayılan %0,05). Sıralama karşılaştırmaları bu ölü bandı aşmayı ister;
bu yüzden çizgiler iç içe geçtiğinde sonuç NÖTR'dür (kararsızlık kuralı).
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np

import config

# Grafik çizgisi -> analysis.ma_series anahtarı.
LINE_KEYS: dict[str, str] = {
    "TURUNCU": "ema20",
    "MAVİ": "ema50",
    "MOR": "ema200",
    "PEMBE": "hma",
    "YEŞİL": "vwma",
}

# Kullanıcı isteğindeki üç algoritma.
MODES: tuple[str, ...] = ("algograf", "algograf_short", "algograf_long")

LABELS: tuple[str, ...] = ("AL", "SAT", "NÖTR", "AL-KAPAT", "SAT-KAPAT")


def is_algograf_mode(mode: object) -> bool:
    """Mod ALGO-GRAF ailesinden mi?"""
    return str(mode or "").strip() in MODES


def side_for_mode(mode: object) -> Optional[int]:
    """Varyantın izin verdiği yön: +1 long-only, -1 short-only, None iki yön."""
    m = str(mode or "").strip()
    if m == "algograf_long":
        return 1
    if m == "algograf_short":
        return -1
    return None


def touch_ratio() -> float:
    """Çakışma/aynı seviye toleransı (fiyat oranı)."""
    try:
        return max(0.0, float(getattr(config, "PAPER_ALGOGRAF_TOUCH",
                                     0.0005)))
    except (TypeError, ValueError):
        return 0.0005


def decide_target(label: str, current: int = 0) -> Optional[int]:
    """Etiketi hedef pozisyona çevirir (+1 LONG, -1 SHORT, 0 DÜZ).

    KAPAT etiketleri yalnızca AYNI yöndeki pozisyonu kapatır; ters yönde
    pozisyon açmaz. Tanınmayan etikette None döner (durum korunur).
    """
    lab = str(label or "").strip()
    if lab in ("AL", "GÜÇLÜ AL"):
        return 1
    if lab in ("SAT", "GÜÇLÜ SAT"):
        return -1
    if lab == "AL-KAPAT":
        return 0 if int(current) > 0 else int(current)
    if lab == "SAT-KAPAT":
        return 0 if int(current) < 0 else int(current)
    if lab == "NÖTR":
        return 0
    return None


# --------------------------------------------------------------------------
# Karşılaştırma yardımcıları (tolerans = fiyat * oran)
# --------------------------------------------------------------------------
def _top(x: float, others: tuple, eps: float) -> bool:
    """x en üstte: hiçbir çizgi ondan belirgin şekilde yüksek değil."""
    return all(x >= o - eps for o in others)


def _bottom(x: float, others: tuple, eps: float) -> bool:
    """x en altta: hiçbir çizgi ondan belirgin şekilde düşük değil."""
    return all(x <= o + eps for o in others)


def _above(a: float, b: float, eps: float) -> bool:
    """a, b'nin belirgin şekilde ÜSTÜNDE (çakışma sıralama sayılmaz)."""
    return a > b + eps


def _below(a: float, b: float, eps: float) -> bool:
    """a, b'nin belirgin şekilde ALTINDA."""
    return a < b - eps


def _touch(a: float, b: float, eps: float) -> bool:
    """İki çizgi aynı seviyede (çakışma)."""
    return abs(a - b) <= eps


def _conditions(t: float, mavi: float, mor: float,
                pembe: float, yesil: float,
                eps: float) -> dict[str, bool]:
    """Bir barın kullanıcı kuralı koşulları."""
    r1 = (_top(mavi, (t, mor, pembe, yesil), eps)
          and _bottom(pembe, (t, mavi, mor, yesil), eps)
          and _above(mavi, t, eps) and _above(mavi, yesil, eps)
          and _above(t, pembe, eps) and _above(yesil, pembe, eps))
    r3 = (_top(pembe, (t, mavi, mor, yesil), eps)
          and _bottom(mavi, (t, mor, pembe, yesil), eps))
    r4 = (_top(yesil, (t, mavi, mor, pembe), eps)
          and _bottom(pembe, (t, mavi, mor, yesil), eps))
    r5 = (_above(pembe, yesil, eps) and _above(yesil, t, eps)
          and _above(t, mavi, eps))
    r6 = (_top(pembe, (t, mavi, mor, yesil), eps)
          and _bottom(yesil, (t, mavi, mor, pembe), eps))
    r7 = (r3 and (_touch(mor, yesil, eps) or _touch(mor, t, eps)))
    r8 = (_above(pembe, t, eps) and _above(t, yesil, eps)
          and _above(yesil, mor, eps) and _above(mor, mavi, eps))
    r9 = (mavi <= mor and (mor - mavi) <= eps
          and _bottom(pembe, (t, mavi, mor, yesil), eps))
    return {"r1": r1, "r3": r3, "r4": r4, "r5": r5,
            "r6": r6, "r7": r7, "r8": r8, "r9": r9}


def _arrays(ma_series: dict) -> Optional[tuple]:
    try:
        return tuple(np.asarray(ma_series[k], dtype=float)
                     for k in (LINE_KEYS["TURUNCU"], LINE_KEYS["MAVİ"],
                               LINE_KEYS["MOR"], LINE_KEYS["PEMBE"],
                               LINE_KEYS["YEŞİL"]))
    except (KeyError, TypeError):
        return None


def series(ma_series: dict, *, side: Optional[int] = None,
           touch: Optional[float] = None) -> list[str]:
    """Bar başına ALGO-GRAF kararı (pozisyona duyarlı).

    `ma_series`: analysis.TimeframeAnalysis.ma_series (ema20/ema50/ema200/
    hma/vwma okunur; sma200 kullanılmaz).

    `side`: +1 yalnız LONG, -1 yalnız SHORT, None iki yön. `paper.py` ve
    `service.py` AYNI fonksiyonu çağırır; canlı, geriye dönük test ve
    grafik yıldızları birebir aynı kararı gösterir.

    Seri NEDENSELDİR: i. bar yalnızca 0..i barlarına bakar.
    """
    arrs = _arrays(ma_series)
    if arrs is None:
        return []
    t_a, m_a, mor_a, p_a, y_a = arrs
    n = min(len(t_a), len(m_a), len(mor_a), len(p_a), len(y_a))
    if n <= 0:
        return []
    eps_oran = touch_ratio() if touch is None else max(0.0, float(touch))
    yon = 0 if side is None else (1 if int(side) > 0 else -1)

    out: list[str] = []
    state = 0              # +1 LONG, -1 SHORT, 0 düz
    giris_kural = ""       # "r1" | "r8" | "r3"

    for i in range(n):
        t = float(t_a[i])
        mavi = float(m_a[i])
        mor = float(mor_a[i])
        pembe = float(p_a[i])
        yesil = float(y_a[i])
        degerler = (t, mavi, mor, pembe, yesil)
        if not all(math.isfinite(x) for x in degerler) or t <= 0:
            # Gösterge ısınması / eksik veri: karar yok.
            out.append("NÖTR")
            continue
        eps = abs(t) * eps_oran
        c = _conditions(t, mavi, mor, pembe, yesil, eps)

        if state > 0:
            # ---- AÇIK LONG: yalnız çıkış kuralları -------------------
            # R3 çıkışı: YEŞİL, PEMBE'nin üstüne çıktı.
            cikis = _above(yesil, pembe, eps)
            # R5: PEMBE->YEŞİL->TURUNCU->MAVİ dizilimi.
            cikis = cikis or c["r5"]
            # R6: PEMBE en üstte, YEŞİL en altta -> NÖTR.
            cikis = cikis or c["r6"]
            # R7: PEMBE üst / MAVİ alt iken MOR, YEŞİL veya TURUNCU ile
            # aynı seviyede.
            cikis = cikis or c["r7"]
            # R8: net SHORT dizilimi long'u geçersiz kılar.
            cikis = cikis or c["r8"]
            if cikis:
                out.append("AL-KAPAT")
                state = 0
                giris_kural = ""
            else:
                out.append("AL")
            continue

        if state < 0:
            # ---- AÇIK SHORT: giriş kuralına göre çıkış ----------------
            if giris_kural == "r1":
                # R2: PEMBE en alttan çıktı ya da YEŞİL/TURUNCU ile
                # çakıştı/üstüne çıktı.
                cikis = (not _bottom(pembe, (t, mavi, mor, yesil), eps)
                         or not _below(pembe, yesil, eps)
                         or not _below(pembe, t, eps))
            else:
                # R8: PEMBE, YEŞİL'in veya TURUNCU'nun altına indi.
                cikis = (_below(pembe, yesil, eps)
                         or _below(pembe, t, eps))
                # R9: MAVİ, MOR ile çakışıp altında kalırken PEMBE en alta.
                cikis = cikis or c["r9"]
            # R4 / R6: nötr dizilimleri açık short'u kapatır.
            cikis = cikis or c["r4"] or c["r6"]
            if cikis:
                out.append("SAT-KAPAT")
                state = 0
                giris_kural = ""
            else:
                out.append("SAT")
            continue

        # ---- DÜZ: giriş / nötr ---------------------------------------
        if yon < 0:
            # algograf_short: YALNIZ kural 1 (MAVİ üst / PEMBE alt).
            short_giris = c["r1"]
        else:
            # R8 (tam SHORT dizilimi) R3'ü de kapsadığı için önce gelir.
            short_giris = c["r8"] or c["r1"]
        # R5/R6/R7/R8 long girişini geçersiz kılar (aynı dizilimler).
        long_giris = (c["r3"] and not c["r5"] and not c["r6"]
                      and not c["r7"] and not c["r8"])

        if yon <= 0 and short_giris:
            out.append("SAT")
            state = -1
            giris_kural = "r8" if c["r8"] else "r1"
        elif yon >= 0 and long_giris:
            out.append("AL")
            state = 1
            giris_kural = "r3"
        else:
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
