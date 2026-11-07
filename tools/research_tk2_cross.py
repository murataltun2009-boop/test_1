# -*- coding: utf-8 -*-
"""TIK2 stabilizasyon capraz dogrulama (2026-11-07).

Ayni aday filtreleri farkli sembol/dilim ve FARKLI 500-barlik pencerelerde
olcer. Amac: tek bir sansli pencereye degil, tekrar eden davranisa bakmak.

Kullanim:
    python tools/research_tk2_cross.py
"""
import os
import sys
import time

ROOT = r"C:\Users\PC-ITENG\Documents\BTCUSDT_TA_Live"
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import numpy as np  # noqa: E402

from core import tk2_rules  # noqa: E402
from core.analysis import analyze  # noqa: E402
from core.paper import PaperTrader  # noqa: E402
from tools.research_tk2_stab import HULL, load, stabilize  # noqa: E402

VARIANTS = [
    ("ham", {}),
    ("giris2", dict(confirm_entry=2)),
    ("HULLg", dict(hull_entry_veto=True)),
    ("HULLg+giris2", dict(hull_entry_veto=True, confirm_entry=2)),
    ("ham+hold3", dict(__min_hold=3)),
    ("ham+hold4", dict(__min_hold=4)),
    ("ham+hold5", dict(__min_hold=5)),
    ("HULLg+hold3", dict(hull_entry_veto=True, __min_hold=3)),
    ("HULLg+hold4", dict(hull_entry_veto=True, __min_hold=4)),
    ("HULLg+s3+hold3", dict(hull_entry_veto=True, hull_smooth=3,
                            __min_hold=3)),
    ("giris2+hold3", dict(confirm_entry=2, __min_hold=3)),
    ("HULLg+giris2+hold3", dict(hull_entry_veto=True, confirm_entry=2,
                                __min_hold=3)),
    ("HULL veto s3", dict(hull_veto=True, hull_smooth=3)),
    ("HULL vali+veto", dict(hull_governor=True, hull_veto=True,
                            confirm_exit=3, confirm_flip=3)),
    ("flip2", dict(confirm_flip=2)),
]

DATASETS = [
    ("ENAUSDT", "1m", 4000, 500),
    ("BTCUSDT", "1m", 4000, 500),
    ("ETHUSDT", "1m", 4000, 500),
    ("SOLUSDT", "1m", 4000, 500),
    ("BTCUSDT", "5m", 4000, 500),
    ("BTCUSDT", "15m", 3000, 500),
    ("BTCUSDT", "4h", 1500, 250),
    ("ENAUSDT", "4h", 3000, 500),
]


def bt(sym, tf, candles, sig, min_hold=0):
    p = PaperTrader(sym)
    p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                wallet_fraction=0.8, mode="tk2", risk_pct=0.03)
    p.fixed_stake = True
    p._tk2_min_hold = int(min_hold)
    p._quiet = True
    st = p.backtest(candles, tf, signals=sig)
    tr = list(p.trades)
    st["_gw"] = sum(x.net_pnl for x in tr if x.net_pnl > 0)
    st["_gl"] = -sum(x.net_pnl for x in tr if x.net_pnl < 0)
    cum = peak = dd = 0.0
    for x in tr:
        cum += x.net_pnl
        peak = max(peak, cum)
        dd = min(dd, cum - peak)
    st["_dd"] = dd
    st["_long"] = sum(1 for x in tr if str(x.side).upper().startswith("LONG"))
    return st


def analyze_codes(sym, tf, candles):
    res = analyze(
        symbol=sym, timeframe=tf,
        open_times=[c.open_time for c in candles],
        o=[c.open for c in candles], h=[c.high for c in candles],
        l=[c.low for c in candles], c=[c.close for c in candles],
        v=[c.volume for c in candles],
        close_times=[c.close_time for c in candles])
    raw = tk2_rules.series(res.osc_codes, res.ma_codes)
    hull = np.asarray(res.ma_codes[HULL])
    return raw, hull


def main():
    quick = "--quick" in sys.argv
    only_1m = "--1m" in sys.argv
    datasets = DATASETS[:2] if quick else DATASETS
    if only_1m:
        datasets = [d for d in datasets if d[1] == "1m"]
    variants = VARIANTS[:4] if quick else VARIANTS
    agg = {name: dict(net=0.0, gw=0.0, gl=0.0, trades=0, comm=0.0,
                      dd=0.0, pos=0, folds=0, worst=0.0, long=0,
                      sum_ret=0.0, n_ret=0, worst_ret=0.0,
                      per_ds=[]) for name, _ in variants}
    t_start = time.monotonic()
    for sym, tf, n, fold in datasets:
        t0 = time.monotonic()
        candles = load(sym, tf, n)
        raw, hull = analyze_codes(sym, tf, candles)
        # Serileri TUM veri uzerinde bir kez yumusat (durum gecisi tasinir).
        sigs = {}
        holds = {}
        for name, kw in variants:
            kw2 = dict(kw)
            holds[name] = int(kw2.pop("__min_hold", 0) or 0)
            sigs[name] = (stabilize(raw, hull, **kw2) if kw2 else raw)
        nf = len(candles) // fold
        print(f"\n--- {sym} {tf} {len(candles)} bar, {nf} x {fold} dilim "
              f"({int((time.monotonic()-t0)*1000)} ms analyze) ---",
              flush=True)
        for name, _ in variants:
            net = gw = gl = comm = 0.0
            trades = longn = pos = 0
            dd = worst = 0.0
            sum_ret = worst_ret = 0.0
            for f in range(nf):
                a = f * fold
                b = a + fold
                sl = slice(a, b)
                st = bt(sym, tf, candles[sl], sigs[name][sl],
                        min_hold=holds[name])
                ret = st["profit"] / 10.0       # 1000$ baslangica gore %
                net += st["profit"]
                gw += st["_gw"]
                gl += st["_gl"]
                comm += st["commission"]
                trades += st["trades"]
                longn += st["_long"]
                dd = min(dd, st["_dd"])
                pos += 1 if st["profit"] > 0 else 0
                worst = min(worst, st["profit"])
                sum_ret += ret
                worst_ret = min(worst_ret, ret)
            pf = gw / gl if gl > 0 else 0.0
            a = agg[name]
            a["net"] += net
            a["gw"] += gw
            a["gl"] += gl
            a["trades"] += trades
            a["comm"] += comm
            a["dd"] = min(a["dd"], dd)
            a["pos"] += pos
            a["folds"] += nf
            a["worst"] = min(a["worst"], worst)
            a["long"] += longn
            a["sum_ret"] += sum_ret
            a["n_ret"] += nf
            a["worst_ret"] = min(a["worst_ret"], worst_ret)
            a["per_ds"].append((sym, tf, net, pf, pos, nf, worst,
                                sum_ret / nf))
            print(f"  {name:20s} net={net:+9.2f}$ PF={pf:4.2f} "
                  f"poz={pos}/{nf} ort_ret={sum_ret/nf:+6.2f}% "
                  f"en_kotu={worst:+8.2f}$ islem={trades:4d} "
                  f"kom={comm:7.2f} DD={dd:+8.2f}", flush=True)
        print(f"  sure {int((time.monotonic()-t0))} s", flush=True)

    print("\n" + "=" * 78)
    print("TOPLAM (tum sembol/dilimler):")
    rows = []
    for name, _ in variants:
        a = agg[name]
        pf = a["gw"] / a["gl"] if a["gl"] > 0 else 0.0
        rows.append((a["net"], name, pf, a))
    for net, name, pf, a in sorted(rows, reverse=True):
        avg = a["sum_ret"] / max(1, a["n_ret"])
        print(f"  {name:20s} net={net:+10.2f}$ PF={pf:4.2f} "
              f"poz={a['pos']}/{a['folds']} ort_ret={avg:+6.2f}% "
              f"en_kotu_ret={a['worst_ret']:+6.2f}% "
              f"en_kotu={a['worst']:+9.2f}$ "
              f"islem={a['trades']:5d} kom={a['comm']:8.2f} "
              f"DD={a['dd']:+9.2f} LONG={a['long']}")

    print("\nEN IYI ADAYLARIN VERI SETI KIRILIMI:")
    for net, name, pf, a in sorted(rows, reverse=True)[:5]:
        print(f"\n  {name} (toplam {net:+.2f}$)")
        for sym, tf, n2, p2, pos, nf, worst, avgret in a["per_ds"]:
            print(f"    {sym:9s} {tf:3s} net={n2:+9.2f}$ PF={p2:4.2f} "
                  f"poz={pos}/{nf} ort_ret={avgret:+6.2f}% "
                  f"en_kotu={worst:+8.2f}$")
    print(f"\ntoplam sure {int(time.monotonic()-t_start)} s")


if __name__ == "__main__":
    main()
