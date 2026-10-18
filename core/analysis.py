"""
TradingView "Technicals" yorum motoru.

Onemli nokta: TradingView'in islem detayi her osilator icin SABIT SEVIYE
kurali kullanmaz. Ornek tablo bunu gosteriyor:

    Stokastik %K (14,3,3)  99,09  -> Nötr   (seviye kurali olsaydi "Sat" olurdu)
    Müthiş Osilatör         71,74  -> Nötr   (pozitif ama sifirin ustunden gecmedi)
    MACD Seviyesi (12,26)  50,64  -> Sat    (macd > 0 ama sinyal cizgisinin altinda)
    Williams %R (14)        0,00  -> Nötr   (−20 altina inmedi)
    RSI (14)              68,92  -> Nötr   (70'e ugramadi)  <- seviye kurali
    CCI (20)              211,69  -> Sat    (>= 100)         <- seviye kurali

Yani bir kismi SEVIYE (RSI, CCI, Momentum, UO), bir kismi KESISIM
(Stochastic, AO, MACD-sinyal, Stoch RSI, Williams %R, ADX) kuralidir.
Burada her osilator icin tek bir kural satiri vardir; degistirmek icin
sadece o fonksiyonu duzenlemek yeterlidir.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import numpy as np

from core import indicators as ind
from core.indicators import to_float as _f

# --------------------------------------------------------------------------
# Sinyal durumlari
# --------------------------------------------------------------------------
class Signal(Enum):
    STRONG_BUY = "GÜÇLÜ AL"
    BUY = "AL"
    NEUTRAL = "NÖTR"
    SELL = "SAT"
    STRONG_SELL = "GÜÇLÜ SAT"

    @property
    def is_actionable(self) -> bool:
        """Grafikte yildiz olarak isaretlenecek durumlar (NÖTR haric)."""
        return self is not Signal.NEUTRAL

    @property
    def strength(self) -> int:
        return {
            Signal.STRONG_BUY: 2,
            Signal.BUY: 1,
            Signal.NEUTRAL: 0,
            Signal.SELL: -1,
            Signal.STRONG_SELL: -2,
        }[self]


class Verdict(Enum):
    BUY = 1
    NEUTRAL = 0
    SELL = -1

    @property
    def label(self) -> str:
        return {1: "Al", 0: "Nötr", -1: "Sat"}[self.value]


def _v(code: int) -> Verdict:
    return {1: Verdict.BUY, 0: Verdict.NEUTRAL, -1: Verdict.SELL}[int(code)]


# --------------------------------------------------------------------------
# Osilator yorum kurallari (dizi -> dizi)
# --------------------------------------------------------------------------
def _rsi_v(x: np.ndarray) -> np.ndarray:
    """Seviye kurali: 70 ustu Sat, 30 alti Al."""
    out = np.zeros(x.size, dtype=int)
    out[x >= 70] = -1
    out[x <= 30] = 1
    out[~np.isfinite(x)] = 0
    return out


def _cross_up(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """a'nin b'nin USTUNE cikisi (once <=, sonra >)."""
    return (np.roll(a, 1) <= np.roll(b, 1)) & (a > b)


def _cross_down(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """a'nin b'nin ALTINA inisi (once >=, sonra <)."""
    return (np.roll(a, 1) >= np.roll(b, 1)) & (a < b)


def _crossover_v(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    out = np.zeros(a.size, dtype=int)
    out[_cross_up(a, b)] = 1
    out[_cross_down(a, b)] = -1
    out[~np.isfinite(a)] = 0
    out[0] = 0          # ilk barin karsilastirmasi anlamsiz
    return out


def _stoch_v(k: np.ndarray, d: np.ndarray) -> np.ndarray:
    """Stokastik %K icin %K'nin %D cizgisini kesmesi esastir."""
    return _crossover_v(k, d)


def _cci_v(x: np.ndarray) -> np.ndarray:
    out = np.zeros(x.size, dtype=int)
    out[x >= 100] = -1
    out[x <= -100] = 1
    out[~np.isfinite(x)] = 0
    return out


def _adx_v(adx_line: np.ndarray) -> np.ndarray:
    """ADX 25 esiginin asilip dusmesi (trend gucu)."""
    return _crossover_v(adx_line, np.full(adx_line.size, 25.0))


def _sign_v(x: np.ndarray) -> np.ndarray:
    out = np.zeros(x.size, dtype=int)
    out[x > 0] = 1
    out[x < 0] = -1
    out[~np.isfinite(x)] = 0
    return out


def _ao_v(x: np.ndarray) -> np.ndarray:
    """Müthiş Osilatör: sifirin ustunden/altindan gecisi."""
    return _crossover_v(x, np.zeros(x.size))


def _macd_v(line: np.ndarray, signal: np.ndarray) -> np.ndarray:
    """MACD Seviyesi: macd cizgisinin sinyal cizgisine gore konumu."""
    out = np.zeros(line.size, dtype=int)
    ok = np.isfinite(line) & np.isfinite(signal)
    out[ok & (line > signal)] = 1
    out[ok & (line < signal)] = -1
    return out


def _williams_v(x: np.ndarray) -> np.ndarray:
    """Williams %R: -80'in ustune cikis Al, -20'nin altina inis Sat."""
    out = np.zeros(x.size, dtype=int)
    prev = np.roll(x, 1)
    out[(prev <= -80) & (x > -80)] = 1
    out[(prev >= -20) & (x < -20)] = -1
    out[~np.isfinite(x)] = 0
    out[0] = 0
    return out


def _bull_bear_v(bull: np.ndarray, bear: np.ndarray) -> np.ndarray:
    """Boga Ayi Gucu: bogalar sifirin ustune cikarsa Al, ayilar altina inerse Sat."""
    out = np.zeros(bull.size, dtype=int)
    prev_b, prev_r = np.roll(bull, 1), np.roll(bear, 1)
    out[(prev_b <= 0) & (bull > 0)] = 1
    out[(prev_r >= 0) & (bear < 0)] = -1
    out[~np.isfinite(bull)] = 0
    out[0] = 0
    return out


def _uo_v(x: np.ndarray) -> np.ndarray:
    out = np.zeros(x.size, dtype=int)
    out[x >= 70] = -1
    out[x <= 30] = 1
    out[~np.isfinite(x)] = 0
    return out


def _ma_v(price: np.ndarray, ma: np.ndarray, deadzone: float) -> np.ndarray:
    """Hareketli ortalama: fiyat MA'nin ustunde Al, altinda Sat.

    deadzone (oran) kadar yakin fiyatlar Nötr sayilir; böylece fiyat tam
    cizginin üzerindeyken her bar Al/Sat arasinda zıplamaz.
    """
    out = np.zeros(price.size, dtype=int)
    with np.errstate(invalid="ignore"):
        up = price > ma * (1.0 + deadzone)
        dn = price < ma * (1.0 - deadzone)
    out[up & np.isfinite(ma)] = 1
    out[dn & np.isfinite(ma)] = -1
    return out


# --------------------------------------------------------------------------
# Gosterge tanimlari
# --------------------------------------------------------------------------
# Ichimoku Ana Hatti icin daha genis bir olu bolgesi kullanilir: TradingView
# bu satiri bulut (senkou) mantigiyla yorumlar, dogrudan fiyat karsilastirmasi
# ile ayni sonucu vermez. Ornek tabloda da fiyat cizginin ustundeyken "Nötr"
# gorunuyor.
ICHIMOKU_DEADZONE = 0.0025
MA_DEADZONE = 0.0002

MA_PERIODS = [10, 20, 30, 50, 100, 200]

# Grafikte iki isaret arasinda en az bu kadar bar bosluk birakilir.
MARKER_MIN_GAP = 3

OSCILLATOR_LABELS = [
    "Göreceli Güç Endeksi(RSI) (14)",
    "Stokastik %K (14, 3, 3)",
    "Emtia Kanal Endeksi(CCI) (20)",
    "Ortalama Yönsel Endeks(ADX) (14)",
    "Müthiş Osilatör",
    "Momentum (10)",
    "MACD Seviyesi (12,26)",
    "Stokastik RSI Hızlı (3, 3, 14, 14)",
    "Williams Yüzde Aralığı (14)",
    "Boğa Ayı Gücü",
    "Nihai Osilatör(UO) (7, 14, 28)",
]


def ma_labels() -> list[str]:
    out = []
    for p in MA_PERIODS:
        out.append(f"Üstel Hareketli Ortalama ({p})")
        out.append(f"Basit Hareketli Ortalama({p})")
    out += [
        "İchimoku Ana Hattı (9, 26, 52, 26)",
        "Hacim Ağırlıklı Hareketli Ortalama (20)",
        "Hull Hareketli Ortalama (9)",
    ]
    return out


def format_number(value: Optional[float], digits: int = 2) -> str:
    """Turkce sayi bicimi: binlik ayraci '.', ondalik ayraci ','.

    TradingView teknik sayfasinda da ayni bicim kullanilir
    (orn. 81.555,21).

    ONDALIK ADEDI: FIYATIN BUYUKLUGUNE GORE OTOMATIK. Sabit 2 ondalik
    kullanmak 0,0038 fiyatlı coinleri "0,00" yapıyordu (orn. 1000PEPE).
    Bkz. digits=None ile cagrilirsa otomatik secilir.
    """
    if value is None or not np.isfinite(value):
        return "—"
    if digits is None:
        # Ondalik sayisi = fiyatin basamak DERECESI.
        # Araliklar yuksekten dusuk siniflanir ve ust sinir KAPSAMAYDIR:
        #   0,4238 -> 4 ondalik (2 ondaliga yuvarlanirsa 0,42 olur ve
        #              %0,38'lik gercek deger kaybolur)
        a = abs(float(value))
        digits = 2
        if a and a < 0.000001:
            digits = 10
        elif a and a < 0.01:
            digits = 8
        elif a and a < 0.1:
            digits = 6
        elif a and a < 1.0:
            digits = 4
    return f"{value:,.{digits}f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")


# --------------------------------------------------------------------------
# Analiz sonucu
# --------------------------------------------------------------------------
@dataclass
class IndicatorValue:
    label: str
    value: Optional[float]
    verdict: Verdict

    @property
    def value_text(self) -> str:
        return format_number(self.value, digits=None)


@dataclass
class TimeframeAnalysis:
    """Bir zaman dilimi icin tum hesaplar + gosterge gecmisi."""

    symbol: str
    timeframe: str
    open_times: np.ndarray        # bar acilis zamanlari (ms)
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray
    close_times: np.ndarray

    ma_series: dict[str, np.ndarray]      # etiket -> dizi
    composite: np.ndarray                 # -1..1
    signals: list[Signal]                 # bar basina sinyal
    oscillator_scores: np.ndarray
    ma_scores: np.ndarray

    rows: list[IndicatorValue] = None     # son bar icin osilatör + MA satirlari
    osc_split: int = 0                    # rows icinde osilator sayisi

    # -- son bar -----------------------------------------------------------
    @property
    def price(self) -> float:
        return float(self.c[-1]) if self.c.size else float("nan")

    @property
    def signal(self) -> Signal:
        return self.signals[-1] if self.signals else Signal.NEUTRAL

    @property
    def composite_value(self) -> float:
        return float(self.composite[-1]) if self.composite.size else 0.0

    @property
    def open_time(self) -> int:
        return int(self.open_times[-1]) if self.open_times.size else 0

    @property
    def close_time(self) -> int:
        return int(self.close_times[-1]) if self.close_times.size else 0

    @property
    def oscillator_rows(self) -> list[IndicatorValue]:
        return self.rows[: self.osc_split]

    @property
    def ma_rows(self) -> list[IndicatorValue]:
        return self.rows[self.osc_split:]

    def marker_indices(self, min_gap: int = MARKER_MIN_GAP) -> list[int]:
        """
        Grafikte yildiz olarak isaretlenecek barlar.

        Iki kural:
          1. Sinyalin surdugu her bar degil, ilk ortaya CIKTIĞI bar isaretlenir.
             Aksi halde 500 barda 190 yildiz cikardi ve grafik okunmaz olurdu.
          2. Ardisik yildizlar arasinda en az `min_gap` bar birakilir; iki
             isaret arasindan guclu olan korunur.
        """
        candidates: list[int] = []
        for i, sig in enumerate(self.signals):
            if sig.is_actionable and (i == 0 or self.signals[i - 1] is not sig):
                candidates.append(i)

        kept: list[int] = []
        for i in candidates:
            if kept and (i - kept[-1]) < min_gap:
                if abs(self.signals[i].strength) <= abs(self.signals[kept[-1]].strength):
                    continue
                kept[-1] = i
                continue
            kept.append(i)
        return kept


# --------------------------------------------------------------------------
# Ana hesap
# --------------------------------------------------------------------------
def analyze(symbol: str, timeframe: str,
            open_times, o, h, l, c, v, close_times,
            strong_threshold: float = 0.65,
            base_threshold: float = 0.40) -> TimeframeAnalysis:
    """OHLCV dizilerinden tum gostergeleri ve bilesik skoru hesaplar."""
    o = _f(o)
    h = _f(h)
    l = _f(l)
    c = _f(c)
    v = _f(v)
    n = c.size

    if n < 60:
        raise ValueError(f"Yetersiz veri: {n} bar (en az 60 gerekli).")

    open_times = np.asarray(open_times, dtype=np.int64)
    close_times = np.asarray(close_times, dtype=np.int64)

    # ---- Osilatorler ------------------------------------------------------
    r = ind.rsi(c, 14)
    stoch_k = ind.stochastic_k(h, l, c, 14, 3)
    stoch_d = ind.rolling_mean(stoch_k, 3)
    cci_v = ind.cci(h, l, c, 20)
    adx_line, pdi, mdi = ind.adx(h, l, c, 14)
    ao = ind.awesome_oscillator(h, l)
    mom = ind.momentum(c, 10)
    macd_line, macd_sig, _ = ind.macd(c, 12, 26, 9)
    srsi_k = ind.stoch_rsi_fast(c, 14, 14, 3, 3)
    srsi_d = ind.rolling_mean(srsi_k, 3)
    wr = ind.williams_r(h, l, c, 14)
    bull, bear = ind.bull_bear_power(h, l, c, 13)
    uo = ind.ultimate_oscillator(h, l, c, 7, 14, 28)

    bull_bear = bull - bear          # TradingView'in gosterdigi deger

    osc_values = [r, stoch_k, cci_v, adx_line, ao, mom, macd_line,
                  srsi_k, wr, bull_bear, uo]
    osc_codes = [
        _rsi_v(r),
        _stoch_v(stoch_k, stoch_d),
        _cci_v(cci_v),
        _adx_v(adx_line),
        _ao_v(ao),
        _sign_v(mom),
        _macd_v(macd_line, macd_sig),
        _stoch_v(srsi_k, srsi_d),
        _williams_v(wr),
        _bull_bear_v(bull, bear),
        _uo_v(uo),
    ]

    # ---- Hareketli ortalamalar -------------------------------------------
    ma_labels_list = ma_labels()
    ma_values: list[np.ndarray] = []
    ma_codes: list[np.ndarray] = []
    ma_series: dict[str, np.ndarray] = {}

    for p in MA_PERIODS:
        e = ind.ema(c, p)
        s = ind.sma(c, p)
        le, ls = f"ema{p}", f"sma{p}"
        ma_values += [e, s]
        ma_codes += [_ma_v(c, e, MA_DEADZONE), _ma_v(c, s, MA_DEADZONE)]
        ma_series[le] = e
        ma_series[ls] = s

    ich = ind.ichimoku_base_line(h, l)
    vw = ind.vwma(c, v, 20)
    hu = ind.hma(c, 9)
    ma_values += [ich, vw, hu]
    ma_codes += [
        _ma_v(c, ich, ICHIMOKU_DEADZONE),
        _ma_v(c, vw, MA_DEADZONE),
        _ma_v(c, hu, MA_DEADZONE),
    ]
    ma_series["ichimoku"] = ich
    ma_series["vwma"] = vw
    ma_series["hma"] = hu

    # ---- Bilesik skor -----------------------------------------------------
    def _score(codes: list[np.ndarray]) -> np.ndarray:
        stacked = np.vstack(codes).astype(float)
        return stacked.mean(axis=0)

    osc_scores = _score(osc_codes)
    ma_scores = _score(ma_codes)
    composite = 0.50 * osc_scores + 0.50 * ma_scores

    signals: list[Signal] = []
    for score in composite:
        if score >= strong_threshold:
            signals.append(Signal.STRONG_BUY)
        elif score >= base_threshold:
            signals.append(Signal.BUY)
        elif score <= -strong_threshold:
            signals.append(Signal.STRONG_SELL)
        elif score <= -base_threshold:
            signals.append(Signal.SELL)
        else:
            signals.append(Signal.NEUTRAL)

    # ---- Son bar icin gosterge satirlari ---------------------------------
    rows: list[IndicatorValue] = []
    for label, values, codes in zip(OSCILLATOR_LABELS, osc_values, osc_codes):
        rows.append(_row(label, values, codes))
    for label, values, codes in zip(ma_labels_list, ma_values, ma_codes):
        rows.append(_row(label, values, codes))

    return TimeframeAnalysis(
        symbol=symbol,
        timeframe=timeframe,
        open_times=open_times,
        o=o, h=h, l=l, c=c, v=v,
        close_times=close_times,
        ma_series=ma_series,
        composite=composite,
        signals=signals,
        oscillator_scores=osc_scores,
        ma_scores=ma_scores,
        rows=rows,
        osc_split=len(osc_codes),
    )


def _row(label: str, values: np.ndarray, codes: np.ndarray) -> IndicatorValue:
    raw = values[-1] if values.size else np.nan
    value = float(raw) if np.isfinite(raw) else None
    code = codes[-1] if codes.size else 0
    return IndicatorValue(label=label, value=value, verdict=_v(code))