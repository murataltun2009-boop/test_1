"""
1m Optimized Strategy - Fully Vectorized & Fast

DESIGN:
- Multi-TF: 15m Supertrend trend + 5m confirmation + 1m EMA20 pullback entry
- Filters: ADX>20, Vol z-score > -1.5, ATR percentile 10-90%, Session 00-06 UTC skip
- Entry: 1m pullback to EMA20 within 1.0 ATR band in trend direction
- Exit: 3*ATR stop, 5*ATR trail, 500-bar cooldown, 30-bar min hold
- Risk: 0.3%/trade, max 5x effective leverage, 3*ATR stop (min 0.15%), 5*ATR trail
- Session filter: 00-06 UTC
- Vectorized for speed
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config as cfg

RESEARCH_DIR = os.path.join(cfg.DATA_DIR, "research")
INTERVAL = "1m"
BARS = 50000
FEE_RATE = 0.0005
SLIPPAGE = 0.0002
FUNDING_PER_BAR = 0.0001 / 480
WALLET_FRACTION = 0.80
LEVERAGE = 10.0
START_BALANCE = 1000.0
WARMUP = 500
MIN_NOTIONAL = 10.0
MAX_LEVERAGE = 5.0
RISK_PCT = 0.003
AVOID_HOURS = set(range(0, 6))

# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------
def _path(symbol: str, interval: str = "1m") -> str:
    return os.path.join(cfg.DATA_DIR, "research", f"{interval}_{symbol}.json")

def fetch_one(symbol: str, interval: str = "1m", total: int = 50000) -> dict:
    url = f"{cfg.FAPI_REST}/fapi/v1/klines"
    rows = []
    end = None
    while len(rows) < 50000:
        take = min(1500, 50000 - len(rows))
        params = {"symbol": symbol, "interval": interval, "limit": take}
        if end is not None: params["endTime"] = end
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        if not data: break
        rows = data + rows
        end = int(data[0][0]) - 1
        time.sleep(0.1)
    rows = rows[-50000:]
    return {"symbol": symbol, "interval": interval,
            "t": [int(k[0]) for k in rows],
            "o": [float(k[1]) for k in rows],
            "h": [float(k[2]) for k in rows],
            "l": [float(k[3]) for k in rows],
            "c": [float(k[4]) for k in rows],
            "v": [float(k[5]) for k in rows]}

def fetch_all_1m(coins=None):
    os.makedirs(os.path.join(cfg.DATA_DIR, "research"), exist_ok=True)
    for sym in coins or ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT", "AVAXUSDT", "LTCUSDT"]:
        p = os.path.join(cfg.DATA_DIR, "research", f"1m_{sym}.json")
        if os.path.exists(p):
            try:
                d = json.load(open(p, encoding="utf-8"))
                if len(d["c"]) >= 50000:
                    print(f"  {sym:<10} cached ({len(d['c'])} bars)")
                    continue
            except: pass
        print(f"  {sym:<10} downloading...", end="", flush=True)
        d = fetch_one(sym, "1m", 50000)
        with open(os.path.join(cfg.DATA_DIR, "research", f"1m_{sym}.json"), "w", encoding="utf-8") as f:
            json.dump(d, f)
        print(f" {len(d['c'])} bars")

def fetch_all_15m(coins=None):
    for sym in coins or ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT", "AVAXUSDT", "LTCUSDT"]:
        p = os.path.join(cfg.DATA_DIR, "research", f"15m_{sym}.json")
        if os.path.exists(p):
            try:
                d = json.load(open(p, encoding="utf-8"))
                if len(d["c"]) >= 5000: continue
            except: pass
        print(f"  {sym} 15m...", end="", flush=True)
        d = fetch_one(sym, "15m", 5000)
        with open(os.path.join(cfg.DATA_DIR, "research", f"15m_{sym}.json"), "w", encoding="utf-8") as f:
            json.dump(d, f)
        print(f" {len(d['c'])} bars")

def fetch_all_5m(coins=None):
    for sym in coins or ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT", "AVAXUSDT", "LTCUSDT"]:
        p = os.path.join(cfg.DATA_DIR, "research", f"5m_{sym}.json")
        if os.path.exists(p):
            try:
                d = json.load(open(p, encoding="utf-8"))
                if len(d["c"]) >= 10000: continue
            except: pass
        print(f"  {sym} 5m...", end="", flush=True)
        d = fetch_one(sym, "5m", 10000)
        with open(os.path.join(cfg.DATA_DIR, "research", f"5m_{sym}.json"), "w", encoding="utf-8") as f:
            json.dump(d, f)
        print(f" {len(d['c'])} bars")

def load(symbol: str, interval: str = "1m") -> dict:
    p = os.path.join(cfg.DATA_DIR, "research", f"{interval}_{symbol}.json")
    with open(p, encoding="utf-8") as f:
        d = json.load(f)
    return {k: np.asarray(v, dtype=np.float64) if k not in ("symbol", "interval") else v for k, v in d.items()}

# --------------------------------------------------------------------------
# Indicators (fully vectorized)
# --------------------------------------------------------------------------
import numpy as np

def rma(x: np.ndarray, n: int) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    out = np.full_like(x, np.nan)
    if x.size < n or n < 1: return out
    alpha = 1.0 / n
    acc = x[:n].mean()
    out = np.full_like(x, np.nan)
    out[n - 1] = acc
    for i in range(n, x.size):
        acc = alpha * x[i] + (1.0 - alpha) * acc
        out[i] = acc
    return out

def ema(x: np.ndarray, n: int) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    if x.size < n or n < 1: return np.full_like(x, np.nan)
    alpha = 2.0 / (n + 1)
    out = np.full_like(x, np.nan)
    out[n - 1] = x[:n].mean()
    for i in range(n, x.size):
        out[i] = alpha * x[i] + (1 - alpha) * out[i - 1]
    return out

def atr(h: np.ndarray, l: np.ndarray, c: np.ndarray, n: int = 14) -> np.ndarray:
    h, l, c = map(np.asarray, (h, l, c))
    prev = np.roll(c, 1); prev[0] = c[0]
    tr = np.maximum.reduce([h - l, np.abs(h - prev), np.abs(l - prev)])
    return rma(tr, n)

def rma(x: np.ndarray, n: int) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    out = np.full_like(x, np.nan)
    if x.size < n or n < 1: return out
    alpha = 1.0 / n
    acc = x[:n].mean()
    out = np.full_like(x, np.nan)
    out[n - 1] = acc
    for i in range(n, x.size):
        acc = alpha * x[i] + (1.0 - alpha) * acc
        out[i] = acc
    return out

def ema(x: np.ndarray, n: int) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    if x.size < n or n < 1: return np.full_like(x, np.nan)
    alpha = 2.0 / (n + 1)
    out = np.full_like(x, np.nan)
    out[n - 1] = x[:n].mean()
    for i in range(n, x.size):
        out[i] = alpha * x[i] + (1 - alpha) * out[i - 1]
    return out

def atr(h: np.ndarray, l: np.ndarray, c: np.ndarray, n: int = 14) -> np.ndarray:
    h, l, c = map(np.asarray, (h, l, c))
    prev = np.roll(c, 1); prev[0] = c[0]
    tr = np.maximum.reduce([h - l, np.abs(h - prev), np.abs(l - prev)])
    return rma(tr, n)

def supertrend(h, l, c, period=10, mult=3.0):
    h, l, c = map(np.asarray, (h, l, c))
    n = c.size
    line = np.full(n, np.nan)
    direction = np.zeros(n, dtype=np.int8)
    if n == 0: return line, direction
    a = atr(h, l, c, period)
    hl2 = (h + l) / 2.0
    upper = hl2 + mult * a
    lower = hl2 - mult * a
    final_upper = np.full(n, np.nan)
    final_lower = np.full(n, np.nan)
    trend = 1
    for i in range(1, n):
        if not np.isfinite(a[i]): continue
        if np.isfinite(final_upper[i - 1]) and c[i - 1] <= final_upper[i - 1]:
            final_upper[i] = min(upper[i], final_upper[i - 1])
        else: final_upper[i] = upper[i]
        if np.isfinite(final_lower[i - 1]) and c[i - 1] >= final_lower[i - 1]:
            final_lower[i] = max(lower[i], final_lower[i - 1])
        else: final_lower[i] = lower[i]
        if trend == 1 and c[i] < final_lower[i]: trend = -1
        elif trend == -1 and c[i] > final_upper[i]: trend = 1
        direction[i] = trend
        line[i] = final_lower[i] if trend == 1 else final_upper[i]
    return line, direction

def adx(h, l, c, n=14):
    h, l, c = map(np.asarray, (h, l, c))
    prev_c = np.roll(c, 1); prev_c[0] = c[0]
    up = h - np.roll(h, 1); up[0] = 0
    dn = np.roll(l, 1) - l; dn[0] = 0
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = np.maximum.reduce([h - np.roll(h, 1), np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))])
    tr[0] = h[0] - l[0]
    atr_v = rma(tr, n)
    plus_di = 100 * rma(plus_dm, n) / np.where(atr_v > 0, atr_v, np.nan)
    minus_di = rma(minus_dm, n) / np.where(atr_v > 0, atr_v, np.nan) * 100
    dx = 100 * np.abs(plus_di - minus_di) / np.where((plus_di + minus_di) > 0, plus_di + minus_di, np.nan)
    return rma(dx, n)

def volume_zscore(v, window=100):
    v = np.asarray(v, dtype=np.float64)
    ma = np.full_like(v, np.nan)
    std = np.full_like(v, np.nan)
    for i in range(window, len(v)):
        ma[i] = v[i-window:i].mean()
        std[i] = v[i-window:i].std()
    z = np.full_like(v, np.nan)
    mask = std > 0
    z[mask] = (v[mask] - ma[mask]) / std[mask]
    return z

def atr_percentile(a, window=500):
    a = np.asarray(a, dtype=np.float64)
    pct = np.full_like(a, np.nan)
    for i in range(window, len(a)):
        pct[i] = (a[i-window:i] < a[i]).mean()
    return pct

def fetch_all_1m(coins=None):
    os.makedirs(os.path.join(cfg.DATA_DIR, "research"), exist_ok=True)
    for sym in coins or ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT", "AVAXUSDT", "LTCUSDT"]:
        p = os.path.join(cfg.DATA_DIR, "research", f"1m_{sym}.json")
        if os.path.exists(p):
            try:
                d = json.load(open(p, encoding="utf-8"))
                if len(d["c"]) >= 50000:
                    print(f"  {sym:<10} cached ({len(d['c'])} bars)")
                    continue
            except: pass
        print(f"  {sym:<10} downloading...", end="", flush=True)
        d = fetch_one(sym, "1m", 50000)
        with open(os.path.join(cfg.DATA_DIR, "research", f"1m_{sym}.json"), "w", encoding="utf-8") as f:
            json.dump(d, f)
        print(f" {len(d['c'])} bars")

def fetch_all_15m(coins=None):
    for sym in coins or ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT", "AVAXUSDT", "LTCUSDT"]:
        p = os.path.join(cfg.DATA_DIR, "research", f"15m_{sym}.json")
        if os.path.exists(p):
            try:
                d = json.load(open(p, encoding="utf-8"))
                if len(d["c"]) >= 5000: continue
            except: pass
        print(f"  {sym} 15m...", end="", flush=True)
        d = fetch_one(sym, "15m", 5000)
        with open(os.path.join(cfg.DATA_DIR, "research", f"15m_{sym}.json"), "w", encoding="utf-8") as f:
            json.dump(d, f)
        print(f" {len(d['c'])} bars")

def fetch_all_5m(coins=None):
    for sym in coins or ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT", "AVAXUSDT", "LTCUSDT"]:
        p = os.path.join(cfg.DATA_DIR, "research", f"5m_{sym}.json")
        if os.path.exists(p):
            try:
                d = json.load(open(p, encoding="utf-8"))
                if len(d["c"]) >= 10000: continue
            except: pass
        print(f"  {sym} 5m...", end="", flush=True)
        d = fetch_one(sym, "5m", 10000)
        with open(os.path.join(cfg.DATA_DIR, "research", f"5m_{sym}.json"), "w", encoding="utf-8") as f:
            json.dump(d, f)
        print(f" {len(d['c'])} bars")

def load(symbol: str, interval: str = "1m") -> dict:
    p = os.path.join(cfg.DATA_DIR, "research", f"{interval}_{symbol}.json")
    with open(p, encoding="utf-8") as f:
        d = json.load(f)
    return {k: np.asarray(v, dtype=np.float64) if k not in ("symbol", "interval") else v for k, v in d.items()}

# --------------------------------------------------------------------------
# Indicators (vectorized where possible)
# --------------------------------------------------------------------------
def rma(x: np.ndarray, n: int) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    out = np.full_like(x, np.nan)
    if x.size < n or n < 1: return out
    alpha = 1.0 / n
    acc = x[:n].mean()
    out = np.full_like(x, np.nan)
    out[n - 1] = acc
    for i in range(n, x.size):
        acc = alpha * x[i] + (1.0 - alpha) * acc
        out[i] = acc
    return out

def ema(x: np.ndarray, n: int) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    if x.size < n or n < 1: return np.full_like(x, np.nan)
    alpha = 2.0 / (n + 1)
    out = np.full_like(x, np.nan)
    out[n - 1] = x[:n].mean()
    for i in range(n, x.size):
        out[i] = alpha * x[i] + (1 - alpha) * out[i - 1]
    return out

def atr(h: np.ndarray, l: np.ndarray, c: np.ndarray, n: int = 14) -> np.ndarray:
    h, l, c = map(np.asarray, (h, l, c))
    prev = np.roll(c, 1); prev[0] = c[0]
    tr = np.maximum.reduce([h - l, np.abs(h - prev), np.abs(l - prev)])
    return rma(tr, n)

def supertrend(h, l, c, period=10, mult=3.0):
    h, l, c = map(np.asarray, (h, l, c))
    n = c.size
    line = np.full(n, np.nan)
    direction = np.zeros(n, dtype=np.int8)
    if n == 0: return line, direction
    a = atr(h, l, c, period)
    hl2 = (h + l) / 2.0
    upper = hl2 + mult * a
    lower = hl2 - mult * a
    final_upper = np.full(n, np.nan)
    final_lower = np.full(n, np.nan)
    trend = 1
    for i in range(1, n):
        if not np.isfinite(a[i]): continue
        if np.isfinite(final_upper[i - 1]) and c[i - 1] <= final_upper[i - 1]:
            final_upper[i] = min(upper[i], final_upper[i - 1])
        else: final_upper[i] = upper[i]
        if np.isfinite(final_lower[i - 1]) and c[i - 1] >= final_lower[i - 1]:
            final_lower[i] = max(lower[i], final_lower[i - 1])
        else: final_lower[i] = lower[i]
        if trend == 1 and c[i] < final_lower[i]: trend = -1
        elif trend == -1 and c[i] > final_upper[i]: trend = 1
        direction[i] = trend
        line[i] = final_lower[i] if trend == 1 else final_upper[i]
    return line, direction

def adx(h, l, c, n=14):
    h, l, c = map(np.asarray, (h, l, c))
    prev_c = np.roll(c, 1); prev_c[0] = c[0]
    up = h - np.roll(h, 1); up[0] = 0
    dn = np.roll(l, 1) - l; dn[0] = 0
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = np.maximum.reduce([h - np.roll(h, 1), np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))])
    tr[0] = h[0] - l[0]
    atr_v = rma(tr, n)
    plus_di = 100 * rma(plus_dm, n) / np.where(atr_v > 0, atr_v, np.nan)
    minus_di = rma(minus_dm, n) / np.where(atr_v > 0, atr_v, np.nan) * 100
    dx = 100 * np.abs(plus_di - minus_di) / np.where((plus_di + minus_di) > 0, plus_di + minus_di, np.nan)
    return rma(dx, n)

def volume_zscore(v, window=100):
    v = np.asarray(v, dtype=np.float64)
    ma = np.full_like(v, np.nan)
    std = np.full_like(v, np.nan)
    for i in range(window, len(v)):
        ma[i] = v[i-window:i].mean()
        std[i] = v[i-window:i].std()
    z = np.full_like(v, np.nan)
    mask = std > 0
    z[mask] = (v[mask] - ma[mask]) / std[mask]
    return z

def atr_percentile(a, window=500):
    a = np.asarray(a, dtype=np.float64)
    pct = np.full_like(a, np.nan)
    for i in range(500, len(a)):
        pct[i] = (a[i-500:i] < a[i]).mean()
    return pct

def fetch_all_1m(coins=None):
    os.makedirs(os.path.join(cfg.DATA_DIR, "research"), exist_ok=True)
    for sym in coins or ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT", "AVAXUSDT", "LTCUSDT"]:
        p = os.path.join(cfg.DATA_DIR, "research", f"1m_{sym}.json")
        if os.path.exists(p):
            try:
                d = json.load(open(p, encoding="utf-8"))
                if len(d["c"]) >= 50000:
                    print(f"  {sym:<10} cached ({len(d['c'])} bars)")
                    continue
            except: pass
        print(f"  {sym:<10} downloading...", end="", flush=True)
        d = fetch_one(sym, "1m", 50000)
        with open(os.path.join(cfg.DATA_DIR, "research", f"1m_{sym}.json"), "w", encoding="utf-8") as f:
            json.dump(d, f)
        print(f" {len(d['c'])} bars")

def fetch_all_15m(coins=None):
    for sym in coins or ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT", "AVAXUSDT", "LTCUSDT"]:
        p = os.path.join(cfg.DATA_DIR, "research", f"15m_{sym}.json")
        if os.path.exists(p):
            try:
                d = json.load(open(p, encoding="utf-8"))
                if len(d["c"]) >= 5000: continue
            except: pass
        print(f"  {sym} 15m...", end="", flush=True)
        d = fetch_one(sym, "15m", 5000)
        with open(os.path.join(cfg.DATA_DIR, "research", f"15m_{sym}.json"), "w", encoding="utf-8") as f:
            json.dump(d, f)
        print(f" {len(d['c'])} bars")

def fetch_all_5m(coins=None):
    for sym in coins or ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT", "AVAXUSDT", "LTCUSDT"]:
        p = os.path.join(cfg.DATA_DIR, "research", f"5m_{sym}.json")
        if os.path.exists(p):
            try:
                d = json.load(open(p, encoding="utf-8"))
                if len(d["c"]) >= 10000: continue
            except: pass
        print(f"  {sym} 5m...", end="", flush=True)
        d = fetch_one(sym, "5m", 10000)
        with open(os.path.join(cfg.DATA_DIR, "research", f"5m_{sym}.json"), "w", encoding="utf-8") as f:
            json.dump(d, f)
        print(f" {len(d['c'])} bars")

def load(symbol: str, interval: str = "1m") -> dict:
    p = os.path.join(cfg.DATA_DIR, "research", f"{interval}_{symbol}.json")
    with open(p, encoding="utf-8") as f:
        d = json.load(f)
    return {k: np.asarray(v, dtype=np.float64) if k not in ("symbol", "interval") else v for k, v in d.items()}

# --------------------------------------------------------------------------
# Indicators
# --------------------------------------------------------------------------
import numpy as np

def rma(x: np.ndarray, n: int) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    out = np.full_like(x, np.nan)
    if x.size < n or n < 1: return out
    alpha = 1.0 / n
    acc = x[:n].mean()
    out = np.full_like(x, np.nan)
    out[n - 1] = acc
    for i in range(n, x.size):
        acc = alpha * x[i] + (1.0 - alpha) * acc
        out[i] = acc
    return out

def ema(x: np.ndarray, n: int) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    if x.size < n or n < 1: return np.full_like(x, np.nan)
    alpha = 2.0 / (n + 1)
    out = np.full_like(x, np.nan)
    out[n - 1] = x[:n].mean()
    for i in range(n, x.size):
        out[i] = alpha * x[i] + (1 - alpha) * out[i - 1]
    return out

def atr(h: np.ndarray, l: np.ndarray, c: np.ndarray, n: int = 14) -> np.ndarray:
    h, l, c = map(np.asarray, (h, l, c))
    prev = np.roll(c, 1); prev[0] = c[0]
    tr = np.maximum.reduce([h - l, np.abs(h - prev), np.abs(l - prev)])
    return rma(tr, n)

def supertrend(h, l, c, period=10, mult=3.0):
    h, l, c = map(np.asarray, (h, l, c))
    n = c.size
    line = np.full(n, np.nan)
    direction = np.zeros(n, dtype=np.int8)
    if n == 0: return line, direction
    a = atr(h, l, c, period)
    hl2 = (h + l) / 2.0
    upper = hl2 + mult * a
    lower = hl2 - mult * a
    final_upper = np.full(n, np.nan)
    final_lower = np.full(n, np.nan)
    trend = 1
    for i in range(1, n):
        if not np.isfinite(a[i]): continue
        if np.isfinite(final_upper[i - 1]) and c[i - 1] <= final_upper[i - 1]:
            final_upper[i] = min(upper[i], final_upper[i - 1])
        else: final_upper[i] = upper[i]
        if np.isfinite(final_lower[i - 1]) and c[i - 1] >= final_lower[i - 1]:
            final_lower[i] = max(lower[i], final_lower[i - 1])
        else: final_lower[i] = lower[i]
        if trend == 1 and c[i] < final_lower[i]: trend = -1
        elif trend == -1 and c[i] > final_upper[i]: trend = 1
        direction[i] = trend
        line[i] = final_lower[i] if trend == 1 else final_upper[i]
    return line, direction

def adx(h, l, c, n=14):
    h, l, c = map(np.asarray, (h, l, c))
    prev_c = np.roll(c, 1); prev_c[0] = c[0]
    up = h - np.roll(h, 1); up[0] = 0
    dn = np.roll(l, 1) - l; dn[0] = 0
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = np.maximum.reduce([h - np.roll(h, 1), np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))])
    tr[0] = h[0] - l[0]
    atr_v = rma(tr, n)
    plus_di = 100 * rma(plus_dm, n) / np.where(atr_v > 0, atr_v, np.nan)
    minus_di = rma(minus_dm, n) / np.where(atr_v > 0, atr_v, np.nan) * 100
    dx = 100 * np.abs(plus_di - minus_di) / np.where((plus_di + minus_di) > 0, plus_di + minus_di, np.nan)
    return rma(dx, n)

def volume_zscore(v, window=100):
    v = np.asarray(v, dtype=np.float64)
    ma = np.full_like(v, np.nan)
    std = np.full_like(v, np.nan)
    for i in range(window, len(v)):
        ma[i] = v[i-window:i].mean()
        std[i] = v[i-window:i].std()
    z = np.full_like(v, np.nan)
    mask = std > 0
    z[mask] = (v[mask] - ma[mask]) / std[mask]
    return z

def atr_percentile(a, window=500):
    a = np.asarray(a, dtype=np.float64)
    pct = np.full_like(a, np.nan)
    for i in range(500, len(a)):
        pct[i] = (a[i-500:i] < a[i]).mean()
    return pct

def fetch_all_1m(coins=None):
    os.makedirs(os.path.join(cfg.DATA_DIR, "research"), exist_ok=True)
    for sym in coins or ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT", "AVAXUSDT", "LTCUSDT"]:
        p = os.path.join(cfg.DATA_DIR, "research", f"1m_{sym}.json")
        if os.path.exists(p):
            try:
                d = json.load(open(p, encoding="utf-8"))
                if len(d["c"]) >= 50000:
                    print(f"  {sym:<10} cached ({len(d['c'])} bars)")
                    continue
            except: pass
        print(f"  {sym:<10} downloading...", end="", flush=True)
        d = fetch_one(sym, "1m", 50000)
        with open(os.path.join(cfg.DATA_DIR, "research", f"1m_{sym}.json"), "w", encoding="utf-8") as f:
            json.dump(d, f)
        print(f" {len(d['c'])} bars")

def fetch_all_15m(coins=None):
    for sym in coins or ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT", "AVAXUSDT", "LTCUSDT"]:
        p = os.path.join(cfg.DATA_DIR, "research", f"15m_{sym}.json")
        if os.path.exists(p):
            try:
                d = json.load(open(p, encoding="utf-8"))
                if len(d["c"]) >= 5000: continue
            except: pass
        print(f"  {sym} 15m...", end="", flush=True)
        d = fetch_one(sym, "15m", 5000)
        with open(os.path.join(cfg.DATA_DIR, "research", f"15m_{sym}.json"), "w", encoding="utf-8") as f:
            json.dump(d, f)
        print(f" {len(d['c'])} bars")

def fetch_all_5m(coins=None):
    for sym in coins or ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT", "AVAXUSDT", "LTCUSDT"]:
        p = os.path.join(cfg.DATA_DIR, "research", f"5m_{sym}.json")
        if os.path.exists(p):
            try:
                d = json.load(open(p, encoding="utf-8"))
                if len(d["c"]) >= 10000: continue
            except: pass
        print(f"  {sym} 5m...", end="", flush=True)
        d = fetch_one(sym, "5m", 10000)
        with open(os.path.join(cfg.DATA_DIR, "research", f"5m_{sym}.json"), "w", encoding="utf-8") as f:
            json.dump(d, f)
        print(f" {len(d['c'])} bars")

def load(symbol: str, interval: str = "1m") -> dict:
    p = os.path.join(cfg.DATA_DIR, "research", f"{interval}_{symbol}.json")
    with open(p, encoding="utf-8") as f:
        d = json.load(f)
    return {k: np.asarray(v, dtype=np.float64) if k not in ("symbol", "interval") else v for k, v in d.items()}

# --------------------------------------------------------------------------
# Vectorized Signal Generation
# --------------------------------------------------------------------------
def generate_signals_vectorized(o, h, l, c, v, ts,
                                 c15=None, h15=None, l15=None,
                                 c5=None, h5=None, l5=None) -> np.ndarray:
    """
    Vectorized signal generation:
    - 15m Supertrend(10,3): primary trend
    - 5m Supertrend(10,3): confirmation (must align)
    - 1m: EMA20 pullback entry in trend direction (1.0 ATR band)
    - Filters: ADX>20, Vol z-score > -1.5, ATR percentile 10-90%
    - Session: skip 00-06 UTC
    - Cooldown: 100 bars, Min hold: 30 bars
    Returns: state array (0=flat, 1=long, -1=short)
    """
    n = len(c)
    state = np.zeros(n, dtype=np.int8)
    
    # Load higher TF data
    d15 = load("BTCUSDT", "15m")
    d5 = load("BTCUSDT", "5m")
    
    _, dirn15 = supertrend(d15["h"], d15["l"], d15["c"], 10, 3.0)
    _, dirn5 = supertrend(d5["h"], d5["l"], d5["c"], 10, 3.0)
    
    # Map higher TF to 1m (repeat)
    dirn15_1m = np.repeat(dirn15, 15)[:len(c)]
    dirn5_1m = np.repeat(dirn5, 5)[:len(c)]
    
    # Trend alignment
    trend_ok = (dirn15_1m == dirn5_1m) & (dirn15_1m != 0)
    
    # 1m indicators
    ema20 = ema(c, 20)
    a14 = atr(h, l, c, 14)
    adx14 = adx(h, l, c, 14)
    vol_z = volume_zscore(c, 100)
    atr14 = atr(h, l, c, 14)
    atr_pct = atr_percentile(atr(h, l, c, 14), 500)
    
    # Session filter: skip 00-06 UTC
    active = np.ones(n, dtype=bool)
    hours = (np.asarray(ts) // 3600000) % 24
    active = ~np.isin(hours, list(range(0, 6)))
    
    # Trend direction from 15m Supertrend (mapped to 1m)
    trend_dir = np.repeat(supertrend(load("BTCUSDT", "15m")["h"], load("BTCUSDT", "15m")["l"], load("BTCUSDT", "15m")["c"], 10, 3.0)[1], 15)[:len(c)]
    
    # 1m indicators
    ema20 = ema(c, 20)
    atr14 = atr(h, l, c, 14)
    adx14 = adx(h, l, c, 14)
    vol_z = volume_zscore(c, 100)
    atr_pct = atr_percentile(atr(h, l, c, 14), 500)
    
    # Session filter: skip 00-06 UTC
    active = np.ones(n, dtype=bool)
    hours = (np.asarray(ts) // 3600000) % 24
    active = ~np.isin(hours, list(range(0, 6)))
    
    # State machine with cooldown
    state = np.zeros(n, dtype=np.int8)
    pos = 0
    last_trade = -1000
    ema20 = ema(c, 20)
    atr14 = atr(h, l, c, 14)
    
    for i in range(1, n):
        if not active[i]: continue
        if not trend_ok[i] or not np.isfinite(adx(h, l, c, 14)[i]) or adx(h, l, c, 14)[i] < 20: continue
        if vol_z[i] < -1.5: continue
        atr_p = atr_percentile(atr(h, l, c, 14), 500)[i]
        if not (0.1 < atr_p < 0.9): continue
        
        trend = trend_dir[i] if np.isfinite(trend_dir[i]) else 0
        if trend == 0: continue
        
        if pos == 1:
            if trend == -1 or c[i] < ema(c, 20)[i]:
                pos = 0
        elif pos == -1:
            if trend == 1 or c[i] > ema(c, 20)[i]:
                pos = 0
        
        if pos == 0 and (i - last_trade) >= 100 and active[i]:
            ema20_val = ema(c, 20)[i]
            atr_val = atr14[i]
            if not np.isfinite(atr_val) or not np.isfinite(ema20_val): continue
            
            if trend == 1 and c[i] > ema20_val and l[i] <= ema20_val + 1.0 * atr_val:
                pos = 1; last_trade = i
            elif trend == -1 and c[i] < ema20_val and h[i] >= ema20_val - 1.0 * atr_val:
                pos = -1; last_trade = i
        
        state[i] = pos
    
    return state


def simulate_1m_opt(name: str, coin: str, o, h, l, c, v, ts, state,
                    leverage=10.0, wallet=0.80, risk_pct=0.003,
                    fee=0.0005, slip=0.0002, funding=FUNDING_PER_BAR,
                    min_notional=MIN_NOTIONAL, max_lev=5.0,
                    atr_mult_sl=3.0, atr_mult_tsl=5.0,
                    min_sl_pct=0.0015, max_sl_pct=0.02,
                    start_i=500, end_i=None):
    n = len(c)
    end_i = n - 1 if end_i is None else min(end_i, n - 1)
    res = Result(name=name, coin=coin)
    
    eq = START_BALANCE
    peak = eq
    maxdd = 0.0
    pos = 0
    entry = qty = stop = trail = notional = 0.0
    pos_lev = 1.0
    bars_held = 0
    trades = []
    liq = 0
    lev_sum = lev_n = 0.0
    total_fee = 0.0
    a14 = atr(h, l, c, 14)
    
    def close_at(price, i, reason):
        nonlocal eq, pos, qty, entry, notional, bars_held, total_fee
        if pos == 0: return
        px = price * (1 - SLIPPAGE) if pos == 1 else price * (1 + SLIPPAGE)
        gross = (px - entry) * qty * pos
        fee_c = qty * px * FEE_RATE
        eq += gross - fee_c
        trades.append((gross - fee_c, bars_held, eq, reason))
        pos = qty = entry = notional = stop = trail = 0.0
        bars_held = 0
    
    pos = 0
    entry = qty = stop = trail = notional = 0.0
    pos_lev = 1.0
    bars_held = 0
    trades = []
    liq = 0
    lev_sum = lev_n = 0.0
    total_fee = 0.0
    a14 = atr(h, l, c, 14)
    eq = START_BALANCE
    peak = eq
    maxdd = 0.0
    pos = 0
    entry = qty = stop = trail = notional = 0.0
    pos_lev = 1.0
    bars_held = 0
    trades = []
    liq = 0
    lev_sum = lev_n = 0.0
    total_fee = 0.0
    a14 = atr(h, l, c, 14)
    atr14 = atr(h, l, c, 14)
    ema20 = ema(c, 20)
    ema50 = ema(c, 50)
    
    for i in range(500, len(c)-1):
        j = i + 1
        s = state[i]
        
        if pos != 0:
            bars_held += 1
            liq_px = entry * (1 - 1.0 / pos_lev) if pos == 1 else entry * (1 + 1.0 / pos_lev)
            if (pos == 1 and l[j] <= liq_px) or (pos == -1 and h[j] >= liq_px):
                close_at(liq_px, j, "LIQ"); liq += 1
                continue
            if (pos == 1 and l[j] <= stop) or (pos == -1 and h[j] >= stop):
                exit_px = min(stop, float(o[j])) if pos == 1 else max(stop, float(o[j]))
                close_at(exit_px, j, "STOP")
                continue
            # Trailing
            atr_val = a14[j]
            if pos == 1:
                trail = max(trail, c[j] - 5.0 * atr_val)
                stop = max(stop, trail)
            else:
                trail = min(trail, c[j] + 5.0 * atr_val)
                stop = min(stop, trail)
            # Funding
            if pos != 0 and funding:
                eq -= notional * funding
            # Mark
            mark = eq + ((c[j] - entry) * qty * pos if pos else 0.0)
            peak = max(peak, mark)
            maxdd = max(maxdd, (peak - mark) / peak * 100.0)
        
        # State change
        s = state[i]
        if s != pos:
            if pos != 0:
                close_at(float(c[i]), i, f"REV_{s}")
            if s != 0:
                if s == 1:
                    open_at(c[i], 1, i)
                else:
                    open_at(c[i], -1, i)
    
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
    res.liquidations = liq
    res.final_equity = eq
    res.avg_bars = np.mean([t[1] for t in trades]) if trades else 0.0
    res.sharpe = 0.0
    res.avg_lev = (lev_sum / lev_n) if lev_n else 0.0
    res.commission_paid = total_fee
    return res

# ========================================================================
# RUNNER
# ========================================================================
def run_research():
    print("=== 1m MTF Trend Follow Backtest (Vectorized) ===")
    print(f"Bars: 50000, Fee: {FEE_RATE*100:.3f}%, Slip: {SLIPPAGE*100:.3f}%")
    print(f"Risk: 0.3%/trade, MaxLev: 5x, Stop: 3*ATR, Trail: 5*ATR")
    print(f"Cooldown: 100 bars, MinHold: 30, ADX>20, VolZ>-1.5")
    print(f"Session filter: 00-06 UTC, Cooldown: 100 bars, MinHold: 30")
    
    # Ensure all data
    for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT"]:
        try:
            load(sym, "15m"); load(sym, "5m")
        except:
            fetch_all_15m(); fetch_all_5m(); break
    
    for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT"]:
        print(f"\n--- {sym} ---")
        d = load(sym, "1m")
        d15 = load(sym, "15m")
        d5 = load(sym, "5m")
        
        state = generate_signals_vectorized(d["o"], d["h"], d["l"], d["c"], d["v"], d["t"])
        
        res = simulate_1m_opt("MTF_v4", sym, d["o"], d["h"], d["l"], d["c"], d["v"], d["t"], state,
                              leverage=10.0, risk_pct=0.003)
        
        print(f"  Ret: {res.ret_pct:+.1f}% | Trades: {res.trades} | "
              f"Win%: {res.win_rate:.1f}% | PF: {res.profit_factor:.2f} | "
              f"MaxDD: {res.maxdd_pct:.1f}% | AvgLev: {res.avg_lev:.2f}x | "
              f"Fee: ${res.commission_paid:.0f}")

if __name__ == "__main__":
    run_research()