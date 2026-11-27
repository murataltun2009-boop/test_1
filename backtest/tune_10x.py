"""
10x kaldiracli parametre arama - VE dürüst bir uyari.

Kullanicinin istegi: "10x ile kisa surede en fazla kari yapacak parametreler"

Bu script iki sey gosterir:
  1) Gecmis veride EN IYI parametre (in-sample optimum)
  2) AYNI parametrenin, secilmedigi donemdeki performansi (OOS)

Fark buyukse "en iyi" secim gecmis gurultusudur ve gelecekte calismaz.
Bu, curve-fitting'in olcumudur.

Kullanim:  python backtest/tune_10x.py
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

logging.basicConfig(level=logging.ERROR)

# 10x icin anlamli aralik: likidasyon ~%10, SL onun cok icinde olmali
GRID = {
    "strong_buy_threshold": [0.25, 0.35, 0.45, 0.55],
    "stop_loss_pct": [0.008, 0.012, 0.018, 0.025],
    "take_profit_pct": [0.016, 0.024, 0.036, 0.050],
    "max_position_pct": [0.10, 0.20, 0.35],
}

LEVERAGE = 10


def run(df, enriched, kw):
    thr = kw["strong_buy_threshold"]
    cfg = replace(TRADING_CONFIG, leverage=LEVERAGE,
                  strong_buy_threshold=thr, strong_sell_threshold=-thr,
                  stop_loss_pct=kw["stop_loss_pct"],
                  take_profit_pct=kw["take_profit_pct"],
                  max_position_pct=kw["max_position_pct"])
    res = BacktestEngine(cfg).run(df, enriched=enriched)
    return res["metrics"]


def main():
    tf = "4h"
    fetcher = DataFetcher()
    calc = IndicatorsCalculator()

    print("=" * 100)
    print(f"{LEVERAGE}x KALDIRAC - PARAMETRE ARAMA (timeframe {tf})")
    print("=" * 100)

    raw = fetcher.exchange.fetch_ohlcv(TRADING_CONFIG.symbol, tf, limit=1500)
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high",
                                   "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df.set_index("timestamp", inplace=True)
    print(f"  {len(df)} mum | {df.index[0].date()} -> {df.index[-1].date()} "
          f"({len(df)*4/24:.0f} gun)")

    # IS / OOS
    mid = len(df) // 2
    df_is = df.iloc[max(0, mid - 250):mid]
    df_oos = df.iloc[mid:]
    en_is = calc.calculate_all(df_is)
    en_oos = calc.calculate_all(df_oos)

    print(f"  IS : {en_is.index[0].date()} -> {en_is.index[-1].date()} ({len(en_is)} mum)")
    print(f"  OOS: {en_oos.index[0].date()} -> {en_oos.index[-1].date()} ({len(en_oos)} mum)")
    print()

    keys = list(GRID)
    combos = list(itertools.product(*(GRID[k] for k in keys)))
    print(f"  {len(combos)} kombinasyon IS uzerinde taraniyor...")

    rows = []
    for i, combo in enumerate(combos, 1):
        kw = dict(zip(keys, combo))
        try:
            m = run(df_is, en_is, kw)
        except Exception:
            continue
        rows.append({**kw, "m": m})
        if i % 48 == 0:
            print(f"    {i}/{len(combos)}", flush=True)

    if not rows:
        print("  Sonuc yok.")
        return

    # --- IS'de EN IYI (kesinlikle overfit olacak) ---
    best = max(rows, key=lambda r: r["m"]["roi"])
    m_is = best["m"]

    # --- IS'de TUM KADANLARI (daha gercekci bir "olasi" aralik) ---
    rets = sorted(r["m"]["roi"] for r in rows)
    median = rets[len(rets) // 2]
    best_positive = [r for r in rows if r["m"]["roi"] > 0]

    print()
    print("=" * 100)
    print("IS UCERINDE TARAMA SONUCU")
    print("=" * 100)
    print(f"  En iyi ROI    : {max(rets):+.2f}%")
    print(f"  Medyan ROI    : {median:+.2f}%")
    print(f"  En kotu ROI   : {min(rets):+.2f}%")
    print(f"  Karli kombinasyon: {len(best_positive)} / {len(rows)}")
    if best_positive:
        print(f"  En iyi karli  : {max(r['m']['roi'] for r in best_positive):+.2f}%")

    print()
    print("=" * 100)
    print("KRITIK: BU PARAMETRELER GELECEKTE CALISIR MI?")
    print("=" * 100)
    print(f"{'':16}{'IS (secildi)':>14}{'OOS (test)':>14}")
    print(f"{'En iyi param':16}{m_is['roi']:>13.2f}%", end="")
    try:
        m_oos = run(df_oos, en_oos, best)
        print(f"{m_oos['roi']:>13.2f}%")
        print()
        print(f"  IS  : {best['strong_buy_threshold']:.2f} esik, "
              f"SL {best['stop_loss_pct']*100:.1f}%, "
              f"TP {best['take_profit_pct']*100:.1f}%, "
              f"poz {best['max_position_pct']*100:.0f}%")
        print(f"  IS  : n={m_is['trades']} net {m_is['net']:+.2f} "
              f"wr {m_is['win_rate']}% pf {m_is['profit_factor']} "
              f"dd {m_is['equity_max_dd']}%")
        print(f"  OOS : n={m_oos['trades']} net {m_oos['net']:+.2f} "
              f"wr {m_oos['win_rate']}% pf {m_oos['profit_factor']} "
              f"dd {m_oos['equity_max_dd']}%")
        print()
        drop = m_is["roi"] - m_oos["roi"]
        print(f"  IS -> OOS kaybi: {drop:.2f} puan")
        if m_oos["roi"] < 0:
            print("  YORUM: IS'de en iyi olan parametre OOS'te ZARAR ETTI.")
            print("        Bu tam anlamiyla overfit: gecmis gurultusu.")
        elif drop > abs(m_is["roi"]) * 0.6:
            print("  YORUM: OOS ciddi sekilde daha kotu -> overfit riski yuksek.")
        else:
            print("  YORUM: OOS pozitif ve cok kotu degil -> bir sinyal var,")
            print("        ama tek dönem ile kesin sonuc verilemez.")
    except Exception as exc:
        print(f"  OOS hatasi: {exc}")

    # --- likidasyon riski ---
    print()
    print("=" * 100)
    print(f"{LEVERAGE}x LIKIDASYON RISKI")
    print("=" * 100)
    liq = 1.0 / LEVERAGE * 100
    print(f"  Bakim marjini (BTCUSDT ~%0.4) dikkate alinmazsa likidasyon ~%{liq:.0f} fiyat hareketinde")
    print(f"  Ilk SL seviyesi: %{best['stop_loss_pct']*100:.1f} -> likidasyona {liq/(best['stop_loss_pct']*100):.1f}x pay")
    print()
    print("  Pozisyon buyuklugune gore en kotu senaryo (SL dogrudan vurulursa):")
    for pct in [0.10, 0.20, 0.35]:
        notional = pct * LEVERAGE
        risk = notional * best["stop_loss_pct"]
        print(f"    marjin %{pct*100:.0f} (notional cuzdanin %{notional*100:.0f}) -> "
              f"SL cuzdanin %{risk*100:.2f}zi")
    print()
    print("  10x ile ardisik 3 SL: cuzdanin %%.0f'i gider" % (
        3 * GRID["max_position_pct"][0] * LEVERAGE * best["stop_loss_pct"] * 100))


if __name__ == "__main__":
    main()