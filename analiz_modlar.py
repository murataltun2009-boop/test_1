"""Karar mekanizmalarini karsilastirir: "range" (aralik) vs "signal".

Sinyal modunda geriye donuk test, gecmisin bar basina sinyalini
kullanir. analyze() tek cagriyla tum diziyi uretir ve nedenseldir
(150/150 kirpma testi dogruladi).

Calistir:  python analiz_modlar.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config
from core.analysis import analyze
from core.binance_client import BinanceFuturesClient
from core.paper import PaperTrader

cl = BinanceFuturesClient(config.SYMBOL)
SINYALLER = {"strong": 0.65, "base": 0.40}


def sinyaller(cs, tf):
    """Gecmisin bar basina sinyali (tek analyze cagrisi)."""
    res = analyze(
        symbol=config.SYMBOL, timeframe=tf,
        open_times=[c.open_time for c in cs], o=[c.open for c in cs],
        h=[c.high for c in cs], l=[c.low for c in cs],
        c=[c.close for c in cs], v=[c.volume for c in cs],
        close_times=[c.close_time for c in cs],
        strong_threshold=SINYALLER["strong"],
        base_threshold=SINYALLER["base"])
    return [s.value for s in res.signals]


def kosu(cs, tf, mod, sig=None):
    tr = PaperTrader(symbol=config.SYMBOL, balance=1000.0, leverage=10.0,
                     lookback=20)
    tr.running = True
    tr.mode = mod
    tr.configure(balance=1000.0)
    st = tr.backtest(cs, tf, sig)
    n_long = sum(1 for t in tr.trades if t.side == "LONG")
    n_short = sum(1 for t in tr.trades if t.side == "SHORT")
    return st, n_long, n_short


print("Karar mekanizmasi karsilastirmasi — 500 mum gercek veri")
print("1.000 USDT · x10 kaldirac · %80 teminat · %0,05 komisyon")
print("Esikler: GUC LU ±0,65 · AL/SAT ±0,40")
print("=" * 96)
print("%-5s %-9s %6s %7s %7s %8s %11s %11s  %s"
      % ("dilim", "mod", "LONG#", "SHORT#", "islem", "komisyon", "net",
         "bakiye", "acik"))
print("-" * 96)

ozet = {}
for tf in ("15m", "1h", "4h"):
    cs = cl.fetch_klines(tf, 500)
    sig = sinyaller(cs, tf)
    dag = {}
    for s in sig:
        dag[s] = dag.get(s, 0) + 1
    print("%-5s sinyal dagilimi: %s" % (tf, dag))
    for mod in ("range", "signal"):
        st, nl, ns = kosu(cs, tf, mod, sig if mod == "signal" else None)
        p = st["open_position"]
        ozet[(tf, mod)] = st["profit"]
        print("%-5s %-9s %6d %7d %7d %8.2f %+11.2f %11.2f  %s"
              % (tf, mod, nl, ns, st["trades"], st["commission"],
                 st["profit"], st["equity"], p or "-"))
    print("-" * 96)

print()
print("FARK (signal - range):")
for tf in ("15m", "1h", "4h"):
    a = ozet[(tf, "range")]
    b = ozet[(tf, "signal")]
    print("  " + tf.ljust(5) + " range {:+10.2f} ->  signal {:+10.2f}   "
          "(fark {:+10.2f})".format(a, b, b - a))

print()
print("=" * 96)
print("SİNYAL MODU + MİNİMUM TUTMA SÜRESİ (komisyonu sınırlamak için)")
print("=" * 96)
print("%-5s %-7s %7s %9s %11s %11s  %s"
      % ("dilim", "bekleme", "islem", "komisyon", "net", "bakiye", "not"))
print("-" * 96)
for tf in ("15m", "1h", "4h"):
    cs = cl.fetch_klines(tf, 500)
    sig = sinyaller(cs, tf)
    for bekleme in (0, 3, 5, 10, 20):
        tr = PaperTrader(symbol=config.SYMBOL, balance=1000.0,
                         leverage=10.0, lookback=20)
        tr.running = True
        tr.mode = "signal"
        tr.min_hold_bars = bekleme
        tr.configure(balance=1000.0)
        st = tr.backtest(cs, tf, sig)
        print("%-5s %-7d %7d %9.2f %+11.2f %11.2f  %s"
              % (tf, bekleme, st["trades"], st["commission"], st["profit"],
                 st["equity"], st["open_position"] or "-"))
    print("-" * 96)