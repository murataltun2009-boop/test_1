"""
Kullanicinin canli senaryosunun regresyon testi (HYPE logu).

Sorun: Supertrend yonu OLUSAN (kapanmamis) bar icinde tik tik
degisiyordu; simulator her sinyal degisiminde pozisyon degistiriyor,
kazanc komisyona gidiyordu.

Bu betik canli dongusunu taklit eder ve islem sayisini olcer.
"""
import sys
sys.path.insert(0, r"C:\Users\PC-ITENG\Documents\BTCUSDT_TA_Live")
import numpy as np
from core.binance_client import Candle
from core.paper import PaperTrader, _kapali_mumlar
from core import trend as trend_mod
import config as cfg


def series(n=200, base=79.68, amp=0.002):
    """SESSIZ piyasa: ATR kucuk -> Supertrend bandi dar."""
    rng = np.random.default_rng(5)
    return base + rng.normal(0, amp, n)


def bars(fiyat, start_ms=0, step_ms=60000):
    out = []
    for i, f in enumerate(fiyat):
        out.append(Candle(open_time=start_ms + i * step_ms, open=f,
                          high=f + 0.004, low=f - 0.004, close=f, volume=1.0,
                          close_time=start_ms + i * step_ms + step_ms - 1,
                          closed=True))
    return out


def calistir(kapali_barlar_sinyal, bekleme_saniye, ticks=400):
    p = PaperTrader(symbol="HYPEUSDT", balance=1000.0, leverage=10.0,
                    fee_rate=0.0005, wallet_fraction=0.8)
    p.configure(mode="trend", risk_pct=0.05)
    p.running = True
    p.start_balance = 1000.0
    p.balance = 1000.0
    p.flip_cooldown_ms = bekleme_saniye * 1000

    fiyat = series()
    cs = bars(fiyat[:60])
    cs[-1].closed = False
    son = cs[-1]
    olay = 0
    rng2 = np.random.default_rng(9)
    for t in range(ticks):
        son.close = (fiyat[60] + rng2.choice([-0.02, 0.02]) * (1 + t % 3)
                     + rng2.normal(0, 0.002))
        son.high = max(son.high, son.close)
        son.low = min(son.low, son.close)
        kaynak = _kapali_mumlar(cs) if kapali_barlar_sinyal else cs
        if len(kaynak) < 30:
            continue
        sig = trend_mod.last_signal([c.high for c in kaynak],
                                    [c.low for c in kaynak],
                                    [c.close for c in kaynak])
        if p.on_price(son.close, cs, "15m", sig):
            olay += 1
        if t % 20 == 19:
            cs = cs + bars([fiyat[60]], start_ms=cs[-1].open_time + 60000)
            cs[-1].closed = False
            son = cs[-1]
    return olay, len(p.trades), p.balance


if __name__ == "__main__":
    print("HYPE senaryosu (400 tick):")
    print("%-42s %8s %8s %10s" % ("kip", "olay", "islem", "bakiye"))
    for ad, kapali, bek in (
            ("A) ESKI: olusan bar + bekleme yok", False, 0),
            ("B) YENI: kapanmis bar + 5 dk bekleme", True, 300)):
        o, i, b = calistir(kapali, bek)
        print("%-42s %8d %8d %10.2f" % (ad, o, i, b))
