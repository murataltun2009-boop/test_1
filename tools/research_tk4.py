# -*- coding: utf-8 -*-
"""
TIK YOGUN MOD taramasi — kullanici hedefi: SIK islem + az az kazanc.
Aşama 1: frekans eksenleri (theta_min gevset, fill shalt) @ tp2/sl3.
Aşama 2: en iyi frekans noktasinda kucuk tp-sl izegarasi.
Hedef metrik: islem/gun + toplam net (+ belki WR).
Calistirma: python tools/research_tk4.py
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


BARS_GUN = {"5m": 288, "1m": 1440, "15m": 96}


def calistir(candles, tf, sym, tp, sl, tmin, fill):
    from core.paper import PaperTrader
    p = PaperTrader(sym)
    p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                wallet_fraction=0.8, mode="tk", risk_pct=0.03)
    p.tk_window = 60
    p.tk_theta_max = 0.85          # yogun mod: ust sinir gevsek
    p.tk_theta_min = tmin
    p.tk_fill = fill
    p.tk_tp = tp
    p.tk_sl = sl
    p.running = True
    p.start_balance = 1000.0
    p.balance = 1000.0
    bt = p.backtest(candles, tf)
    return bt


def main():
    par = [("BTCUSDT", "5m"), ("SOLUSDT", "1m")]
    cach = {}
    for sym, tf in par:
        cach[(sym, tf)] = to_mum(fetch_rows(sym, tf, 1500))

    tp, sl = 0.002, 0.003
    print("### ASAMA 1: frekans eksenleri (tp=%0.1f%% sl=%0.1f%%)" %
          (tp * 100, sl * 100))
    gun = None
    for sym, tf in par:
        mums = cach[(sym, tf)]
        gun = BARS_GUN[tf] / 3.0        # her pencere ~gun
        print(f"\n#### {sym} {tf} (3x500) ####")
        sat = []
        for tmin in (0.44, 0.30, 0.20, 0.0):
            for fill in (0.55, 0.40, 0.30):
                net = n = k = z = 0
                for wi in range(3):
                    a = 1500 - (3 - wi) * 500
                    bt = calistir(mums[a:a + 500], tf, sym, tp, sl,
                                  tmin, fill)
                    net += bt["profit"]; n += bt["trades"]
                    k += bt["wins"]; z += bt["losses"]
                sad = n / 3.0 * BARS_GUN[tf] / 500
                sat.append((net, n, k, z, tmin, fill, sad))
        for net, n, k, z, tmin, fill, sad in sorted(
                sat, key=lambda r: r[0], reverse=True):
            print(f"  thmin={tmin:<4} fill={fill:<4}: {net:>+9.2f}$"
                  f" islem {n:>3} (~{sad:>4.1f}/gun) K{k} Z{z}")


if __name__ == "__main__":
    main()
