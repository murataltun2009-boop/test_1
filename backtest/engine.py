"""
Backtest motoru: gecmis veri ile ayni sinyal stratejisini test eder.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import pandas as pd

from config import INDICATOR_CONFIG, TRADING_CONFIG
from indicators.calculator import IndicatorsCalculator
from signals.generator import Signal, SignalGenerator
from signals.hareketli_yeni import HareketliYeniEngine, HAREKETLI_YENI_MODE
from trading.engine import Side, TradingEngine

logger = logging.getLogger(__name__)


class BacktestEngine:
    """Veri uzerinde bar bar ilerleyerek paper trading yapar."""

    def __init__(self, config: TRADING_CONFIG = None,
                 indicator_config: INDICATOR_CONFIG = None,
                 balance: Optional[float] = None,
                 mode: str = "composite"):  # "composite" | "hareketli_yeni" | "hareketli_yeni_long" | "hareketli_yeni_short"
        self.config = config or TRADING_CONFIG
        self.ind_config = indicator_config or INDICATOR_CONFIG
        self.calc = IndicatorsCalculator(self.ind_config)
        self.generator = SignalGenerator(self.config, self.ind_config)
        self.hareketli_yeni_engine = None
        self.mode = mode
        self.balance = balance if balance is not None else self.config.backtest_initial \
            if hasattr(self.config, "backtest_initial") else self.config.initial_balance

    # ------------------------------------------------------------------
    def run(self, df: pd.DataFrame,
            enriched: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
        """df: timestamp index'li OHLCV.

        enriched verilirse indikator hesabi atlanir (parametre taramasi icin).
        
        mode: "composite" (varsayılan, bileşik skor) 
              "hareketli_yeni" (çift yönlü)
              "hareketli_yeni_long" (sadece LONG)
              "hareketli_yeni_short" (sadece SHORT)
        """
        if df is None or len(df) < 210:
            raise ValueError("Yetersiz veri (en az 210 mum gerekli)")

        if enriched is None:
            logger.info("İndikatorler hesaplaniyor (%d mum)...", len(df))
            enriched = self.calc.calculate_all(df)
        else:
            logger.debug("Onbellekten indikatorler kullanildi (%d mum)", len(enriched))

        # Hareketli_Yeni modu
        if self.mode.startswith("hareketli_yeni"):
            logger.info("Hareketli_Yeni modu: %s", self.mode)
            hy_mode = HAREKETLI_YENI_MODE.TWO_WAY
            if self.mode == "hareketli_yeni_long":
                hy_mode = HAREKETLI_YENI_MODE.LONG_ONLY
            elif self.mode == "hareketli_yeni_short":
                hy_mode = HAREKETLI_YENI_MODE.SHORT_ONLY
            
            self.hareketli_yeni_engine = HareketliYeniEngine(
                self.config, self.ind_config, self.balance)
            self.hareketli_yeni_engine.generator.mode = hy_mode
            
            result = self.hareketli_yeni_engine.run(enriched)
            return result

        # Varsayılan: Bileşik skor algoritması
        logger.info("Sinyal serisi uretiliyor...")
        signals = self.generator.generate_series(enriched)
        signals = signals.dropna(subset=["composite"])

        engine = TradingEngine(self.config, self.balance)
        gen = self.generator

        equity_rows: List[Dict[str, Any]] = []
        last_idx = None

        for ts, row in enriched.iterrows():
            if ts not in signals.index:
                continue
            sig_row = signals.loc[ts]
            last_idx = ts
            close = float(row["close"])
            high = float(row["high"])
            low = float(row["low"])
            composite = float(sig_row["composite"])
            signal_name = str(sig_row["signal"])
            sig_obj = self._make_signal_obj(signal_name, composite, close, ts)

            # 1) Pozisyon yonetimi: SL/TP -> basaba -> kar kilidi -> sinyal
            if engine.open_positions:
                pos = engine.open_positions[0]
                by_signal = self._close_by_signal(sig_obj, pos, close)
                engine.manage_position(
                    pos, close, ts, high=high, low=low,
                    should_close_by_signal=by_signal,
                    signal_reason=(self._close_reason(sig_obj, pos, close)
                                   if by_signal else "sinyal"),
                )
            else:
                # 2) Yeni pozisyon: sadece GUCLU sinyal
                is_buy = (composite >= self.config.strong_buy_threshold
                          and signal_name in ("STRONG_BUY",))
                is_sell = (composite <= self.config.strong_sell_threshold
                           and signal_name in ("STRONG_SELL",))
                if is_buy or is_sell:
                    engine.open_position(Side.LONG if is_buy else Side.SHORT,
                                         close, ts, signal=sig_obj)

            # 3) Acik pozisyonun anlik degeri
            engine.mark_to_market(close)

            equity_rows.append({
                "timestamp": ts,
                "close": close,
                "composite": composite,
                "signal": signal_name,
                "equity": engine.wallet.equity(engine.open_positions),
            })

        # Son acik pozisyon varsa son fiyattan kapat
        if engine.open_positions and last_idx is not None:
            engine.close_position(engine.open_positions[0],
                                   float(enriched.loc[last_idx, "close"]),
                                   last_idx, "backtest-son")

        equity_df = pd.DataFrame(equity_rows).set_index("timestamp") if equity_rows \
            else pd.DataFrame()

        metrics = self._metrics(engine, equity_df)
        logger.info("Backtest bitti: %s", metrics)

        return {
            "engine": engine,
            "signals": signals,
            "data": enriched,
            "equity_curve": equity_df,
            "metrics": metrics,
        }

    # ------------------------------------------------------------------
    def _close_by_signal(self, sig_obj, pos, price: float) -> bool:
        """Sinyal ile kapatma karari.

        - Ters yon GUCLU sinyal        -> kapat
        - Sinyal sogdu (LONG <= +thr / SHORT >= -thr) -> kapat
        - NOTR + pozisyon KARDA        -> kapat (opsiyonel, kapali)
        """
        if self.generator.should_close(sig_obj, pos.side.value.lower()):
            return True
        # notr + pozisyon karda (opsiyonel, varsayilan kapali)
        if self.config.exit_on_neutral_profit and sig_obj.signal == Signal.NEUTRAL:
            pos.update(price, self.config.taker_fee)
            return pos.unrealized_pnl > 0
        return False

    def _close_reason(self, sig_obj, pos, price: float) -> str:
        """Kapatma sebebini etiketler (grafik/log icin)."""
        if self.generator.should_close(sig_obj, pos.side.value.lower()):
            return self.generator.close_reason(sig_obj, pos.side.value.lower())
        if self.config.exit_on_neutral_profit and sig_obj.signal == Signal.NEUTRAL:
            pos.update(price, self.config.taker_fee)
            if pos.unrealized_pnl > 0:
                return "notr-karda"
        return "sinyal"

        if self.config.exit_on_neutral_profit and sig_obj.signal == Signal.NEUTRAL:
            pos.update(price, self.config.taker_fee)
            return pos.unrealized_pnl > 0
        return False

    # ------------------------------------------------------------------
    @staticmethod
    def _make_signal_obj(name: str, composite: float, price: float, ts):
        from signals.generator import Signal, SignalResult
        mapping = {
            "STRONG_BUY": Signal.STRONG_BUY, "BUY": Signal.BUY,
            "NEUTRAL": Signal.NEUTRAL, "SELL": Signal.SELL,
            "STRONG_SELL": Signal.STRONG_SELL,
        }
        return SignalResult(
            timestamp=ts, price=price, composite=composite,
            signal=mapping.get(name, Signal.NEUTRAL),
            oscillator_score=0.0, ma_score=0.0, pivot_score=0.0,
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _metrics(engine: TradingEngine, equity_df: pd.DataFrame) -> Dict[str, Any]:
        stats = engine.wallet.stats(engine.open_positions)
        closed = engine.closed_positions

        gross_win = sum(p.realized_pnl for p in closed if p.realized_pnl > 0)
        gross_loss = sum(p.realized_pnl for p in closed if p.realized_pnl <= 0)

        pf = (gross_win / abs(gross_loss)) if gross_loss < 0 else float("inf")
        avg_win = (gross_win / engine.wallet.wins) if engine.wallet.wins else 0.0
        avg_loss = (gross_loss / engine.wallet.losses) if engine.wallet.losses else 0.0
        expectancy = ((avg_win * engine.wallet.wins +
                       avg_loss * engine.wallet.losses) / engine.wallet.trades
                      if engine.wallet.trades else 0.0)

        # Max drawdown equity serisinden
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
