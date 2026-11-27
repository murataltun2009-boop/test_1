"""
Coin karsilastirma: ayni strateji farkli USDT-M futures coinlerinde.

Maliyet yapisi:
  - Komisyon ORANI tum coinlerde ayni (Binance taker %0.05) -> degismez
  - Degisenler: spread (bid-ask), fonlama orani, oynaklik

Bu yuzden "maliyeti dusuk coin" yerine su soru sorulur:
  ayni SL/TP ve komisyonla hangi coinde daha az stop-out olur?

Kullanim:  python backtest/coin_compare.py
"""
from __future__ import annotations

import logging
import sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from backtest.engine import BacktestEngine            # noqa: E402
from config import TRADING_CONFIG                    # noqa: E402
from data.fetcher import DataFetcher                 # noqa: E402
from indicators.calculator import IndicatorsCalculator  # noqa: E402
from signals.generator import SignalGenerator        # noqa: E402

logging.basicConfig(level=logging.ERROR)

START = "2026-08-15"
END = "2026-10-06"

COINS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]

# rate limit: her coin arasinda bekle (Binance 1200 istek/dk)
PAUSE_BETWEEN_COINS = 4.0


def ccxt_symbol(symbol: str) -> str:
    return f"{symbol[:-4]}/USDT:USDT"


def live_metrics(symbol: str):
    """(bid, ask, spread_bps, funding_rate)"""
    ex = DataFetcher().exchange
    bt = ex.fapiPublicGetTickerBookTicker({"symbol": symbol})
    bid, ask = float(bt["bidPrice"]), float(bt["askPrice"])
    pr = ex.fapiPublicGetPremiumIndex({"symbol": symbol})
    mid = (bid + ask) / 2 or 1.0
    return bid, ask, (ask - bid) / mid * 10000, float(pr["lastFundingRate"])


def main():
    fetcher = DataFetcher()
    calc = IndicatorsCalculator()
    cfg = TRADING_CONFIG

    print("=" * 104)
    print(f"COIN KARSILASTIRMASI  ({START} -> {END}, 1dk, esik {cfg.strong_buy_threshold})")
    print("=" * 104)

    results = []

    for symbol in COINS:
        name = symbol[:-4]
        try:
            t0 = time.time()
            df = fetcher.fetch_range(START, END, symbol=ccxt_symbol(symbol))
            if len(df) < 500:
                print(f"{name:6} veri yetersiz ({len(df)} bar)")
                continue

            enriched = calc.calculate_all(df)

            # oynaklik
            r = np.log(enriched["close"] / enriched["close"].shift(1)).dropna()
            vol_day = float(r.std() * np.sqrt(1440) * 100)
            atr = float(((enriched["high"] - enriched["low"])
                         / enriched["close"]).mean() * 100)

            res = BacktestEngine(cfg).run(df, enriched=enriched)
            m = res["metrics"]
            bid, ask, spread, funding = live_metrics(symbol)

            results.append({
                "coin": name, "bars": len(df),
                "spread": spread, "funding": funding * 100,
                "vol": vol_day, "atr": atr,
                "trades": m["trades"], "net": m["net"], "roi": m["roi"],
                "wr": m["win_rate"], "pf": m["profit_factor"],
                "dd": m["equity_max_dd"], "fees": m["fees"],
            })
            print(f"{name:6} bitti ({len(df):,} bar, {time.time()-t0:.0f}s) "
                  f"-> n={m['trades']:3d} roi {m['roi']:+7.2f}%", flush=True)

        except Exception as exc:
            print(f"{name:6} HATA: {type(exc).__name__} {exc}", flush=True)

        time.sleep(PAUSE_BETWEEN_COINS)

    if not results:
        print("Sonuc yok.")
        return

    df_res = pd.DataFrame(results)

    print()
    print("=" * 104)
    print("MALIYET YAPISI")
    print("=" * 104)
    print("Komisyon orani TUM coinlerde ayni: giris %0.05 + cikis %0.05 = %0.10")
    print("Degisen maliyet kalemleri yalnizca:")
    print()
    hdr = (f"{'COIN':6} {'SPREAD bps':>11} {'Fonlama/8s':>11} {'Yillik %':>9} "
           f"{'Gunluk oyn. %':>13} {'1dk ATR %':>10}")
    print(hdr)
    print("-" * len(hdr))
    for _, r in df_res.sort_values("spread").iterrows():
        print(f"{r['coin']:6} {r['spread']:11.3f} {r['funding']:11.5f} "
              f"{r['funding']*3*365:9.2f} {r['vol']:13.2f} {r['atr']:10.4f}")
    print()
    print("Not: fonlama orani ANLIK GORUNTUDUR (surekli degisir). Pozisyon")
    print("     saatlerce acik kalirsa yillik degere carpilip maliyete donusur.")

    print()
    print("=" * 104)
    print("BACKTEST SONUCU")
    print("=" * 104)
    hdr2 = (f"{'COIN':6} {'Islem':>6} {'Net PnL':>10} {'ROI %':>8} {'Kazanc %':>9} "
            f"{'PF':>6} {'DD %':>6} {'Ucret':>9} {'Ucret/islem':>11} {'Ucret/ROI':>10}")
    print(hdr2)
    print("-" * len(hdr2))
    for _, r in df_res.sort_values("roi", ascending=False).iterrows():
        per = r["fees"] / r["trades"] if r["trades"] else 0
        drag = (r["fees"] / abs(r["net"]) * 100) if r["net"] else float("nan")
        print(f"{r['coin']:6} {r['trades']:6d} {r['net']:+10.2f} {r['roi']:+8.2f} "
              f"{r['wr']:9.1f} {str(r['pf']):>6} {r['dd']:6.1f} {r['fees']:9.2f} "
              f"{per:11.2f} {drag:9.0f}%")
    print()

    best = df_res.sort_values("roi", ascending=False).iloc[0]
    cheapest_spread = df_res.sort_values("spread").iloc[0]
    calmest = df_res.sort_values("vol").iloc[0]

    print("=" * 104)
    print("OZET")
    print("=" * 104)
    print(f"En ucuz spread   : {cheapest_spread['coin']} ({cheapest_spread['spread']:.3f} bps)")
    print(f"En dusuk oynaklik: {calmest['coin']} (gunluk %{calmest['vol']:.2f})")
    print(f"En iyi backtest  : {best['coin']} (ROI %{best['roi']:+.2f}, "
          f"{best['trades']} islem, PF {best['pf']})")
    print()
    print("Spread maliyeti pratikte ONEMSIZ: en kotu coin 4 bps, yani")
    print("gidis-donus %0.08. Asil kalem KOMISYON (%0.10) ve STOP-OUT oranidir.")
    print("Komisyon sabit oldugu icin 'daha ucuz coin' secerek maliyet")
    print("dusurulemez; kazanilan sey daha az stop-out = daha az islem = ")
    print("daha az komisyon.")


if __name__ == "__main__":
    main()
