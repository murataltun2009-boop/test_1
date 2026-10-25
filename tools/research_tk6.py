# -*- coding: utf-8 -*-
"""
TIK modu COIN TARAMASI: uygulamanin 36 coin listesinin TAMAMI,
uretim hook parametreleriyle (configure(mode='tk')), 3x500 (1m).
Hedef: kullaniciya OLCULMIS kullanilabilir coin listesi vermek.
Calistirma: python tools/research_tk6.py
"""
from __future__ import annotations

import os
import sys
import datetime

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


def main():
    sonuclar = []
    for sym in cfg.SYMBOLS:
        try:
            mums = to_mum(fetch_rows(sym, "1m", 1500))
        except Exception as e:                       # noqa: BLE001
            print(f"{sym}: VERI YOK ({e})")
            sonuclar.append((sym, None, None, None, None, None))
            continue
        net = n = k = z = 0
        dil_aralik = None
        for wi in range(3):
            a = 1500 - (3 - wi) * 500
            dil = mums[a:a + 500]
            from core.paper import PaperTrader
            p = PaperTrader(sym)
            p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                        wallet_fraction=0.8, mode="tk", risk_pct=0.03)
            p.tk_window = 60
            p.running = True
            p.start_balance = 1000.0
            p.balance = 1000.0
            bt = p.backtest(dil, "1m")
            net += bt["profit"]; n += bt["trades"]
            k += bt["wins"]; z += bt["losses"]
            b = datetime.datetime.fromtimestamp(
                dil[0].open_time / 1000, datetime.timezone.utc)
            if dil_aralik is None or b < dil_aralik[0]:
                dil_aralik = (b, None)
        sonuclar.append((sym, net, n, k, z, dil_aralik[0]))
        print(f"{sym:<14} {net:>+9.2f}$ islem {n:>3} K{k} Z{z} "
              f"(hook: tp={p.tk_tp*1000:.0f}%. sl={p.tk_sl*1000:.0f}%)")

    print("\n===== OLCUMLU SIRALAMA (1m, yoğun hook, 3x500) =====")
    olan = [r for r in sonuclar if r[1] is not None]
    for sym, net, n, k, z, bas in sorted(olan, key=lambda r: r[1],
                                         reverse=True):
        print(f"  {sym:<14} {net:>+9.2f}$ islem {n:>3} K{k} Z{z}")


if __name__ == "__main__":
    main()
