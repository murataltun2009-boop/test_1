# -*- coding: utf-8 -*-
"""Hareketli_Yeni — hareketli ortalama AL/SAT/NÖTR sayısı algoritması.

KULLANICI KURALI (2026-11-28, 5 dk periyot)

Grafikteki 15 hareketli ortalamanın (EMA/SMA 10-200, İchimoku, VWMA20, HULL9)
o bar için kararını sayar:
    AL   = fiyat ortalamanın belirgin ÜSTÜNDE
    SAT  = fiyat ortalamanın belirgin ALTINDA
    NÖTR = ölü bant içi (fiyat ortalama seviyesinde)

  LONG  : AL sayısı > SAT sayısı VE AL sayısı > NÖTR sayısı olduğu
          sürece LONG aç / pozisyonda kal.
  LONG KAPAT: AL sayısı ≤ NÖTR sayısı VEYA AL sayısı ≤ SAT sayısı
          (eşitlik veya küçülme) olduğunda LONG'u kapat ve NÖTR'e geç.
  SHORT : SAT sayısı > AL sayısı VE SAT sayısı > NÖTR sayısı olduğu
          sürece SHORT aç / pozisyonda kal.
  SHORT KAPAT: SAT sayısı ≤ NÖTR sayısı VEYA SAT sayısı ≤ AL sayısı
          (eşitlik veya küçülme) olduğunda SHORT'u kapat ve NÖTR'e geç.

Kararlar yalnız KAPANMIŞ mumdan üretilir (bar kapanışı). Kapanıştan
sonra kural sürekli izlenir; yeni yön koşulu oluşursa sonraki barda
yeni pozisyon açılır.

ÜÇ VARYANT (TAKİPÇİ / ALGO-GRAF ile aynı desen):
    hareketli_yeni       : iki yön — LONG ve SHORT birlikte (sırayla)
    hareketli_yeni_long  : yalnız LONG (SHORT hiç açılmaz)
    hareketli_yeni_short : yalnız SHORT (LONG hiç açılmaz)

YÜRÜTME: `paper._algograf` yürütücüsü kullanılır — kâr bankası, zarar
freni ve "Min. bekleme" aynen geçerlidir; koruyucu stop KAPALIDIR.

Pozisyon aç/kapa log satırlarında o barın sayıları da gösterilir:
    "AL 9 / SAT 3 / NÖTR 3"
"""
from __future__ import annotations

from typing import Optional

import numpy as np

# Üç varyant (TAKİPÇİ / ALGO-GRAF ile aynı desen).
MODES: tuple[str, ...] = (
    "hareketli_yeni", "hareketli_yeni_long", "hareketli_yeni_short")

LABELS: tuple[str, ...] = ("AL", "SAT", "NÖTR", "AL-KAPAT", "SAT-KAPAT")


def is_mode(mode: object) -> bool:
    """Mod Hareketli_Yeni ailesinden mi?"""
    return str(mode or "").strip() in MODES


def side_for_mode(mode: object) -> Optional[int]:
    """Varyantın izin verdiği yön: +1 long-only, -1 short-only, None iki yön."""
    m = str(mode or "").strip()
    if m == "hareketli_yeni_long":
        return 1
    if m == "hareketli_yeni_short":
        return -1
    return None


def counts_text(al: int, sat: int, notr: int) -> str:
    """Log satırı için sayı metni."""
    return f"AL {int(al)} / SAT {int(sat)} / NÖTR {int(notr)}"


def _arrays(ma_codes: dict) -> list:
    out = []
    for value in (ma_codes or {}).values():
        try:
            out.append(np.asarray(value, dtype=np.int8).reshape(-1))
        except (TypeError, ValueError):
            return []
    return out


def counts_at(ma_codes: dict, idx: int) -> tuple[int, int, int]:
    """Bir barın AL/SAT/NÖTR sayıları (15 hareketli ortalama)."""
    al = sat = notr = 0
    i = int(idx)
    for arr in _arrays(ma_codes):
        if 0 <= i < arr.size:
            code = int(arr[i])
            if code > 0:
                al += 1
            elif code < 0:
                sat += 1
            else:
                notr += 1
    return al, sat, notr


def series_with_counts(
        ma_codes: dict,
        side: Optional[int] = None
) -> tuple[list[str], list[tuple[int, int, int]]]:
    """Bar başına karar + AL/SAT/NÖTR sayıları (pozisyona duyarlı).

    `side`: +1 yalnız LONG, -1 yalnız SHORT, None iki yön. `paper.py` ve
    `service.py` AYNI fonksiyonu çağırır; canlı, geriye dönük test ve grafik
    yıldızları birebir aynı kararı gösterir.

    Seri NEDENSELDİR: i. bar yalnızca 0..i barlarına bakar.
    """
    arrs = _arrays(ma_codes)
    if not arrs:
        return [], []
    n = min(arr.size for arr in arrs)
    if n <= 0:
        return [], []

    yon = 0 if side is None else (1 if int(side) > 0 else -1)
    out: list[str] = []
    counts: list[tuple[int, int, int]] = []
    state = 0              # +1 LONG, -1 SHORT, 0 düz

    for i in range(n):
        al = sat = notr = 0
        for arr in arrs:
            code = int(arr[i])
            if code > 0:
                al += 1
            elif code < 0:
                sat += 1
            else:
                notr += 1
        counts.append((al, sat, notr))

        # Kullanıcı kuralı: sayı "en büyük" olmalı; eşitlik kapatır.
        long_ok = al > sat and al > notr
        short_ok = sat > al and sat > notr

        if state > 0:
            if long_ok:
                out.append("AL")
            else:
                out.append("AL-KAPAT")
                state = 0
            continue

        if state < 0:
            if short_ok:
                out.append("SAT")
            else:
                out.append("SAT-KAPAT")
                state = 0
            continue

        if yon > 0:
            if long_ok:
                out.append("AL")
                state = 1
            else:
                out.append("NÖTR")
        elif yon < 0:
            if short_ok:
                out.append("SAT")
                state = -1
            else:
                out.append("NÖTR")
        elif long_ok:
            out.append("AL")
            state = 1
        elif short_ok:
            out.append("SAT")
            state = -1
        else:
            out.append("NÖTR")

    return out, counts


def series(ma_codes: dict, *, side: Optional[int] = None) -> list[str]:
    """Bar başına Hareketli_Yeni kararı (AL/SAT/NÖTR/AL-KAPAT/SAT-KAPAT)."""
    return series_with_counts(ma_codes, side=side)[0]


def label_at(ma_codes: dict, idx: int, *,
             side: Optional[int] = None) -> str:
    """Tek barın kararı (seri baştan üretilir; nedensel)."""
    s = series(ma_codes, side=side)
    if 0 <= int(idx) < len(s):
        return s[int(idx)]
    return "NÖTR"


def summary() -> dict:
    """Test/araştırma için özet."""
    return {"modes": list(MODES), "labels": list(LABELS)}