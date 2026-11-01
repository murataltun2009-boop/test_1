# -*- coding: utf-8 -*-
"""
TK 4. tur: PIYASA HAFIZASI olcumu — 2026-10-31 (canli ENA 1m: 8 islem, 2K/6Z).

Canli desen: ayni seviyede ust uste kayip
  LONG 0,1945 / 0,1944 / 0,1946 -> hepsi 0,1938-0,1939'da stop.
Iki yeni mekanizma:
  * SERI FRENI (streak): arka arkaya N zarar -> TUM yonlerde K bar giris yok.
  * SEVIYE HAFIZASI (level ban): son zararli giris seviyesine yakin AYNI
    yonde tekrar giris yok.

Sabit: pullback -0.05%, db 0.05, cf2, REQ, bp3.5, rr1.8, pause3, f0.5.
Calistirma: python tools/research_tk20.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import research_tk16 as r
from core.paper import PaperTrader

# (etiket, streak_n, streak_bars, level_ban, level_bars)
VARIANTS = [
    ("A taban (fren yok)", 0, 0, 0.0, 0),
    ("B seri 2/10", 2, 10, 0.0, 0),
    ("C seri 3/10", 3, 10, 0.0, 0),
    ("D seviye .2%/15", 0, 0, 0.002, 15),
    ("E seri2 + seviye", 2, 10, 0.002, 15),
    ("F seri2/15 + seviye", 2, 15, 0.002, 15),
    ("G seri2/6 + seviye", 2, 6, 0.002, 15),
]


def olc(data, nwin, etiket, sn, sb, lb, lbar):
    tpl = 0.0
    n = 0
    k = 0
    z = 0
    km = 0.0
    zm = 0.0
    kom = 0.0
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
            p.tk_streak_n = sn
            p.tk_streak_bars = sb
            p.tk_level_ban = lb
            p.tk_level_bars = lbar
            p.running = True
            p.start_balance = 1000.0
            p.balance = 1000.0
            p.backtest(mums[a:a + 500], "1m")
            w = sum(t.net_pnl for t in p.trades)
            sp += w
            tpl += w
            worst = min(worst, w)
            n += len(p.trades)
            kom += p.commission_paid
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
          f"kom {kom:.0f}$ en-kotu {worst:+.0f}$")
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
