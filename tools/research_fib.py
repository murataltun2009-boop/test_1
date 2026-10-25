"""
AUTO FIB RETRACEMENT etkisi — olcumlu karar (trend + muro).

Karsilastirma: ayni motor (PaperTrader.backtest), ayni islem/komisyon
kurallari, TEK fark fib filtresi acik/kapali:
  trend : kapali = klasik Supertrend karar serisi
          acik    = altin cebe GÜÇLÜ bypass + uc-banti devam engeli
  muro  : kapali = klasik MURO trend varyanti
          acik    = ayni fib gate (actions_trend)

Calistirma:
  python tools/research_fib.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as cfg
import research_ppt as base


def _yeni_trader(mode: str):
    from core.paper import PaperTrader
    p = PaperTrader(cfg.Settings())
    p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                wallet_fraction=0.8, mode=mode, risk_pct=0.03)
    p.running = True
    p.start_balance = 1000.0
    p.balance = 1000.0
    return p


def run_trend(candles, tf, fib: bool, pull=0.0, mult=None):
    from core import trend as trend_mod
    p = _yeni_trader("trend")
    if mult is not None:
        p.trend_mult = float(mult)
    p.trend_pull_atr = float(pull)
    p._no_entry_until = 0.0
    eski = trend_mod.FIB_ON
    try:
        trend_mod.FIB_ON = bool(fib)
        bt = p.backtest(candles, tf)
    finally:
        trend_mod.FIB_ON = eski
    return bt


def run_muro(candles, tf, fib: bool):
    p = _yeni_trader("muro")
    p.muro_cfg.fib_on = bool(fib)
    bt = p.backtest(candles, tf)
    return bt


def show(label, bt):
    n = bt["trades"]
    wins = bt["wins"]
    wr = (100.0 * wins / n) if n else 0.0
    print(f"{label:>30} | {n:>5} islem | {bt['profit']:>8.2f}$ "
          f"{bt['return_pct']:>7.2f}% | kazan {wr:>5.1f}% ({wins}/{n})")


def main():
    for name, cdl, tf in base.jobs():
        print(f"\n############ {name} ############")
        for pull in (0.0, 1.0):
            bt_off = run_trend(cdl, tf, fib=False, pull=pull)
            bt_on = run_trend(cdl, tf, fib=True, pull=pull)
            show(f"TREND fib=KAPALI pull={pull}", bt_off)
            show(f"TREND fib=AÇIK   pull={pull}", bt_on)
        for fib in (False, True):
            bt = run_muro(cdl, tf, fib=fib)
            show(f"MURO  fib={'AÇık' if fib else 'KAPALI'}", bt)


if __name__ == "__main__":
    main()
