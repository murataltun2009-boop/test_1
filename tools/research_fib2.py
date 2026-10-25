"""
Skor tabanli + aralik motoruna AUTO FIB etkisi — olcumlu karar.

Kapsam (kullanicinin istegi): "sadece hareketli ortalamalar", "sadece
osilatorler", sinyal ailesi (signal / sadece long) ve "aralik pencere
tabanli" motor. Ayni islem/komisyon kurallari, TEK fark fib.

Her varyant fib KAPALI (taban) vs fib ACIK olarak yanyana yazilir:
  skor modlari : gate_labels (uc engel + altin cebe guclendirme)
  aralik motor : taban sarti yetmedikce ALTIN CEBE giris izni

Calistirma:
  python tools/research_fib2.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as cfg
import research_ppt as base


def yeni_trader(mode: str):
    from core.paper import PaperTrader
    p = PaperTrader(cfg.Settings())
    p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                wallet_fraction=0.8, mode=mode, risk_pct=0.03)
    p.running = True
    p.start_balance = 1000.0
    p.balance = 1000.0
    return p


def calistir(mode: str, cdl, tf, fib: bool):
    p = yeni_trader(mode)
    if mode == "range":
        p.fib_range_on = bool(fib)
        # aralik motoru short_rule pullback (default) kalir
    else:
        p.fib_score_on = bool(fib)
    return p.backtest(cdl, tf)


def show(label, bt):
    n = bt["trades"]
    wins = bt["wins"]
    wr = (100.0 * wins / n) if n else 0.0
    print(f"{label:>34} | {n:>6} islem | {bt['profit']:>8.2f}$ "
          f"{bt['return_pct']:>7.2f}% | kazan {wr:>5.1f}% ({wins}/{n})")


def main():
    modlar = ["ma_only", "osc_only", "signal", "signal_long", "range"]
    toplam = {m: [0.0, 0.0] for m in modlar}
    for name, cdl, tf in base.jobs():
        print(f"\n############ {name} ############")
        for m in modlar:
            bt0 = calistir(m, cdl, tf, fib=False)
            bt1 = calistir(m, cdl, tf, fib=True)
            show(f"{m} fib=KAPALI", bt0)
            show(f"{m} fib=ACIK", bt1)
            toplam[m][0] += bt0["profit"]
            toplam[m][1] += bt1["profit"]
    print("\n############ OZET (4 pencerenin toplam net kar/Z) ############")
    for m in modlar:
        kapali, acik = toplam[m]
        fark = acik - kapali
        isaret = "ARTAR" if fark > 0 else ("AZALIR" if fark < 0 else "=")
        print(f"{m:>14}: kapali {kapali:>9.2f}$ | acik {acik:>9.2f}$ "
              f"| fark {fark:>8.2f}$ ({isaret})")


if __name__ == "__main__":
    main()
