# -*- coding: utf-8 -*-
"""
TK 5. tur: VOLATILITE-DUYARLI stop + risk-BE + zaman stopu — 2026-11-01.

Canli IK deseni (23 islem, 4K/19Z, -140$): butun kayiplar tam %0,30
stop — sabit stop 1m gurultusi genisligi icinde kalir, giris stop-avi
oluyor. Eski sequel (streak/level) onceden olculdu; bu tarama stopin
kendisini konusur:

  * SL_ATR: stop = max(SL, ATR14 * kat)
  * BE_RISK: acik kar >= kat * stop-mesafesi -> stop girise cekilir
  * TIME_BARS: islem K bar sonuca ulasamadiysa market ile kapanir

Sabit: pullback -0.05, db 0.05, cf2, REQ, bp3.5, rr1.8, pause3, f0.5,
streak 2/10, level 0.002/15.
Calistirma: python tools/research_tk21.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import research_tk16 as r
from core.paper import PaperTrader

# (etiket, sl_atr, be_risk, time_bars)
VARIANTS = [
    ("A taban (sabit %0.3)", 0.0, 0.0, 0),
    ("B atr2.0", 2.0, 0.0, 0),
    ("C atr2.5", 2.5, 0.0, 0),
    ("D atr3.0", 3.0, 0.0, 0),
    ("E atr2.0 + be0.9", 2.0, 0.9, 0),
    ("F atr2.0 + be0.6", 2.0, 0.6, 0),
    ("G atr2.5 + be0.9", 2.5, 0.9, 0),
    ("H atr2.0 be0.9 t45", 2.0, 0.9, 45),
    ("I atr2.5 be0.9 t45", 2.5, 0.9, 45),
    ("J atr2.0 be0.9 t30", 2.0, 0.9, 30),
]


def olc(data, nwin, etiket, atr, ber, tb):
    tpl = 0.0
    n = 0
    k = 0
    z = 0
    km = 0.0
    zm = 0.0
    worst = 0.0
    per = {}
    for sym, mums in data.items():
        N = len(mums)
        sp = 0.0
        for wi in range(nwin):
            a = N - (nwin - wi) * 500
            if a < 200:
                continue
            p = PaperTrader(sym)
            p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                        wallet_fraction=0.8, mode="tk", risk_pct=0.03)
            p.tk_sl_atr = atr
            p.tk_be_risk = ber
            p.tk_time_bars = tb
            p.running = True
            p.start_balance = 1000.0
            p.balance = 1000.0
            p.backtest(mums[a:a + 500], "1m")
            w = sum(t.net_pnl for t in p.trades)
            sp += w
            tpl += w
            worst = min(worst, w)
            n += len(p.trades)
            for t in p.trades:
                if t.net_pnl >= 0:
                    k += 1
                    km += t.net_pnl
                else:
                    z += 1
                    zm += t.net_pnl
        per[sym] = sp
    print(f"{etiket:<22} {tpl:>+7.0f}$ islem {n:>4} K{k}/Z{z} "
          f"(%{100*k/max(1,k+z):.0f}) ort {tpl/max(1,n):+.2f}$ "
          f"kaz {km/max(1,k):+.1f}/kay {zm/max(1,z):+.1f} "
          f"en-kotu {worst:+.0f}$")
    print("   " + " ".join(f"{s[:4]}{v:+.0f}" for s, v in per.items()))


if __name__ == "__main__":
    rows = {}
    for sym in r.COINS:
        try:
            rows[sym] = r.fetch_rows(sym, "1m", 4500)
        except Exception as e:                    # noqa: BLE001
            print(sym, "veri yok:", e)
    d8 = {s: r.to_mum(v) for s, v in rows.items()}
    d6 = {s: r.to_mum(v[-3000:]) for s, v in rows.items()}
    print("=== 8x500 (4500 bar) ===")
    for v in VARIANTS:
        olc(d8, 8, *v)
    print("=== 6x500 (3000 bar) ===")
    for v in VARIANTS:
        olc(d6, 6, *v)
