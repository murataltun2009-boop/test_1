"""
osc_only icin esik secimi — OLCCULE REK.

Sorun: osc skoru 11 osilatorun ORTALAMASI. Tek bir osilatorun katkisi
en fazla 1/11 = 0,091. Bilesik skor icin kullanilan 0,40 / 0,65 esikleri
bu yuzden neredeyse hicbir zaman asilmaz (olcum: 280 barda 3 sinyal).

Bu arac, farkli esik ciftleri icin:
  * sinyal sayisi
  * AL/SAT dengesi
  * ISLEM SAYISI (sinyal DEGISIMI — komisyonu belirleyen budur)
olcer.

    python tools/pick_osc_threshold.py
"""
from __future__ import annotations

import os
import statistics
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np                                    # noqa: E402

import config                                         # noqa: E402
from core.analysis import analyze                     # noqa: E402
from core.binance_client import BinanceFuturesClient  # noqa: E402

# Ilk 220 bar atilir: 200 periyotluk MA'lar NaN doner ve osilator
# yumusatmeleri (RMA/EMA) yerlesmeden yaniltir.
ISLENCEK = 220

COINLER = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
           "BNBUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "SUIUSDT",
           "LTCUSDT", "BCHUSDT", "NEARUSDT", "TRUMPUSDT", "APTUSDT"]

# Denenecek esik ciftleri: (AL/SAT esigi, GÜCLU esigi)
CANDIDATES = [(0.40, 0.65),      # mevcut (bilesik) — referans
              (0.30, 0.45),
              (0.25, 0.40),
              (0.20, 0.30),
              (0.15, 0.25),
              (0.12, 0.20)]


def sinyal(x: float, base: float, strong: float) -> str:
    if x >= strong:
        return "AL"
    if x >= base:
        return "AL"
    if x <= -strong:
        return "SAT"
    if x <= -base:
        return "SAT"
    return "NÖTR"


def yon(s: str) -> int:
    return 1 if s == "AL" else (-1 if s == "SAT" else 0)


def topla(symbol: str, tf: str):
    c = BinanceFuturesClient(symbol)
    k = c.fetch_klines(tf, config.CANDLE_LIMIT)
    r = analyze(symbol, tf, [x.open_time for x in k], [x.open for x in k],
                [x.high for x in k], [x.low for x in k],
                [x.close for x in k], [x.volume for x in k],
                [x.close_time for x in k])
    return r.oscillator_scores[ISLENCEK:], r.ma_scores[ISLENCEK:]


def istatistik(veri: dict, dizi: int, base: float, strong: float,
               tf: str | None = None) -> dict:
    """Sinyal degisimi sayisi ve ortalama pozisyon suresi.

    ONEMLI — sayim kurali: uygulamada islem, sinyalin DEGISMESIyle
    olur (NÖTR'e gecis de bir degisimdir, cunku NÖTR bu modlarda ters
    yon sinyalidir). Onceki sadece "son YON" tutulursa her NÖTR bar
    islem sayilir ve sonuc sahte olarak on binlere cikar.
    """
    al = sat = notr = degisim = 0
    bar_arasinda = []
    for (sym, t), pair in veri.items():
        if tf is not None and t != tf:
            continue
        d = pair[dizi]
        onceki = None
        son_degisim = 0
        for i, v in enumerate(d):
            s = sinyal(float(v), base, strong)
            if s == "AL":
                al += 1
            elif s == "SAT":
                sat += 1
            else:
                notr += 1
            if onceki is not None and s != onceki:
                degisim += 1
                bar_arasinda.append(i - son_degisim)
                son_degisim = i
            onceki = s
    ort = statistics.mean(bar_arasinda) if bar_arasinda else 0.0
    return {"al": al, "sat": sat, "notr": notr, "degisim": degisim,
            "ort_bar": ort}


def main() -> int:
    print(f"{len(COINLER)} coin x {len(config.TIMEFRAMES)} dilim yukleniyor...\n")
    veri: dict = {}
    for sym in COINLER:
        for tf in config.TIMEFRAMES:
            try:
                veri[(sym, tf)] = topla(sym, tf)
            except Exception as exc:                  # noqa: BLE001
                print(f"  {sym}/{tf} atlandi: {exc}")
    if not veri:
        print("veri yok")
        return 1

    nbar = len(next(iter(veri.values()))[0])
    print(f"her kombinasyon icin {nbar} bar degerlendirildi\n")
    print("ISLEM = sinyal DEGISIMI sayisi. NÖTR de bir degisimdir")
    print("(bu modlarda ters yon sinyalidir).\n")

    for ad, dizi in (("OSILATOR", 0), ("MA", 1)):
        print("=" * 78)
        print(f"{ad} SKORU — esik adaylari (tum dilimler birlikte)")
        print("=" * 78)
        print("%-13s %8s %8s %8s %9s %10s %8s" %
              ("ESIK", "AL bar", "SAT bar", "NÖTR", "ISLEM", "ORT BAR", "DENGЕ"))
        print("-" * 78)
        for base, strong in CANDIDATES:
            s = istatistik(veri, dizi, base, strong)
            denge = (min(s["al"], s["sat"]) / max(s["al"], s["sat"])
                     if max(s["al"], s["sat"]) else 0.0)
            print("%-13s %8d %8d %8d %9d %10.1f %8.2f" %
                  (f"{base:.2f}/{strong:.2f}", s["al"], s["sat"], s["notr"],
                   s["degisim"], s["ort_bar"], denge))
        print()

    # Dilim bazinda 4h odakli (varsayilan dilim)
    print("=" * 78)
    print("OSILATOR — yalnizca 4h (varsayilan dilim)")
    print("=" * 78)
    print("%-13s %8s %8s %9s %10s" %
          ("ESIK", "AL bar", "SAT bar", "ISLEM", "ORT BAR"))
    print("-" * 78)
    for base, strong in CANDIDATES:
        s = istatistik(veri, 0, base, strong, tf="4h")
        print("%-13s %8d %8d %9d %10.1f" %
              (f"{base:.2f}/{strong:.2f}", s["al"], s["sat"],
               s["degisim"], s["ort_bar"]))
    print()

    print("=" * 78)
    print("OSILATOR — yalnizca 1h")
    print("=" * 78)
    for base, strong in CANDIDATES:
        s = istatistik(veri, 0, base, strong, tf="1h")
        print("  %-13s AL=%-5d SAT=%-5d islem=%-5d ort=%5.1f bar" %
              (f"{base:.2f}/{strong:.2f}", s["al"], s["sat"],
               s["degisim"], s["ort_bar"]))
    print()

    print("=" * 78)
    print("ONERI")
    print("=" * 78)
    print("  Hedef: sinyal atmasi yeterli olsun (AL/SAT >= 1000 bar),")
    print("  islem sayisi ASIRI olmasin (4h ort bar >= 4).")
    print()
    for base, strong in CANDIDATES:
        s4 = istatistik(veri, 0, base, strong, tf="4h")
        yeterli = (s4["al"] + s4["sat"]) >= 1000
        makul = s4["ort_bar"] >= 4.0
        isaret = "  <== UYGUN" if (yeterli and makul) else ""
        print("  %-13s 4h: AL=%-5d SAT=%-5d islem=%-5d ort=%5.1f bar%s" %
              (f"{base:.2f}/{strong:.2f}", s4["al"], s4["sat"],
               s4["degisim"], s4["ort_bar"], isaret))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())