# -*- coding: utf-8 -*-
"""ALGO-GRAF varyant + koruyucu stop olcumu (2026-11-13).

Uc algoritma (algograf / algograf_long / algograf_short) 5m 50.000 bar
gercek Binance Futures verisinde olculur. Ikinci bolum koruyucu stopun
(`PAPER_ALGOGRAF_SL`) etkisini tarar.

Cizgiler: MAVI=EMA50, YESIL=VWMA20, TURUNCU=EMA20, PEMBE=HULL9,
MOR=EMA200 (SMA200 kullanilmaz).

Kullanim:
    python tools/research_algograf.py
    python tools/research_algograf.py 20000
"""
import os
import sys
import time

ROOT = r"C:\Users\PC-ITENG\Documents\BTCUSDT_TA_Live"
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from core import algograf  # noqa: E402
from core.analysis import analyze  # noqa: E402
from core.paper import PaperTrader  # noqa: E402
from tools.research_tk2_stab import load  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TF = "5m"
BARS = 50000
MODES = ["algograf", "algograf_long", "algograf_short"]
# Koruyucu stop taramasi (0 = stop kapali).
STOPS = [0.0, 0.005, 0.01, 0.02, 0.03]


def bt(sym, candles, sig, mode, sl=0.0, lev=10.0):
    p = PaperTrader(sym)
    p.configure(balance=1000.0, leverage=lev, fee_rate=0.0005,
                wallet_fraction=0.8, mode=mode)
    p.algo_sl = sl
    p.fixed_stake = True
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
    return {"net": st["profit"], "trades": st["trades"],
            "wins": st["wins"], "losses": st["losses"],
            "pf": pf, "dd": dd, "comm": st["commission"]}


def main():
    bars = int(sys.argv[1]) if len(sys.argv) > 1 else BARS
    print(f"ALGO-GRAF · {TF} {bars} bar · fixed 1000$, 10x, teminat %80, "
          f"komisyon %0,05, maker giris/cikis · cakisma toleransi "
          f"%{algograf.touch_ratio()*100:.2f}", flush=True)
    t0 = time.monotonic()
    rows = []
    series = {}
    for sym in SYMBOLS:
        candles = load(sym, TF, bars)
        res = analyze(
            symbol=sym, timeframe=TF,
            open_times=[c.open_time for c in candles],
            o=[c.open for c in candles], h=[c.high for c in candles],
            l=[c.low for c in candles], c=[c.close for c in candles],
            v=[c.volume for c in candles],
            close_times=[c.close_time for c in candles])
        print(f"\n--- {sym} {TF} {len(candles)} bar ---", flush=True)
        for mode in MODES:
            side = algograf.side_for_mode(mode)
            sig = algograf.series(res.ma_series, side=side)
            series[(sym, mode)] = sig
            say = {k: sig.count(k) for k in algograf.LABELS}
            r = bt(sym, candles, sig, mode)
            print(f"  {mode:15s} stop YOK  islem={r['trades']:5d} "
                  f"net={r['net']:+10.2f}$ PF={r['pf']:.2f} "
                  f"DD={r['dd']:+9.2f}$ kom={r['comm']:8.2f} "
                  f"K/Z={r['wins']}/{r['losses']} · "
                  f"AL={say['AL']} SAT={say['SAT']} "
                  f"AL-KAPAT={say['AL-KAPAT']} "
                  f"SAT-KAPAT={say['SAT-KAPAT']} "
                  f"NOTR={say['NÖTR']}", flush=True)
            rows.append((sym, mode, 0.0, r))

        print(f"  -- koruyucu stop taramasi ({sym}) --", flush=True)
        for mode in MODES:
            sig = series[(sym, mode)]
            for sl in STOPS[1:]:
                r = bt(sym, candles, sig, mode, sl=sl)
                print(f"  {mode:15s} SL %{sl*100:.1f}  islem={r['trades']:5d} "
                      f"net={r['net']:+10.2f}$ PF={r['pf']:.2f} "
                      f"DD={r['dd']:+9.2f}$ kom={r['comm']:8.2f} "
                      f"K/Z={r['wins']}/{r['losses']}", flush=True)
                rows.append((sym, mode, sl, r))

    print("\n" + "=" * 80)
    print("OZET — net$ (islem) · 10x · stop = PAPER_ALGOGRAF_SL")
    head = "  " + f"{'mod':15s}" + "".join(f"{s[:-4]:>18s}" for s in SYMBOLS)
    print(head)
    for mode in MODES:
        for sl in STOPS:
            cells = []
            for sym in SYMBOLS:
                r = next(x[3] for x in rows
                         if x[0] == sym and x[1] == mode and x[2] == sl)
                cells.append(f"{r['net']:+9.2f}$({r['trades']:3d})"
                             .rjust(18))
            etiket = f"{mode}" + ("" if sl == 0 else f" SL%{sl*100:.1f}")
            print("  " + f"{etiket:15s}" + "".join(cells))
        print()
    print(f"toplam sure {int(time.monotonic() - t0)} s")


if __name__ == "__main__":
    main()
