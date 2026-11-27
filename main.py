"""
BTCUSDT Futures Trading Bot - ana giris noktasi.

Kullanim:
    python main.py              -> GUI (canli / backtest)
    python main.py --backtest   -> konsol backtest
    python main.py --tune       -> parametre taramasi
"""
from __future__ import annotations

import argparse
import logging
import sys


def _setup_logging(verbose: bool = False):
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)-24s | %(message)s",
        datefmt="%H:%M:%S",
    )
    # ccxt cok gurultulu
    logging.getLogger("ccxt").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def run_gui():
    from gui.app import main as gui_main
    gui_main()


def run_console_backtest(start: str, end: str):
    import pandas as pd

    from backtest.engine import BacktestEngine
    from config import TRADING_CONFIG
    from data.fetcher import DataFetcher

    print("Veri cekiliyor...", flush=True)
    df = DataFetcher().fetch_range(start, end)
    print(f"{len(df)} mum | {len(df.index.normalize().unique())} gun\n")

    result = BacktestEngine(TRADING_CONFIG).run(df)

    print("=" * 62)
    print("BACKTEST SONUCU")
    print("=" * 62)
    for key, value in result["metrics"].items():
        print(f"  {key:18}: {value}")

    trades = result["engine"].trades_df()
    if not trades.empty:
        print("\n--- Son 10 islem ---")
        cols = ["side", "entry", "exit", "qty", "pnl", "roi", "reason"]
        print(trades[cols].tail(10).to_string(index=False))

    # grafik
    try:
        from gui.matplotlib_chart import show_chart
        print("\nGrafik aciliyor...")
        show_chart(result["data"], result["engine"].markers,
                   None, result["equity_curve"], result["signals"])
    except Exception as exc:
        print(f"Grafik acilamadi: {exc}")


def main():
    parser = argparse.ArgumentParser(description="BTCUSDT Futures Trading Bot")
    parser.add_argument("--backtest", action="store_true", help="Konsol backtest calistir")
    parser.add_argument("--tune", action="store_true", help="Parametre taramasi calistir")
    parser.add_argument("--start", default="2026-08-01", help="Backtest baslangic (YYYY-MM-DD)")
    parser.add_argument("--end", default="2026-10-05", help="Backtest bitis (YYYY-MM-DD)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    _setup_logging(args.verbose)

    if args.tune:
        from backtest.tune import main as tune_main
        tune_main()
        return

    if args.backtest:
        run_console_backtest(args.start, args.end)
        return

    run_gui()


if __name__ == "__main__":
    sys.exit(main())
