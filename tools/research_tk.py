# -*- coding: utf-8 -*-
"""
TICK (super-hizli limit scalper) parametre taramasi — TAZE veri.
  * mod "tk": fib altin-cebe pasif limit giris (maker), TP resting
    limit (maker), stop-market SL (taker).
  * tarama: tp x sl x pause (corr) kombinasyonlari.
  * notional 8000$ (1000$ x %80 x 10x) ile TP %0.2 ~ +12.8$ net,
    SL %0.3 ~ -28$; breakeven WR ~ %65.

Calistirma: python tools/research_tk.py
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


def calistir(candles, tf, tp, sl):
    from core.paper import PaperTrader
    p = PaperTrader(cfg.Settings())
    p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                wallet_fraction=0.8, mode="tk", risk_pct=0.03)
    p.running = True
    p.start_balance = 1000.0
    p.balance = 1000.0
    p.tk_on = True
    p.tk_tp = tp
    p.tk_sl = sl
    bt = p.backtest(candles, tf)
    return bt, p


def show(bt, p):
    seb = {}
    for t in p.trades:
        k = t.exit_reason[:22]
        a, n = seb.get(k, (0, 0.0))
        seb[k] = (a + 1, n + t.net_pnl)
    for k, (n, net) in sorted(seb.items(), key=lambda kv: -kv[1][0])[:3]:
        print(f"        {k:<24} {n:>4} islem {net:>+9.1f}$")


def main():
    PY, PX = (0.001, 0.002, 0.003), (0.002, 0.003, 0.005)
    TF_LIMIT = {"1m": 1500, "5m": 1500, "15m": 1500, "1h": 1500}
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        for tf, limit in TF_LIMIT.items():
            try:
                mums = to_mum(fetch_rows(sym, tf, limit))
            except Exception as e:                       # noqa: BLE001
                print(f"{sym} {tf}: veri hatasi {e}")
                continue
            print(f"\n#### {sym} {tf} x{len(mums)} ####")
            en = None
            for tp in PY:
                for sl in PX:
                    bt, p = calistir(mums, tf, tp, sl)
                    net = bt["profit"]
                    satir = (f"tp={tp*1000:.0f}%. sl={sl*1000:.0f}%: "
                             f"{net:>+9.2f}$ islem {bt['trades']:>3} "
                             f"K{bt['wins']} Z{bt['losses']}")
                    print("  " + satir)
                    if en is None or net > en[0]:
                        en = (net, tp, sl, bt, p)
            if en and en[4] is not None:
                net, tp, sl, bt, p = en
                if bt["trades"] > 0:
                    print(f"  >> EN IYI tp={tp*1000:.0f}% sl={sl*1000:.0f}% "
                          f"{net:+.2f}$")
                    show(bt, p)


if __name__ == "__main__":
    main()
