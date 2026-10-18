"""
Kesif: Williams %R + ADX(14) gercekten ise yarar mi?

ADIM 1 (research_indicators.py): her gostergenin BILGI KATSAYISI (IC)
olculdu. 9 kirilimin 8'inde pozitif cikan iki gosterge:
    Williams %R  (ort +0,051)
    ADX(14)     (ort +0,049)

ADIM 2 (bu dosya): IC "piyasa yonunu tahmin edebilir" demektir; ama
KAR EDIP ETMEDIGINI soylemez. Burada gercek trade kuralina donusturulur
ve mevcut simulator ile ayni kosullarda (kaldirac, komisyon, hedef,
likidasyon) BACKTEST ile olculur.

KURAL TASARIMI
--------------
Williams %R  : -80'in ALTINA inince AL (asiri satim), -20'nin USTUNA
               cikince SAT (asiri alim).
ADX(14)     : trend gucu. 25'i asip gecmesi trendin BASLADIGINI,
               asagi inmesi trendin BITTIGINI gosterir.

Uc varyant denenir:
  A) Williams %R tek          — asiri alim/satim tersine cevrilir
  B) Williams %R + ADX filtresi— Williams yonunde, ADX 25'i astigi
                               kadar pozisyon tutulur
  C) Williams %R + ADX kapisi — ADX yalnizca GIRIS kapisi

    python tools/validate_combo.py
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
from core.binance_client import BinanceFuturesClient  # noqa: E402
from core.paper import PaperTrader                   # noqa: E402

LEVERAGE = 10.0
FEE = 0.0005
FRACTION = 0.80
BALANCE = 1000.0

COINLER = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT",
           "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT",
           "BCHUSDT", "SUIUSDT", "NEARUSDT", "TRUMPUSDT", "APTUSDT",
           "ATOMUSDT", "XMRUSDT", "HBARUSDT"]

HORIZON_BARS = 12     # bir sinyalden sonra kac bar beklenir
ADX_MIN = 25.0        # trend esigi (klasik ADX duyarliligi)


# ----------------------------------------------------------------------
# Sinyal uretecleri (research_indicators ile ayni kriterler)
# ----------------------------------------------------------------------
def wr_signal(c, h, l, horizon=16):
    """Williams %R: -80 alti AL, -20 ustu SAT."""
    from core import indicators as ind
    wr = ind.williams_r(h, l, c, 14)
    s = np.zeros(c.size, dtype=int)
    prev = np.roll(wr, 1)
    s[(prev <= -80) & (wr > -80)] = 1
    s[(prev >= -20) & (wr < -20)] = -1
    s[~np.isfinite(wr)] = 0
    s[0] = 0
    return s


def adx_trend(h, l, c, esik=25.0):
    """1 = trend guclu yukselis, -1 = trend guclu dusus, 0 = zayif.

    ONEMLI: esik parametresi ONCEDEN YOKTU ve iceride 25'e sabitlenisti.
    Bu yuzden "ADX filtresi YOK" varyantı bile aslinda 25 filtresi
    uyguluyordu; dort varyantin tamami ayni sonucu verdi (olculdu).
    """
    from core import indicators as ind
    adx, pdi, mdi = ind.adx(h, l, c, 14)
    s = np.zeros(c.size, dtype=int)
    guclu = adx > esik
    up = guclu & (pdi > mdi)
    dn = guclu & (mdi > pdi)
    s[up] = 1
    s[dn] = -1
    s[~np.isfinite(adx)] = 0
    return s


def combo_signal(c, h, l, varyant="B", adx_min=ADX_MIN):
    w = wr_signal(c, h, l)
    a = adx_trend(h, l, c, adx_min)
    if varyant == "A":
        return w
    if varyant == "B":
        out = np.zeros_like(w)
        m = w != 0
        out[m] = np.where(a[m] != 0, w[m], 0)
        return out
    if varyant == "C":
        out = np.zeros_like(w)
        m = (w != 0) & (a != 0)
        out[m] = w[m]
        return out
    return w


def sinyal_donustur(sinyal: np.ndarray) -> list:
    """numpy dizi -> metin listesi (_on_price'in bekledigi format)."""
    ad = {1: "AL", -1: "SAT", 0: "NÖTR"}
    return [ad[int(v)] for v in sinyal]


# ----------------------------------------------------------------------
def backtest_butun(mode: str, sinyal_fn=None, sinyaller: dict | None = None):
    """Verilen sinyal dizileriyle butun coinlerde backtest yapar."""
    toplam = {"net": 0.0, "islem": 0, "kazanc": 0, "kayip": 0,
              "acik": 0, "coin": 0}
    for sym in COINLER:
        for tf in config.TIMEFRAMES:
            try:
                c = BinanceFuturesClient(sym)
                k = c.fetch_klines(tf, config.CANDLE_LIMIT)
            except Exception:                          # noqa: BLE001
                continue
            sig = (sinyaller or {}).get((sym, tf))
            p = PaperTrader(config.Settings())
            p.configure(balance=BALANCE, leverage=LEVERAGE, fee_rate=FEE,
                        wallet_fraction=FRACTION, mode=mode)
            st = p.backtest(k, tf, sig)
            toplam["net"] += st["profit"]
            toplam["islem"] += st["trades"]
            toplam["kazanc"] += st["wins"]
            toplam["kayip"] += st["losses"]
            if st["open_position"]:
                toplam["acik"] += 1
            toplam["coin"] += 1
    return toplam


def main() -> int:
    print("=" * 78)
    print("KESIF DOGRULAMA — Williams %R + ADX gercek trade eder mi?")
    print(f"Kosullar: {BALANCE:.0f} USDT · {LEVERAGE:.0f}x · "
          f"%{FRACTION*100:.0f} teminat · %{FEE*100:.3f} komisyon")
    print("=" * 78)

    veri = pickle.load(open(os.path.join(config.DATA_DIR,
                                         "research_cache.pkl"), "rb"))

    varyantlar = [("A", "Williams %R tek (ADX yok)"),
                  ("B", "Williams %R + ADX onayı"),
                  ("C", "Williams %R + ADX giriş kapısı")]

    sonuclar = []
    for kod, ad in varyantlar:
        sinyaller = {}
        for (sym, tf), d in veri.items():
            sinyaller[(sym, tf)] = sinyal_donustur(
                combo_signal(d["c"], d["h"], d["l"], kod))
        # signal_long modu: yalniz LONG ac, SAT ile kapat (SHORT acma)
        t = backtest_butun("signal_long", sinyaller=sinyaller)
        sonuclar.append((kod, ad, t))

    print()
    print("%-34s %7s %7s %7s %12s %10s" %
          ("KURAL", "COIN", "ISLEM", "KAZ/KAY", "NET", "ISLEM/COIN"))
    print("-" * 84)
    for kod, ad, t in sonuclar:
        print("%-34s %7d %7d %3d/%-3d %12.2f %10.2f" %
              (ad, t["coin"], t["islem"], t["kazanc"], t["kayip"],
               t["net"], t["islem"] / max(1, t["coin"])))

    # Mevcut modlarla karsilastirma (ayni veri, ayni kosullar)
    print()
    print("MEVCUT KURALLARLA KARSILASTIRMA (ayni veri ile)")
    print("%-34s %7s %7s %12s" % ("KURAL", "ISLEM", "KAZ/KAY", "NET"))
    print("-" * 66)
    for m, ad in [("range", "range (varsayılan)"),
                  ("ma_only", "ma_only (MA'lar)"),
                  ("osc_only", "osc_only (osilatörler)")]:
        t = backtest_butun(m)
        print("%-34s %7d %3d/%-3d %12.2f" %
              (ad, t["islem"], t["kazanc"], t["kayip"], t["net"]))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())