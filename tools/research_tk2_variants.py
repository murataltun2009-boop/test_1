# -*- coding: utf-8 -*-
"""TIK2 varyant + dolar kar bankasi olcumu (2026-11-11).

`list3 (1).xlsx` 199 satirlik tablo ile UC varyantin (tk2 / tk2_long /
tk2_short) ve DOLAR bazli kar bankasinin (varsayilan 10$) 5m 50.000 bar
gercek Binance Futures verisindeki sonucu.

  * tk2       : AL + SAT (iki yon) ve KAPAT satirlari
  * tk2_long  : yalniz AL / AL-KAPAT
  * tk2_short : yalniz SAT / SAT-KAPAT

Her sembol icin: banka ACIK (10$) ve banka KAPALI (0$) karsilastirmasi.

Kullanim:
    python tools/research_tk2_variants.py
    python tools/research_tk2_variants.py 15
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

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TF = "5m"
BARS = 50000
MODES = ["tk2", "tk2_long", "tk2_short"]


def seri_for(mode, res):
    return tk2_rules.series_stable(
        res.osc_codes, res.ma_codes,
        side=tk2_rules.side_for_mode(mode))


def bt(sym, candles, sig, mode, bank):
    p = PaperTrader(sym)
    p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                wallet_fraction=0.8, mode=mode, risk_pct=0.03)
    p.fixed_stake = True
    p.tk2_bank_usd = float(bank)
    p._tk2_min_hold = 0
    p._quiet = True
    st = p.backtest(candles, TF, signals=sig)
    tr = list(p.trades)
    gw = sum(x.net_pnl for x in tr if x.net_pnl > 0)
    gl = -sum(x.net_pnl for x in tr if x.net_pnl < 0)
    cum = peak = dd = 0.0
    for x in tr:
        cum += x.net_pnl
        peak = max(peak, cum)
        dd = min(dd, cum - peak)
    pf = gw / gl if gl > 0 else 0.0
    return {
        "net": st["profit"], "trades": st["trades"],
        "wins": st["wins"], "losses": st["losses"],
        "pf": pf, "dd": dd, "comm": st["commission"],
    }


def main():
    bank = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0
    assert not bool(getattr(config, "PAPER_TK2_STAB_ON", True))
    assert int(getattr(config, "PAPER_TK2_MIN_HOLD", -1)) == 0
    assert int(getattr(config, "PAPER_TK2_AFTER_SEC", -1)) == 0
    tbl = tk2_rules.summary()
    print(f"tablo: {tbl['rows']} satir · {tbl['al']} AL / {tbl['sat']} SAT / "
          f"{tbl['al_kapat']} AL-KAPAT / {tbl['sat_kapat']} SAT-KAPAT · "
          f"banka={bank:.2f}$ (0=kapali)", flush=True)
    print("veri: 5m 50.000 bar, fixed stake 1000$, 10x, teminat %80, "
          "komisyon %0,05, maker giris/cikis", flush=True)

    t0 = time.monotonic()
    rows = []
    for sym in SYMBOLS:
        candles = load(sym, TF, BARS)
        res = analyze(
            symbol=sym, timeframe=TF,
            open_times=[c.open_time for c in candles],
            o=[c.open for c in candles], h=[c.high for c in candles],
            l=[c.low for c in candles], c=[c.close for c in candles],
            v=[c.volume for c in candles],
            close_times=[c.close_time for c in candles])
        print(f"\n--- {sym} {TF} {len(candles)} bar ---", flush=True)
        for mode in MODES:
            sig = seri_for(mode, res)
            say = {k: sig.count(k) for k in tk2_rules.LABELS}
            for b in (bank, 0.0):
                r = bt(sym, candles, sig, mode, b)
                etiket = f"{mode:9s} banka={'%.0f$' % b if b > 0 else 'KAPALI'}"
                print(f"  {etiket:26s} islem={r['trades']:5d} "
                      f"net={r['net']:+10.2f}$ PF={r['pf']:.2f} "
                      f"DD={r['dd']:+9.2f}$ kom={r['comm']:8.2f} "
                      f"K/Z={r['wins']}/{r['losses']}", flush=True)
                rows.append((sym, mode, b, r, say))

    print("\n" + "=" * 78)
    print("OZET: banka ACIK vs KAPALI")
    for sym in SYMBOLS:
        for mode in MODES:
            a = next(x for x in rows
                     if x[0] == sym and x[1] == mode and x[2] == bank)
            z = next(x for x in rows
                     if x[0] == sym and x[1] == mode and x[2] == 0.0)
            print(f"  {sym:8s} {mode:9s} banka {bank:5.0f}$: "
                  f"net={a[3]['net']:+10.2f}$ PF={a[3]['pf']:.2f} "
                  f"islem={a[3]['trades']:5d} | kapali: "
                  f"net={z[3]['net']:+10.2f}$ PF={z[3]['pf']:.2f} "
                  f"islem={z[3]['trades']:5d}", flush=True)
        print(flush=True)
    print(f"toplam sure {int(time.monotonic() - t0)} s")


if __name__ == "__main__":
    main()
