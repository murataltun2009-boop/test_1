# -*- coding: utf-8 -*-
"""ALGO-GRAF — grafik çizgi sıralamasına dayanan LONG/SHORT algoritması.

KULLANICI KURALI (2026-11-13, 5 dk periyot)

Grafik panelindeki çizgiler ve renkleri:
    TURUNCU = EMA20        #f7a35c
    MAVİ    = EMA50        #4fc3f7  (açık mavi / turkuaz)
    PEMBE   = HULL 9       #ff8fb1
    YEŞİL   = VWMA20       #7dd6a0  (açık yeşil / mint)

    EMA200 (mor/lila #b07cff) ve SMA200 (gri/mavi-gri #8d9db0) grafikten
    KALDIRILDI ve hiçbir kuralda kullanılmaz.

Kurallar (sıralama = fiyat değeri büyükten küçüğe, üstten alta):

  SHORT  : MAVİ en üstte, PEMBE en altta olduğu sürece (TURUNCU ve YEŞİL
           bu ikisinin arasında ve TURUNCU, YEŞİL'in üstünde) SHORT aç ve
           pozisyonda kal.
  SHORT KAPAT (2026-11-15 kullanıcı düzeltmesi — iki kuraldan hangisi
           önce olursa):
             1) SHORT dizilimi bozulursa (MAVİ en üst / PEMBE en alt /
                EMA20 > VWMA20 koşullarından biri biterse),
             2) HULL satırı "AL" DURUMUNDAYSA (fiyat HULL9'un üstünde).
           HULL AL iken yeni SHORT açılmaz; NÖTR beklenir.
  LONG (iki yön)   : PEMBE en üstte, MAVİ en altta olduğu aralıkta LONG
           açık kalsın; YEŞİL, PEMBE'nin üstüne çıkarsa kapat.
  LONG (yalnız algograf_long — 2026-11-15 kullanıcı kuralı):
           AÇ / TUT: PEMBE en üst + MAVİ en alt dizilimi VEYA HULL ve
           VWMA ikisi de "AL" durumu. İkisi de AL iken YEŞİL > PEMBE olsa
           bile LONG açık kalır (both-AL üstün).
           KAPAT: YEŞİL, PEMBE'nin üstüne çıkarsa (both-AL değilken)
           VEYA HULL değeri "SAT" durumuna girerse. HULL SAT iken yeni
           LONG açılmaz.
  NÖTR   : YEŞİL en üstte, PEMBE en altta kaldığında pozisyon NÖTR kalsın.
  Bu üç dizilimin dışında karar verilemeyen her durumda NÖTR.

ÜÇ VARYANT:
    algograf       : iki yön (tüm kurallar)
    algograf_long  : yalnız LONG (PEMBE üst + MAVİ alt VEYA HULL & VWMA
                     AL; YEŞİL>PEMBE veya HULL SAT kapatır)
    algograf_short : yalnız SHORT (MAVİ üst + PEMBE alt; SHORT dizilimi
                     bozulur veya HULL AL olursa kapatır; HULL AL iken
                     yeni SHORT açmaz)

Etiketler pozisyona duyarlıdır:
    AL / SAT / AL-KAPAT / SAT-KAPAT / NÖTR

"Çakışma" (aynı seviye) eşiği fiyatın `PAPER_ALGOGRAF_TOUCH` kadarıdır.
Varsayılan 0'dır: "en üstte" = kesin büyük, eşitlik sıralama sayılmaz
(kararsızlık -> NÖTR). Sıfırdan büyük değer bir ölü bant ekler; 5 dk
grafikte çizgiler sık sık birkaç dolar aralıkla ayrıldığı için geniş bant
girişleri tamamen engelleyebilir (2026-11-13'te %0,05 -> 0 yapıldı).

KORUYUCU STOP kural katmanında DEĞİLDİR: `paper._algograf` giriş
fiyatından `PAPER_ALGOGRAF_SL` kadar ters harekette pozisyonu kapatır
(acil çıkış). Etiket serisi ve grafik yıldızları stop yüzünden değişmez;
stop sonrası kural sıfırlanana kadar aynı yönde yeni giriş yapılmaz.

KÂR BANKASI (2026-11-14) da yürütme katmanındadır: açık kâr
`PAPER_ALGOGRAF_BANK_USD` (varsayılan 10$) tutarına ulaşınca pozisyon
kapatılır, net kâr cüzdana yazılır ve AYNI yönde, AYNI ana para ×
kaldıraç notional ile anında yeniden girilir (pozisyon kaybolmaz,
bileşik büyüme yok). Yeni eşik taze +tutar kârdır. Kural etiketleri
değişmez.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np

import config
from core.analysis import MA_DEADZONE as _MA_DEADZONE

# Grafik çizgisi -> analysis.ma_series anahtarı (yalnız 4 çizgi).
LINE_KEYS: dict[str, str] = {
    "TURUNCU": "ema20",
    "MAVİ": "ema50",
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
    """Çakışma/aynı seviye toleransı (fiyat oranı). Varsayılan 0 = sıkı."""
    try:
        return max(0.0, float(getattr(config, "PAPER_ALGOGRAF_TOUCH",
                                     0.0)))
    except (TypeError, ValueError):
        return 0.0


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
def _above(a: float, b: float, eps: float) -> bool:
    """a, b'nin belirgin şekilde ÜSTÜNDE (çakışma sıralama sayılmaz)."""
    return a > b + eps


def _below(a: float, b: float, eps: float) -> bool:
    """a, b'nin belirgin şekilde ALTINDA."""
    return a < b - eps


def _conditions(t: float, mavi: float, pembe: float, yesil: float,
                eps: float, price: Optional[float] = None) -> dict[str, bool]:
    """Bir barın kullanıcı kuralı koşulları (4 çizgi).

    t=TURUNCU(EMA20), mavi=MAVİ(EMA50), pembe=HULL9, yesil=VWMA20.
    `price` verilirse HULL satırının AL/SAT kararı ve VWMA satırının AL
    kararı da üretilir (`core.analysis._ma_v` ile birebir aynı ölü bant).
    """
    # SHORT: MAVİ en üstte, PEMBE en altta; TURUNCU ve YEŞİL arada.
    # 2026-11-14: TURUNCU (EMA20) YEŞİL'in (VWMA20) ÜSTÜNDE olmalı —
    # aksi halde kapatma kuralı (EMA20 ≤ VWMA20) girişle çelişir ve
    # pozisyon her barda açılıp kapanır (ölçüm: 1263 -> 4171 işlem).
    short_entry = (_above(mavi, t, eps) and _above(mavi, yesil, eps)
                   and _below(pembe, t, eps) and _below(pembe, yesil, eps)
                   and _above(t, yesil, eps))
    # SHORT KAPAT (2026-11-15): iki koşuldan hangisi önce olursa —
    #   1) SHORT dizilimi bozulursa (`short_entry` false; EMA20 ≤ VWMA20
    #      bunun özel hâli, `short_exit`),
    #   2) HULL "AL" durumundaysa (`hull_al`).
    # `short_exit` yardımcı bayrak olarak korunur.
    short_exit = not _above(t, yesil, eps)
    # HULL satırı "AL": fiyat HULL9'un belirgin üstünde (ölü bant
    # analysis.MA_DEADZONE). Fiyat verilmezse bu kapatma devre dışı.
    hull_al = bool(price is not None and pembe > 0
                   and float(price) > pembe * (1.0 + _MA_DEADZONE))
    # HULL satırı "SAT": fiyat HULL9'un belirgin altında (aynı ölü bant).
    hull_sat = bool(price is not None and pembe > 0
                    and float(price) < pembe * (1.0 - _MA_DEADZONE))
    # VWMA satırı "AL": fiyat VWMA20'nin belirgin üstünde.
    vwma_al = bool(price is not None and yesil > 0
                   and float(price) > yesil * (1.0 + _MA_DEADZONE))
    # 2026-11-15 yalnız-LONG kullanıcı kuralı: HULL ve VWMA ikisi de AL
    # ise LONG açılır/tutulur (YEŞİL > PEMBE kapatmasını ezer).
    both_al = hull_al and vwma_al
    # LONG: PEMBE en üstte, MAVİ en altta.
    long_entry = (_above(pembe, t, eps) and _above(pembe, yesil, eps)
                  and _below(mavi, t, eps) and _below(mavi, yesil, eps))
    # LONG KAPAT: YEŞİL, PEMBE'nin üstüne çıktı.
    long_exit = _above(yesil, pembe, eps)
    # NÖTR: YEŞİL en üstte, PEMBE en altta.
    neutral = (_above(yesil, t, eps) and _above(yesil, mavi, eps)
               and _above(yesil, pembe, eps)
               and _below(pembe, t, eps) and _below(pembe, mavi, eps))
    return {"short_entry": short_entry, "short_exit": short_exit,
            "hull_al": hull_al, "hull_sat": hull_sat,
            "vwma_al": vwma_al, "both_al": both_al,
            "long_entry": long_entry, "long_exit": long_exit,
            "neutral": neutral}


def _arrays(ma_series: dict) -> Optional[tuple]:
    try:
        return tuple(np.asarray(ma_series[k], dtype=float)
                     for k in (LINE_KEYS["TURUNCU"], LINE_KEYS["MAVİ"],
                               LINE_KEYS["PEMBE"], LINE_KEYS["YEŞİL"]))
    except (KeyError, TypeError):
        return None


def series(ma_series: dict, *, side: Optional[int] = None,
           touch: Optional[float] = None,
           prices: Optional[object] = None) -> list[str]:
    """Bar başına ALGO-GRAF kararı (pozisyona duyarlı).

    `ma_series`: analysis.TimeframeAnalysis.ma_series (ema20/ema50/hma/vwma
    okunur; ema200/sma200 kullanılmaz).

    `side`: +1 yalnız LONG, -1 yalnız SHORT, None iki yön. `paper.py` ve
    `service.py` AYNI fonksiyonu çağırır; canlı, geriye dönük test ve
    grafik yıldızları birebir aynı kararı gösterir.

    `prices`: bar kapanış fiyatları (aynı uzunlukta). SHORT kapatmanın
    HULL "AL" durumu (fiyat HULL9'un üstünde) ve yalnız-LONG kuralları
    (HULL/VWMA AL, HULL SAT) için gerekir; verilmezse o kurallar devre
    dışı kalır (yalnız dizilim kuralları çalışır).

    Seri NEDENSELDİR: i. bar yalnızca 0..i barlarına bakar.
    """
    arrs = _arrays(ma_series)
    if arrs is None:
        return []
    t_a, m_a, p_a, y_a = arrs
    n = min(len(t_a), len(m_a), len(p_a), len(y_a))
    if n <= 0:
        return []
    pr_a = None
    if prices is not None:
        try:
            pr_a = np.asarray(prices, dtype=float).reshape(-1)
        except (TypeError, ValueError):
            pr_a = None
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
            # Gösterge ısınması / eksik veri: karar yok.
            out.append("NÖTR")
            continue
        price = None
        if pr_a is not None and i < pr_a.size and math.isfinite(pr_a[i]):
            price = float(pr_a[i])
        eps = abs(t) * eps_oran
        c = _conditions(t, mavi, pembe, yesil, eps, price)

        if state > 0:
            # ---- AÇIK LONG ------------------------------------------
            if yon > 0:
                # YALNIZ-LONG (2026-11-15 kullanıcı kuralı):
                #   * HULL ve VWMA ikisi de AL ise YEŞİL > PEMBE olsa bile
                #     LONG açık kalır (both-AL üstün).
                #   * Kapat: HULL SAT durumu VEYA (YEŞİL > PEMBE ve
                #     both-AL değil).
                #   * NÖTR / SHORT dizilimi tek başına kapatmaz.
                if c["hull_sat"] or (c["long_exit"] and not c["both_al"]):
                    out.append("AL-KAPAT")
                    state = 0
                else:
                    out.append("AL")
                continue
            # İki yön: çıkış YEŞİL > PEMBE, NÖTR dizilimi veya SHORT
            # dizilimi.
            if c["long_exit"] or c["neutral"] or c["short_entry"]:
                out.append("AL-KAPAT")
                state = 0
            else:
                out.append("AL")
            continue

        if state < 0:
            # ---- AÇIK SHORT -----------------------------------------
            # 2026-11-15 kullanıcı kuralı: SHORT'tan çıkış iki koşuldan
            # hangisi önce olursa:
            #   1) SHORT dizilimi bozulursa (MAVİ en üst + PEMBE en alt
            #      + EMA20 > VWMA20 koşullarından biri biterse),
            #   2) HULL satırı "AL" DURUMUNDAYSA (fiyat HULL9'un üstünde).
            # HULL AL iken yeni SHORT da açılmaz; NÖTR beklenir.
            if not c["short_entry"] or c["hull_al"]:
                out.append("SAT-KAPAT")
                state = 0
            else:
                out.append("SAT")
            continue

        # ---- DÜZ: giriş / nötr ---------------------------------------
        if yon > 0:
            # YALNIZ-LONG giriş (2026-11-15 kullanıcı kuralı): PEMBE en üst
            # + MAVİ en alt dizilimi VEYA HULL & VWMA ikisi de AL.
            # HULL SAT durumunda yeni LONG açılmaz.
            if not c["hull_sat"] and (c["long_entry"] or c["both_al"]):
                out.append("AL")
                state = 1
            else:
                out.append("NÖTR")
        elif yon < 0:
            # YALNIZ-SHORT: LONG dizilimi giriş üretmez. HULL AL (durum)
            # iken yeni SHORT açılmaz; NÖTR beklenir (2026-11-15).
            if c["short_entry"] and not c["hull_al"]:
                out.append("SAT")
                state = -1
            else:
                out.append("NÖTR")
        elif c["short_entry"] and not c["hull_al"]:
            out.append("SAT")
            state = -1
        elif c["long_entry"]:
            out.append("AL")
            state = 1
        else:
            out.append("NÖTR")

    return out


def label_at(ma_series: dict, idx: int, *,
             side: Optional[int] = None,
             prices: Optional[object] = None) -> str:
    """Tek barın kararı (seri baştan üretilir; nedensel)."""
    s = series(ma_series, side=side, prices=prices)
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
