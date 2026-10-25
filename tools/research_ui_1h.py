# -*- coding: utf-8 -*-
"""
UI GERIYE DÖNÜK TEpariturak leastim YOLUNUN birebir çoğaltması:
  * taze Binance verisi (cache KULLANMADAN)
  * 500 bar (UIministra CANDLE_LIMIT) vs 1500 bar (araştırma penceresi)
  * production config defaultları (düzeltici AÇIK) + düzeltici kapalı
Calistirma: python tools/research_ui_1h.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as cfg
from core.paper import PaperTrader


def fetch_top(symbol, interval, limit=500):
    """Uretim client'i ile tam olarak sunun cekildigi kadar mum."""
    from core.binance_client import BinanceClient
    cli = BinanceClient() if hasattr(BinanceClient, "__init__") else None
    cli = BinanceClient.__new__(BinanceClient)
    import requests
    url = f"{cfg.FAPI_REST}/fapi/v1/klines"
    r = requests.get(url, params={"symbol": symbol, "interval": interval,
                                  "limit": limit}, timeout=20)
    r.raise_for_status()
    rows = r.json()
    from core.binance_client import candle_from_payload
    out = []
    for row in rows:
        c = candle_from_payload(row)
        c.closed = True
        out.append(c)
    return out


def to_candles(rows):
    from core.binance_client import candle_from_payload
    out = []
    for r in rows:
        c = candle_from_payload(r)
        c.closed = True
        out.append(c)
    return out


import requests


def fetch_rows(symbol, interval, limit=500):
    url = f"{cfg.FAPI_REST}/fapi/v1/klines"
    r = requests.get(url, params={"symbol": symbol, "interval": interval,
                                  "limit": limit}, timeout=20)
    r.raise_for_status()
    return r.json()


def to_mum(rows):
    from core.binance_client import candle_from_payload
    out = []
    for row in rows:
        c = candle_from_payload(row)
        c.closed = True
        out.append(c)
    return out


def backtest_bt(candles, tf, mode, corr=True):
    p = PaperTrader(cfg.Settings())
    p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                wallet_fraction=0.8, mode=mode, risk_pct=0.03)
    p.running = True
    p.start_balance = 1000.0
    p.balance = 1000.0
    p.corr_on = corr
    p.corr_arm_on = corr
    p.corr_strong_only = corr
    p.corr_strong_first = corr
    bt = p.backtest(candles, tf)
    return bt, p


def main():
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        for limit in (500, 1500):
            rows = fetch_rows(sym, "1h", limit)
            mums = to_mum(rows)
            tf = "1h"
            ilk = mums[0].open_time / 1000
            son = mums[-1].open_time / 1000
            import datetime
            bas = datetime.datetime.fromtimestamp(ilk, datetime.timezone.utc)
            bit = datetime.datetime.fromtimestamp(son, datetime.timezone.utc)
            for corr in (True, False):
                bt, p = backtest_bt(mums, tf, "ma_only", corr)
                print(f"{sym} 1h x{limit} [{bas:%d.%m}..{bit:%d.%m}] "
                      f"corr={'ACIK' if corr else 'KAPALI'}: "
                      f"{bt['profit']:>+9.2f}$ ({bt['return_pct']:+.1f}%) "
                      f"islem {bt['trades']} K{bt['wins']} Z{bt['losses']}")
            # corr acik olan son seride cikis sebepleri
            bt, p = backtest_bt(mums, tf, "ma_only", True)
            from collections import defaultdict
            seb = defaultdict(lambda: [0, 0.0])
            for t in p.trades:
                seb[t.exit_reason[:28]][0] += 1
                seb[t.exit_reason[:28]][1] += t.net_pnl
            for k, (n, net) in sorted(seb.items(), key=lambda kv: kv[1][1])[:5]:
                print(f"      {k:<30} {n:>4} islem {net:>+9.1f}$")


if __name__ == "__main__":
    main()
