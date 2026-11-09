"""TİK2 kural listesi — kullanıcı karar tablosu (2026-11-09).

KULLANICI KURALI (2026-11-09, `list2.xlsx`, BTCUSDT 5m)
--------------------------------------------------------
TİK2'nin grafik/hesaplamaları DEĞİŞMEZ. Yalnızca pozisyon açma/kapama
kararı, kullanıcının verdiği 85 satırlık tablodan üretilir:

    * Her satırda bir POZİYON (AL veya SAT) ve gösterge durumları
      vardır. AL = LONG, SAT = SHORT.
    * Osilatör ve hareketli ortalama sütunlarında her gösterge için
      durum yazılıdır: AL (+1), SAT (-1), NÖTR (0).
    * Bir satır, yazılan **tüm göstergelerin durumu aynen**
      sağlandığında geçerlidir. Yazılmayan göstergeler serbesttir.
    * Birden çok satır tutarsa **en çok gösterge belirten (en özel)**
      satır kazanır. Eşitlikte **sonraki satır** geçerlidir.
    * Hiçbir satır tutmuyorsa karar NÖTR'dür.

Eski "tüm göstergeler satır yönünde" biçimi geriye dönük uyumluluk
için desteklenir: durum yazılmayan gösterge satır yönünde kabul edilir.

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

import config
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
    "WILLIAMSYUZDE": "Williams Yüzde Aralığı (14)",
    "WILLAMS": "Williams Yüzde Aralığı (14)",
    "BOGA AYI": "Boğa Ayı Gücü",
    "BOGAAYI": "Boğa Ayı Gücü",
    "BOGA GUCU": "Boğa Ayı Gücü",
    "MUTHIS OSILATOR": "Müthiş Osilatör",
    "MUTHISOSILATOR": "Müthiş Osilatör",
    "NUTHIS OSILATOR": "Müthiş Osilatör",
    "NIHAI OSILATOR": "Nihai Osilatör(UO) (7, 14, 28)",
    "NIHAIOSILATOR": "Nihai Osilatör(UO) (7, 14, 28)",
    "YONSEL ENDEKS": "Ortalama Yönsel Endeks(ADX) (14)",
    "YONSELENDEKS": "Ortalama Yönsel Endeks(ADX) (14)",
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
    """Tek bir kural satırı.

    `osc_states` / `ma_states` : (tam etiket, istenen kod) çiftleri.
    Kodlar +1 AL, 0 NÖTR, -1 SAT. Eski biçimde (durum yazılmamış)
    çiftler satır yönüyle doldurulur; bu durumda eşleşme eski
    "hepsi satır yönünde" kuralına döner.
    """

    direction: int                    # +1 AL/LONG, -1 SAT/SHORT
    oscillators: tuple[str, ...]      # tam osilatör etiketleri
    mas: tuple[str, ...]              # tam MA etiketleri
    source: str                       # ham satır (denetim için)
    osc_states: tuple[tuple[str, int], ...] = ()
    ma_states: tuple[tuple[str, int], ...] = ()

    @property
    def label(self) -> str:
        return "AL" if self.direction > 0 else "SAT"

    @property
    def specificity(self) -> int:
        """Koşuldaki gösterge sayısı (en özel satır seçimi için)."""
        n = len(self.osc_states) + len(self.ma_states)
        if n:
            return n
        return len(self.oscillators) + len(self.mas)

    def osc_pairs(self) -> tuple[tuple[str, int], ...]:
        if self.osc_states:
            return self.osc_states
        return tuple((lab, self.direction) for lab in self.oscillators)

    def ma_pairs(self) -> tuple[tuple[str, int], ...]:
        if self.ma_states:
            return self.ma_states
        return tuple((lab, self.direction) for lab in self.mas)


# --------------------------------------------------------------------------
# Kullanıcının verdiği kural listesi (85 satır, `list2.xlsx`, BTCUSDT 5m).
# Biçim: POZİYON | osilatörler (DURUM) | hareketli ortalamalar (DURUM)
# DURUM: AL (+1) / SAT (-1) / NOTR (0). Durum yazılmayan gösterge satır
# yönünde kabul edilir (eski biçim uyumluluğu).
# --------------------------------------------------------------------------
RAW_RULES = """
AL|MOMENTUM(AL),MACD(AL)|HACIM AGIRLIKLI(AL),HULL(NOTR)
AL|MOMENTUM(AL),MACD(AL),STOKASTIK RSI HIZLI(AL)|HACIM AGIRLIKLI(AL),HULL(NOTR)
AL|MOMENTUM(AL),MACD(AL),STOKASTIK RSI HIZLI(SAT)|HACIM AGIRLIKLI(AL),HULL(NOTR)
AL|MOMENTUM(AL),MACD(AL)|HACIM AGIRLIKLI(AL),HULL(NOTR)
AL|MOMENTUM(AL),MACD(AL)|HACIM AGIRLIKLI(AL),HULL(AL)
AL|MOMENTUM(AL),MACD(AL),EMTIA(SAT)|HACIM AGIRLIKLI(AL),HULL(AL)
AL|MOMENTUM(AL),MACD(AL)|HACIM AGIRLIKLI(AL),HULL(NOTR)
AL|MOMENTUM(AL),MACD(AL)|HACIM AGIRLIKLI(AL),HULL(NOTR)
AL|MOMENTUM(AL),MACD(AL)|HACIM AGIRLIKLI(AL),HULL(AL)
AL|MOMENTUM(AL),MACD(AL)|HACIM AGIRLIKLI(AL),HULL(NOTR)
SAT|EMTIA(SAT),MOMENTUM(AL),MACD(AL)|HACIM AGIRLIKLI(AL),HULL(AL)
SAT|MOMENTUM(AL),MACD(AL)|HACIM AGIRLIKLI(NOTR),HULL(SAT)
SAT|MOMENTUM(AL),MACD(AL),BOGA AYI(SAT)|HACIM AGIRLIKLI(NOTR),HULL(SAT)
SAT|MOMENTUM(AL),MACD(AL)|HACIM AGIRLIKLI(NOTR),HULL(SAT)
SAT|MOMENTUM(AL),MACD(SAT)|HACIM AGIRLIKLI(NOTR),HULL(NOTR)
SAT|MOMENTUM(SAT),MACD(SAT),NIHAI OSILATOR(AL)|HACIM AGIRLIKLI(SAT),HULL(NOTR)
SAT|MOMENTUM(SAT),MACD(SAT),NIHAI OSILATOR(AL)|HACIM AGIRLIKLI(SAT),HULL(NOTR)
AL|MOMENTUM(SAT),MACD(SAT),STOKASTIK RSI HIZLI(AL)|HACIM AGIRLIKLI(SAT),HULL(NOTR)
AL|MOMENTUM(SAT),MACD(SAT),STOKASTIK(AL),WILLIAMS YUZDE(AL)|HACIM AGIRLIKLI(SAT),HULL(AL)
AL|MOMENTUM(SAT),MACD(SAT)|HACIM AGIRLIKLI(SAT),HULL(AL)
AL|MOMENTUM(AL),MACD(SAT),BOGA AYI(SAT)|HACIM AGIRLIKLI(SAT),HULL(NOTR)
SAT|MOMENTUM(AL),MACD(SAT),BOGA AYI(SAT)|HACIM AGIRLIKLI(NOTR),HULL(NOTR)
SAT|MOMENTUM(AL),MACD(SAT),MUTHIS OSILATOR(AL)|HACIM AGIRLIKLI(NOTR),HULL(NOTR)
SAT|MOMENTUM(SAT),MACD(SAT),BOGA AYI(SAT)|HACIM AGIRLIKLI(SAT),HULL(SAT)
SAT|MOMENTUM(SAT),MACD(SAT),BOGA AYI(SAT),WILLIAMS(SAT),STOKASTIK RSI HIZLI(NOTR)|HACIM AGIRLIKLI(SAT),HULL(SAT)
SAT|MOMENTUM(AL),MACD(SAT),BOGA AYI(AL),WILLIAMS(NOTR),STOKASTIK RSI HIZLI(NOTR)|HACIM AGIRLIKLI(SAT),HULL(NOTR)
SAT|MOMENTUM(AL),MACD(SAT),MUTHIS OSILATOR(SAT)|HACIM AGIRLIKLI(NOTR),HULL(NOTR)
SAT|MOMENTUM(AL),MACD(SAT),STOKASTIK RSI HIZLI(AL),WILLIAMS YUZDE(AL),WILLIAMS(NOTR)|HACIM AGIRLIKLI(NOTR),HULL(NOTR)
SAT|MOMENTUM(AL),MACD(SAT),BOGA AYI(NOTR)|HACIM AGIRLIKLI(NOTR),HULL(NOTR)
SAT|MOMENTUM(SAT),MACD(SAT),BOGA AYI(NOTR),WILLIAMS(NOTR),STOKASTIK RSI HIZLI(SAT)|HACIM AGIRLIKLI(NOTR),HULL(NOTR)
SAT|MOMENTUM(SAT),MACD(SAT),BOGA AYI(NOTR),WILLIAMS(NOTR),STOKASTIK RSI HIZLI(NOTR)|HACIM AGIRLIKLI(SAT),HULL(SAT)
SAT|EMTIA(AL),MOMENTUM(SAT),MACD(SAT),BOGA AYI(NOTR),WILLIAMS(NOTR),STOKASTIK RSI HIZLI(NOTR)|HACIM AGIRLIKLI(SAT),HULL(NOTR)
SAT|EMTIA(AL),MOMENTUM(SAT),MACD(SAT),BOGA AYI(NOTR),WILLIAMS(NOTR),STOKASTIK RSI HIZLI(AL)|HACIM AGIRLIKLI(SAT),HULL(NOTR)
SAT|EMTIA(AL),MOMENTUM(SAT),MACD(SAT),BOGA AYI(NOTR),WILLIAMS(NOTR),STOKASTIK RSI HIZLI(AL)|HACIM AGIRLIKLI(SAT),HULL(NOTR)
AL|EMTIA(AL),MOMENTUM(SAT),MACD(SAT),STOKASTIK RSI HIZLI(NOTR),WILLIAMS(AL)|HACIM AGIRLIKLI(SAT),HULL(AL)
SAT|MOMENTUM(SAT),MACD(SAT),WILLIAMS(NOTR),STOKASTIK RSI HIZLI(NOTR)|HACIM AGIRLIKLI(SAT),HULL(NOTR)
SAT|EMTIA(AL),MOMENTUM(SAT),MACD(SAT),STOKASTIK RSI HIZLI(NOTR),WILLIAMS(NOTR)|HACIM AGIRLIKLI(SAT),HULL(NOTR)
SAT|EMTIA(NOTR),MOMENTUM(SAT),MACD(SAT),STOKASTIK RSI HIZLI(SAT),WILLIAMS(NOTR),BOGA AYI(AL)|HACIM AGIRLIKLI(SAT),HULL(NOTR)
SAT|EMTIA(AL),MOMENTUM(SAT),MACD(SAT),STOKASTIK RSI HIZLI(NOTR),WILLIAMS(NOTR)|HACIM AGIRLIKLI(SAT),HULL(NOTR)
AL|EMTIA(NOTR),MOMENTUM(SAT),MACD(SAT),STOKASTIK RSI HIZLI(AL),WILLIAMS(NOTR),BOGA AYI(AL)|HACIM AGIRLIKLI(SAT),HULL(AL)
AL|EMTIA(NOTR),MOMENTUM(AL),MACD(AL),STOKASTIK RSI HIZLI(NOTR),WILLIAMS(NOTR),BOGA AYI(NOTR)|HACIM AGIRLIKLI(AL),HULL(AL)
AL|EMTIA(SAT),MOMENTUM(AL),MACD(AL),STOKASTIK RSI HIZLI(NOTR),WILLIAMS(NOTR),BOGA AYI(NOTR)|HACIM AGIRLIKLI(AL),HULL(AL)
AL|EMTIA(SAT),MOMENTUM(AL),MACD(AL),STOKASTIK RSI HIZLI(NOTR),WILLIAMS(NOTR),BOGA AYI(NOTR),MUTHIS OSILATOR(AL)|HACIM AGIRLIKLI(AL),HULL(NOTR)
SAT|EMTIA(NOTR),MOMENTUM(AL),MACD(AL),STOKASTIK RSI HIZLI(NOTR),WILLIAMS(NOTR),BOGA AYI(NOTR),MUTHIS OSILATOR(AL)|HACIM AGIRLIKLI(AL),HULL(NOTR)
SAT|EMTIA(SAT),MOMENTUM(AL),MACD(AL),STOKASTIK RSI HIZLI(NOTR),WILLIAMS(NOTR),BOGA AYI(NOTR),MUTHIS OSILATOR(NOTR)|HACIM AGIRLIKLI(AL),HULL(SAT)
SAT|EMTIA(SAT),MOMENTUM(AL),MACD(AL),STOKASTIK RSI HIZLI(NOTR),WILLIAMS(NOTR),BOGA AYI(NOTR),MUTHIS OSILATOR(NOTR)|HACIM AGIRLIKLI(AL),HULL(SAT)
SAT|EMTIA(SAT),MOMENTUM(AL),MACD(AL),STOKASTIK RSI HIZLI(NOTR),WILLIAMS(SAT),BOGA AYI(NOTR),MUTHIS OSILATOR(NOTR)|HACIM AGIRLIKLI(AL),HULL(SAT)
AL|EMTIA(NOTR),MOMENTUM(AL),MACD(AL),STOKASTIK RSI HIZLI(NOTR),WILLIAMS(NOTR),BOGA AYI(NOTR),MUTHIS OSILATOR(NOTR)|HACIM AGIRLIKLI(AL),HULL(NOTR)
AL|EMTIA(NOTR),MOMENTUM(AL),MACD(AL),STOKASTIK RSI HIZLI(NOTR),WILLIAMS(NOTR)|HACIM AGIRLIKLI(AL),HULL(NOTR)
AL|EMTIA(NOTR),MOMENTUM(AL),MACD(AL),STOKASTIK RSI HIZLI(AL),WILLIAMS(NOTR),BOGA AYI(NOTR),MUTHIS OSILATOR(NOTR)|HACIM AGIRLIKLI(AL),HULL(AL)
AL|EMTIA(NOTR),MOMENTUM(AL),MACD(AL),STOKASTIK RSI HIZLI(NOTR),WILLIAMS(SAT),BOGA AYI(NOTR),MUTHIS OSILATOR(NOTR)|HACIM AGIRLIKLI(AL),HULL(NOTR)
AL|EMTIA(NOTR),MOMENTUM(AL),MACD(AL),STOKASTIK RSI HIZLI(NOTR),WILLIAMS(SAT),BOGA AYI(NOTR),MUTHIS OSILATOR(NOTR)|HACIM AGIRLIKLI(AL),HULL(NOTR)
AL|EMTIA(NOTR),MOMENTUM(AL),MACD(AL),STOKASTIK RSI HIZLI(AL),WILLIAMS(SAT),BOGA AYI(NOTR),MUTHIS OSILATOR(NOTR)|HACIM AGIRLIKLI(AL),HULL(NOTR)
AL|EMTIA(NOTR),MOMENTUM(AL),MACD(AL),STOKASTIK RSI HIZLI(AL),WILLIAMS(NOTR),BOGA AYI(NOTR),MUTHIS OSILATOR(NOTR)|HACIM AGIRLIKLI(AL),HULL(AL)
AL|EMTIA(NOTR),STOKASTIK(AL),MOMENTUM(AL),MACD(AL),STOKASTIK RSI HIZLI(AL),WILLIAMS(NOTR),BOGA AYI(NOTR),MUTHIS OSILATOR(NOTR)|HACIM AGIRLIKLI(AL),HULL(AL)
SAT|EMTIA(NOTR),STOKASTIK(NOTR),MOMENTUM(AL),MACD(AL),STOKASTIK RSI HIZLI(AL),WILLIAMS(NOTR),BOGA AYI(NOTR),MUTHIS OSILATOR(NOTR)|HACIM AGIRLIKLI(AL),HULL(NOTR)
SAT|EMTIA(NOTR),STOKASTIK(NOTR),MOMENTUM(AL),MACD(AL),STOKASTIK RSI HIZLI(NOTR),WILLIAMS(SAT),BOGA AYI(NOTR),MUTHIS OSILATOR(NOTR)|HACIM AGIRLIKLI(AL),HULL(NOTR)
SAT|EMTIA(NOTR),STOKASTIK(NOTR),MOMENTUM(SAT),MACD(SAT),STOKASTIK RSI HIZLI(SAT),WILLIAMS(NOTR),BOGA AYI(SAT),MUTHIS OSILATOR(NOTR)|HACIM AGIRLIKLI(NOTR),HULL(SAT)
SAT|EMTIA(NOTR),STOKASTIK(NOTR),MOMENTUM(AL),MACD(SAT),STOKASTIK RSI HIZLI(NOTR),WILLIAMS(NOTR),BOGA AYI(NOTR),MUTHIS OSILATOR(NOTR)|HACIM AGIRLIKLI(NOTR),HULL(SAT)
SAT|EMTIA(NOTR),STOKASTIK(NOTR),MOMENTUM(SAT),MACD(SAT),STOKASTIK RSI HIZLI(NOTR),WILLIAMS(NOTR),BOGA AYI(NOTR),NIHAI OSILATOR(AL)|HACIM AGIRLIKLI(SAT),HULL(SAT)
AL|EMTIA(NOTR),STOKASTIK(NOTR),MOMENTUM(SAT),MACD(SAT),STOKASTIK RSI HIZLI(NOTR),WILLIAMS(NOTR),BOGA AYI(NOTR),NIHAI OSILATOR(AL)|HACIM AGIRLIKLI(SAT),HULL(NOTR)
AL|EMTIA(NOTR),STOKASTIK(NOTR),MOMENTUM(SAT),MACD(SAT),STOKASTIK RSI HIZLI(AL),WILLIAMS(NOTR),BOGA AYI(NOTR),NIHAI OSILATOR(AL)|HACIM AGIRLIKLI(SAT),HULL(AL)
AL|EMTIA(NOTR),STOKASTIK(AL),MOMENTUM(SAT),MACD(SAT),STOKASTIK RSI HIZLI(AL),WILLIAMS(AL),BOGA AYI(NOTR),NIHAI OSILATOR(NOTR)|HACIM AGIRLIKLI(SAT),HULL(AL)
SAT|EMTIA(NOTR),STOKASTIK(AL),MOMENTUM(SAT),MACD(SAT),STOKASTIK RSI HIZLI(NOTR),WILLIAMS(NOTR),BOGA AYI(SAT),NIHAI OSILATOR(NOTR),YONSEL ENDEKS(SAT)|HACIM AGIRLIKLI(SAT),HULL(NOTR)
SAT|EMTIA(NOTR),STOKASTIK(NOTR),MOMENTUM(AL),MACD(AL),STOKASTIK RSI HIZLI(NOTR),WILLIAMS(SAT),BOGA AYI(NOTR),NIHAI OSILATOR(NOTR)|HACIM AGIRLIKLI(AL),HULL(NOTR)
SAT|EMTIA(NOTR),STOKASTIK(NOTR),MOMENTUM(SAT),MACD(SAT),STOKASTIK RSI HIZLI(SAT),WILLIAMS(NOTR),BOGA AYI(NOTR),NIHAI OSILATOR(NOTR)|HACIM AGIRLIKLI(NOTR),HULL(SAT)
SAT|EMTIA(NOTR),STOKASTIK(NOTR),MOMENTUM(SAT),MACD(SAT),STOKASTIK RSI HIZLI(SAT),WILLIAMS(NOTR),BOGA AYI(NOTR),NIHAI OSILATOR(NOTR)|HACIM AGIRLIKLI(NOTR),HULL(SAT)
SAT|EMTIA(NOTR),STOKASTIK(NOTR),MOMENTUM(SAT),MACD(SAT),STOKASTIK RSI HIZLI(NOTR),WILLIAMS(NOTR),BOGA AYI(NOTR),NIHAI OSILATOR(AL)|HACIM AGIRLIKLI(SAT),HULL(SAT)
AL|EMTIA(NOTR),STOKASTIK(NOTR),MOMENTUM(SAT),MACD(SAT),STOKASTIK RSI HIZLI(AL),WILLIAMS(NOTR),BOGA AYI(NOTR),NIHAI OSILATOR(AL)|HACIM AGIRLIKLI(SAT),HULL(AL)
AL|EMTIA(NOTR),STOKASTIK(AL),MOMENTUM(SAT),MACD(SAT),STOKASTIK RSI HIZLI(NOTR),WILLIAMS(AL),BOGA AYI(NOTR),NIHAI OSILATOR(NOTR)|HACIM AGIRLIKLI(SAT),HULL(AL)
AL|EMTIA(NOTR),STOKASTIK(NOTR),MOMENTUM(SAT),MACD(SAT),STOKASTIK RSI HIZLI(NOTR),WILLIAMS(NOTR),BOGA AYI(AL),NIHAI OSILATOR(NOTR)|HACIM AGIRLIKLI(NOTR),HULL(AL)
AL|EMTIA(NOTR),STOKASTIK(NOTR),MOMENTUM(SAT),MACD(SAT),STOKASTIK RSI HIZLI(NOTR),WILLIAMS(NOTR),BOGA AYI(NOTR),NIHAI OSILATOR(NOTR)|HACIM AGIRLIKLI(NOTR),HULL(AL)
SAT|EMTIA(NOTR),YONSEL ENDEKS(SAT),MOMENTUM(SAT),MACD(SAT),STOKASTIK RSI HIZLI(NOTR),WILLIAMS(NOTR),BOGA AYI(SAT),NIHAI OSILATOR(NOTR)|HACIM AGIRLIKLI(SAT),HULL(NOTR)
SAT|EMTIA(NOTR),STOKASTIK(SAT),MOMENTUM(SAT),MACD(SAT),STOKASTIK RSI HIZLI(SAT),WILLIAMS(NOTR),BOGA AYI(NOTR),NIHAI OSILATOR(NOTR)|HACIM AGIRLIKLI(SAT),HULL(SAT)
SAT|EMTIA(NOTR),STOKASTIK(NOTR),MOMENTUM(SAT),MACD(SAT),STOKASTIK RSI HIZLI(NOTR),WILLIAMS(NOTR),BOGA AYI(NOTR),NIHAI OSILATOR(NOTR)|HACIM AGIRLIKLI(SAT),HULL(NOTR)
SAT|EMTIA(NOTR),STOKASTIK(NOTR),MUTHIS OSILATOR(SAT),MOMENTUM(AL),MACD(SAT),STOKASTIK RSI HIZLI(NOTR),WILLIAMS(NOTR),BOGA AYI(NOTR),NIHAI OSILATOR(NOTR)|HACIM AGIRLIKLI(SAT),HULL(SAT)
SAT|EMTIA(NOTR),STOKASTIK(NOTR),MUTHIS OSILATOR(SAT),MOMENTUM(SAT),MACD(SAT),STOKASTIK RSI HIZLI(NOTR),WILLIAMS(NOTR),BOGA AYI(NOTR),NIHAI OSILATOR(NOTR)|HACIM AGIRLIKLI(SAT),HULL(SAT)
SAT|EMTIA(AL),STOKASTIK(NOTR),MUTHIS OSILATOR(NOTR),MOMENTUM(SAT),MACD(SAT),STOKASTIK RSI HIZLI(NOTR),WILLIAMS(NOTR),BOGA AYI(NOTR),NIHAI OSILATOR(AL)|HACIM AGIRLIKLI(SAT),HULL(NOTR)
AL|EMTIA(AL),STOKASTIK(NOTR),MUTHIS OSILATOR(NOTR),MOMENTUM(SAT),MACD(SAT),STOKASTIK RSI HIZLI(NOTR),WILLIAMS(NOTR),BOGA AYI(NOTR),NIHAI OSILATOR(AL)|HACIM AGIRLIKLI(SAT),HULL(AL)
AL|EMTIA(AL),STOKASTIK(NOTR),MUTHIS OSILATOR(NOTR),MOMENTUM(SAT),MACD(SAT),STOKASTIK RSI HIZLI(NOTR),WILLIAMS(NOTR),BOGA AYI(NOTR),NIHAI OSILATOR(AL)|HACIM AGIRLIKLI(SAT),HULL(NOTR)
AL|EMTIA(AL),STOKASTIK(SAT),MUTHIS OSILATOR(NOTR),MOMENTUM(SAT),MACD(SAT),STOKASTIK RSI HIZLI(SAT),WILLIAMS(NOTR),BOGA AYI(NOTR),NIHAI OSILATOR(NOTR)|HACIM AGIRLIKLI(SAT),HULL(NOTR)
AL|EMTIA(AL),STOKASTIK(NOTR),MUTHIS OSILATOR(NOTR),MOMENTUM(SAT),MACD(SAT),STOKASTIK RSI HIZLI(NOTR),WILLIAMS(NOTR),BOGA AYI(NOTR),NIHAI OSILATOR(AL)|HACIM AGIRLIKLI(SAT),HULL(NOTR)
AL|EMTIA(NOTR),STOKASTIK(AL),MUTHIS OSILATOR(NOTR),MOMENTUM(AL),MACD(SAT),STOKASTIK RSI HIZLI(NOTR),WILLIAMS(NOTR),BOGA AYI(AL),NIHAI OSILATOR(NOTR)|HACIM AGIRLIKLI(NOTR),HULL(NOTR)
AL|EMTIA(NOTR),STOKASTIK(NOTR),MUTHIS OSILATOR(NOTR),MOMENTUM(AL),MACD(AL),STOKASTIK RSI HIZLI(AL),WILLIAMS(NOTR),BOGA AYI(NOTR),NIHAI OSILATOR(NOTR)|HACIM AGIRLIKLI(NOTR),HULL(AL)
AL|EMTIA(NOTR),STOKASTIK(NOTR),MUTHIS OSILATOR(NOTR),MOMENTUM(AL),MACD(AL),STOKASTIK RSI HIZLI(NOTR),WILLIAMS(NOTR),BOGA AYI(NOTR),NIHAI OSILATOR(NOTR)|HACIM AGIRLIKLI(AL),HULL(AL)
""".strip()


_STATE_CODES = {"AL": 1, "SAT": -1, "NOTR": 0}


def _split(text: str) -> list[str]:
    """Virgülle ayırır, boş parçaları atar, normalize eder."""
    out: list[str] = []
    for part in str(text).replace(";", ",").split(","):
        n = norm(part)
        if n:
            out.append(n)
    return out


def _tokens(text: str) -> list[tuple[str, Optional[int]]]:
    """`AD(DURUM)` parçalarını (normalize ad, durum kodu) olarak ayırır.

    Durum yazılmamışsa kod None döner; çağıran satır yönüyle doldurur.
    Parantezler `norm()` çağrılmadan ÖNCE ayrılır, çünkü norm parantezi
    siler ve durum bilgisi kaybolur.
    """
    out: list[tuple[str, Optional[int]]] = []
    for part in str(text).replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^(.*?)\s*\(\s*([^()]*)\s*\)\s*$", part)
        if m:
            name = norm(m.group(1))
            state = norm(m.group(2))
            if state not in _STATE_CODES:
                raise ValueError(
                    f"TİK2 kuralı: geçersiz gösterge durumu {state!r} "
                    f"({part!r})")
            if name:
                out.append((name, _STATE_CODES[state]))
        else:
            name = norm(part)
            if name:
                out.append((name, None))
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
        osc_map: dict[str, int] = {}
        for name, state in _tokens(parts[1]):
            lab = _resolve_osc(name, line)
            if state is None:
                state = direction
            if lab not in osc_map:
                osc_labels.append(lab)
            osc_map[lab] = state          # aynı gösterge tekrar yazılırsa SON kazanır
        if not osc_labels:
            raise ValueError(f"TİK2 kuralı: osilatör yok: {line!r}")
        osc_states = [(lab, osc_map[lab]) for lab in osc_labels]

        ma_labels_out: list[str] = []
        ma_map: dict[str, int] = {}
        for name, state in _tokens(parts[2]):
            group = _resolve_ma(name, line)
            if state is None:
                state = direction
            for lab in MA_GROUPS[group]:
                if lab not in ma_map:
                    ma_labels_out.append(lab)
                ma_map[lab] = state       # aynı MA tekrar yazılırsa SON kazanır
        if not ma_labels_out:
            raise ValueError(
                f"TİK2 kuralı: hareketli ortalama yok: {line!r}")
        ma_states = [(lab, ma_map[lab]) for lab in ma_labels_out]

        rules.append(Rule(direction=direction,
                          oscillators=tuple(osc_labels),
                          mas=tuple(ma_labels_out),
                          source=line,
                          osc_states=tuple(osc_states),
                          ma_states=tuple(ma_states)))
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
    """Her kural satırının bar başına tutma maskesini döndürür.

    Dönen `masks`: (kural, bar) bool. `d`: kural yönü (+1 AL / -1 SAT).
    Bir gösterge kuralda yazılıysa İSTENEN DURUM (AL/SAT/NÖTR) aynen
    aranır; yazılmayan göstergeler serbesttir.
    """
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
        for lab, want in rule.osc_pairs():
            arr = _array(osc_codes, lab, n)
            if arr is None:
                ok = False
                break
            m &= (arr == want)
        if ok:
            for lab, want in rule.ma_pairs():
                arr = _array(ma_codes, lab, n)
                if arr is None:
                    ok = False
                    break
                m &= (arr == want)
        if ok:
            masks[i] = m
    return masks, d


def _rule_priority() -> np.ndarray:
    """Kural önceliği: önce daha özel (çok gösterge), eşitlikte son satır."""
    spec = np.asarray([r.specificity for r in RULES], dtype=np.int32)
    idx = np.arange(len(RULES), dtype=np.int32)
    order = np.lexsort((idx, spec))          # artan özgüllük, sonra index
    priority = np.empty(len(RULES), dtype=np.int32)
    priority[order] = np.arange(len(RULES))  # büyük değer = kazanan
    return priority


def series(osc_codes: dict, ma_codes: dict) -> list[str]:
    """Bar başına TİK2 kararı: "AL" / "SAT" / "NÖTR".

    Tutan satırlar arasından en özel satır seçilir; eşit özgüllükte
    sonraki (daha alttaki) satır kazanır. Hiçbiri tutmazsa NÖTR.
    """
    masks, d = rule_masks(osc_codes, ma_codes)
    if masks.shape[1] == 0:
        return []
    priority = _rule_priority()
    scores = np.where(masks, priority[:, None], -1)
    winner = scores.argmax(axis=0)
    hit = scores.max(axis=0) >= 0
    out: list[str] = []
    for w, h in zip(winner, hit):
        out.append(_label_of(int(d[w])) if h else "NÖTR")
    return out


def decision_at(osc_codes: dict, ma_codes: dict, idx: int) -> str:
    """Tek bar için karar (seriyi baştan üretmeden)."""
    s = series(osc_codes, ma_codes)
    if 0 <= idx < len(s):
        return s[idx]
    return "NÖTR"


# --------------------------------------------------------------------------
# STABİLİZASYON (2026-11-07, kullanıcı geri bildirimi)
# --------------------------------------------------------------------------
# Sorun: kural serisi ortalama ~2 barda bir yön değiştiriyor. Kullanıcı
# canlıda "iki mum AL, üçüncü mum SAT -> pozisyon hemen bozuluyor,
# bekliyor, sonra aynı yönde devam ediyor; kayıplar bu geçişlerde"
# gözlemini bildirdi. HULL'ın yön için belirleyici olduğunu vurguladı.
#
# Çözüm iki katmanlı ve NEDENSELDİR (yalnızca o bar ve önceki barlar):
#   1) HULL GİRİŞ KAPISI: yeni bir AL yalnızca HULL +1 iken (veya HULL
#      nötrken), yeni bir SAT yalnızca HULL -1 iken açılabilir. Açık
#      pozisyonun çıkışı HULL yüzünden GECİKTİRİLMEZ; stop/banka her
#      zaman anındadır. Böylece HULL yönü belirler, kural listesi
#      zamanlama verir; kural listesi dışına yeni sinyal üretilmez.
#   2) MİNİMUM TUTMA (paper.py): sinyal ters döndü diye pozisyon ilk
#      barda kapatılmaz; K bar beklenir. Stop/banka çıkışları bu
#      kapıdan etkilenmez. (2026-11-07 kullanıcı kararı: bu bekleme
#      varsayılan olarak KAPATILDI — PAPER_TK2_MIN_HOLD=0. Mekanizma
#      test/araştırma için kodda duruyor.)
#
# Ölçüm (1m, 4 sembol x 8 x 500 bar, gerçek veri; 2026-11-07):
#   ham +338$, PF 1.13, 15/32 pozitif dilim
#   HULL giriş kapısı + 3 bar tutma: +726$, PF 1.29, 18/32 pozitif,
#   komisyon 1599$ -> 1548$, DD -92,6$ -> -85,8$. Dört sembolün
#   dördünde de hamdan iyi (ENA +318->+592, BTC -95->-55,
#   ETH +74->+114, SOL +42->+75). Ayrıntı: ALGORITMA_ARASTIRMASI.md
#   OTURUM 17 ve tools/research_tk2_cross.py.
#   Beklemesiz sürüm (2 dk + min tutma kaldırıldı, production ayarı):
#   +650$, 18/32 pozitif, DD -85,3$ (OTURUM 19).
HULL_LABEL = MA_GROUPS["HULL"][0]
VWMA_LABEL = MA_GROUPS["VWMA"][0]


def _dir_of(label: str) -> int:
    if label == "AL":
        return 1
    if label == "SAT":
        return -1
    return 0


def _label_of(direction: int) -> str:
    if direction > 0:
        return "AL"
    if direction < 0:
        return "SAT"
    return "NÖTR"


def _smooth_dirs(values, window: int) -> list[int]:
    """Pencere içi çoğunluk: |toplam| >= ceil(window/2) ise yön."""
    arr = [int(x) for x in values]
    n = len(arr)
    if window <= 1:
        return arr
    need = window // 2 + 1
    out: list[int] = []
    acc = 0
    for i, v in enumerate(arr):
        acc += v
        if i >= window:
            acc -= arr[i - window]
        if acc >= need:
            out.append(1)
        elif acc <= -need:
            out.append(-1)
        else:
            out.append(0)
    return out


def hull_direction(ma_codes: dict, n: int) -> Optional[list[int]]:
    """HULL(9) yön serisi: +1 fiyat üstünde, -1 altında, 0 eksik."""
    arr = _array(ma_codes or {}, HULL_LABEL, n)
    if arr is None:
        return None
    return [int(x) for x in arr]


def ma_direction(ma_codes: dict, label: str, n: int) -> Optional[list[int]]:
    """Tek bir hareketli ortalamanın yön serisi (+1/0/-1)."""
    arr = _array(ma_codes or {}, label, n)
    if arr is None:
        return None
    return [int(x) for x in arr]


def oscillator_majority(osc_codes: dict, n: int) -> Optional[list[int]]:
    """Osilatör çoğunluğu: AL sayısı SAT'tan fazlaysa +1, azsa -1.

    NÖTR kodlar sayılmaz (kullanıcı kuralı 2026-11-08). Eşitlik -> 0.
    Eksik/bozuk seriler sessizce atlanır; hiç geçerli seri yoksa None.
    """
    if not osc_codes or n <= 0:
        return None
    al = np.zeros(n, dtype=np.int16)
    sat = np.zeros(n, dtype=np.int16)
    used = 0
    for arr in osc_codes.values():
        a = np.asarray(arr)
        if a.size != n:
            continue
        used += 1
        al += (a > 0)
        sat += (a < 0)
    if used == 0:
        return None
    out = np.zeros(n, dtype=np.int8)
    out[al > sat] = 1
    out[sat > al] = -1
    return [int(x) for x in out]


def stabilize(raw: list[str], hull=None, *, vote: int = 1,
              vote_min: int = 0, confirm_entry: int = 1,
              confirm_exit: int = 1, confirm_flip: int = 1,
              min_dwell: int = 0, hull_entry_veto: bool = False,
              hull_neutral_block: bool = False,
              osc_major=None, vwma=None,
              vwma_hull_long: bool = False,
              vwma_hull_long_neutral: bool = False,
              vwma_hull_hold: bool = False,
              vwma_hull_always: bool = False,
              vwma_hull_short: bool = False,
              hull_veto: bool = False, hull_smooth: int = 1,
              hull_entry_fast: bool = False, hull_governor: bool = False,
              hull_fast_exit: bool = True) -> list[str]:
    """Ham kural serisini nedensel olarak yumuşatır.

    Parametreler (hepsi opsiyonel; varsayılan yalnızca HULL giriş
    kapısını uygular, çıkışları geciktirmez):

    vote          : son N barın yön toplamı (1 = kapalı)
    vote_min      : toplamın bu büyüklüğe ulaşması gerekir (0=otomatik)
    confirm_entry : 0'dan yöne geçiş için arka arkaya K bar
    confirm_exit  : yönden 0'a (nötr) çıkış için K bar
    confirm_flip  : yönden ters yöne geçiş için K bar
    min_dwell     : bir yönde en az K bar kal (erken çıkış/flip engeli)
    hull_entry_veto: yalnızca YENİ girişte HULL'a ters sinyali engelle
    hull_neutral_block: HULL NÖTR (0) iken YENİ giriş yapma; açık
                    pozisyonun çıkışı etkilenmez (kullanıcı kuralı)
    osc_major     : osilatör çoğunluğu (+1 AL fazla, -1 SAT fazla, 0 eşit)
    vwma          : hacim ağırlıklı MA yönü (+1 AL, -1 SAT, 0 NÖTR)
    vwma_hull_long: osilatör çoğunluğu AL, HULL SAT ve VWMA AL ise
                    SHORT yerine LONG aç (kullanıcı kuralı 2026-11-08)
    vwma_hull_long_neutral: aynı LONG geçişini kural serisi NÖTR iken de
                    uygula (varsayılan kapalı)
    vwma_hull_hold: koşul açık LONG pozisyon varken de geçerli olsun;
                    LONG'u SAT sinyaliyle kapatma (kullanıcı kuralı)
    vwma_hull_always: koşul açık pozisyon varken de geçerli olsun
                    (LONG'u korur / SHORT'u LONG'a çevirir)
    vwma_hull_short: simetrik durum: osilatör çoğunluğu SAT, HULL AL ve
                    VWMA SAT ise LONG yerine SHORT aç
    hull_veto     : açık pozisyon dahil HULL'a ters sinyali nötr yap
    hull_smooth   : HULL yönünü son K barlık çoğunlukla yumuşat
    hull_entry_fast: HULL yeni yönü doğruluyorsa giriş onayını bekleme
    hull_governor : HULL pozisyon yönündeyken çıkışa K bar sabır;
                    HULL ters döndüyse hızlı çıkış (hull_fast_exit)
    """
    n = len(raw)
    if n == 0:
        return []
    dirs = np.asarray([_dir_of(x) for x in raw], dtype=np.int8)

    if vote and vote > 1:
        need = vote_min or (vote // 2 + 1)
        cand = np.zeros(n, dtype=np.int8)
        for i in range(n):
            a = max(0, i - vote + 1)
            s = int(dirs[a:i + 1].sum())
            if s >= need:
                cand[i] = 1
            elif s <= -need:
                cand[i] = -1
    else:
        cand = dirs.copy()

    hs: Optional[list[int]] = None
    if hull is not None:
        hv = list(hull)
        if len(hv) == n:
            hs = _smooth_dirs(hv, max(1, int(hull_smooth)))
    vs: Optional[list[int]] = None
    if vwma is not None:
        vv = list(vwma)
        if len(vv) == n:
            vs = [int(x) for x in vv]
    os_major: Optional[list[int]] = None
    if osc_major is not None:
        ov = list(osc_major)
        if len(ov) == n:
            os_major = [int(x) for x in ov]
    if hs is not None and hull_veto:
        for i in range(n):
            if cand[i] != 0 and hs[i] != 0 and cand[i] != hs[i]:
                cand[i] = 0

    out = np.zeros(n, dtype=np.int8)
    state = 0
    pending = 0
    pc = 0
    last_change = -10 ** 9
    for i in range(n):
        c = int(cand[i])
        # HULL + VWMA BİRLİKTE (kullanıcı kuralı 2026-11-08):
        # Osilatörlerin çoğunluğu AL, HULL SAT ve VWMA AL ise SHORT
        # açma; LONG aç. VWMA AL iken HULL NÖTR ise pozisyon tehlikeli
        # sayılır ve bu geçiş uygulanmaz (HULL nötr giriş yasağı da
        # ayrıca devrededir). Girişte (state==0) ve -- hold açıksa --
        # açık LONG'u korurken uygulanır.
        vw_override = False
        _vw_apply = (state == 0 or vwma_hull_always
                     or (vwma_hull_hold and state > 0))
        if _vw_apply and hs is not None \
                and vs is not None and os_major is not None:
            if vwma_hull_long and c == -1 and hs[i] < 0 \
                    and vs[i] > 0 and os_major[i] > 0:
                c = 1
                vw_override = True
            elif vwma_hull_long and vwma_hull_long_neutral and c == 0 \
                    and hs[i] < 0 and vs[i] > 0 and os_major[i] > 0:
                c = 1
                vw_override = True
            elif vwma_hull_short and c == 1 and hs[i] > 0 \
                    and vs[i] < 0 and os_major[i] < 0:
                c = -1
                vw_override = True
        # GİRİŞ KAPISI: pozisyon yokken HULL'a ters yön açılmaz.
        # VWMA/HULL birleşik kuralı LONG'u açıkça istediyse bu kapı
        # atlanır (kullanıcı kuralı HULL'dan önce gelir).
        if state == 0 and hs is not None and hull_entry_veto \
                and not vw_override:
            if c != 0 and hs[i] != 0 and c != hs[i]:
                c = 0
        # HULL NÖTR İKEN YENİ GİRİŞ YOK (kullanıcı kuralı 2026-11-08).
        # Yalnızca state==0 (pozisyon yok) iken uygulanır; açık
        # pozisyonun çıkışı bu kapıdan ETKİLENMEZ.
        if state == 0 and hs is not None and hull_neutral_block \
                and c != 0 and hs[i] == 0:
            c = 0
        if c == state:
            pending = 0
            pc = 0
            out[i] = state
            continue
        if state != 0 and min_dwell > 0 and (i - last_change) < min_dwell:
            out[i] = state
            continue
        need = confirm_entry if state == 0 else (
            confirm_exit if c == 0 else confirm_flip)
        if state == 0 and hull_entry_fast and hs is not None and c != 0 \
                and hs[i] == c:
            need = 1
        if state != 0 and hull_governor and hs is not None:
            if hs[i] == state:
                need = max(need, confirm_exit if c == 0 else confirm_flip)
            elif hull_fast_exit:
                need = 1
        need = max(1, int(need))
        if c == pending:
            pc += 1
        else:
            pending = c
            pc = 1
        if pc >= need:
            state = c
            last_change = i
            pending = 0
            pc = 0
        out[i] = state
    return [_label_of(int(x)) for x in out]


def series_stable(osc_codes: dict, ma_codes: dict, **overrides) -> list[str]:
    """Kural serisi + varsayılan stabilizasyon (config'ten okunur).

    `paper._build_signal_series` ve `service.mode_signal_series` AYNI
    fonksiyonu çağırır; böylece canlı, geriye dönük test ve grafik
    yıldızları birebir aynı kararı gösterir.

    `overrides` yalnızca test/araştırma içindir (config'i ezmez).
    """
    raw = series(osc_codes, ma_codes)
    if not raw:
        return raw
    if not bool(getattr(config, "PAPER_TK2_STAB_ON", True)):
        return raw
    hull = hull_direction(ma_codes, len(raw))
    osc_major = oscillator_majority(osc_codes, len(raw))
    vwma = ma_direction(ma_codes, VWMA_LABEL, len(raw))
    kw = {
        "vote": int(getattr(config, "PAPER_TK2_STAB_VOTE", 1) or 1),
        "confirm_entry": int(getattr(
            config, "PAPER_TK2_STAB_CONFIRM_ENTRY", 1) or 1),
        "confirm_exit": int(getattr(
            config, "PAPER_TK2_STAB_CONFIRM_EXIT", 1) or 1),
        "confirm_flip": int(getattr(
            config, "PAPER_TK2_STAB_CONFIRM_FLIP", 1) or 1),
        "min_dwell": int(getattr(
            config, "PAPER_TK2_STAB_MIN_DWELL", 0) or 0),
        "hull_entry_veto": bool(getattr(
            config, "PAPER_TK2_STAB_HULL_ENTRY", True)),
        "hull_neutral_block": bool(getattr(
            config, "PAPER_TK2_STAB_HULL_NEUTRAL_BLOCK", True)),
        "osc_major": osc_major,
        "vwma": vwma,
        "vwma_hull_long": bool(getattr(
            config, "PAPER_TK2_STAB_VWMA_HULL_LONG", True)),
        "vwma_hull_long_neutral": bool(getattr(
            config, "PAPER_TK2_STAB_VWMA_HULL_LONG_NEUTRAL", False)),
        "vwma_hull_hold": bool(getattr(
            config, "PAPER_TK2_STAB_VWMA_HULL_HOLD", False)),
        "vwma_hull_always": bool(getattr(
            config, "PAPER_TK2_STAB_VWMA_HULL_ALWAYS", False)),
        "vwma_hull_short": bool(getattr(
            config, "PAPER_TK2_STAB_VWMA_HULL_SHORT", False)),
        "hull_veto": bool(getattr(
            config, "PAPER_TK2_STAB_HULL_FULL", False)),
        "hull_smooth": int(getattr(
            config, "PAPER_TK2_STAB_HULL_SMOOTH", 1) or 1),
        "hull_entry_fast": bool(getattr(
            config, "PAPER_TK2_STAB_HULL_FAST", False)),
        "hull_governor": bool(getattr(
            config, "PAPER_TK2_STAB_HULL_GOVERNOR", False)),
    }
    kw.update(overrides)
    return stabilize(raw, hull, **kw)


def summary() -> dict:
    """Kural tablosunun özeti (test/teşhis)."""
    osc_pairs = [p for r in RULES for p in r.osc_pairs()]
    ma_pairs = [p for r in RULES for p in r.ma_pairs()]
    return {
        "rows": len(RULES),
        "al": sum(1 for r in RULES if r.direction > 0),
        "sat": sum(1 for r in RULES if r.direction < 0),
        "unique": len({(r.direction, tuple(r.osc_pairs()), tuple(r.ma_pairs()))
                       for r in RULES}),
        "oscillators": sorted({lab for lab, _ in osc_pairs}),
        "mas": sorted({lab for lab, _ in ma_pairs}),
        "state_rules": sum(1 for r in RULES
                           if r.osc_states or r.ma_states),
        "specificity": {
            "min": min(r.specificity for r in RULES),
            "max": max(r.specificity for r in RULES),
        },
    }
