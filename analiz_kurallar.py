"""Iki SHORT kuralinin ayrintili karsilastirmasi.

Sinyal sayisini (acilan pozisyon) ve ACIK pozisyonun durumunu gosterir;
kapali islem sayisi tek basina yaniltici olabilir.

Calistir:  python analiz_kurallar.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config
from core.binance_client import BinanceFuturesClient
from core.paper import PaperTrader

cl = BinanceFuturesClient(config.SYMBOL)

print("SHORT kurali karsilastirmasi — 500 mum gercek veri")
print("1.000 USDT · x10 kaldirac · %80 teminat · %0,05 komisyon · pencere 20")
print("=" * 92)
print("%-5s %-9s %6s %6s %7s %7s %11s %11s  %s"
      % ("dilim", "kural", "LONG#", "SHORT#", "kapanan", "likid.", "net", "bakiye",
         "acik pozisyon"))
print("-" * 92)

ozet = {}
for tf in ("15m", "1h", "4h"):
    cs = cl.fetch_klines(tf, 500)
    for kural in ("entry", "pullback"):
        tr = PaperTrader(symbol="BTCUSDT", balance=1000.0, leverage=10.0,
                         lookback=20)
        tr.running = True
        tr.short_rule = kural
        tr.configure(balance=1000.0)

        n_long = n_short = 0
        likidasyon = 0
        for i in range(tr.lookback, len(cs)):
            w = cs[i - tr.lookback + 1:i + 1]
            ev = tr._on_price(cs[i].close, w, tf)
            if ev:
                if "LONG açıldı" in ev:
                    n_long += 1
                elif "SHORT açıldı" in ev:
                    n_short += 1
                elif "Likidasyon" in ev:
                    likidasyon += 1

        st = tr.state(cs[-1].close)
        p = st["position"]
        poz = "-"
        if p:
            poz = "%s @ %.2f  acik %+.2f (hedef %.2f)" % (
                p["side"], p["entry"], p["unrealized"], p["target"])
        ozet[(tf, kural)] = {"profit": st["profit"], "long": n_long, "short": n_short}
        print("%-5s %-9s %6d %6d %7d %7d %+11.2f %11.2f  %s"
              % (tf, kural, n_long, n_short, len(tr.trades), likidasyon,
                 st["profit"], st["equity"], poz))
    print("-" * 92)

print()
print("KISA SONUC")
print("-" * 92)
for tf in ("15m", "1h", "4h"):
    a = ozet[(tf, "entry")]
    b = ozet[(tf, "pullback")]
    print("  " + tf.ljust(5)
          + " entry    : LONG {}  SHORT {}  net {:+.2f}".format(
              a["long"], a["short"], a["profit"]))
    print("        pullback : LONG {}  SHORT {}  net {:+.2f}   (fark {:+.2f})"
          .format(b["long"], b["short"], b["profit"],
                  b["profit"] - a["profit"]))