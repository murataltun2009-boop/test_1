# -*- coding: utf-8 -*-
"""TIK YOGUN MOD asama 2: kucuk tp-sl izegarasi.
Aday cekirdek: SOL 1m thmin=0 fill=0.4 (asama 1 winner).
BTC 5m: frekansi kaybetmeden pozitif tp/sl araniyor."""
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


def calistir(candles, tf, sym, tp, sl, tmin, fill):
    from core.paper import PaperTrader
    p = PaperTrader(sym)
    p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                wallet_fraction=0.8, mode="tk", risk_pct=0.03)
    p.tk_window = 60
    p.tk_theta_max = 0.85
    p.tk_theta_min = tmin
    p.tk_fill = fill
    p.tk_tp = tp
    p.tk_sl = sl
    p.running = True
    p.start_balance = 1000.0
    p.balance = 1000.0
    return p.backtest(candles, tf)


def tara(sym, tf, tmin, fill, tps, sls):
    mums = to_mum(fetch_rows(sym, tf, 1500))
    print(f"\n#### {sym} {tf} thmin={tmin} fill={fill} (3x500) ####")
    sat = []
    for tp in tps:
        for sl in sls:
            net = n = k = z = 0
            for wi in range(3):
                a = 1500 - (3 - wi) * 500
                bt = calistir(mums[a:a + 500], tf, sym, tp, sl, tmin, fill)
                net += bt["profit"]; n += bt["trades"]
                k += bt["wins"]; z += bt["losses"]
            sad = n / 3.0 * (288 if tf == "5m" else 1440) / 500
            sat.append((net, n, k, z, tp, sl, sad))
    for net, n, k, z, tp, sl, sad in sorted(
            sat, key=lambda r: r[0], reverse=True):
        print(f"  tp={tp*1000:>4.1f}% sl={sl*1000:>4.1f}%: {net:>+9.2f}$"
              f" islem {n:>3} (~{sad:>4.1f}/gun) K{k} Z{z}")


if __name__ == "__main__":
    tara("SOLUSDT", "1m", 0.0, 0.4,
         (0.001, 0.0015, 0.002, 0.003), (0.002, 0.003, 0.004))
    tara("BTCUSDT", "5m", 0.0, 0.3,
         (0.0008, 0.001, 0.0015, 0.002), (0.0015, 0.002, 0.003, 0.004))
    # BTC 5m icin fill(/thmin) adaptasyonu icin ksa bir kontrol
    for f in (0.35, 0.45):
        tara("BTCUSDT", "5m", 0.0, f,
             (0.0015, 0.002), (0.002, 0.003, 0.004))
