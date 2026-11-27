"""
Test cuzdanı (paper trading) ve pozisyon yonetimi.

Tum maliyetler hesaba katilir:
  - giris / cikis komisyonu (taker)
  - stop-loss / take-profit
  - likidasyon kontrolu
  - realized + unrealized PnL, ROI, drawdown
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Dict, List, Optional

import pandas as pd

from config import TRADING_CONFIG

logger = logging.getLogger(__name__)


class Side(Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class PositionStatus(Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    LIQUIDATED = "LIQUIDATED"


@dataclass
class Position:
    id: str
    side: Side
    entry_price: float
    quantity: float                 # BTC cinsinden
    leverage: int
    entry_time: Any
    entry_fee: float
    margin: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    status: PositionStatus = PositionStatus.OPEN
    _fee_rate: float = 0.0005       # canli PnL hesabi icin

    exit_price: Optional[float] = None
    exit_time: Any = None
    exit_fee: Optional[float] = None
    exit_reason: str = ""

    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    roi_pct: float = 0.0
    max_favorable: float = 0.0      # en iyi anlik PnL
    max_adverse: float = 0.0        # en kotu anlik PnL
    breakeven_moved: bool = False   # SL girişe cekildi mi
    peak_roi_pct: float = 0.0       # ulasilan en yuksek ROI
    
    # Hareketli_Yeni algoritması için MA sayıları (giriş/kapanış anında)
    ma_counts_entry: Dict[str, int] = field(default_factory=dict)
    ma_counts_exit: Dict[str, int] = field(default_factory=dict)

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:8]

    # ------------------------------------------------------------------
    # KAR KILIDI
    # ------------------------------------------------------------------
    def hit_profit_lock(self, price: float, target_roi: float) -> bool:
        """Anlik fiyatta ROI hedefi asildi mi?

        Kapatma fiyati SL/TP seviyesinde degil, o anki fiyattir; boylece
        kazanan tarafin agirligi kaybolmaz.
        """
        if target_roi <= 0:
            return False
        self.update(price, self._fee_rate)
        return self.roi_pct >= target_roi * 100.0

    def move_to_breakeven(self, price: float) -> bool:
        """SL'yi giriş fiyatina + ucretler ceker (yeni seviye dondurulur)."""
        if self.breakeven_moved:
            return False
        fee_buf = (self.quantity * self.entry_price * self._fee_rate) * 1.05
        be = self.entry_price + fee_buf / self.quantity if self.quantity else self.entry_price

        self.update(price, self._fee_rate)
        if self.roi_pct <= 0:
            return False

        # SL'yi sadece gercekten iyilestiriyorsa tasi
        if self.side == Side.LONG and (self.stop_loss is None or be > self.stop_loss):
            self.stop_loss = be
            self.breakeven_moved = True
            return True
        if self.side == Side.SHORT and (self.stop_loss is None or be < self.stop_loss):
            self.stop_loss = be
            self.breakeven_moved = True
            return True
        return False

    # ------------------------------------------------------------------
    @property
    def notional(self) -> float:
        return self.quantity * self.entry_price

    def gross_pnl(self, price: float) -> float:
        if self.side == Side.LONG:
            return (price - self.entry_price) * self.quantity
        return (self.entry_price - price) * self.quantity

    # ------------------------------------------------------------------
    def update(self, mark_price: float, taker_fee: float = None) -> None:
        """Anlik PnL ve ekstrem degerleri gunceller."""
        fee = self._fee_rate if taker_fee is None else taker_fee
        self._fee_rate = fee
        gross = self.gross_pnl(mark_price)
        exit_fee = self.quantity * mark_price * fee
        self.unrealized_pnl = gross - exit_fee
        self.max_favorable = max(self.max_favorable, self.unrealized_pnl)
        self.max_adverse = min(self.max_adverse, self.unrealized_pnl)
        if self.margin > 0:
            self.roi_pct = self.unrealized_pnl / self.margin * 100.0
            self.peak_roi_pct = max(self.peak_roi_pct, self.roi_pct)

    def hit_stop(self, price: float) -> bool:
        if self.stop_loss is None:
            return False
        return price <= self.stop_loss if self.side == Side.LONG else price >= self.stop_loss

    def hit_target(self, price: float) -> bool:
        if self.take_profit is None:
            return False
        return price >= self.take_profit if self.side == Side.LONG else price <= self.take_profit

    # ------------------------------------------------------------------
    @property
    def net_cash_change(self) -> float:
        """Pozisyonun bakiyeye net etkisi.

        realized_pnl ISLEM KAZANCIDIR (giriş ve çıkış ücretini içerir).
        Bakiye ise giriş ücreti giriş anında zaten düşüldüğü için burada
        yalnızca brüt zarar ve çıkış ücreti işlenir. Aksi halde giriş
        ücreti iki kez düşülürdü.
        """
        if self.exit_price is None:
            return 0.0
        return self.gross_pnl(self.exit_price) - (self.exit_fee or 0.0)

    # ------------------------------------------------------------------
    def close(self, price: float, timestamp: Any, exit_fee: float,
              reason: str) -> None:
        gross = self.gross_pnl(price)
        self.realized_pnl = gross - self.entry_fee - exit_fee
        self.exit_price = price
        self.exit_time = timestamp
        self.exit_fee = exit_fee
        self.exit_reason = reason
        self.status = (PositionStatus.LIQUIDATED
                       if reason == "likidasyon" else PositionStatus.CLOSED)
        self.unrealized_pnl = 0.0
        self.roi_pct = (self.realized_pnl / self.margin * 100.0) if self.margin else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "side": self.side.value,
            "entry": round(self.entry_price, 2),
            "qty": self.quantity,
            "lev": f"{self.leverage}x",
            "margin": round(self.margin, 2),
            "SL": round(self.stop_loss, 2) if self.stop_loss else None,
            "TP": round(self.take_profit, 2) if self.take_profit else None,
            "status": self.status.value,
            "exit": round(self.exit_price, 2) if self.exit_price else None,
            "pnl": round(self.realized_pnl, 2),
            "roi": round(self.roi_pct, 2),
            "reason": self.exit_reason,
            "entry_time": str(self.entry_time),
            "exit_time": str(self.exit_time) if self.exit_time else None,
        }


@dataclass
class Wallet:
    """Test cuzdanı."""
    initial_balance: float
    balance: float = field(init=False)
    used_margin: float = 0.0
    total_fees: float = 0.0
    realized_pnl: float = 0.0
    trades: int = 0
    wins: int = 0
    losses: int = 0
    peak_equity: float = field(init=False)
    max_drawdown_pct: float = 0.0
    equity_curve: List[float] = field(default_factory=list)

    def __post_init__(self):
        self.balance = self.initial_balance
        self.peak_equity = self.initial_balance

    # ------------------------------------------------------------------
    @property
    def available_margin(self) -> float:
        return max(0.0, self.balance - self.used_margin)

    def unrealized(self, positions: List[Position]) -> float:
        return sum(p.unrealized_pnl for p in positions if p.status == PositionStatus.OPEN)

    def equity(self, positions: List[Position]) -> float:
        return self.balance + self.unrealized(positions)

    # ------------------------------------------------------------------
    def can_open(self, margin: float) -> bool:
        return self.available_margin >= margin * 0.999

    # NOT: bakiye guncellemeleri TradingEngine icinde, pozisyon
    # acilip kapandiginda yapilir (asagida open_position/close_position).

    def mark_equity(self, positions: List[Position]) -> None:
        eq = self.equity(positions)
        self.equity_curve.append(eq)
        if eq > self.peak_equity:
            self.peak_equity = eq
        if self.peak_equity > 0:
            dd = (self.peak_equity - eq) / self.peak_equity * 100.0
            self.max_drawdown_pct = max(self.max_drawdown_pct, dd)

    # ------------------------------------------------------------------
    def stats(self, positions: List[Position]) -> Dict[str, Any]:
        eq = self.equity(positions)
        win_rate = (self.wins / self.trades * 100.0) if self.trades else 0.0
        return {
            "initial": round(self.initial_balance, 2),
            "balance": round(self.balance, 2),
            "equity": round(eq, 2),
            "available": round(self.available_margin, 2),
            "used_margin": round(self.used_margin, 2),
            "unrealized": round(self.unrealized(positions), 2),
            "realized": round(self.realized_pnl, 2),
            "fees": round(self.total_fees, 2),
            "trades": self.trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": round(win_rate, 1),
            "roi": round((eq - self.initial_balance) / self.initial_balance * 100.0, 2),
            "max_dd": round(self.max_drawdown_pct, 2),
            "net": round(eq - self.initial_balance, 2),
        }


class TradingEngine:
    """Paper trading motoru."""

    def __init__(self, config: TRADING_CONFIG = None, balance: Optional[float] = None):
        # kopyala: paylasilan config uzerinde mutasyon olmasin
        self.config = replace(config) if config is not None else replace(TRADING_CONFIG)
        self.wallet = Wallet(balance if balance is not None
                             else self.config.initial_balance)
        self.open_positions: List[Position] = []
        self.closed_positions: List[Position] = []
        self.log: List[Dict[str, Any]] = []
        self.markers: List[Dict[str, Any]] = []   # grafik icin

    # ------------------------------------------------------------------
    def size_for(self, price: float, leverage: Optional[int] = None) -> float:
        """Kullanilabilir marjin ve kaldiracla pozisyon boyutu (BTC)."""
        lev = leverage or self.config.leverage
        usable = self.wallet.available_margin * self.config.max_position_pct
        notional = usable * lev
        qty = notional / price if price else 0.0
        prec = self.config.quantity_precision
        return round(qty / prec) * prec if qty >= prec else 0.0

    # ------------------------------------------------------------------
    def open_position(self, side: Side, price: float, timestamp: Any,
                      signal=None, leverage: Optional[int] = None) -> Optional[Position]:
        if len(self.open_positions) >= self.config.max_open_positions:
            logger.info("Pozisyon limiti dolu, yeni emir acilmadi")
            return None
        if any(p.side == side for p in self.open_positions):
            return None

        lev = leverage or self.config.leverage
        qty = self.size_for(price, lev)
        if qty <= 0:
            logger.info("Yeterli bakiye yok")
            return None

        notional = qty * price
        margin = notional / lev
        if not self.wallet.can_open(margin):
            logger.info("Marjin yetersiz (gerek %.2f, var %.2f)",
                        margin, self.wallet.available_margin)
            return None

        fee = notional * self.config.taker_fee

        if side == Side.LONG:
            sl = price * (1 - self.config.stop_loss_pct)
            tp = price * (1 + self.config.take_profit_pct)
        else:
            sl = price * (1 + self.config.stop_loss_pct)
            tp = price * (1 - self.config.take_profit_pct)

        # MA sayıları (Hareketli_Yeni algoritması için)
        ma_counts_entry = {}
        if signal and hasattr(signal, 'ma_counts'):
            ma_counts_entry = signal.ma_counts.copy()
        
        pos = Position(
            id="", side=side, entry_price=price, quantity=qty, leverage=lev,
            entry_time=timestamp, entry_fee=fee, margin=margin,
            stop_loss=sl, take_profit=tp,
            ma_counts_entry=ma_counts_entry,
        )

        self.wallet.balance -= fee
        self.wallet.total_fees += fee
        self.wallet.used_margin += margin
        self.open_positions.append(pos)

        self.log.append({
            "time": timestamp, "action": "GIRIS", "side": side.value,
            "price": price, "qty": qty, "margin": margin, "fee": fee,
            "sl": sl, "tp": tp,
            "signal": signal.signal.value if signal else None,
            "score": round(signal.composite, 3) if signal else None,
        })
        self.markers.append({
            "time": timestamp, "price": price, "side": side.value,
            "kind": "entry", "score": round(signal.composite, 3) if signal else None,
        })

        logger.info("%s giris @ %.2f | %s BTC | marjin %.2f",
                    side.value, price, qty, margin)
        return pos

    # ------------------------------------------------------------------
    def close_position(self, pos: Position, price: float, timestamp: Any,
                       reason: str = "sinyal", signal=None) -> bool:
        if pos not in self.open_positions:
            return False

        fee = pos.quantity * price * self.config.taker_fee
        
        # MA sayıları (Hareketli_Yeni algoritması için kapanış anında)
        ma_counts_exit = {}
        if signal and hasattr(signal, 'ma_counts'):
            ma_counts_exit = signal.ma_counts.copy()
        
        pos.close(price, timestamp, fee, reason)
        pos.ma_counts_exit = ma_counts_exit

        self.wallet.used_margin = max(0.0, self.wallet.used_margin - pos.margin)
        self.wallet.total_fees += fee
        # bakiyeye etki: giriş ücreti girişte düşüldü, burada brüt + cikis
        self.wallet.balance += pos.net_cash_change
        self.wallet.realized_pnl += pos.realized_pnl
        self.wallet.trades += 1
        if pos.realized_pnl > 0:
            self.wallet.wins += 1
        else:
            self.wallet.losses += 1

        self.open_positions.remove(pos)
        self.closed_positions.append(pos)

        self.log.append({
            "time": timestamp, "action": "CIKIS", "side": pos.side.value,
            "price": price, "pnl": pos.realized_pnl, "roi": pos.roi_pct,
            "reason": reason, "fee": fee,
        })
        self.markers.append({
            "time": timestamp, "price": price, "side": pos.side.value,
            "kind": "exit", "pnl": round(pos.realized_pnl, 2), "reason": reason,
        })

        logger.info("%s cikis @ %.2f | PnL %.2f (%.2f%%) | %s",
                    pos.side.value, price, pos.realized_pnl, pos.roi_pct, reason)
        return True

    def close_all(self, price: float, timestamp: Any, reason: str = "kapanis") -> None:
        for p in list(self.open_positions):
            self.close_position(p, price, timestamp, reason)

    # ------------------------------------------------------------------
    # POZISYON YONETIMI - oncelik sirasi
    # ------------------------------------------------------------------
    #   1) SL / TP        -> sert sinir, her zaman birincidir
    #   2) basaba tasima  -> kar +%X'e gelince SL girise cekilir
    #   3) kar kilidi     -> ROI hedefi asilirsa POZISYON KAPANIR (kar bankada)
    #   4) sinyal kapatma -> ters yon guclu sinyal, veya NOTR + pozisyon karda
    def manage_position(self, pos: Position, price: float, timestamp: Any,
                        high: float = None, low: float = None,
                        should_close_by_signal: bool = False,
                        signal_reason: str = "sinyal") -> Optional[str]:
        """Pozisyonu yonetir; kapandiysa kapanis sebebini dondurur."""
        if pos not in self.open_positions:
            return None

        hi = price if high is None else high
        lo = price if low is None else low
        cfg = self.config

        pos.update(price, cfg.taker_fee)

        # 1) SL / TP - mum ici fiyatlara bakilir
        if pos.side == Side.LONG:
            if hi >= pos.take_profit:
                self.close_position(pos, pos.take_profit, timestamp, "take-profit")
                return "take-profit"
            if lo <= pos.stop_loss:
                self.close_position(pos, pos.stop_loss, timestamp, "stop-loss")
                return "stop-loss"
        else:
            if lo <= pos.take_profit:
                self.close_position(pos, pos.take_profit, timestamp, "take-profit")
                return "take-profit"
            if hi >= pos.stop_loss:
                self.close_position(pos, pos.stop_loss, timestamp, "stop-loss")
                return "stop-loss"

        # 2) basaba tasima (kar +X%)
        if cfg.breakeven_enabled and cfg.breakeven_trigger_pct > 0:
            pos.update(price, cfg.taker_fee)
            if pos.roi_pct >= cfg.breakeven_trigger_pct * 100.0:
                pos.move_to_breakeven(price)
                # basaba tasindiktan sonra ayni barda SL'yi kontrol et
                if pos.side == Side.LONG and lo <= pos.stop_loss:
                    self.close_position(pos, pos.stop_loss, timestamp, "basaba-stop")
                    return "basaba-stop"
                if pos.side == Side.SHORT and hi >= pos.stop_loss:
                    self.close_position(pos, pos.stop_loss, timestamp, "basaba-stop")
                    return "basaba-stop"

        # 3) KAR KILIDI - kazanci bankaya yaz
        if cfg.profit_lock_enabled and cfg.profit_lock_pct > 0:
            pos.update(price, cfg.taker_fee)
            if pos.roi_pct >= cfg.profit_lock_pct * 100.0:
                self.close_position(pos, price, timestamp, "kar-kilidi")
                return "kar-kilidi"

        # 4) sinyal ile kapatma
        if should_close_by_signal:
            self.close_position(pos, price, timestamp, signal_reason or "sinyal")
            return signal_reason or "sinyal"

        return None

    # ------------------------------------------------------------------
    def mark_to_market(self, price: float) -> None:
        """Anlik PnL + SL/TP kontrolu."""
        for pos in list(self.open_positions):
            pos.update(price, self.config.taker_fee)

            if pos.hit_stop(price):
                self.close_position(pos, pos.stop_loss, None, "stop-loss")
            elif pos.hit_target(price):
                self.close_position(pos, pos.take_profit, None, "take-profit")
            elif self._is_liquidated(pos, price):
                self.close_position(pos, price, None, "likidasyon")

        self.wallet.mark_equity(self.open_positions)

    def _is_liquidated(self, pos: Position, price: float,
                       maintenance_margin_rate: float = 0.004) -> bool:
        """Basit likidasyon tahmini: marjin orani bakimas altina dustu."""
        if pos.notional <= 0:
            return False
        equity_in_pos = pos.margin + pos.gross_pnl(price)
        return (equity_in_pos / pos.notional) < maintenance_margin_rate

    # ------------------------------------------------------------------
    def summary(self) -> Dict[str, Any]:
        return {
            "wallet": self.wallet.stats(self.open_positions),
            "open": [p.to_dict() for p in self.open_positions],
            "closed_count": len(self.closed_positions),
        }

    def trades_df(self) -> pd.DataFrame:
        if not self.closed_positions:
            return pd.DataFrame()
        rows = [p.to_dict() for p in self.closed_positions]
        df = pd.DataFrame(rows)
        return df.sort_values("entry_time", ignore_index=True)

    def log_df(self) -> pd.DataFrame:
        return pd.DataFrame(self.log) if self.log else pd.DataFrame()
    
    def trades_df_with_ma_counts(self) -> pd.DataFrame:
        """İşlem geçmişi DataFrame'i (MA sayıları ile)."""
        if not self.closed_positions:
            return pd.DataFrame()
        rows = []
        for p in self.closed_positions:
            d = p.to_dict()
            # MA sayıları ekle (Hareketli_Yeni algoritması için)
            if hasattr(p, 'ma_counts_entry'):
                d['ma_al_entry'] = p.ma_counts_entry.get('buy', 0)
                d['ma_sat_entry'] = p.ma_counts_entry.get('sell', 0)
                d['ma_notr_entry'] = p.ma_counts_entry.get('neutral', 0)
            if hasattr(p, 'ma_counts_exit'):
                d['ma_al_exit'] = p.ma_counts_exit.get('buy', 0)
                d['ma_sat_exit'] = p.ma_counts_exit.get('sell', 0)
                d['ma_notr_exit'] = p.ma_counts_exit.get('neutral', 0)
            rows.append(d)
        df = pd.DataFrame(rows)
        return df.sort_values("entry_time", ignore_index=True)

    def reset(self, balance: Optional[float] = None) -> None:
        self.wallet = Wallet(balance if balance is not None
                             else self.config.initial_balance)
        self.open_positions.clear()
        self.closed_positions.clear()
        self.log.clear()
        self.markers.clear()
        logger.info("Motor sifirlandi")
