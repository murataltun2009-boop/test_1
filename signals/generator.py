"""
Sinyal ureteci: indikatorlerden bilesik skor hesaplar.

Skor bilesenleri (agirlikli):
  - Osilatorler  : RSI, Stokastik, CCI, ADX, AO, Momentum, MACD, Williams %R ...
  - Hareketli Ortalamalar : EMA/SMA 10..200, Ichimoku, VWMA, Hull MA
  - Pivotlar     : Classic pivot (P), R1/R2/R3, S1/S2/S3   [agirlik %20]

Pivotlar 3 bilesenin biri olarak geri eklendi: olcumde osilator ve MA
birlikte asiri yuksek korelasyonlu (ikisi de ayni fiyat hareketinden
besleniyor), pivot ise bagimsiz bir referans noktasi saglayarak skoru
seyreltiyor. Pivot harisi varyant OOS testinde pozitif tek konfigürasyondu.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from config import INDICATOR_CONFIG, TRADING_CONFIG
from indicators.calculator import (
    IndicatorsCalculator,
    interpret_ma,
    interpret_oscillator,
    interpret_pivot,
)

logger = logging.getLogger(__name__)


class Signal(Enum):
    STRONG_BUY = "Guc/lu AL"          # Turkce: "Güçlü Al"
    BUY = "AL"
    NEUTRAL = "NOTR"
    SELL = "SAT"
    STRONG_SELL = "GÜÇLÜ SAT"


# (anahtar, gorunen ad)
OSCILLATORS: List[tuple[str, str]] = [
    ("rsi", "Göreceli Güç Endeksi(RSI) (14)"),
    ("stoch_k", "Stokastik %K (14, 3, 3)"),
    ("cci", "Emtia Kanal Endeksi(CCI) (20)"),
    ("adx", "Ortalama Yönsel Endeks(ADX) (14)"),
    ("ao", "Müthiş Osilatör"),
    ("momentum", "Momentum (10)"),
    ("macd", "MACD Seviyesi (12,26)"),
    ("stoch_rsi_k", "Stokastik RSI Hızlı (3, 3, 14, 14)"),
    ("williams_r", "Williams Yüzde Aralığı (14)"),
    ("bull_power", "Boğa Ayı Gücü"),
    ("uo", "Nihai Osilatör(UO) (7, 14, 28)"),
]

PIVOTS: List[tuple[str, str]] = [
    ("pivot", "P (Klasik)"),
    ("r1", "R1"),
    ("r2", "R2"),
    ("r3", "R3"),
    ("s1", "S1"),
    ("s2", "S2"),
    ("s3", "S3"),
]


@dataclass
class IndicatorRow:
    """Tek bir indikatorun ad/deger/yorum satiri."""
    name: str
    value: Optional[float]
    verdict: str          # "buy" | "sell" | "neutral"

    @property
    def verdict_tr(self) -> str:
        return {"buy": "Al", "sell": "Sat", "neutral": "Nötr"}[self.verdict]

    @property
    def value_str(self) -> str:
        if self.value is None or pd.isna(self.value):
            return "—"
        return f"{self.value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


@dataclass
class SignalResult:
    """Bir zaman noktasindaki butun analiz ciktisi."""
    timestamp: Any
    price: float
    composite: float                                   # -1..1
    signal: Signal
    oscillator_score: float
    ma_score: float
    pivot_score: float
    oscillators: List[IndicatorRow] = field(default_factory=list)
    moving_averages: List[IndicatorRow] = field(default_factory=list)
    pivots: List[IndicatorRow] = field(default_factory=list)
    osc_counts: Dict[str, int] = field(default_factory=dict)
    ma_counts: Dict[str, int] = field(default_factory=dict)
    pivot_counts: Dict[str, int] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def verdict_str(self) -> str:
        return {
            "buy": "Al", "sell": "Sat", "neutral": "Nötr"
        }

    def counts_tr(self, counts: Dict[str, int]) -> str:
        return (f"Al {counts.get('buy', 0)}  ·  "
                f"Sat {counts.get('sell', 0)}  ·  "
                f"Nötr {counts.get('neutral', 0)}")

    def summary_lines(self) -> List[str]:
        """TradingView 'Özet' satirina benzer ozet."""
        return [
            f"Osilatörler : {self.counts_tr(self.osc_counts)}  (skor {self.oscillator_score:+.2f})",
            f"Hareketli Ort. : {self.counts_tr(self.ma_counts)}  (skor {self.ma_score:+.2f})",
            f"Pivotlar    : {self.counts_tr(self.pivot_counts)}  (skor {self.pivot_score:+.2f})",
            f"BİLEŞİK SKOR: {self.composite:+.3f}   →   {self.signal.value}",
        ]


def _counts(rows: List[IndicatorRow]) -> Dict[str, int]:
    out = {"buy": 0, "sell": 0, "neutral": 0}
    for row in rows:
        out[row.verdict] += 1
    return out


def _score(rows: List[IndicatorRow]) -> float:
    """(al - sat) / toplam  ->  -1..1"""
    total = len(rows)
    if total == 0:
        return 0.0
    counts = _counts(rows)
    return (counts["buy"] - counts["sell"]) / total


class SignalGenerator:
    """Indikator DataFrame'inden SignalResult uretir."""

    def __init__(self, config: TRADING_CONFIG = None,
                 indicator_config: INDICATOR_CONFIG = None):
        self.config = config or TRADING_CONFIG
        self.ind_config = indicator_config or INDICATOR_CONFIG
        self.calc = IndicatorsCalculator(self.ind_config)

    # ------------------------------------------------------------------
    def build_ma_rows(self, values: Dict[str, Any]) -> List[IndicatorRow]:
        """EMA/SMA + Ichimoku + VWMA + Hull satirlari."""
        price = values["close"]
        rows: List[IndicatorRow] = []

        for period in self.calc.MA_PERIODS:
            for kind, label in (("ema", "Üstel Hareketli Ortalama"),
                                ("sma", "Basit Hareketli Ortalama")):
                key = f"{kind}_{period}"
                val = values.get(key)
                rows.append(IndicatorRow(
                    name=f"{label} ({period})",
                    value=val,
                    verdict=interpret_ma(price, val),
                ))

        for key, label in (("ichimoku_tenkan", "İchimoku Tenkan (9)"),
                           ("ichimoku_kijun", "İchimoku Kijun (26)"),
                           ("vwma", "Hacim Ağırlıklı Hareketli Ortalama (20)"),
                           ("hull_ma", "Hull Hareketli Ortalama (9)")):
            val = values.get(key)
            rows.append(IndicatorRow(name=label, value=val,
                                     verdict=interpret_ma(price, val)))

        return rows

    @staticmethod
    def build_pivot_rows(values: Dict[str, Any]) -> List[IndicatorRow]:
        """Pivot seviyeleri; fiyat seviyenin ustunde/altinda."""
        price = values["close"]
        rows: List[IndicatorRow] = []

        for key, label in PIVOTS:
            level = values.get(key)
            if level is None or pd.isna(level):
                rows.append(IndicatorRow(name=label, value=level,
                                         verdict="neutral"))
            elif key == "pivot":
                rows.append(IndicatorRow(name=label, value=level,
                                         verdict=interpret_pivot(price, values)))
            else:
                verdict = "buy" if price > level else "sell"
                rows.append(IndicatorRow(name=label, value=level,
                                         verdict=verdict))
        return rows

    @staticmethod
    def build_oscillator_rows(values: Dict[str, Any]) -> List[IndicatorRow]:
        rows: List[IndicatorRow] = []
        for key, label in OSCILLATORS:
            val = values.get(key)
            rows.append(IndicatorRow(name=label, value=val,
                                     verdict=interpret_oscillator(key, val)))
        return rows

    # ------------------------------------------------------------------
    def classify(self, composite: float) -> Signal:
        cfg = self.config
        if composite >= cfg.strong_buy_threshold:
            return Signal.STRONG_BUY
        if composite >= cfg.entry_threshold:
            return Signal.BUY
        if composite <= cfg.strong_sell_threshold:
            return Signal.STRONG_SELL
        if composite <= -cfg.entry_threshold:
            return Signal.SELL
        return Signal.NEUTRAL

    # ------------------------------------------------------------------
    def generate(self, df_with_indicators: pd.DataFrame) -> Optional[SignalResult]:
        """DataFrame'in son satirindan sinyal uretir."""
        if df_with_indicators is None or len(df_with_indicators) == 0:
            return None

        values = self.calc.get_latest(df_with_indicators)

        osc_rows = self.build_oscillator_rows(values)
        ma_rows = self.build_ma_rows(values)
        pivot_rows = self.build_pivot_rows(values)

        osc_score = _score(osc_rows)
        ma_score = _score(ma_rows)
        pivot_score = _score(pivot_rows)

        # agirliklar config'den; uc bilesen toplami 1.0
        w_osc = self.config.oscillator_weight
        w_ma = self.config.ma_weight
        w_pv = getattr(self.config, "pivot_weight", 0.0)
        w_sum = (w_osc + w_ma + w_pv) or 1.0

        composite = (
            osc_score * w_osc + ma_score * w_ma + pivot_score * w_pv
        ) / w_sum
        composite = float(np.clip(composite, -1.0, 1.0))

        result = SignalResult(
            timestamp=df_with_indicators.index[-1],
            price=values["close"],
            composite=composite,
            signal=self.classify(composite),
            oscillator_score=osc_score,
            ma_score=ma_score,
            pivot_score=pivot_score,
            oscillators=osc_rows,
            moving_averages=ma_rows,
            pivots=pivot_rows,
            osc_counts=_counts(osc_rows),
            ma_counts=_counts(ma_rows),
            pivot_counts=_counts(pivot_rows),
            raw=values,
        )

        logger.info("Sinyal: %s | skor %+.3f | fiyat %.2f",
                    result.signal.value, result.composite, result.price)
        return result

    def generate_series(self, df_with_indicators: pd.DataFrame) -> pd.DataFrame:
        """Backtest icin her bar icin bilesik skor serisi uretir.

        Donen kolonlar: composite, osc_score, ma_score, pivot_score, signal
        """
        cfg = self.config

        close = df_with_indicators["close"]
        osc_keys = [k for k, _ in OSCILLATORS]
        ma_keys = [f"{kind}_{p}" for p in self.calc.MA_PERIODS
                   for kind in ("ema", "sma")]
        ma_keys += ["ichimoku_tenkan", "ichimoku_kijun", "vwma", "hull_ma"]
        pivot_keys = [k for k, _ in PIVOTS]

        # 1) Osilator skorleri (-1..1), NaN -> 0 (notincelenmis)
        buy = pd.Series(0.0, index=close.index)
        sell = pd.Series(0.0, index=close.index)
        n_osc = pd.Series(0.0, index=close.index)

        for key in osc_keys:
            if key not in df_with_indicators:
                continue
            vals = df_with_indicators[key]
            valid = vals.notna()
            v = vals.where(valid)

            is_buy = pd.Series(0.0, index=close.index)
            is_sell = pd.Series(0.0, index=close.index)

            if key == "rsi":
                is_buy = (v <= 30).astype(float)
                is_sell = (v >= 70).astype(float)
            elif key in ("stoch_k", "stoch_rsi_k"):
                is_buy = (v <= 20).astype(float)
                is_sell = (v >= 80).astype(float)
            elif key == "cci":
                is_buy = (v <= -100).astype(float)
                is_sell = (v >= 100).astype(float)
            elif key == "adx":
                is_buy = (v >= 25).astype(float)
            elif key in ("ao", "momentum", "macd"):
                is_buy = (v > 0).astype(float)
                is_sell = (v <= 0).astype(float)
            elif key == "macd_hist":
                is_buy = (v > 0).astype(float)
                is_sell = (v <= 0).astype(float)
            elif key == "williams_r":
                is_buy = (v <= -80).astype(float)
                is_sell = (v >= -20).astype(float)
            elif key == "bull_power":
                is_buy = (v > 0).astype(float)
            elif key == "bear_power":
                is_sell = (v < 0).astype(float)
            elif key == "uo":
                is_buy = (v <= 30).astype(float)
                is_sell = (v >= 70).astype(float)
            elif key == "di_plus":
                is_buy = (v > 20).astype(float)
            elif key == "di_minus":
                is_sell = (v > 20).astype(float)

            buy += is_buy.fillna(0.0)
            sell += is_sell.fillna(0.0)
            n_osc += valid.astype(float)

        osc_score = ((buy - sell) / n_osc.replace(0.0, np.nan)).fillna(0.0)

        # 2) MA skorleri
        ma_buy = pd.Series(0.0, index=close.index)
        ma_sell = pd.Series(0.0, index=close.index)
        n_ma = pd.Series(0.0, index=close.index)

        for key in ma_keys:
            if key not in df_with_indicators:
                continue
            ma = df_with_indicators[key]
            valid = ma.notna()
            ma_buy += (close > ma).astype(float).where(valid, 0.0)
            ma_sell += (close < ma).astype(float).where(valid, 0.0)
            n_ma += valid.astype(float)

        ma_score = ((ma_buy - ma_sell) / n_ma.replace(0.0, np.nan)).fillna(0.0)

        # 3) Pivot skoru
        p_buy = pd.Series(0.0, index=close.index)
        p_sell = pd.Series(0.0, index=close.index)
        n_p = pd.Series(0.0, index=close.index)

        for key in pivot_keys:
            if key not in df_with_indicators:
                continue
            lvl = df_with_indicators[key]
            valid = lvl.notna()
            p_buy += (close > lvl).astype(float).where(valid, 0.0)
            p_sell += (close < lvl).astype(float).where(valid, 0.0)
            n_p += valid.astype(float)

        pivot_score = ((p_buy - p_sell) / n_p.replace(0.0, np.nan)).fillna(0.0)

        # 4) Bilesik skor (agirliklar normalize edilir)
        w_osc = cfg.oscillator_weight
        w_ma = cfg.ma_weight
        w_pv = getattr(cfg, "pivot_weight", 0.0)
        w_sum = (w_osc + w_ma + w_pv) or 1.0

        composite = (
            (osc_score * w_osc + ma_score * w_ma + pivot_score * w_pv) / w_sum
        ).clip(-1.0, 1.0)

        out = pd.DataFrame({
            "close": close,
            "composite": composite,
            "osc_score": osc_score,
            "ma_score": ma_score,
            "pivot_score": pivot_score,
        })

        out["signal"] = np.select(
            [out["composite"] >= cfg.strong_buy_threshold,
             out["composite"] >= cfg.entry_threshold,
             out["composite"] <= cfg.strong_sell_threshold,
             out["composite"] <= -cfg.entry_threshold],
            ["STRONG_BUY", "BUY", "STRONG_SELL", "SELL"],
            default="NEUTRAL",
        )

        return out

    # ------------------------------------------------------------------
    def should_open_long(self, result: SignalResult) -> bool:
        """Sadece GÜÇLÜ AL skoru emir acar (orta seviye beklemede kalir)."""
        return (result.signal == Signal.STRONG_BUY
                and result.composite >= self.config.strong_buy_threshold)

    def should_open_short(self, result: SignalResult) -> bool:
        """Sadece GÜÇLÜ SAT skoru emir acar."""
        return (result.signal == Signal.STRONG_SELL
                and result.composite <= self.config.strong_sell_threshold)

    def should_close(self, result: SignalResult, side: str) -> bool:
        """Mevcut pozisyon kapatilmali mi?

        Iki kriter (sirayla kontrol edilir):

        1) TERS YON GUC LU SINYAL
           LONG icin STRONG_SELL, SHORT icin STRONG_BUY.

        2) SINYAL SOGUMESI  (exit_threshold, varsayilan 0.10)
           Pozisyonun acilis gerekcesi olan guclu yon zayifladiginda:
             LONG  : skor <= +0.10  (guc nötre dondu)
             SHORT : skor >= -0.10  (guc nötre dondu)
           Kullanici istegi: "skor 0 / -0.10 arasina dustugune kapat".

           Bu esik NOTR bolgesinden (|skor| < entry_threshold) cok daha
           dar oldugu icin, sadece neredeyse nokta olan durumlarda
           tetiklenir; her kucuk salinimda kapatmaz.

        risk SL/TP / kâr kilidi ise pozisyon yonetim katmaninda
        (TradingEngine.manage_position) ele alinir.
        """
        if result is None:
            return False

        # 1) ters yon guclu sinyal
        if side == "long" and result.signal == Signal.STRONG_SELL:
            return True
        if side == "short" and result.signal == Signal.STRONG_BUY:
            return True

        # 2) sinyal sogumesi
        if getattr(self.config, "exit_on_decay", False):
            thr = self.config.exit_threshold
            if side == "long" and result.composite <= thr:
                return True
            if side == "short" and result.composite >= -thr:
                return True

        return False

    # ------------------------------------------------------------------
    def close_reason(self, result: SignalResult, side: str) -> str:
        """Kapatma gerekcesini etiket olarak dondurur (gunlendirme icin)."""
        if result is None:
            return ""
        if side == "long" and result.signal == Signal.STRONG_SELL:
            return "ters-guclu-sinyal"
        if side == "short" and result.signal == Signal.STRONG_BUY:
            return "ters-guclu-sinyal"
        if getattr(self.config, "exit_on_decay", False):
            thr = self.config.exit_threshold
            if side == "long" and result.composite <= thr:
                return "sinyal-sogudu"
            if side == "short" and result.composite >= -thr:
                return "sinyal-sogudu"
        return ""
