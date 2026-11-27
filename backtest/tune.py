"""
Parametre arama: farklı sinyal/SL/TP/pozisyon ayarlarını test eder.
Kullanim:  python backtest/tune.py
"""
from __future__ import annotations

import itertools
import logging
import sys
from dataclasses import replace
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest.engine import BacktestEngine            # noqa: E402
from config import TRADING_CONFIG                    # noqa: E402
from data.fetcher import DataFetcher                 # noqa: E402

logging.basicConfig(level=logging.WARNING)

START = "2026-09-15"
END = "2026-10-05"

GRID = {
    "strong_buy_threshold": [0.55, 0.60, 0.65, 0.70, 0.75],
    "stop_loss_pct": [0.006, 0.008, 0.010, 0.013],
    "take_profit_pct": [0.012, 0.016, 0.020, 0.026],
    "max_position_pct": [0.20, 0.35],
}


def run_grid(df, enriched) -> List[dict]:
    results = []
    keys = list(GRID)
    combos = list(itertools.product(*(GRID[k] for k in keys)))
    total = len(combos)
    print(f"  {total} kombinasyon\n")

    for n, combo in enumerate(combos, 1):
        cfg = replace(
            TRADING_CONFIG,
            strong_buy_threshold=combo[0],
            strong_sell_threshold=-combo[0],
            stop_loss_pct=combo[1],
            take_profit_pct=combo[2],
            max_position_pct=combo[3],
        )
        try:
            out = BacktestEngine(cfg).run(df, enriched=enriched)
        except Exception as exc:
            print(f"  [{n}/{total}] HATA {combo}: {exc}")
            continue

        m = out["metrics"]
        row = {**dict(zip(keys, combo)), **{
            "net": m["net"], "roi": m["roi"], "trades": m["trades"],
            "win_rate": m["win_rate"], "pf": m["profit_factor"],
            "dd": m["equity_max_dd"], "fees": m["fees"],
        }}
        results.append(row)
        print(f"  [{n:2d}/{total}] thr{row['strong_buy_threshold']:.2f} "
              f"SL{row['stop_loss_pct']*100:.1f}% TP{row['take_profit_pct']*100:.1f}% "
              f"pos{row['max_position_pct']*100:.0f}% → net {row['net']:+9.2f} | "
              f"roi {row['roi']:+7.2f}% | n={row['trades']:4d} | "
              f"wr {row['win_rate']:5.1f}% | pf {str(row['pf']):>6s} | dd {row['dd']:5.1f}%",
              flush=True)
    return results


def main():
    from indicators.calculator import IndicatorsCalculator

    print("Veri cekiliyor...")
    df = DataFetcher().fetch_range(START, END)
    print(f"{len(df)} mum, {len(df.index.normalize().unique())} gun")
    if len(df) < 210:
        print("Yetersiz veri.")
        return

    print("Indikatorler hesaplaniyor (bir kez)...")
    enriched = IndicatorsCalculator().calculate_all(df)
    print(f"{len(enriched)} satir\n")

    print("Izgara taraniyor...")
    results = run_grid(df, enriched)

 # ROI + kalite filtresi: kar + makul islem sayisi + dusuk drawdown
    def quality(r: dict) -> float:
        if r["trades"] < 12 or r["dd"] > 45:
            return float("-inf")
        return r["roi"] - r["dd"] * 0.25

    results.sort(key=quality, reverse=True)
    print("\n=== EN IYI 20 (roi - dd*0.25, en az 12 islem, dd<45%) ===")
    for r in results[:20]:
        print(f"  thr={r['strong_buy_threshold']:.2f} SL={r['stop_loss_pct']*100:.1f}% "
              f"TP={r['take_profit_pct']*100:.1f}% pos={r['max_position_pct']*100:.0f}% "
              f"→ net {r['net']:+.2f} roi {r['roi']:+.2f}% n={r['trades']} "
              f"wr={r['win_rate']}% pf={r['pf']} dd={r['dd']}%")

    best = results[0] if results else None
    if best:
        print("\n=== config.py icin onerilen ayarlar ===")
        print(f"  strong_buy_threshold = {best['strong_buy_threshold']}")
        print(f"  stop_loss_pct        = {round(best['stop_loss_pct'], 4)}")
        print(f"  take_profit_pct      = {round(best['take_profit_pct'], 4)}")
        print(f"  max_position_pct     = {round(best['max_position_pct'], 2)}")


if __name__ == "__main__":
    main()
