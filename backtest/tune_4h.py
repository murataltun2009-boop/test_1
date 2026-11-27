"""
4 saatlik (4h) timeframe parametre taramasi.

Neden 4h? 1dk'da:
  - komisyon (giris+cikis %0.10) TP'nin %5.6'si
  - mum ATR %0.054 -> %1.0 SL tamamen gurultu
4h'de:
  - komisyon TP'nin ~%2'si
  - mum ATR %1.135 -> %2.3 SL anlamli bir seviye

Kullanim:  python backtest/tune_4h.py
"""
from __future__ import annotations

import itertools
import logging
import sys
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

BARS = 1500          # 1500 x 4h = 250 gun
TIMEFRAME = "4h"

GRID = {
    "strong_buy_threshold": [0.30, 0.40, 0.50, 0.60],
    "stop_loss_pct": [0.015, 0.023, 0.030],
    "take_profit_pct": [0.030, 0.046, 0.060],
    "max_position_pct": [0.30, 0.60],
}


def main():
    fetcher = DataFetcher()
    calc = IndicatorsCalculator()
    gen = SignalGenerator()

    print("4h VERI CEKILIYOR...")
    raw = fetcher.exchange.fetch_ohlcv(TRADING_CONFIG.symbol, TIMEFRAME, limit=BARS)
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high",
                                   "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df.set_index("timestamp", inplace=True)

    print(f"  {len(df)} mum | {df.index[0].date()} -> {df.index[-1].date()}"
          f" | {len(df)*4/24:.0f} gun")

    enriched = calc.calculate_all(df)
    if len(enriched) < 250:
        print("Yetersiz veri.")
        return

    # skor dagilimi
    s = gen.generate_series(enriched)
    d = s["composite"].dropna()
    print()
    print("SKOR DAGILIMI (4h)")
    print(f"  min {d.min():+.3f} | p10 {d.quantile(.10):+.3f} | medyan {d.median():+.3f} "
          f"| p90 {d.quantile(.90):+.3f} | max {d.max():+.3f} | std {d.std():.3f}")
    for thr in [0.30, 0.40, 0.50, 0.60]:
        print(f"  esik {thr:.2f}: yukari {(d >= thr).sum():4d} | asagi {(d <= -thr).sum():4d}")

    print()
    print("SL / TP SECIMI ICIN ATR")
    atr = ((enriched["high"] - enriched["low"]) / enriched["close"]).mean() * 100
    r = np.log(enriched["close"] / enriched["close"].shift(1)).dropna()
    print(f"  4h mum ATR : %{atr:.3f}")
    print(f"  4h bar std: %{r.std()*100:.3f}")
    print(f"  gunluk std : %{r.std()*np.sqrt(6)*100:.2f}")

    print()
    print("IZGARA TARAMASI")
    print("-" * 92)
    keys = list(GRID)
    combos = list(itertools.product(*(GRID[k] for k in keys)))
    results = []
    for i, combo in enumerate(combos, 1):
        kw = dict(zip(keys, combo))
        thr = kw["strong_buy_threshold"]
        cfg = replace(TRADING_CONFIG,
                      strong_buy_threshold=thr, strong_sell_threshold=-thr,
                      stop_loss_pct=kw["stop_loss_pct"],
                      take_profit_pct=kw["take_profit_pct"],
                      max_position_pct=kw["max_position_pct"])
        try:
            res = BacktestEngine(cfg).run(df, enriched=enriched)
        except Exception as exc:
            print(f"  [{i}/{len(combos)}] HATA {exc}")
            continue
        m = res["metrics"]
        row = {**kw, "trades": m["trades"], "net": m["net"], "roi": m["roi"],
               "wr": m["win_rate"], "pf": m["profit_factor"],
               "dd": m["equity_max_dd"], "fees": m["fees"]}
        results.append(row)
        print(f"  [{i:2d}/{len(combos)}] thr{thr:.2f} "
              f"SL{kw['stop_loss_pct']*100:.1f}% TP{kw['take_profit_pct']*100:.1f}% "
              f"poz{kw['max_position_pct']*100:.0f}% -> n={m['trades']:3d} "
              f"net {m['net']:+9.2f} roi {m['roi']:+7.2f}% "
              f"wr {m['win_rate']:5.1f}% pf {str(m['profit_factor']):>5s} "
              f"dd {m['equity_max_dd']:5.1f}%", flush=True)

    def quality(r):
        if r["trades"] < 5 or r["dd"] > 45:
            return float("-inf")
        return r["roi"] - r["dd"] * 0.2

    results.sort(key=quality, reverse=True)
    print()
    print("=" * 92)
    print("EN IYI 10")
    print("=" * 92)
    for r in results[:10]:
        print(f"  thr={r['strong_buy_threshold']:.2f} "
              f"SL={r['stop_loss_pct']*100:.1f}% TP={r['take_profit_pct']*100:.1f}% "
              f"poz={r['max_position_pct']*100:.0f}% -> n={r['trades']} "
              f"net {r['net']:+.2f} roi {r['roi']:+.2f}% wr={r['win_rate']}% "
              f"pf={r['pf']} dd={r['dd']}%")

    if results:
        b = results[0]
        print()
        print("config.py ICIN ONERI:")
        print(f"  strong_buy_threshold = {b['strong_buy_threshold']}")
        print(f"  strong_sell_threshold = {-b['strong_buy_threshold']}")
        print(f"  stop_loss_pct        = {round(b['stop_loss_pct'], 4)}")
        print(f"  take_profit_pct      = {round(b['take_profit_pct'], 4)}")
        print(f"  max_position_pct     = {round(b['max_position_pct'], 2)}")

    # ucret payi
    print()
    print("KOMISYONUN TP ICINDEKI PAYI (4h)")
    for tp in [0.030, 0.046, 0.060]:
        print(f"  TP %{tp*100:.1f} -> %{0.10/tp*100:.2f}")


if __name__ == "__main__":
    main()