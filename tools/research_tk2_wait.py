# -*- coding: utf-8 -*-
"""TIK2 bekleme kaldirma olcumu (2026-11-07).

Kullanici: "long/short pozisyon kapatmalarindaki beklemeyi iptal et;
bekleme pozisyonu kacirmaya ve zarara sebep oluyor."

Olculen iki ayri bekleme:
  after : PAPER_TK2_AFTER_SEC  (ac/kapa sonrasi K sn yeni islem yok)
  hold  : PAPER_TK2_MIN_HOLD   (sinyal cikisini K bar geciktirme)

Kullanim:
    python tools/research_tk2_wait.py
"""
import os
import sys

ROOT = r"C:\Users\PC-ITENG\Documents\BTCUSDT_TA_Live"
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from core import tk2_rules  # noqa: E402
from core.analysis import analyze  # noqa: E402
from core.paper import PaperTrader  # noqa: E402
from tools.research_tk2_stab import load  # noqa: E402

DATASETS = [
    ("ENAUSDT", "1m", 4000),
    ("BTCUSDT", "1m", 4000),
    ("ETHUSDT", "1m", 4000),
    ("SOLUSDT", "1m", 4000),
]
FOLD = 500

VARIANTS = [
    ("prod (120s + hold3)", 120, 3),
    ("bekleme yok (0+0)", 0, 0),
    ("sadece after=0 (hold3)", 0, 3),
    ("sadece hold=0 (after120)", 120, 0),
]


def bt(sym, tf, candles, sig, after_sec, min_hold):
    p = PaperTrader(sym)
    p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                wallet_fraction=0.8, mode="tk2", risk_pct=0.03)
    p.fixed_stake = True
    p.tk_after_ms = float(after_sec) * 1000.0
    p._tk2_min_hold = int(min_hold)
    p._quiet = True
    st = p.backtest(candles, tf, signals=sig)
    tr = list(p.trades)
    cum = peak = dd = 0.0
    for t in tr:
        cum += t.net_pnl
        peak = max(peak, cum)
        dd = min(dd, cum - peak)
    st["_dd"] = dd
    return st


def main():
    agg = {n: dict(net=0.0, trades=0, comm=0.0, dd=0.0, pos=0, folds=0)
           for n, _a, _h in VARIANTS}
    for sym, tf, n in DATASETS:
        candles = load(sym, tf, n)
        res = analyze(
            symbol=sym, timeframe=tf,
            open_times=[c.open_time for c in candles],
            o=[c.open for c in candles], h=[c.high for c in candles],
            l=[c.low for c in candles], c=[c.close for c in candles],
            v=[c.volume for c in candles],
            close_times=[c.close_time for c in candles])
        sig = tk2_rules.series_stable(res.osc_codes, res.ma_codes)
        nf = len(candles) // FOLD
        print(f"\n--- {sym} {tf} {len(candles)} bar, {nf} dilim ---")
        for name, after, hold in VARIANTS:
            net = comm = 0.0
            trades = pos = 0
            dd = 0.0
            for f in range(nf):
                a, b = f * FOLD, (f + 1) * FOLD
                st = bt(sym, tf, candles[a:b], sig[a:b], after, hold)
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
            print(f"  {name:26s} net={net:+9.2f}$ poz={pos}/{nf} "
                  f"islem={trades:4d} kom={comm:7.2f} DD={dd:+8.2f}")
    print("\n" + "=" * 78)
    print("TOPLAM:")
    for name, g in sorted(agg.items(), key=lambda kv: -kv[1]["net"]):
        print(f"  {name:26s} net={g['net']:+10.2f}$ "
              f"poz={g['pos']}/{g['folds']} islem={g['trades']:5d} "
              f"kom={g['comm']:8.2f} DD={g['dd']:+9.2f}")


if __name__ == "__main__":
    main()
