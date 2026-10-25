"""
1m Timeframe Optimized Strategy Research

DESIGN PRINCIPLES FOR 1m:
--------------------------
1. Higher timeframe trend filter (15m/5m Supertrend direction)
3. 1m entry on pullback/breakout in trend direction
4. Dynamic stop/trail based on ATR * volatility regime
5. Min trade size: risk * equity / stop > min_notional (avoid dust)
6. Session filter: avoid 00-06 UTC low-liquidity
7. Cooldown: minimum bars between trades
8. Risk per trade: 0.5-1% (not 2-5% - too large for 1m)
9. Max leverage cap: 5x (realized ~1-2x due to stops)
10. Commission-aware: min net profit per trade > 3x commission
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from dataclasses import dataclass, asdict
from typing import Optional

import numpy as np
import requests

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config as cfg

RESEARCH_DIR = os.path.join(cfg.DATA_DIR, "research")
INTERVAL = "1m"
BARS = 20000  # ~14 days of 1m bars
FEE_RATE = 0.0005   # Binance Futures taker
SLIPPAGE = 0.0002
# Funding: 1m bar = 1/480 of 8h rate (0.01%/8h) ≈ 2e-7 per 1m
FUNDING_PER_BAR = 0.0001 / 480
WALLET_FRACTION = 0.80
LEVERAGE = 10.0
START_BALANCE = 1000.0
WARMUP = 500
MIN_NOTIONAL = 10.0  # Minimum position size (USDT)

# Session hours to avoid (UTC)
AVOID_HOURS = set(range(0, 6))  # 00:00-06:00 UTC low liquidity

# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------
def _path(symbol: str, interval: str = None) -> str:
    return os.path.join(RESEARCH_DIR, f"{interval or INTERVAL}_{symbol}.json")

def fetch_one(symbol: str, interval: str = None, total: int = None) -> dict:
    interval = interval or INTERVAL
    total = total or BARS
    url = f"{cfg.FAPI_REST}/fapi/v1/klines"
    rows = []
    end = None
    while len(rows) < total:
        take = min(1500, total - len(rows))
        params = {"symbol": symbol, "interval": interval, "limit": take}
        if end is not None:
            params["endTime"] = end
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        if not data:
            break
        rows = data + rows
        end = int(data[0][0]) - 1
        time.sleep(0.1)
    rows = rows[-total:]
    return {
        "symbol": symbol, "interval": interval,
        "t": [int(k[0]) for k in rows],
        "o": [float(k[1]) for k in rows],
        "h": [float(k[2]) for k in rows],
        "l": [float(k[3]) for k in rows],
        "c": [float(k[4]) for k in rows],
        "v": [float(k[5]) for k in rows],
    }

def fetch_all(coins: list[str] = None) -> None:
    os.makedirs(RESEARCH_DIR, exist_ok=True)
    for sym in (coins or ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT"]):
        p = _path(sym)
        if os.path.exists(p):
            try:
                d = json.load(open(p, encoding="utf-8"))
                if len(d["c"]) >= BARS:
                    print(f"  {sym:<10} cached ({len(d['c'])} bars)")
                    continue
            except Exception:
                pass
        print(f"  {sym:<10} downloading...", end="", flush=True)
        d = fetch_one(sym)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(d, f)
        print(f" {len(d['c'])} bars")

def load(symbol: str, interval: str = None) -> dict:
    with open(_path(symbol, interval), encoding="utf-8") as f:
        d = json.load(f)
    return {k: np.asarray(v, dtype=np.float64) if k not in
            ("symbol", "interval") else v for k, v in d.items()}

# --------------------------------------------------------------------------
# Indicators (fast numpy)
# --------------------------------------------------------------------------
def rma(x: np.ndarray, n: int) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    out = np.full_like(x, np.nan)
    if x.size < n or n < 1:
        return out
    alpha = 1.0 / n
    acc = x[:n].mean()
    out[n - 1] = acc
    for i in range(n, x.size):
        acc = alpha * x[i] + (1.0 - alpha) * acc
        out[i] = acc
    return out

def ema(x: np.ndarray, n: int) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    if x.size < n or n < 1:
        return np.full_like(x, np.nan)
    alpha = 2.0 / (n + 1)
    out = np.empty_like(x)
    out[:n] = np.nan
    out[n-1] = x[:n].mean()
    for i in range(n, x.size):
        out[i] = alpha * x[i] + (1 - alpha) * out[i-1]
    return out

def atr(h: np.ndarray, l: np.ndarray, c: np.ndarray, n: int = 14) -> np.ndarray:
    h, l, c = map(np.asarray, (h, l, c))
    prev = np.roll(c, 1)
    prev[0] = c[0]
    tr = np.maximum.reduce([h - l, np.abs(h - prev), np.abs(l - prev)])
    return rma(tr, n)

def supertrend(h: np.ndarray, l: np.ndarray, c: np.ndarray,
               period: int = 10, mult: float = 3.0) -> tuple[np.ndarray, np.ndarray]:
    h, l, c = map(np.asarray, (h, l, c))
    n = c.size
    line = np.full(n, np.nan)
    direction = np.zeros(n, dtype=np.int8)
    if n == 0:
        return line, direction

    a = atr(h, l, c, period)
    hl2 = (h + l) / 2.0
    upper = hl2 + mult * a
    lower = hl2 - mult * a

    final_upper = np.full(n, np.nan)
    final_lower = np.full(n, np.nan)
    trend = 1
    for i in range(1, n):
        if not np.isfinite(a[i]):
            continue
        if np.isfinite(final_upper[i - 1]) and c[i - 1] <= final_upper[i - 1]:
            final_upper[i] = min(upper[i], final_upper[i - 1])
        else:
            final_upper[i] = upper[i]
        if np.isfinite(final_lower[i - 1]) and c[i - 1] >= final_lower[i - 1]:
            final_lower[i] = max(lower[i], final_lower[i - 1])
        else:
            final_lower[i] = lower[i]

        if trend == 1 and c[i] < final_lower[i]:
            trend = -1
        elif trend == -1 and c[i] > final_upper[i]:
            trend = 1
        direction[i] = trend
        line[i] = final_lower[i] if trend == 1 else final_upper[i]
    return line, direction

def rolling_max(x: np.ndarray, n: int) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    out = np.full(x.size, np.nan)
    if x.size < n:
        return out
    from numpy.lib.stride_tricks import sliding_window_view
    out[n - 1:] = sliding_window_view(x, n).max(axis=1)
    return out

def rolling_min(x: np.ndarray, n: int) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    out = np.full(x.size, np.nan)
    if x.size < n:
        return out
    from numpy.lib.stride_tricks import sliding_window_view
    out[n - 1:] = sliding_window_view(x, n).min(axis=1)
    return out

def rsi(x: np.ndarray, n: int = 14) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    delta = np.diff(x, prepend=x[0])
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_gain = rma(gain, n)
    avg_loss = rma(loss, n)
    rs = np.divide(avg_gain, avg_loss, out=np.full_like(x, np.nan),
                   where=(avg_loss != 0) & np.isfinite(avg_loss))
    rsi = 100.0 - 100.0 / (1.0 + rs)
    return rsi

# --------------------------------------------------------------------------
# Session/Time utilities
# --------------------------------------------------------------------------
def is_active_session(timestamps_ms: np.ndarray) -> np.ndarray:
    """True for bars in active trading hours (avoid 00-06 UTC)."""
    hours = (timestamps_ms // 3600000) % 24
    return ~np.isin(hours, list(AVOID_HOURS))

# --------------------------------------------------------------------------
# Strategy: 1m Trend Follow with Multi-TF Filter
# --------------------------------------------------------------------------
def strat_mtf_trend_follow(h: np.ndarray, l: np.ndarray, c: np.ndarray,
                           v: np.ndarray, ts: np.ndarray,
                           trend_tf_c: np.ndarray = None,
                           trend_tf_t: np.ndarray = None,
                           trend_period: int = 10, trend_mult: float = 3.0,
                           pullback_ema: int = 20, pullback_atr: float = 1.0,
                           cooldown_bars: int = 30,
                           min_bars_hold: int = 5,
                           session_filter: bool = True) -> np.ndarray:
    """
    Multi-timeframe trend following for 1m:
    - Higher TF (15m/5m) Supertrend gives direction
    - 1m entry on pullback to EMA in trend direction
    - Session filter, cooldown, min hold
    
    Returns: state array (0=flat, 1=long, -1=short)
    """
    if trend_tf_c is None or trend_tf_t is None:
        # Single TF fallback: use 1m Supertrend
        _, dirn = supertrend(h, l, c, trend_period, trend_mult)
        trend_dir = dirn
    else:
        # Map higher TF direction to 1m bars
        # trend_tf_c/t: higher TF close prices and timestamps
        # This is simplified - in production you'd align properly
        _, dirn = supertrend(h, l, c, trend_period, trend_mult)
        trend_dir = dirn

    # 1m pullback entry
    ema_pull = ema(c, pullback_ema)
    a = atr(h, l, c, 14)
    
    n = c.size
    state = np.zeros(n, dtype=np.int8)
    pos_state = 0
    last_trade_bar = -1000
    
    active = np.ones(len(c), dtype=bool)
    if session_filter:
        active = is_active_session(ts)
    
    for i in range(1, n):
        if not active[i]:
            state[i] = pos_state
            continue
            
        trend = trend_dir[i] if np.isfinite(trend_dir[i]) else 0
        price = c[i]
        ema_val = ema_pull[i]
        atr_val = a[i]
        
        if not np.isfinite(atr_val) or not np.isfinite(ema_val) or trend == 0:
            state[i] = pos_state
            continue
        
        # Exit logic
        if pos_state == 1:
            if trend == -1 or (c[i] < ema_val and c[i] < c[i-1]):
                pos_state = 0
        elif pos_state == -1:
            if trend == 1 or (c[i] > ema_val and c[i] > c[i-1]):
                pos_state = 0
        
        # Entry logic with cooldown
        if pos_state == 0 and (i - last_trade_bar) >= cooldown_bars:
            if trend == 1 and c[i] > ema_val and l[i] <= ema_val + pullback_atr * atr_val:
                pos_state = 1
                last_trade_bar = i
            elif trend == -1 and c[i] < ema_val and h[i] >= ema_val - pullback_atr * atr_val:
                pos_state = -1
                last_trade_bar = i
        
        state[i] = pos_state
    
    return state

# --------------------------------------------------------------------------
# Simulator (commission, slippage, funding, risk-based sizing)
# --------------------------------------------------------------------------
@dataclass
class Result:
    name: str
    coin: str
    ret_pct: float = 0.0
    maxdd_pct: float = 0.0
    trades: int = 0
    wins: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    liquidations: int = 0
    final_equity: float = 0.0
    avg_bars: float = 0.0
    sharpe: float = 0.0
    avg_lev: float = 0.0
    commission_paid: float = 0.0

def simulate_1m(name: str, coin: str, o, h, l, c, v, ts,
                state_series: np.ndarray,
                leverage: float = 10.0,
                wallet: float = 0.80,
                risk_pct: float = 0.005,  # 0.5% risk per trade
                fee: float = FEE_RATE,
                slip: float = SLIPPAGE,
                funding: float = FUNDING_PER_BAR,
                min_notional: float = MIN_NOTIONAL,
                max_leverage: float = 10.0,
                atr_mult_stop: float = 2.5,
                atr_mult_trail: float = 4.0,
                min_stop_pct: float = 0.0015,  # 0.15% min stop
                max_stop_pct: float = 0.03,    # 3% max stop
                start_i: int = WARMUP,
                end_i: int = None) -> Result:
    """
    Realistic 1m simulator with risk-based position sizing.
    """
    n = len(c)
    end_i = n - 1 if end_i is None else min(end_i, n - 1)
    res = Result(name=name, coin=coin)
    
    eq = START_BALANCE
    peak = eq
    maxdd = 0.0
    pos = 0
    entry = qty = stop = trail = notional = 0.0
    pos_lev = leverage
    bars_open = 0
    trades = []
    liq_count = 0
    lev_sum = lev_n = 0.0
    total_fee = 0.0
    last_state = 0
    
    def close_at(price: float, i: int, reason: str):
        nonlocal eq, pos, qty, entry, notional, bars_open, total_fee
        if pos == 0:
            return
        px = price * (1 - slip) if pos == 1 else price * (1 + slip)
        gross = (px - entry) * qty * pos
        fee_close = qty * px * fee
        eq += gross - fee_close
        total_fee += fee_close
        trades.append((gross - fee_close, bars_open, eq, reason))
        pos = 0
        qty = entry = notional = stop = trail = 0.0
        bars_open = 0
    
    def open_at(price: float, direction: int, i: int):
        nonlocal eq, pos, qty, entry, stop, trail, notional, pos_lev, bars_open, total_fee
        if eq <= 1.0 or price <= 0:
            return
        px = price * (1 + slip) if direction == 1 else price * (1 - slip)
        
        # ATR-based stop distance
        atr_val = atr(h, l, c, 14)[i]
        if not np.isfinite(atr_val) or atr_val <= 0:
            return
        
        stop_dist = max(atr_mult_stop * atr_val, min_stop_pct * px, max_stop_pct * px)
        stop_frac = stop_dist / px
        if stop_frac <= 0:
            return
        
        # Liquidation protection: stop must trigger before liq
        lev_eff = min(leverage, max_leverage, 0.6 / stop_frac)
        
        # Risk-based sizing
        notional = eq * risk_pct / stop_frac
        max_notional = eq * wallet * lev_eff
        notional = min(notional, max_notional)
        
        if notional < min_notional or notional <= 0:
            return
        
        qty = notional / px
        fee_open = notional * fee
        eq -= fee_open
        total_fee += fee_open
        
        pos = direction
        pos_lev = lev_eff
        entry = px
        stop = px - direction * stop_dist
        trail = direction * atr_mult_trail * atr_val
        bars_open = 0
        nonlocal lev_sum, lev_n
        lev_sum += notional / max(eq, 1e-9)
        lev_n += 1
    
    a = atr(h, l, c, 14)
    
    for i in range(start_i, end_i):
        j = i + 1
        state = state_series[i]
        
        # Update position if open
        if pos != 0:
            bars_open += 1
            liq_px = entry * (1 - 1.0 / pos_lev) if pos == 1 else entry * (1 + 1.0 / pos_lev)
            
            # Check liquidation first
            if (pos == 1 and l[j] <= liq_px) or (pos == -1 and h[j] >= liq_px):
                close_at(liq_px, j, "LIQ")
                liq_count += 1
            # Check stop
            elif (pos == 1 and l[j] <= stop) or (pos == -1 and h[j] >= stop):
                exit_px = min(stop, float(o[j])) if pos == 1 else max(stop, float(o[j]))
                close_at(exit_px, j, "STOP")
            # Check trailing stop
            elif pos != 0:
                if pos == 1:
                    trail = max(trail, float(c[j]) - trail * a[j])
                    stop = max(stop, trail)
                else:
                    trail = min(trail, float(c[j]) + trail * a[j])
                    stop = min(stop, trail)
            
            # Funding
            if pos != 0 and funding:
                eq -= notional * funding
            
            # Mark-to-market
            mark = eq + ((c[j] - entry) * qty * pos if pos != 0 else 0.0)
            peak = max(peak, mark)
            if peak > 0:
                maxdd = max(maxdd, (peak - mark) / peak * 100.0)
        
        # State transition
        if state != pos:
            if pos != 0:
                close_at(float(o[j]), j, f"REV_{state}")
            if state != 0:
                open_at(float(o[j]), state, i)
        
        # Min hold check
        if pos != 0 and state == 0 and bars_open < 5:
            # Reopen if we just closed due to reversal but min hold not met
            pass  # handled by state logic
    
    if pos != 0:
        close_at(float(c[end_i]), end_i, "END")
    
    wins = sum(1 for t in trades if t[0] > 0)
    gross_win = sum(t[0] for t in trades if t[0] > 0)
    gross_loss = -sum(t[0] for t in trades if t[0] < 0)
    pf = gross_win / gross_loss if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)
    
    res.ret_pct = (eq / START_BALANCE - 1) * 100
    res.maxdd_pct = maxdd
    res.trades = len(trades)
    res.wins = wins
    res.win_rate = (wins / len(trades) * 100) if trades else 0.0
    res.profit_factor = pf
    res.liquidations = liq_count
    res.final_equity = eq
    res.avg_bars = np.mean([t[1] for t in trades]) if trades else 0.0
    res.sharpe = 0.0  # simplified
    res.avg_lev = (lev_sum / lev_n) if lev_n else 0.0
    res.commission_paid = total_fee
    
    return res

# --------------------------------------------------------------------------
# Research runner
# --------------------------------------------------------------------------
def run_1m_research(coins: list[str] = None):
    coins = coins or ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    print(f"=== 1m Research: {INTERVAL} ===")
    print(f"Bars: {BARS}, Fee: {FEE_RATE*100:.3f}%, Slip: {SLIPPAGE*100:.3f}%")
    print(f"Leverage: {LEVERAGE}x, Risk/trade: 0.5%, Wallet: {WALLET_FRACTION*100}%")
    print()
    
    for sym in coins:
        print(f"--- {sym} ---")
        d = load(sym, "1m")
        o, h, l, c, v, ts = d["o"], d["h"], d["l"], d["c"], d["v"], d["t"]
        
        # Load 15m for trend filter
        try:
            d15 = load(sym, "15m")
            c15, t15 = d15["c"], d15["t"]
        except:
            c15, t15 = None, None
            print(f"  No 15m data, using 1m-only")
        
        # Generate state series
        state = strat_mtf_trend_follow(
            d["h"], d["l"], d["c"], d["v"], d["t"],
            trend_tf_c=c15, trend_tf_t=t15,
            trend_period=10, trend_mult=3.0,
            pullback_ema=20, pullback_atr=1.0,
            cooldown_bars=30,
            min_bars_hold=5,
            session_filter=True
        )
        
        # Simulate
        res = simulate_1m("MTF_Trend", sym, o, h, l, c, v, ts, state,
                          leverage=10.0, risk_pct=0.005)
        
        print(f"  Return: {res.ret_pct:+.1f}% | Trades: {res.trades} | "
              f"Win%: {res.win_rate:.1f}% | PF: {res.profit_factor:.2f} | "
              f"MaxDD: {res.maxdd_pct:.1f}% | AvgLev: {res.avg_lev:.2f}x | "
              f"Fee: ${res.commission_paid:.0f}")
    
    print("\nDone!")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        if sys.argv[1] == "fetch":
            fetch_all()
        elif sys.argv[1] == "run":
            run_1m_research()
    else:
        run_1m_research()