# -*- coding: utf-8 -*-
"""TIK2: HULL notrken yeni giris yasagi olcumu (2026-11-08).

Kullanici kurali: "HULL notr durumdayken yeni pozisyon acma, beklemede
kal." Acik pozisyonun cikisi etkilenmez.

Kullanim:
    python tools/research_tk2_hullblock.py
"""
import os
import sys

ROOT = r"C:\Users\PC-ITENG\Documents\BTCUSDT_TA_Live"
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from core import tk2_rules  # noqa: E402
from core.analysis import analyze  # noqa: E402
from tools.research_tk2_stab import load  # noqa: E402
from tools.research_tk2_cross import bt  # noqa: E402

DATASETS = [
    ("ENAUSDT", "1m", 4000),
    ("BTCUSDT", "1m", 4000),
    ("ETHUSDT", "1m", 4000),
    ("SOLUSDT", "1m", 4000),
]
FOLD = 500

VARIANTS = [
    ("yasak KAPALI", False),
    ("yasak ACIK", True),
]


def main():
    agg = {n: dict(net=0.0, trades=0, comm=0.0, dd=0.0, pos=0, folds=0)
           for n, _v in VARIANTS}
    for sym, tf, n in DATASETS:
        candles = load(sym, tf, n)
        res = analyze(
            symbol=sym, timeframe=tf,
            open_times=[c.open_time for c in candles],
            o=[c.open for c in candles], h=[c.high for c in candles],
            l=[c.low for c in candles], c=[c.close for c in candles],
            v=[c.volume for c in candles],
            close_times=[c.close_time for c in candles])
        sigs = {n: tk2_rules.series_stable(
                    res.osc_codes, res.ma_codes,
                    hull_neutral_block=v)
                for n, v in VARIANTS}
        nf = len(candles) // FOLD
        print(f"\n--- {sym} {tf} {len(candles)} bar, {nf} dilim ---")
        for name, _v in VARIANTS:
            net = comm = 0.0
            trades = pos = 0
            dd = 0.0
            for f in range(nf):
                a, b = f * FOLD, (f + 1) * FOLD
                st = bt(sym, tf, candles[a:b], sigs[name][a:b])
                net += st["profit"]
                trades += st["trades"]
                comm += st["commission"]
                dd = min(dd, st["_dd"])
                pos += 1 if st["profit"] > 0 else 0
            g = agg[name]
            g["net"] += net
            g["trades"] += trades
            g["comm"] += comm
            g["dd"] = min(g["dd"], dd)
            g["pos"] += pos
            g["folds"] += nf
            print(f"  {name:14s} net={net:+9.2f}$ poz={pos}/{nf} "
                  f"islem={trades:4d} kom={comm:7.2f} DD={dd:+8.2f}")
    print("\n" + "=" * 70)
    print("TOPLAM:")
    for name, g in sorted(agg.items(), key=lambda kv: -kv[1]["net"]):
        print(f"  {name:14s} net={g['net']:+10.2f}$ "
              f"poz={g['pos']}/{g['folds']} islem={g['trades']:5d} "
              f"kom={g['comm']:8.2f} DD={g['dd']:+9.2f}")


if __name__ == "__main__":
    main()
