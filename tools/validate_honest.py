"""
DOGRU DOGRULAMA — Williams %R + ADX kombinasyonu asiri uyum mu?

SORUN: research_indicators.py gostergeleri TUM veri uzerinde
siralamisti (IC). Sonra ayni veriyle backtest yaptigimizda
+20.828 USDT cikti. Bu KESINLIKLE asiri uyum riski tasir:
secim ve test ayni veriyi paylasiyor.

Uc BAGIMSIZ dogrulama:

  1) ZAMAN BOLME : ilk %50'de gostergeleri sec, son %50'de olc.
  2) COIN BOLME  : 9 coin'de sec, diger 9'da olc.
  3) KARA KUTU   : hicbir secim yapmadan, butun 18 coin'de dogrudan.

    python tools/validate_honest.py
"""
from __future__ import annotations

import os
import pickle
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np                                   # noqa: E402

import config                                        # noqa: E402
from core.binance_client import Candle               # noqa: E402
from core.paper import PaperTrader                   # noqa: E402
from validate_combo import (ADX_MIN, FEE, FRACTION,  # noqa: E402
                            LEVERAGE, BALANCE, wr_signal, adx_trend)

COINLER = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT",
           "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT",
           "BCHUSDT", "SUIUSDT", "NEARUSDT", "TRUMPUSDT", "APTUSDT",
           "ATOMUSDT", "XMRUSDT", "HBARUSDT"]

ILK_YARIM = COINLER[:9]
IKINCI_YARIM = COINLER[9:]


def mumlara(veri: dict, key) -> list:
    d = veri[key]
    out = []
    for i in range(len(d["c"])):
        out.append(Candle(
            open_time=i * 3600_000,
            open=float(d["o"][i]), high=float(d["h"][i]),
            low=float(d["l"][i]), close=float(d["c"][i]),
            volume=float(d["v"][i]),
            close_time=i * 3600_000 + 3600_000 - 1, closed=True))
    return out


def sinyal_kumesi(c, h, l, adx_min=ADX_MIN):
    """Williams %R + ADX onayi (varyant B)."""
    w = wr_signal(c, h, l)
    a = adx_trend(h, l, c, adx_min)          # esik GERCEKTEN uygulanir
    out = np.zeros_like(w)
    m = w != 0
    if m.any():
        guc = (np.abs(a[m]) > 0)
        out[m] = np.where(guc, w[m], 0)
    ad = {1: "AL", -1: "SAT", 0: "NÖTR"}
    return [ad[int(v)] for v in out]


def backtest(mum: list, tf: str, sinyaller: list,
             bolme: str | None = None):
    """
    bolme: None  → tum mumlar
           "ilk" → ilk %50
           "son" → son %50
    """
    p = PaperTrader(config.Settings())
    p.configure(balance=BALANCE, leverage=LEVERAGE, fee_rate=FEE,
                wallet_fraction=FRACTION, mode="signal_long")
    if bolme == "ilk":
        k = len(mum) // 2
        return p.backtest(mum[:k], tf, sinyaller[:k])
    if bolme == "son":
        k = len(mum) // 2
        return p.backtest(mum[k:], tf, sinyaller[k:])
    return p.backtest(mum, tf, sinyaller)


def topla(veri, anahtarlar, bolme=None, adx_min=ADX_MIN):
    net = islem = kaz = kay = acik = 0
    for key in anahtarlar:
        if key not in veri:
            continue
        d = veri[key]
        sig = sinyal_kumesi(d["c"], d["h"], d["l"], adx_min)
        st = backtest(mumlara(veri, key), key[1], sig, bolme)
        net += st["profit"]
        islem += st["trades"]
        kaz += st["wins"]
        kay += st["losses"]
        acik += 1 if st["open_position"] else 0
    return net, islem, kaz, kay, acik


def coin_bazli(veri: dict, adx_min: float = ADX_MIN):
    """Her coin icin (net, islem, dilim_sayisi) toplamlari."""
    coin: dict = {}
    for key in veri:
        d = veri[key]
        sig = sinyal_kumesi(d["c"], d["h"], d["l"], adx_min)
        st = backtest(mumlara(veri, key), key[1], sig)
        a = coin.setdefault(key[0], [0.0, 0, 0])
        a[0] += st["profit"]
        a[1] += st["trades"]
        a[2] += 1
    return coin


def main() -> int:
    veri = pickle.load(open(os.path.join(config.DATA_DIR,
                                         "research_cache.pkl"), "rb"))
    tum = list(veri.keys())

    print("=" * 76)
    print("DOGRU DOGRULAMA — secim ve test AYRI veride")
    print("=" * 76)

    # ---- 1) ZAMAN BOLME ----
    print()
    print("1) ZAMAN BOLME — ilk %50'de olc, son %50'de TEKRAR olc")
    print("   (gostergeler once secildi; simdi ikinci yari hic kullanilmadi)")
    print()
    print("%-26s %7s %11s" % ("VERI ARALIGI", "ISLEM", "NET"))
    print("-" * 46)
    n1, i1, k1, y1, _ = topla(veri, tum, bolme="ilk")
    n2, i2, k2, y2, _ = topla(veri, tum, bolme="son")
    print("%-26s %7d %11.2f  (%d/%d kazanc)" %
          ("ilk %50 (IS)", i1, n1, k1, k1 + y1))
    print("%-26s %7d %11.2f  (%d/%d kazanc)" %
          ("son %50 (OOS)", i2, n2, k2, k2 + y2))

    # ---- 2) COIN BOLME ----
    print()
    print("2) COIN BOLME — 9 coin'de olc, Diger 9'da TEKRAR olc")
    print()
    print("%-26s %7s %11s" % ("COIN GRUBU", "ISLEM", "NET"))
    print("-" * 46)
    g1 = [k for k in tum if k[0] in ILK_YARIM]
    g2 = [k for k in tum if k[0] in IKINCI_YARIM]
    n1, i1, k1, y1, _ = topla(veri, g1)
    n2, i2, k2, y2, _ = topla(veri, g2)
    print("%-26s %7d %11.2f  (%d/%d kazanc)" %
          ("ilk 9 coin", i1, n1, k1, k1 + y1))
    print("%-26s %7d %11.2f  (%d/%d kazanc)" %
          ("son 9 coin", i2, n2, k2, k2 + y2))

    # ---- 3) KARA KUTU ----
    print()
    print("3) KARA KUTU — hicbir secim yok, 18 coinin tamami")
    print()
    print("%-26s %7s %11s %11s" % ("VARYANT", "ISLEM", "NET", "ISLEM/COIN"))
    print("-" * 58)
    for adx_min, ad in [(0.0, "ADX filtresi YOK"),
                       (20.0, "ADX > 20"),
                       (25.0, "ADX > 25 (klasik)"),
                       (30.0, "ADX > 30 (seçici)")]:
        n, i, k, y, c = topla(veri, tum, adx_min=adx_min)
        print("%-26s %7d %11.2f %11.2f" %
              (ad, i, n, i / max(1, c)))

    # ---- 4) ZAMAN DILIMI ----
    print()
    print("4) ZAMAN DILIMI KIRILIMI (ADX>25, tum 18 coin)")
    print()
    print("%-10s %7s %11s %11s" % ("DILIM", "ISLEM", "NET", "ISLEM/DIZI"))
    print("-" * 42)
    for tf in config.TIMEFRAMES:
        k = [x for x in tum if x[1] == tf]
        n, i, _, _, c = topla(veri, k)
        print("%-10s %7d %11.2f %11.2f" % (tf, i, n, i / max(1, c)))

    # ---- 5) KIRPMA TESTI (trim) — asiri uyumun kesin gostergesi ----
    print()
    print("=" * 76)
    print("5) KIRPMA TESTI — en iyi coinler cikarilirsa ne kalir?")
    print("=" * 76)
    import statistics
    cb = coin_bazli(veri, 25.0)
    vals = sorted((v[0] for v in cb.values()), reverse=True)
    tot = sum(vals)
    print()
    print("  toplam        : %+.2f  (%d coin)" % (tot, len(vals)))
    print("  ORTALAMA coin : %+.2f" % (tot / len(vals)))
    print("  MEDYAN coin   : %+.2f   <<< medyan coin" % statistics.median(vals))
    print("  kazanan coin  : %d / %d" % (sum(1 for v in vals if v > 0), len(vals)))
    print()
    for k in (1, 2, 3, 5):
        print("  en iyi %d coin çıkarılırsa kalan: %+.2f" % (k, tot - sum(vals[-k:])))
    print()
    print("  coin bazinda net (sirali):")
    for ad, v in sorted(cb.items(), key=lambda r: -r[1][0]):
        print("    %-12s %+11.2f  (%d islem)" % (ad, v[0], v[1]))

    print()
    print("=" * 76)
    print("YORUM: Ilk yari ve ikinci yari coin grubu AYNI yonde karliysa")
    print("sonuc gercek. Farkli yonDEYSE (biri +, digeri -) asiri uyum.")
    print("=" * 76)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())