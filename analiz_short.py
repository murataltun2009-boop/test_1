"""SHORT sinyallerinin neden acilmadigini oler.

Kullanicinin kurali: SHORT yalnizca fiyat son LONG'un ALTINDA ve
pencerenin zirvesindeyse verilir. Bu script her barda hangi sartin
engelledigini sayar.

Calistir:  python analiz_short.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config
from core.binance_client import BinanceFuturesClient
from core.paper import PaperTrader

cl = BinanceFuturesClient("BTCUSDT")

print("SHORT sinyali icin gereken sartlar ve hepsinin gercek sayimi")
print("=" * 74)

for tf in ("15m", "1h", "4h"):
    cs = cl.fetch_klines(tf, 500)
    tr = PaperTrader(lookback=20)
    tr.running = True

    say = dict(long_acilan=0, short_acilan=0, short_no_ref=0,
               short_long_ustu=0, short_zirve_disi=0, short_hazir=0,
               pozisyon_varken=0)

    for i in range(tr.lookback, len(cs)):
        w = cs[i - tr.lookback + 1:i + 1]
        p = cs[i].close

        if tr.position is not None:
            say["pozisyon_varken"] += 1
            tr._on_price(p, w, tf)
            continue

        # SHORT sartlarini sirayla denetle
        if tr.last_long_price is None:
            say["short_no_ref"] += 1
        elif p >= tr.last_long_price:
            say["short_long_ustu"] += 1
        else:
            pos = tr._position_in_range(w, p)
            if pos < config.PAPER_TOP_POS:
                say["short_zirve_disi"] += 1
            else:
                say["short_hazir"] += 1

        ev = tr._on_price(p, w, tf)
        if ev:
            if "SHORT açıldı" in ev:
                say["short_acilan"] += 1
            elif "LONG açıldı" in ev:
                say["long_acilan"] += 1

    print()
    print("%-4s  LONG acildi: %d   SHORT acildi: %d" % (tf, say["long_acilan"],
                                                        say["short_acilan"]))
    print("      480 barin dagilimi:")
    print("        pozisyon ACIKti (degerlendirilmedi) : %d"
          % say["pozisyon_varken"])
    print("        referans LONG yok                    : %d"
          % say["short_no_ref"])
    print("        fiyat son LONG'un USTUNDE  (kural)   : %d  <-- ENGELLEYEN"
          % say["short_long_ustu"])
    print("        fiyat zirve bolgesinde degil          : %d"
          % say["short_zirve_disi"])
    print("        sartlar hazir -> SHORT acilmaliydi   : %d"
          % say["short_hazir"])

print()
class SerbestShort(PaperTrader):
    """Ayni motor, yalnizca zarar kurali devre disi."""

    def _short_signal(self, candles, price):
        w = self._window(candles)
        if len(w) < 5:
            return None
        if self._position_in_range(w, price) < config.PAPER_TOP_POS:
            return None
        return "pencere zirvesinde (zarar kurali yok)"


for tf in ("15m", "1h", "4h"):
    cs = cl.fetch_klines(tf, 500)
    for etiket, sinif in (("kural VARLI", PaperTrader),
                          ("kural YOK  ", SerbestShort)):
        tr = sinif(lookback=20)
        tr.running = True
        n_short = n_long = 0
        for i in range(tr.lookback, len(cs)):
            w = cs[i - tr.lookback + 1:i + 1]
            ev = tr._on_price(cs[i].close, w, tf)
            if ev:
                if "SHORT açıldı" in ev:
                    n_short += 1
                elif "LONG açıldı" in ev:
                    n_long += 1
        eq = tr.equity(cs[-1].close)
        print("%-4s  %s  LONG %2d  SHORT %2d  net %+10.2f  bakiye %9.2f"
              % (tf, etiket, n_long, n_short, eq - tr.start_balance, eq))
    print()
