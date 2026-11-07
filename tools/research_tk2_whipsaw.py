# -*- coding: utf-8 -*-
"""TIK2 whipsaw teshisi (2026-11-07).

Kullanici gozlemi: "1 mum kirmizi iken short aciliyor, arkasindaki yesil
mumla kapaniyor; sonra tekrar donuyor".

Bu betik production serisinde islemleri TUTMA SURESINE gore kirar.
NOT: Trade.closed_at geriye donuk testte duvar saati (time.time()) oldugu
icin kullanilamaz. Sureler _on_price/_close sarmalanarak BAR indeksinden
olculur.

Kullanim:
    python tools/research_tk2_whipsaw.py
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


def run(sym, tf, candles, sig):
    p = PaperTrader(sym)
    p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                wallet_fraction=0.8, mode="tk2", risk_pct=0.03)
    p.fixed_stake = True
    p._tk2_min_hold = 3
    p._quiet = True

    idx_of = {int(c.open_time): i for i, c in enumerate(candles)}
    state = {"bar": None}
    orig_on_price = p._on_price
    orig_close = p._close
    records = []

    def on_price(price, window, timeframe, signal=None, low=None, high=None):
        state["bar"] = idx_of.get(int(window[-1].open_time))
        return orig_on_price(price, window, timeframe, signal, low, high)

    def close(price, reason, timeframe, reset_signal=True, maker=False):
        pos = p.position
        if pos is not None and state["bar"] is not None:
            a = idx_of.get(int(pos.entry_bar))
            if a is not None:
                records.append({
                    "side": str(pos.side),
                    "bars": state["bar"] - a + 1,
                    "net": None,        # asagida trades ile eslestirilecek
                    "reason": reason,
                })
        return orig_close(price, reason, timeframe, reset_signal, maker)

    p._on_price = on_price
    p._close = close
    p.backtest(candles, tf, signals=sig)
    tr = list(p.trades)
    for rec, t in zip(records, tr):
        rec["net"] = t.net_pnl
        rec["exit_reason"] = str(t.exit_reason)
    return tr, records


def main():
    grand = {"<=1": [0, 0, 0.0, 0.0], "2": [0, 0, 0.0, 0.0],
             "3-5": [0, 0, 0.0, 0.0], "6+": [0, 0, 0.0, 0.0]}
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
        tr, recs = run(sym, tf, candles, sig)
        print(f"\n{sym} {tf}: islem={len(tr)} kayit={len(recs)} "
              f"net={sum(t.net_pnl for t in tr):+.2f}$")
        buckets = {"<=1": [], "2": [], "3-5": [], "6+": []}
        for r in recs:
            b = r["bars"]
            key = "<=1" if b <= 1 else ("2" if b == 2 else
                                        ("3-5" if b <= 5 else "6+"))
            buckets[key].append(r)
        for key, group in buckets.items():
            if not group:
                print(f"   {key:3s} bar: -")
                continue
            net = sum(g["net"] for g in group)
            win = sum(1 for g in group if g["net"] > 0)
            avg = net / len(group)
            print(f"   {key:3s} bar: islem={len(group):3d} kazanan={win:3d} "
                  f"net={net:+9.2f}$ ortalama={avg:+7.3f}$")
            g = grand[key]
            g[0] += len(group)
            g[1] += win
            g[2] += net
            g[3] += net
        # cikis nedeni dagilimi (kisa islemler)
        reasons = {}
        for r in recs:
            if r["bars"] <= 2:
                reasons[r["exit_reason"]] = reasons.get(
                    r["exit_reason"], 0) + 1
        top = sorted(reasons.items(), key=lambda kv: -kv[1])[:5]
        print("   kisa cikis nedenleri:",
              ", ".join(f"{k}:{v}" for k, v in top))
    print("\nTOPLAM")
    for key, (cnt, win, net, _x) in grand.items():
        avg = net / cnt if cnt else 0.0
        print(f"  {key:4s} bar: islem={cnt:4d} kazanan={win:4d} "
              f"net={net:+9.2f}$ ortalama={avg:+7.3f}$")


if __name__ == "__main__":
    main()
