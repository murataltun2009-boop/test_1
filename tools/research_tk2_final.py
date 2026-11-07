# -*- coding: utf-8 -*-
"""TIK2 final aday dogrulama: HULL giris kapisi + minimum tutma.

Kullanim:
    python tools/research_tk2_final.py ENAUSDT 1m 500
    python tools/research_tk2_final.py ENAUSDT 1m 402
    python tools/research_tk2_final.py BTCUSDT 1m 500
"""
import os
import sys

ROOT = r"C:\Users\PC-ITENG\Documents\BTCUSDT_TA_Live"
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from core.analysis import analyze  # noqa: E402
from core.paper import PaperTrader  # noqa: E402
from tools.research_tk2_stab import HULL, load, stabilize  # noqa: E402

CANDIDATES = [
    ("ham", {}, 0),
    ("hold3", {}, 3),
    ("HULLg", dict(hull_entry_veto=True), 0),
    ("HULLg+hold3", dict(hull_entry_veto=True), 3),
    ("HULLg+hold4", dict(hull_entry_veto=True), 4),
    ("HULLg+s3+hold3", dict(hull_entry_veto=True, hull_smooth=3), 3),
    ("hold4", {}, 4),
]


def bt(sym, tf, candles, sig, min_hold):
    p = PaperTrader(sym)
    p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                wallet_fraction=0.8, mode="tk2", risk_pct=0.03)
    p.fixed_stake = True
    p._tk2_min_hold = int(min_hold)
    p._quiet = True
    st = p.backtest(candles, tf, signals=sig)
    tr = list(p.trades)
    st["_long"] = sum(1 for x in tr if str(x.side).upper().startswith("LONG"))
    cum = peak = dd = 0.0
    for x in tr:
        cum += x.net_pnl
        peak = max(peak, cum)
        dd = min(dd, cum - peak)
    st["_dd"] = dd
    return st


def main():
    sym, tf, n = sys.argv[1], sys.argv[2], int(sys.argv[3])
    candles = load(sym, tf, n)
    res = analyze(
        symbol=sym, timeframe=tf,
        open_times=[c.open_time for c in candles],
        o=[c.open for c in candles], h=[c.high for c in candles],
        l=[c.low for c in candles], c=[c.close for c in candles],
        v=[c.volume for c in candles],
        close_times=[c.close_time for c in candles])
    from core import tk2_rules
    raw = tk2_rules.series(res.osc_codes, res.ma_codes)
    hull = res.ma_codes[HULL]
    print(f"\n=== {sym} {tf} son {n} bar | ham AL={raw.count('AL')} "
          f"SAT={raw.count('SAT')} NOTR={raw.count('NÖTR')} ===")
    for name, kw, mh in CANDIDATES:
        sig = stabilize(raw, hull, **kw) if kw else raw
        st = bt(sym, tf, candles, sig, mh)
        print(f"  {name:16s} islem={st['trades']:3d} "
              f"({st['_long']}L/{st['trades']-st['_long']}S) "
              f"net={st['profit']:+8.2f}$ "
              f"kaz=%{100*st['wins']/max(1,st['trades']):3.0f} "
              f"kom={st['commission']:7.2f} DD={st['_dd']:+8.2f} "
              f"son={st['balance']:.2f}")


if __name__ == "__main__":
    main()
