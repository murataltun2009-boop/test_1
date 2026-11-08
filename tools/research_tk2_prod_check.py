# -*- coding: utf-8 -*-
"""TIK2 production dogrulama (2026-11-07).

Amac: arastirmada secilen hibritin (HULL giris kapisi + 3 bar minimum
tutma) PRODUCTION koduyla ayni sonucu verdigini gostermek.

  * ham seri   : tk2_rules.series(...)
  * production : tk2_rules.series_stable(...)  + config.PAPER_TK2_MIN_HOLD

4 sembol x 8 x 500 bar 1m, gercek Binance Futures verisi.

Kullanim:
    python tools/research_tk2_prod_check.py
"""
import os
import sys
import time

ROOT = r"C:\Users\PC-ITENG\Documents\BTCUSDT_TA_Live"
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import config  # noqa: E402
from core import tk2_rules  # noqa: E402
from core.analysis import analyze  # noqa: E402
from core.paper import PaperTrader  # noqa: E402
from tools.research_tk2_stab import load  # noqa: E402

DATASETS = [
    ("ENAUSDT", "1m", 4000, 500),
    ("BTCUSDT", "1m", 4000, 500),
    ("ETHUSDT", "1m", 4000, 500),
    ("SOLUSDT", "1m", 4000, 500),
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
    gw = sum(x.net_pnl for x in tr if x.net_pnl > 0)
    gl = -sum(x.net_pnl for x in tr if x.net_pnl < 0)
    cum = peak = dd = 0.0
    for x in tr:
        cum += x.net_pnl
        peak = max(peak, cum)
        dd = min(dd, cum - peak)
    return st, (gw / gl if gl > 0 else 0.0), dd


def new_agg():
    return dict(net=0.0, gw=0.0, gl=0.0, trades=0, comm=0.0,
                dd=0.0, pos=0, folds=0, per=[])


def main():
    assert bool(getattr(config, "PAPER_TK2_STAB_ON", True))
    assert bool(getattr(config, "PAPER_TK2_STAB_HULL_ENTRY", True))
    assert int(getattr(config, "PAPER_TK2_MIN_HOLD", 0)) == 0
    assert int(getattr(config, "PAPER_TK2_AFTER_SEC", 0)) == 0
    assert bool(getattr(config, "PAPER_TK2_STAB_HULL_NEUTRAL_BLOCK", True))
    assert bool(getattr(config, "PAPER_TK2_STAB_VWMA_HULL_LONG", True))
    assert bool(getattr(config, "PAPER_TK2_STAB_VWMA_HULL_HOLD", True))
    assert not bool(getattr(config, "PAPER_TK2_STAB_VWMA_HULL_ALWAYS", False))
    print(f"config: STAB_ON={config.PAPER_TK2_STAB_ON} "
          f"HULL_ENTRY={config.PAPER_TK2_STAB_HULL_ENTRY} "
          f"HULL_NEUTRAL_BLOCK={config.PAPER_TK2_STAB_HULL_NEUTRAL_BLOCK} "
          f"VWMA_LONG={config.PAPER_TK2_STAB_VWMA_HULL_LONG} "
          f"VWMA_HOLD={config.PAPER_TK2_STAB_VWMA_HULL_HOLD} "
          f"MIN_HOLD={config.PAPER_TK2_MIN_HOLD} "
          f"AFTER_SEC={config.PAPER_TK2_AFTER_SEC} "
          f"FLIP={config.PAPER_TK2_STAB_CONFIRM_FLIP}", flush=True)

    agg = {"ham": new_agg(), "prod": new_agg()}
    t_start = time.monotonic()
    for sym, tf, n, fold in DATASETS:
        candles = load(sym, tf, n)
        res = analyze(
            symbol=sym, timeframe=tf,
            open_times=[c.open_time for c in candles],
            o=[c.open for c in candles], h=[c.high for c in candles],
            l=[c.low for c in candles], c=[c.close for c in candles],
            v=[c.volume for c in candles],
            close_times=[c.close_time for c in candles])
        ham = tk2_rules.series(res.osc_codes, res.ma_codes)
        prod = tk2_rules.series_stable(res.osc_codes, res.ma_codes)
        # Production serisi, arastirma prototipinin varsayilaniyla ayni mi?
        proto = tk2_rules.stabilize(
            ham, res.ma_codes[tk2_rules.HULL_LABEL],
            osc_major=tk2_rules.oscillator_majority(
                res.osc_codes, len(ham)),
            vwma=tk2_rules.ma_direction(
                res.ma_codes, tk2_rules.VWMA_LABEL, len(ham)),
            hull_entry_veto=True,
            hull_neutral_block=bool(config.PAPER_TK2_STAB_HULL_NEUTRAL_BLOCK),
            vwma_hull_long=bool(config.PAPER_TK2_STAB_VWMA_HULL_LONG),
            vwma_hull_long_neutral=bool(
                config.PAPER_TK2_STAB_VWMA_HULL_LONG_NEUTRAL),
            vwma_hull_hold=bool(config.PAPER_TK2_STAB_VWMA_HULL_HOLD),
            vwma_hull_always=bool(config.PAPER_TK2_STAB_VWMA_HULL_ALWAYS),
            vwma_hull_short=bool(config.PAPER_TK2_STAB_VWMA_HULL_SHORT))
        if prod != proto:
            diff = sum(1 for a, b in zip(prod, proto) if a != b)
            print(f"  UYARI: production/prototip farki {diff} bar", flush=True)
        sigs = {"ham": ham, "prod": prod}
        holds = {"ham": 0, "prod": int(config.PAPER_TK2_MIN_HOLD)}
        nf = len(candles) // fold
        print(f"\n--- {sym} {tf} {len(candles)} bar, {nf} x {fold} dilim ---",
              flush=True)
        for name in ("ham", "prod"):
            net = comm = 0.0
            trades = pos = 0
            dd = 0.0
            for f in range(nf):
                a, b = f * fold, (f + 1) * fold
                sl = slice(a, b)
                st, _pf, fdd = bt(sym, tf, candles[sl], sigs[name][sl],
                                  holds[name])
                net += st["profit"]
                trades += st["trades"]
                comm += st["commission"]
                dd = min(dd, fdd)
                pos += 1 if st["profit"] > 0 else 0
            a_ = agg[name]
            a_["net"] += net
            a_["trades"] += trades
            a_["comm"] += comm
            a_["dd"] = min(a_["dd"], dd)
            a_["pos"] += pos
            a_["folds"] += nf
            a_["per"].append((sym, net, pos, nf, dd))
            print(f"  {name:5s} net={net:+9.2f}$ poz={pos}/{nf} "
                  f"islem={trades:4d} kom={comm:7.2f} DD={dd:+8.2f}",
                  flush=True)

    print("\n" + "=" * 70)
    print("TOPLAM (production kod):")
    for name in ("ham", "prod"):
        a = agg[name]
        print(f"  {name:5s} net={a['net']:+10.2f}$ poz={a['pos']}/{a['folds']} "
              f"islem={a['trades']:5d} kom={a['comm']:8.2f} "
              f"DD={a['dd']:+9.2f}")
    print(f"\ntoplam sure {int(time.monotonic()-t_start)} s")


if __name__ == "__main__":
    main()
