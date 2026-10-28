# -*- coding: utf-8 -*-
"""
TK yildiz-kurali OLCUMU (2026-10-28 kural: yesil->LONG, kirmizi->SHORT,
gri->TERS; ac/kapa LIMIT; TP kapali SL koruyucu).
DOGE 1m ana hedef + digerleri karsilastirma. 6x500 pencere.
Calistirma: python tools/research_tk14.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests

import config as cfg


def fetch_rows(symbol, interval, total):
    url = f"{cfg.FAPI_REST}/fapi/v1/klines"
    out = []
    end = None
    while len(out) < total:
        take = min(1500, total - len(out))
        params = {"symbol": symbol, "interval": interval, "limit": take}
        if end is not None:
            params["endTime"] = end
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
        rows = r.json()
        if not rows:
            break
        out = rows + out
        end = rows[0][0] - 1
    return out


def to_mum(rows):
    from core.binance_client import candle_from_payload
    out = []
    for row in rows:
        c = candle_from_payload(row)
        c.closed = True
        out.append(c)
    return out


from core.paper import PaperTrader

COINS = ["DOGEUSDT", "HBARUSDT", "UNIUSDT", "BTCUSDT", "ETHUSDT",
         "ENAUSDT", "ADAUSDT"]

for sym in COINS:
    try:
        mums = to_mum(fetch_rows(sym, "1m", 3000))
    except Exception as e:                       # noqa: BLE001
        print(sym, "veri yok:", e)
        continue
    n = len(mums)
    tpl = 0.0
    poz = 0
    n_is = 0
    print(f"\n#### {sym} 1m x{n} (TK yildiz kurali) ####")
    for wi in range(6):
        a = n - (6 - wi) * 500
        if a < 200:
            continue
        p = PaperTrader(sym)
        p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                    wallet_fraction=0.8, mode="tk", risk_pct=0.03)
        p.tk_window = 60
        p.running = True
        p.start_balance = 1000.0
        p.balance = 1000.0
        bt = p.backtest(mums[a:a + 500], "1m")
        kapali = sum(t.net_pnl for t in p.trades)
        kp = sum(1 for t in p.trades if t.net_pnl >= 0)
        kz = len(p.trades) - kp
        weights = {}
        for t in p.trades:
            k = "stop" if "stop" in t.exit_reason else \
                "flip" if "flip" in t.exit_reason else "adapter"
            w, m = weights.get(k, (0, 0.0))
            weights[k] = (w + 1, m + t.net_pnl)
        det = " ".join(f"{k}{w}/{m:+.0f}" for k, (w, m) in weights.items())
        tpl += kapali
        n_is += len(p.trades)
        if kapali > 0:
            poz += 1
        print(f"  pencere {wi+1} {kapali:>+9.2f}$ islem {len(p.trades):>3} "
              f"K{kp} Z{kz} | {det}")
    print(f"  TOPLAM {sym}: {tpl:+.2f}$  islem {n_is}  poz-pencere {poz}/6")
