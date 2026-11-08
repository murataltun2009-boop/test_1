# -*- coding: utf-8 -*-
"""TIK2: HULL + hacim agirlikli MA birlikte degerlendirme olcumu.

Kullanici kurali (2026-11-08):
  * Osilatorlerin cogunlugu AL (notrler sayilmaz), HULL SAT ve hacim
    agirlikli MA AL ise SHORT acma; LONG ac.
  * VWMA AL iken HULL notr ise pozisyon tehlikeli (yeni giris yok).

Kullanim:
    python tools/research_tk2_vwma_hull.py
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

# Tum varyantlarda HULL notr giris yasagi ve HULL giris kapisi acik.
VARIANTS = [
    ("taban (kural)", dict(vwma_hull_long=False,
                           vwma_hull_long_neutral=False,
                           vwma_hull_hold=False,
                           vwma_hull_always=False,
                           vwma_hull_short=False)),
    ("LONG giris", dict(vwma_hull_long=True,
                        vwma_hull_long_neutral=False,
                        vwma_hull_hold=False,
                        vwma_hull_always=False,
                        vwma_hull_short=False)),
    ("LONG giris+koru", dict(vwma_hull_long=True,
                             vwma_hull_long_neutral=False,
                             vwma_hull_hold=True,
                             vwma_hull_always=False,
                             vwma_hull_short=False)),
    ("LONG giris+koru+notr", dict(vwma_hull_long=True,
                                  vwma_hull_long_neutral=True,
                                  vwma_hull_hold=True,
                                  vwma_hull_always=False,
                                  vwma_hull_short=False)),
    ("LONG hep", dict(vwma_hull_long=True,
                      vwma_hull_long_neutral=False,
                      vwma_hull_hold=False,
                      vwma_hull_always=True,
                      vwma_hull_short=False)),
    ("simetrik giris", dict(vwma_hull_long=True,
                            vwma_hull_long_neutral=False,
                            vwma_hull_hold=False,
                            vwma_hull_always=False,
                            vwma_hull_short=True)),
]


def main():
    agg = {n: dict(net=0.0, trades=0, comm=0.0, dd=0.0, pos=0, folds=0,
                   long=0, short=0)
           for n, _kw in VARIANTS}
    for sym, tf, n in DATASETS:
        candles = load(sym, tf, n)
        res = analyze(
            symbol=sym, timeframe=tf,
            open_times=[c.open_time for c in candles],
            o=[c.open for c in candles], h=[c.high for c in candles],
            l=[c.low for c in candles], c=[c.close for c in candles],
            v=[c.volume for c in candles],
            close_times=[c.close_time for c in candles])
        sigs = {name: tk2_rules.series_stable(
                    res.osc_codes, res.ma_codes, **kw)
                for name, kw in VARIANTS}
        nf = len(candles) // FOLD
        print(f"\n--- {sym} {tf} {len(candles)} bar, {nf} x {FOLD} dilim ---")
        for name, _kw in VARIANTS:
            net = comm = 0.0
            trades = pos = lng = sht = 0
            dd = 0.0
            for f in range(nf):
                a, b = f * FOLD, (f + 1) * FOLD
                st = bt(sym, tf, candles[a:b], sigs[name][a:b])
                net += st["profit"]
                trades += st["trades"]
                comm += st["commission"]
                dd = min(dd, st["_dd"])
                pos += 1 if st["profit"] > 0 else 0
                lng += st["_long"]
                sht += st["trades"] - st["_long"]
            g = agg[name]
            g["net"] += net
            g["trades"] += trades
            g["comm"] += comm
            g["dd"] = min(g["dd"], dd)
            g["pos"] += pos
            g["folds"] += nf
            g["long"] += lng
            g["short"] += sht
            print(f"  {name:20s} net={net:+9.2f}$ poz={pos}/{nf} "
                  f"islem={trades:4d} (L{lng}/S{sht}) "
                  f"kom={comm:7.2f} DD={dd:+8.2f}")
    print("\n" + "=" * 78)
    print("TOPLAM:")
    for name, g in sorted(agg.items(), key=lambda kv: -kv[1]["net"]):
        print(f"  {name:20s} net={g['net']:+10.2f}$ "
              f"poz={g['pos']}/{g['folds']} islem={g['trades']:5d} "
              f"(L{g['long']}/S{g['short']}) kom={g['comm']:8.2f} "
              f"DD={g['dd']:+9.2f}")


if __name__ == "__main__":
    main()
