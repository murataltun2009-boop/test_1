"""TİK2 kural listesi — osilatör + hareketli ortalama çiftleri.

KULLANICI KURALI (2026-11-06)
-----------------------------
TİK2'nin grafik/hesaplamaları DEĞİŞMEZ. Yalnızca pozisyon açma/kapama
kararı, kullanıcının verdiği satır listesine göre üretilir:

    * Her satırda bir DURUM (AL veya SAT), bir osilatör kümesi ve bir
      hareketli ortalama kümesi vardır.
    * SAT = SHORT, AL = LONG.
    * Bir satırın geçerli olması için o satırdaki **tüm osilatörler**
      ve **tüm hareketli ortalamalar** satırın yönünde olmalıdır
      (AL satırı: hepsi +1, SAT satırı: hepsi -1).
    * Satırlar arasında VEYA vardır: herhangi bir satır tutuyorsa sinyal
      o yöndedir.
    * Aynı barda hem AL hem SAT satırı tutuyorsa karar NÖTR'dür
      (çakışma -> işlem yok).
    * Hiçbir satır tutmuyorsa karar NÖTR'dür.

Girdi: `analysis.analyze()` çıktısındaki `osc_codes` ve `ma_codes`
sözlükleri. Bunlar TAM Türkçe etiket -> bar başına karar kodu
(+1 AL / 0 NÖTR / -1 SAT) eşlemesidir. Bu modül o sözlükleri YALNIZCA
OKUR; gösterge hesabına ve grafik serilerine dokunmaz.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import numpy as np

from core.analysis import MA_PERIODS, ma_labels

# --------------------------------------------------------------------------
# Etiket eşlemesi
# --------------------------------------------------------------------------
# Osilatör kısa adları -> analysis.OSCILLATOR_LABELS içindeki tam etiket.
# Yazım hataları (NUTHIS/MUTHIS, SKOTASTIK, WILLAMS, AGIRLIKI ...) burada
# normalize edilir; kural tablosu kullanıcının yazdığı gibi kalır.
OSC_BY_ALIAS: dict[str, str] = {
    "MACD": "MACD Seviyesi (12,26)",
    "MOMENTUM": "Momentum (10)",
    "EMTIA": "Emtia Kanal Endeksi(CCI) (20)",
    "EMTIA KANAL ENDEKS": "Emtia Kanal Endeksi(CCI) (20)",
    "STOKASTIK": "Stokastik %K (14, 3, 3)",
    "SKOTASTIK": "Stokastik %K (14, 3, 3)",
    "STOKASTIK RSI HIZLI": "Stokastik RSI Hızlı (3, 3, 14, 14)",
    "SKOTASTIK RSI HIZLI": "Stokastik RSI Hızlı (3, 3, 14, 14)",
    "WILLIAMS": "Williams Yüzde Aralığı (14)",
    "WILLIAMS YUZDE": "Williams Yüzde Aralığı (14)",
    "WILLAMS": "Williams Yüzde Aralığı (14)",
    "BOGA AYI": "Boğa Ayı Gücü",
    "BOGA GUCU": "Boğa Ayı Gücü",
    "MUTHIS OSILATOR": "Müthiş Osilatör",
    "NUTHIS OSILATOR": "Müthiş Osilatör",
    "NIHAI OSILATOR": "Nihai Osilatör(UO) (7, 14, 28)",
}

# Hareketli ortalama grupları. Kısa ad -> grup anahtarı.
MA_GROUP_BY_ALIAS: dict[str, str] = {
    "USTEL HAREKETLI": "EMA",
    "BASIT HAREKETLI": "SMA",
    "HULL": "HULL",
    "HULL HAREKETLI": "HULL",
    "HACIM AGIRLIKLI": "VWMA",
    "HACIM AGIRLIKI": "VWMA",      # kullanıcı yazımı
    "HACIM AGIRLIK": "VWMA",       # kullanıcı yazımı
    "HAREKETLI HEPSI": "ALL",
}

_TR = str.maketrans({
    "İ": "I", "ı": "I", "Ş": "S", "ş": "s",
    "Ğ": "G", "ğ": "g", "Ü": "U", "ü": "u",
    "Ö": "O", "ö": "o", "Ç": "C", "ç": "c",
})


def norm(text: str) -> str:
    """Türkçe büyük/küçük harf ve noktalama farklarını siler."""
    s = str(text).translate(_TR).upper()
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# MA etiketleri (analysis.ma_labels ile birebir aynı kaynaktan üretilir).
_MA_LABELS = ma_labels()
_EMA_LABELS = tuple(
    f"Üstel Hareketli Ortalama ({p})" for p in MA_PERIODS)
_SMA_LABELS = tuple(
    f"Basit Hareketli Ortalama({p})" for p in MA_PERIODS)
_ICHIMOKU, _VWMA, _HULL = _MA_LABELS[-3:]
_ALL_MA_LABELS = tuple(_MA_LABELS)

MA_GROUPS: dict[str, tuple[str, ...]] = {
    "EMA": _EMA_LABELS,
    "SMA": _SMA_LABELS,
    "HULL": (_HULL,),
    "VWMA": (_VWMA,),
    "ALL": _ALL_MA_LABELS,
}


@dataclass(frozen=True)
class Rule:
    """Tek bir kural satırı."""

    direction: int                    # +1 AL/LONG, -1 SAT/SHORT
    oscillators: tuple[str, ...]      # tam osilatör etiketleri
    mas: tuple[str, ...]              # tam MA etiketleri
    source: str                       # ham satır (denetim için)

    @property
    def label(self) -> str:
        return "AL" if self.direction > 0 else "SAT"


# --------------------------------------------------------------------------
# Kullanıcının verdiği kural listesi (74 satır, tekrarlar dahil).
# Biçim: DURUM | osilatörler | hareketli ortalamalar
# --------------------------------------------------------------------------
RAW_RULES = """
SAT|MACD|USTEL HAREKETLI,BASIT HAREKETLI,HULL HAREKETLI
AL|NUTHIS OSILATOR,MOMENTUM|HAREKETLI HEPSI
SAT|EMTIA|HULL
AL|SKOTASTIK, MOMENTUM, STOKASTIK RSI HIZLI|HAREKETLI HEPSI
SAT|MACD|HULL
AL|STOKASTIK RSI HIZLI,WILLIAMS YUZDE|HULL
SAT|MOMENTUM,MACD, WILLIAMS|HULL
AL|STOKASTIK RSI HIZLI,WILLIAMS YUZDE|HULL
SAT|WILLIAMS YUZDE|HULL
SAT|MOMENTUM,MACD, STOKASTIK RSI HIZLI|HULL, HACIM AGIRLIKI
SAT|MOMENTUM,MACD|HULL,HACIM AGIRLIKLI
SAT|MOMENTUM,MACD|HULL,HACIM AGIRLIKLI
AL|MACD|HULL, HACIM AGIRLIK
AL|STOKASTIK RSI HIZLI,WILLIAMS YUZDE|HULL
SAT|MOMENTUM,MACD|HULL,HACIM AGIRLIKLI
SAT|MOMENTUM,MACD|HULL,HACIM AGIRLIKLI
SAT|WILLIAMS,STOKASTIK RSI HIZLI,BOGA AYI|HULL
SAT|WILLIAMS,STOKASTIK RSI HIZLI,BOGA AYI|HULL
SAT|WILLAMS,STOKASTIK RSI HIZLI|HULL
SAT|MOMENTUM,MACD|HULL, HACIM AGIRLIKI
AL|EMTIA|HULL
AL|WILLIAMS,STOKASTIK RSI HIZLI,BOGA AYI|HULL
SAT|MOMENTUM|HULL
AL|MOMENTUM,MACD|HULL,HACIM AGIRLIKLI
SAT|EMTIA,SKOTASTIK RSI HIZLI|HULL
AL|BOGA AYI|HULL
SAT|MACD,STOKASTIK RSI HIZLI|HULL
SAT|MOMENTUM,MACD|HULL
SAT|MOMENTUM,MACD|HULL
AL|WILLIAMS,STOKASTIK RSI HIZLI|HULL
SAT|WILLIAMS,STOKASTIK RSI HIZLI,BOGA AYI|HULL
SAT|MOMENTUM|HULL
SAT|MOMENTUM, MACD|HULL
SAT|MOMENTUM,MACD,STOKASTIK RSI HIZLI|HULL, HACIM AGIRLIKI
AL|MOMENTUM,MACD,STOKASTIK RSI HIZLI, WILLIAMS|HULL, HACIM AGIRLIKI
SAT|MOMENTUM,MACD,STOKASTIK RSI HIZLI|HULL, HACIM AGIRLIKLI
AL|MOMENTUM,STOKASTIK RSI HIZLI, WILLIAMS|HULL
SAT|MOMENTUM,MACD,STOKASTIK RSI HIZLI|HULL, HACIM AGIRLIKLI
SAT|MOMENTUM,MACD,STOKASTIK RSI HIZLI|HULL, HACIM AGIRLIKLI
AL|STOKASTIK RSI HIZLI, WILLIAMS|HULL
SAT|WILLIAMS,STOKASTIK RSI HIZLI,BOGA AYI|HULL
SAT|MOMENTUM,STOKASTIK RSI HIZLI|HULL, HACIM AGIRLIKLI
AL|MOMENTUM,MACD,STOKASTIK RSI HIZLI, WILLIAMS,BOGA AYI|HULL, HACIM AGIRLIKLI
SAT|WILLIAMS,STOKASTIK RSI HIZLI|HULL
SAT|MOMENTUM,BOGA AYI|HULL
SAT|MOMENTUM,MACD|HACIM AGIRLIKLI
AL|MOMENTUM,STOKASTIK RSI HIZLI, WILLIAMS,BOGA AYI|HULL
SAT|WILLIAMS|HULL
SAT|STOKASTIK RSI HIZLI,BOGA AYI|HULL
SAT|MOMENTUM, MACD|HULL
AL|EMTIA KANAL ENDEKS|HULL
AL|STOKASTIK RSI HIZLI, WILLIAMS,BOGA AYI|HULL
SAT|MOMENTUM,MACD|HULL, HACIM AGIRLIKLI
SAT|MOMENTUM,MACD,STOKASTIK RSI HIZLI,|HACIM AGIRLIKLI
SAT|MACD,STOKASTIK RSI HIZLI|HULL, HACIM AGIRLIKLI
AL|STOKASTIK,EMTIA|HULL
AL|WILLIAMS, BOGA AYI|HULL, HACIM AGIRLIKLI
SAT|WILLIAMS|HULL
AL|MOMENTUM, MACD|HULL, HACIM AGIRLIKLI
SAT|STOKASTIK,EMTIA,NIHAI OSILATOR|HULL
SAT|WILLIAMS|HULL
AL|MOMENTUM, MACD|HULL, HACIM AGIRLIKLI
SAT|MOMENTUM, MACD|HACIM AGIRLIKLI
SAT|MOMENTUM, MACD|HULL, HACIM AGIRLIKLI
SAT|MUTHIS OSILATOR,MOMENTUM, MACD|HULL, HACIM AGIRLIKLI
AL|MOMENTUM, MACD|HULL, HACIM AGIRLIKLI
AL|MOMENTUM,MACD,STOKASTIK RSI HIZLI,|HACIM AGIRLIKLI
SAT|EMTIA KANAL ENDEKS|HULL
SAT|MOMENTUM, WILLIAMS|HULL
SAT|STOKASTIK, MOMENTUM,MACD,STOKASTIK RSI HIZLI,|HULL, HACIM AGIRLIKLI
AL|MOMENTUM|HULL, HACIM AGIRLIKLI
SAT|EMTIA,SKOTASTIK RSI HIZLI|HULL
SAT|STOKASTIK, WILLIAMS,BOGA GUCU,STOKASTIK RSI HIZLI,|HULL
SAT|MOMENTUM,MACD,STOKASTIK RSI HIZLI,|HULL
""".strip()


def _split(text: str) -> list[str]:
    """Virgülle ayırır, boş parçaları atar, normalize eder."""
    out: list[str] = []
    for part in str(text).replace(";", ",").split(","):
        n = norm(part)
        if n:
            out.append(n)
    return out


def _resolve_osc(token: str, raw: str) -> str:
    try:
        return OSC_BY_ALIAS[token]
    except KeyError:
        raise ValueError(
            f"TİK2 kuralı: bilinmeyen osilatör {token!r} ({raw!r})") from None


def _resolve_ma(token: str, raw: str) -> str:
    try:
        group = MA_GROUP_BY_ALIAS[token]
    except KeyError:
        raise ValueError(
            f"TİK2 kuralı: bilinmeyen hareketli ortalama {token!r} "
            f"({raw!r})") from None
    return group


def _parse(raw_rows: str) -> tuple[Rule, ...]:
    rules: list[Rule] = []
    for line in raw_rows.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 3:
            raise ValueError(f"TİK2 kuralı bozuk satır: {line!r}")
        durum = norm(parts[0])
        if durum not in ("AL", "SAT"):
            raise ValueError(f"TİK2 kuralı: geçersiz DURUM {durum!r}")
        direction = 1 if durum == "AL" else -1

        osc_labels: list[str] = []
        for token in _split(parts[1]):
            lab = _resolve_osc(token, line)
            if lab not in osc_labels:
                osc_labels.append(lab)
        if not osc_labels:
            raise ValueError(f"TİK2 kuralı: osilatör yok: {line!r}")

        ma_labels_out: list[str] = []
        for token in _split(parts[2]):
            group = _resolve_ma(token, line)
            for lab in MA_GROUPS[group]:
                if lab not in ma_labels_out:
                    ma_labels_out.append(lab)
        if not ma_labels_out:
            raise ValueError(
                f"TİK2 kuralı: hareketli ortalama yok: {line!r}")

        rules.append(Rule(direction=direction,
                          oscillators=tuple(osc_labels),
                          mas=tuple(ma_labels_out),
                          source=line))
    return tuple(rules)


RULES: tuple[Rule, ...] = _parse(RAW_RULES)


# --------------------------------------------------------------------------
# Seri üretimi
# --------------------------------------------------------------------------
def _array(store: dict, label: str, n: int) -> Optional[np.ndarray]:
    """Etiketi bar dizisine çevirir; eksik/bozuk etiket -> None."""
    arr = store.get(label)
    if arr is None:
        return None
    arr = np.asarray(arr)
    if arr.size != n:
        return None
    return arr


def rule_masks(osc_codes: dict, ma_codes: dict) -> tuple[np.ndarray, np.ndarray]:
    """Her kural satırının bar başına tutma maskesini döndürür."""
    n = 0
    for store in (osc_codes or {}, ma_codes or {}):
        for arr in store.values():
            n = max(n, int(np.asarray(arr).size))
    if n == 0:
        return np.zeros(0, dtype=bool), np.zeros(0, dtype=bool)

    d = np.asarray([r.direction for r in RULES], dtype=np.int8)
    masks = np.zeros((len(RULES), n), dtype=bool)
    for i, rule in enumerate(RULES):
        m = np.ones(n, dtype=bool)
        ok = True
        for lab in rule.oscillators:
            arr = _array(osc_codes, lab, n)
            if arr is None:
                ok = False
                break
            m &= (arr == rule.direction)
        if ok:
            for lab in rule.mas:
                arr = _array(ma_codes, lab, n)
                if arr is None:
                    ok = False
                    break
                m &= (arr == rule.direction)
        if ok:
            masks[i] = m
    # Not: d yalnızca denetim/raporlama için; ayrım mask üzerinden.
    _ = d
    return masks, d


def series(osc_codes: dict, ma_codes: dict) -> list[str]:
    """Bar başına TİK2 kararı: "AL" / "SAT" / "NÖTR"."""
    masks, d = rule_masks(osc_codes, ma_codes)
    if masks.shape[1] == 0:
        return []
    al = (masks & (d[:, None] > 0)).any(axis=0)
    sat = (masks & (d[:, None] < 0)).any(axis=0)
    out: list[str] = []
    for a, s in zip(al, sat):
        if a and not s:
            out.append("AL")
        elif s and not a:
            out.append("SAT")
        else:
            out.append("NÖTR")
    return out


def decision_at(osc_codes: dict, ma_codes: dict, idx: int) -> str:
    """Tek bar için karar (seriyi baştan üretmeden)."""
    s = series(osc_codes, ma_codes)
    if 0 <= idx < len(s):
        return s[idx]
    return "NÖTR"


def summary() -> dict:
    """Kural tablosunun özeti (test/teşhis)."""
    return {
        "rows": len(RULES),
        "al": sum(1 for r in RULES if r.direction > 0),
        "sat": sum(1 for r in RULES if r.direction < 0),
        "unique": len({(r.direction, r.oscillators, r.mas) for r in RULES}),
        "oscillators": sorted({o for r in RULES for o in r.oscillators}),
        "mas": sorted({m for r in RULES for m in r.mas}),
    }
