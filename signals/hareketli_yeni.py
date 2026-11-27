"""
Hareketli_Yeni Algoritması - Hareketli Ortalama AL/SAT/NÖTR Sayımı

Kural:
- Grafikteki tüm hareketli ortalamaların (EMA/SMA 10-200, Ichimoku, VWMA, Hull MA)
  o bar için kararını (AL/SAT/NÖTR) sayar

LONG Giriş/Devam:
- AL sayısı > SAT sayısı VE AL sayısı > NÖTR sayısı olduğu SÜRECE
- LONG açılır ve pozisyonda kalınır

LONG Kapatma:
- AL sayısı NÖTR sayısına EŞİT VE SAT sayısına EŞİT olduğunda
- VEYA AL sayısı NÖTR'ten KÜÇÜK olduğunda
- VEYA AL sayısı SAT'ten KÜÇÜK olduğunda
- O anda LONG pozisyonu KAPATILIR

SHORT Giriş/Devam:
- SAT sayısı > AL sayısı VE SAT sayısı > NÖTR sayısı olduğu SÜRECE
- SHORT açılır ve pozisyonda kalınır

SHORT Kapatma:
- SAT sayısı NÖTR sayısına EŞİT VE AL sayısına EŞİT olduğunda
- VEYA SAT sayısı NÖTR'ten KÜÇÜK olduğunda
- VEYA SAT sayısı AL'den KÜÇÜK olduğunda
- O anda SHORT pozisyonu KAPATILIR

TAKİPÇİ kuralları (giriş/çıkış):
- Çift yönlü + sadece LONG / sadece SHORT varyantları
- Kâr bankası (profit bank), Zarar freni (loss brake), Min. bekleme
- Koruyucu stop YOK
- LONG çıkış: Tamamlanmış mumda HULL SAT olduğunda
- SHORT çıkış: Tamamlanmış mumda HULL AL olduğunda
- Ters HULL yeni girişi engeller
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from config import TRADING_CONFIG
from indicators.calculator import IndicatorsCalculator
from signals.generator import Signal
from trading.engine import Side, PositionStatus, TradingEngine, Position, Wallet

logger = logging.getLogger(__name__)


class HAREKETLI_YENI_MODE(Enum):
    """Hareketli_Yeni algoritması modları."""
    TWO_WAY = "two_way"       # Çift yönlü (LONG + SHORT)
    LONG_ONLY = "long_only"   # Sadece LONG
    SHORT_ONLY = "short_only" # Sadece SHORT


@dataclass
class HareketliYeniResult:
    """Hareketli_Yeni algoritması sonucu."""
    timestamp: Any
    price: float
    ma_counts: Dict[str, int]          # AL/SAT/NÖTR sayıları
    ma_rows: List[Dict[str, Any]]      # Detaylı MA satırları
    signal: Signal
    composite: float                   # -1..1 arası kompozit skor
    direction: str                     # "LONG", "SHORT", "NEUTRAL"
    
    def counts_str(self) -> str:
        """Sayıları okunabilir formatta döndürür."""
        return (f"AL {self.ma_counts.get('buy', 0)}  ·  "
                f"SAT {self.ma_counts.get('sell', 0)}  ·  "
                f"NÖTR {self.ma_counts.get('neutral', 0)}")


class HareketliYeniGenerator:
    """Hareketli_Yeni algoritması sinyal üreteci."""
    
    # TradingView "Hareketli Ortalamalar" sayfasındaki tüm MA'ler
    MA_KEYS = [
        # EMA
        "ema_10", "ema_20", "ema_30", "ema_50", "ema_100", "ema_200",
        # SMA
        "sma_10", "sma_20", "sma_30", "sma_50", "sma_100", "sma_200",
        # Ichimoku
        "ichimoku_tenkan", "ichimoku_kijun",
        # VWMA
        "vwma",
        # Hull MA
        "hull_ma",
    ]
    
    def __init__(self, config: TRADING_CONFIG = None,
                 indicator_config=None):
        self.config = config or TRADING_CONFIG
        self.calc = IndicatorsCalculator(indicator_config)
        
        # TAKİPÇİ ayarları
        self.mode = HAREKETLI_YENI_MODE.TWO_WAY
        self.profit_bank_enabled = True       # Kâr bankası
        self.loss_brake_enabled = True        # Zarar freni
        self.min_wait_bars = 3                # Min. bekleme (mum sayısı)
        
        # HULL MA (giriş/çıkış kontrolü için)
        self.hull_key = "hull_ma"
        
        # İç durum
        self._bars_since_last_close = 0
        self._last_direction = "NEUTRAL"
    
    def _interpret_ma(self, price: float, ma_value: float) -> str:
        """Tek bir MA için AL/SAT/NÖTR kararı.
        
        TradingView "Hareketli Ortalamalar" sayfasındaki mantık:
        - Fiyat MA'nin üstündeyse -> AL
        - Fiyat MA'nin altındaysa -> SAT
        - Fiyat MA ile çok yakınsa (ölü bant) -> NÖTR
        """
        if ma_value is None or pd.isna(ma_value) or pd.isna(price):
            return "neutral"
        
        # Ölü bant: fiyat MA'nın %0.05'i içindeyse NÖTR
        # TradingView'de "Nötr" olarak gösterilen alan bu aralıktır
        deadzone = abs(ma_value) * 0.0005  # %0.05
        
        if price > ma_value + deadzone:
            return "buy"
        elif price < ma_value - deadzone:
            return "sell"
        return "neutral"
    
    def _interpret_hull(self, price: float, hull_value: float) -> str:
        """HULL MA için AL/SAT kararı (ölü bant YOK - TAKİPÇİ kuralı)."""
        if hull_value is None or pd.isna(hull_value) or pd.isna(price):
            return "neutral"
        return "buy" if price > hull_value else "sell"
    
    def analyze_ma_counts(self, values: Dict[str, Any]) -> tuple[Dict[str, int], List[Dict[str, Any]]]:
        """Tüm MA'ler için AL/SAT/NÖTR sayılarını hesaplar."""
        price = values["close"]
        counts = {"buy": 0, "sell": 0, "neutral": 0}
        rows = []
        
        for key in self.MA_KEYS:
            if key not in values:
                continue
            ma_val = values[key]
            if pd.isna(ma_val):
                verdict = "neutral"
            else:
                verdict = self._interpret_ma(price, float(ma_val))
            
            counts[verdict] += 1
            
            # İnsan okunabilir isim
            display_name = self._ma_display_name(key)
            rows.append({
                "name": display_name,
                "value": float(ma_val) if not pd.isna(ma_val) else None,
                "verdict": verdict,
            })
        
        return counts, rows
    
    def _ma_display_name(self, key: str) -> str:
        """MA anahtarını görüntüleme ismine çevirir."""
        mapping = {
            "ema_10": "EMA (10)", "ema_20": "EMA (20)", "ema_30": "EMA (30)",
            "ema_50": "EMA (50)", "ema_100": "EMA (100)", "ema_200": "EMA (200)",
            "sma_10": "SMA (10)", "sma_20": "SMA (20)", "sma_30": "SMA (30)",
            "sma_50": "SMA (50)", "sma_100": "SMA (100)", "sma_200": "SMA (200)",
            "ichimoku_tenkan": "İchimoku Tenkan (9)",
            "ichimoku_kijun": "İchimoku Kijun (26)",
            "vwma": "VWMA (20)",
            "hull_ma": "Hull MA (9)",
        }
        return mapping.get(key, key)
    
    def _determine_direction(self, counts: Dict[str, int]) -> str:
        """MA sayımlarına göre yön belirler."""
        al = counts.get("buy", 0)
        sat = counts.get("sell", 0)
        notr = counts.get("neutral", 0)
        
        # LONG koşulu: AL > SAT VE AL > NÖTR
        long_cond = (al > sat) and (al > notr)
        
        # SHORT koşulu: SAT > AL VE SAT > NÖTR
        short_cond = (sat > al) and (sat > notr)
        
        # Kapatma koşulları
        # LONG kapat: AL <= NÖTR VEYA AL <= SAT
        long_close = (al <= notr) or (al <= sat)
        
        # SHORT kapat: SAT <= NÖTR VEYA SAT <= AL
        short_close = (sat <= notr) or (sat <= al)
        
        if self._last_direction == "LONG":
            if long_close:
                return "NEUTRAL"
            return "LONG"
        elif self._last_direction == "SHORT":
            if short_close:
                return "NEUTRAL"
            return "SHORT"
        else:  # NEUTRAL
            if long_cond:
                return "LONG"
            if short_cond:
                return "SHORT"
            return "NEUTRAL"
    
    def generate(self, values: Dict[str, Any]) -> HareketliYeniResult:
        """Anlık sinyal üretir."""
        price = values["close"]
        counts, rows = self.analyze_ma_counts(values)
        direction = self._determine_direction(counts)
        
        # Sinyal enum'una çevir
        if direction == "LONG":
            signal = Signal.BUY
        elif direction == "SHORT":
            signal = Signal.SELL
        else:
            signal = Signal.NEUTRAL
        
        # Kompozit skor: (AL - SAT) / TOPLAM
        total = sum(counts.values())
        composite = (counts["buy"] - counts["sell"]) / total if total > 0 else 0.0
        
        self._last_direction = direction
        
        return HareketliYeniResult(
            timestamp=values.get("timestamp"),
            price=price,
            ma_counts=counts,
            ma_rows=rows,
            signal=signal,
            composite=composite,
            direction=direction,
        )
    
    def generate_series(self, df: pd.DataFrame) -> pd.DataFrame:
        """Backtest için tüm barlar için sinyal serisi üretir."""
        results = []
        
        for ts, row in df.iterrows():
            # Son indeks değerlerini sözlüğe çevir
            values = {"close": float(row["close"])}
            for key in self.MA_KEYS:
                if key in df.columns:
                    v = row[key]
                    values[key] = float(v) if pd.notna(v) else float("nan")
            values["timestamp"] = ts
            
            res = self.generate(values)
            results.append({
                "timestamp": ts,
                "close": res.price,
                "direction": res.direction,
                "signal": res.signal.value,
                "composite": res.composite,
                "ma_al": res.ma_counts.get("buy", 0),
                "ma_sat": res.ma_counts.get("sell", 0),
                "ma_notr": res.ma_counts.get("neutral", 0),
            })
        
        out = pd.DataFrame(results).set_index("timestamp")
        return out
    
    def should_open_long(self, result: HareketliYeniResult,
                         hull_value: float = None) -> bool:
        """LONG açılmalı mı? (TAKİPÇİ HULL girişi kontrolü)"""
        if result.direction != "LONG":
            return False
        
        # Sadece LONG modunda veya çift yönlüyse
        if self.mode == HAREKETLI_YENI_MODE.SHORT_ONLY:
            return False
        
        # HULL AL kontrolü: fiyat HULL üstünde olmalı (LONG girişi için)
        if hull_value is not None and not pd.isna(hull_value):
            if result.price <= hull_value:  # HULL SAT veya NÖTR
                return False
        
        return True
    
    def should_open_short(self, result: HareketliYeniResult,
                          hull_value: float = None) -> bool:
        """SHORT açılmalı mı? (TAKİPÇİ HULL girişi kontrolü)"""
        if result.direction != "SHORT":
            return False
        
        # Sadece SHORT modunda veya çift yönlüyse
        if self.mode == HAREKETLI_YENI_MODE.LONG_ONLY:
            return False
        
        # HULL SAT kontrolü: fiyat HULL altında olmalı (SHORT girişi için)
        if hull_value is not None and not pd.isna(hull_value):
            if result.price >= hull_value:  # HULL AL veya NÖTR
                return False
        
        return True
    
    def should_close_long(self, result: HareketliYeniResult,
                          hull_value: float = None) -> bool:
        """LONG pozisyonu kapatılmalı mı? (TAKİPÇİ HULL çıkışı kontrolü)"""
        # 1. MA sayımı kuralı: yön NEUTRAL veya SHORT olduysa
        if result.direction in ("NEUTRAL", "SHORT"):
            return True
        
        # 2. TAKİPÇİ kuralı: Tamamlanmış mumda HULL SAT ise LONG kapat
        if hull_value is not None and not pd.isna(hull_value):
            if result.price < hull_value:  # HULL SAT (fiyat HULL altına düştü)
                return True
        
        return False
    
    def should_close_short(self, result: HareketliYeniResult,
                           hull_value: float = None) -> bool:
        """SHORT pozisyonu kapatılmalı mı? (TAKİPÇİ HULL çıkışı kontrolü)"""
        # 1. MA sayımı kuralı: yön NEUTRAL veya LONG olduysa
        if result.direction in ("NEUTRAL", "LONG"):
            return True
        
        # 2. TAKİPÇİ kuralı: Tamamlanmış mumda HULL AL ise SHORT kapat
        if hull_value is not None and not pd.isna(hull_value):
            if result.price > hull_value:  # HULL AL (fiyat HULL üstüne çıktı)
                return True
        
        return False
    
    def close_reason(self, result: HareketliYeniResult,
                     side: str, hull_value: float = None) -> str:
        """Kapatma sebebini döndürür."""
        if side == "long":
            if result.direction == "SHORT":
                return "ma-ters-yön"
            if result.direction == "NEUTRAL":
                if result.ma_counts.get("buy", 0) <= result.ma_counts.get("neutral", 0):
                    return "ma-al≤nötr"
                return "ma-al≤sat"
            if hull_value is not None and result.price < hull_value:
                return "hull-sat-çıkış"
        else:  # short
            if result.direction == "LONG":
                return "ma-ters-yön"
            if result.direction == "NEUTRAL":
                if result.ma_counts.get("sell", 0) <= result.ma_counts.get("neutral", 0):
                    return "ma-sat≤nötr"
                return "ma-sat≤al"
            if hull_value is not None and result.price > hull_value:
                return "hull-al-çıkış"
        return "sinyal"
    
    def check_profit_bank(self, pos: Position, price: float) -> bool:
        """Kâr bankası kontrolü (TAKİPÇİ: kâr bankaya yaz, aynı notional ile tekrar gir)."""
        if not self.profit_bank_enabled:
            return False
        # ROI hedefi (config'den alınır, varsayılan %10 ROI)
        target_roi = getattr(self.config, "profit_lock_pct", 0.10) * 100.0
        pos.update(price, self.config.taker_fee)
        return pos.roi_pct >= target_roi
    
    def check_loss_brake(self, pos: Position, price: float) -> bool:
        """Zarar freni kontrolü (TAKİPÇİ: zarar belli seviyeyi geçerse kapat)."""
        if not self.loss_brake_enabled:
            return False
        # Zarar freni: -%5 ROI (config'den)
        brake_roi = -abs(getattr(self.config, "stop_loss_pct", 0.01) * 100.0 * 2)
        pos.update(price, self.config.taker_fee)
        return pos.roi_pct <= brake_roi
    
    def check_min_wait(self) -> bool:
        """Min. bekleme kontrolü."""
        if self.min_wait_bars <= 0:
            return True
        self._bars_since_last_close += 1
        return self._bars_since_last_close >= self.min_wait_bars
    
    def reset_wait(self):
        """Bekleme sayacını sıfırla."""
        self._bars_since_last_close = 0


# ==============================================================================
# HAREKETLI_YENI TRADING ENGINE - TAKİPÇİ kural seti ile entegre
# ==============================================================================

class HareketliYeniEngine:
    """Hareketli_Yeni algoritması ile paper trading motoru (TAKİPÇİ kuralları)."""
    
    def __init__(self, config: TRADING_CONFIG = None,
                 indicator_config=None,
                 balance: Optional[float] = None):
        self.config = config or TRADING_CONFIG
        self.ind_config = indicator_config
        self.calc = IndicatorsCalculator(self.ind_config)
        self.generator = HareketliYeniGenerator(self.config, self.ind_config)
        self.engine = TradingEngine(self.config, balance)
        
        # TAKİPÇİ ayarlarını kopyala
        self.generator.profit_bank_enabled = getattr(self.config, "profit_lock_enabled", False)
        self.generator.loss_brake_enabled = True
        self.generator.min_wait_bars = 3
    
    def run(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Backtest çalıştırır."""
        if df is None or len(df) < 210:
            raise ValueError("Yetersiz veri (en az 210 mum gerekli)")
        
        logger.info("İndikatorler hesaplaniyor (%d mum)...", len(df))
        enriched = self.calc.calculate_all(df)
        
        logger.info("Hareketli_Yeni sinyal serisi üretiliyor...")
        signals = self.generator.generate_series(enriched)
        signals = signals.dropna(subset=["composite"])
        
        equity_rows = []
        last_idx = None
        
        for ts, row in enriched.iterrows():
            if ts not in signals.index:
                continue
            
            sig_row = signals.loc[ts]
            last_idx = ts
            close = float(row["close"])
            high = float(row["high"])
            low = float(row["low"])
            
            # HULL MA değeri (giriş/çıkış kontrolü için)
            hull_value = None
            if "hull_ma" in enriched.columns:
                hull_value = float(enriched.loc[ts, "hull_ma"]) if pd.notna(enriched.loc[ts, "hull_ma"]) else None
            
            # HareketliYeniResult nesnesi oluştur (generate_series içinde zaten hesaplandı)
            from signals.generator import Signal
            signal_map = {"LONG": Signal.BUY, "SHORT": Signal.SELL, "NEUTRAL": Signal.NEUTRAL}
            
            # Generator'dan tam sonucu al (MA detayları için)
            values = {"close": close, "timestamp": ts}
            for key in self.generator.MA_KEYS:
                if key in enriched.columns:
                    v = enriched.loc[ts, key]
                    values[key] = float(v) if pd.notna(v) else float("nan")
            
            sig_obj = self.generator.generate(values)
            
            # 1) Pozisyon yönetimi
            if self.engine.open_positions:
                pos = self.engine.open_positions[0]
                should_close = False
                reason = ""
                
                # TAKİPÇİ kuralları: HULL çıkışı + MA sayımı kuralı
                if pos.side == Side.LONG:
                    should_close = self.generator.should_close_long(sig_obj, hull_value)
                    if should_close:
                        reason = self.generator.close_reason(sig_obj, "long", hull_value)
                else:
                    should_close = self.generator.should_close_short(sig_obj, hull_value)
                    if should_close:
                        reason = self.generator.close_reason(sig_obj, "short", hull_value)
                
                # Kâr bankası kontrolü
                if not should_close and self.generator.check_profit_bank(pos, close):
                    should_close = True
                    reason = "kar-bankası"
                
                # Zarar freni kontrolü
                if not should_close and self.generator.check_loss_brake(pos, close):
                    should_close = True
                    reason = "zarar-freni"
                
                # Min. bekleme - sadece yeni giriş için, çıkış engellenmez
                # (çıkış her zaman anında yapılır)
                
                if should_close:
                    self.engine.close_position(pos, close, ts, reason)
                    self.generator.reset_wait()
                    logger.info("%s %s @ %.2f | %s", pos.side.value, reason, close,
                                f"PnL {pos.realized_pnl:+.2f}")
                else:
                    # Normal pozisyon yönetimi (SL/TP/basaba/kar_kilidi)
                    self.engine.manage_position(pos, close, ts, high=high, low=low)
            else:
                # 2) Yeni pozisyon - Min. bekleme kontrolü
                if self.generator.check_min_wait():
                    # LONG girişi
                    if self.generator.should_open_long(sig_obj, hull_value):
                        pos = self.engine.open_position(Side.LONG, close, ts, signal=sig_obj)
                        if pos:
                            logger.info("LONG giris @ %.2f | AL %d SAT %d NÖTR %d",
                                        close, sig_obj.ma_counts["buy"],
                                        sig_obj.ma_counts["sell"],
                                        sig_obj.ma_counts["neutral"])
                    
                    # SHORT girişi
                    elif self.generator.should_open_short(sig_obj, hull_value):
                        pos = self.engine.open_position(Side.SHORT, close, ts, signal=sig_obj)
                        if pos:
                            logger.info("SHORT giris @ %.2f | AL %d SAT %d NÖTR %d",
                                        close, sig_obj.ma_counts["buy"],
                                        sig_obj.ma_counts["sell"],
                                        sig_obj.ma_counts["neutral"])
            
            # 3) Anlık PnL
            self.engine.mark_to_market(close)
            
            equity_rows.append({
                "timestamp": ts,
                "close": close,
                "composite": sig_row["composite"],
                "direction": sig_row["direction"],
                "signal": sig_row["signal"],
                "ma_al": sig_row["ma_al"],
                "ma_sat": sig_row["ma_sat"],
                "ma_notr": sig_row["ma_notr"],
                "equity": self.engine.wallet.equity(self.engine.open_positions),
            })
        
        # Son açık pozisyonu kapat
        if self.engine.open_positions and last_idx is not None:
            self.engine.close_position(self.engine.open_positions[0],
                                       float(enriched.loc[last_idx, "close"]),
                                       last_idx, "backtest-son")
        
        equity_df = pd.DataFrame(equity_rows).set_index("timestamp") if equity_rows else pd.DataFrame()
        
        # Metrikler
        metrics = self._metrics(self.engine, equity_df)
        logger.info("Hareketli_Yeni backtest bitti: %s", metrics)
        
        return {
            "engine": self.engine,
            "signals": signals,
            "data": enriched,
            "equity_curve": equity_df,
            "metrics": metrics,
        }
    
    @staticmethod
    def _metrics(engine: TradingEngine, equity_df: pd.DataFrame) -> Dict[str, Any]:
        stats = engine.wallet.stats(engine.open_positions)
        closed = engine.closed_positions
        
        gross_win = sum(p.realized_pnl for p in closed if p.realized_pnl > 0)
        gross_loss = sum(p.realized_pnl for p in closed if p.realized_pnl <= 0)
        
        pf = (gross_win / abs(gross_loss)) if gross_loss < 0 else float("inf")
        avg_win = (gross_win / engine.wallet.wins) if engine.wallet.wins else 0.0
        avg_loss = (gross_loss / engine.wallet.losses) if engine.wallet.losses else 0.0
        expectancy = ((avg_win * engine.wallet.wins + avg_loss * engine.wallet.losses)
                      / engine.wallet.trades if engine.wallet.trades else 0.0)
        
        max_dd = 0.0
        if not equity_df.empty:
            eq = equity_df["equity"]
            peak = eq.cummax()
            dd = (peak - eq) / peak * 100.0
            max_dd = float(dd.max())
        
        return {
            **stats,
            "profit_factor": round(pf, 2) if pf != float("inf") else "∞",
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "expectancy": round(expectancy, 3),
            "gross_win": round(gross_win, 2),
            "gross_loss": round(gross_loss, 2),
            "equity_max_dd": round(max_dd, 2),
            "long_trades": sum(1 for p in closed if p.side == Side.LONG),
            "short_trades": sum(1 for p in closed if p.side == Side.SHORT),
        }


# ==============================================================================
# HAFIF TEST
# ==============================================================================

if __name__ == "__main__":
    import sys
    sys.path.insert(0, "C:\\Users\\PC-ITENG\\Documents\\Default Project")
    
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
    
    from data.fetcher import DataFetcher
    
    # Veri çek
    fetcher = DataFetcher()
    df = fetcher.fetch_ohlcv("5m", limit=1000)
    print(f"Veri: {len(df)} mum (5dk)")
    
    # Algoritmayı test et
    engine = HareketliYeniEngine()
    result = engine.run(df)
    
    print("\n=== SONUÇ ===")
    for k, v in result["metrics"].items():
        print(f"  {k:18}: {v}")
    
    # Son sinyalleri göster
    signals = result["signals"].tail(10)
    print("\n--- Son 10 Sinyal ---")
    for ts, row in signals.iterrows():
        print(f"  {ts} | {row['direction']:7} | AL={row['ma_al']:2d} SAT={row['ma_sat']:2d} NÖTR={row['ma_notr']:2d} | skor={row['composite']:+.3f}")