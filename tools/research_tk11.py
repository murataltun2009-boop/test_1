# -*- coding: utf-8 -*-
"""TIK seсim rehberi - bugunun taze verisi, PRODüksiyon hook (configure).
ADR: ERA/ENA/HBAR/ADA/UNI 1m + BTC 5m. 4x500 pencere, su anki zaman.
"""
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


from core.binance_client import candle_from_payload

HEDEF = [("HBARUSDT", "1m"), ("ERAUSDT", "1m"), ("ENAUSDT", "1m"),
         ("ADAUSDT", "1m"), ("UNIUSDT", "1m"), ("BTCUSDT", "5m")]

for sym, tf in HEDEF:
    try:
        mums = []
        for row in fetch_rows(sym, tf, 2000):
            c = candle_from_payload(row)
            c.closed = True
            mums.append(c)
    except Exception as e:
        print(sym, "veri yok:", e)
        continue
    n = len(mums)
    topl = 0.0
    poz = 0
    islem = 0
    print(f"\n#### {sym} {tf} (uretim hook; 4x500) ####")
    for wi in range(4):
        a = n - (4 - wi) * 500
        p = PaperTrader = None
        from core.paper import PaperTrader
        p = PaperTrader(sym)
        p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                    wallet_fraction=0.8, mode="tk", risk_pct=0.03)
        p.tk_window = 60
        p.running = True
        p.start_balance = 1000.0
        p.balance = 1000.0
        bt = p.backtest(mums[a:a + 500], tf)
        # DURUST METRIK: sadece KAPANMIS islemler. Ucta acik kalan
        # pozisyonun hayali karini alma (ENA p1'de +580$ artifact
        # yaratti: 0 islem, acik LONG unrealized).
        kapali = sum(t.net_pnl for t in p.trades)
        acik_kaldi = p.position is not None
        topl += kapali; islem += bt["trades"]
        if kapali > 0:
            poz += 1
        bas = datetime.datetime.fromtimestamp(
            mums[a].open_time / 1000, datetime.timezone.utc)
        bayrak = " [ACIK POZ KAOSTI]" if acik_kaldi else ""
        print(f"  pencere {wi+1} [{bas:%d.%m %H:%M}] {kapali:>+9.2f}$"
              f" islem {len(p.trades):>2} (bt raporu {bt['profit']:+.2f})"
              f"{bayrak}")
    print(f"  TOPLAM {sym}: {topl:+.2f}$  islem {islem}  "
          f"pozitif-pencere {poz}/4")
