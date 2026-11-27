"""
Out-of-sample (OOS) dogrulama.

Amac: parametreleri TEK bir donemde secmek yerine, secimi ve dogrulamayi
ayri donemlerde yapip asil soruyu yanitlamak:

    "Bu strateji GECMIS verisini gormeden de para kazandir mi?"

Yontem (walk-forward):
  1) Veri ikiye bolunur: IS (in-sample) ve OOS (out-of-sample).
  2) IS uzerinde en iyi parametreler secilir.
  3) O parametreler OOS uzerinde hic ayar yapmadan calistirilir.
  4) Her iki donemin sonucu karsilastirilir.

Eger OOS getirisi IS'te belirgin sekilde kotu ise strateji asiri uyum
(overfitting) yapmaktadir ve gelecek icin guvenilmez.

Kullanim:  python backtest/oos_test.py
"""
from __future__ import annotations

import logging
import sys
from dataclasses import replace
from itertools import product
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from backtest.engine import BacktestEngine            # noqa: E402
from config import TRADING_CONFIG                    # noqa: E402
from data.fetcher import DataFetcher                 # noqa: E402
from indicators.calculator import IndicatorsCalculator  # noqa: E402

logging.basicConfig(level=logging.ERROR)

START = "2026-08-01"
END = "2026-10-06"

GRID = {
    "strong_buy_threshold": [0.55, 0.60, 0.65, 0.70, 0.75],
    "stop_loss_pct": [0.006, 0.008, 0.010, 0.013],
    "take_profit_pct": [0.012, 0.016, 0.020, 0.026],
    "max_position_pct": [0.20, 0.35],
}


def _cfg(**kw):
    thr = kw["strong_buy_threshold"]
    return replace(
        TRADING_CONFIG,
        strong_buy_threshold=thr,
        strong_sell_threshold=-thr,
        stop_loss_pct=kw["stop_loss_pct"],
        take_profit_pct=kw["take_profit_pct"],
        max_position_pct=kw["max_position_pct"],
    )


def _score(m: Dict) -> float:
    """OOS secimi icin hedef: getiri, islem sayisi ve drawdown dengesi."""
    if m["trades"] < 15 or m["equity_max_dd"] > 40:
        return float("-inf")
    return m["roi"] - m["equity_max_dd"] * 0.25


def search(df: pd.DataFrame, enriched: pd.DataFrame, label: str) -> Tuple[Dict, Dict]:
    """Grid aramasi; en iyi parametre ve metrikleri dondurur."""
    best_row, best_metrics = None, None
    keys = list(GRID)
    combos = list(product(*(GRID[k] for k in keys)))

    for i, combo in enumerate(combos, 1):
        kw = dict(zip(keys, combo))
        try:
            res = BacktestEngine(_cfg(**kw)).run(df, enriched=enriched)
        except Exception:
            continue
        m = res["metrics"]
        sc = _score(m)
        if sc > (best_metrics and _score(best_metrics) or float("-inf")):
            best_row, best_metrics = kw, m
        if i % 40 == 0:
            print(f"  {label}: {i}/{len(combos)} tarandi", flush=True)

    return best_row, best_metrics


def main():
    print("=" * 66)
    print("OUT-OF-SAMPLE DOGRULAMASI")
    print("=" * 66)

    print("Veri cekiliyor...")
    df = DataFetcher().fetch_range(START, END)
    if len(df) < 1000:
        print("Yetersiz veri.")
        return

    print("Indikatorler hesaplaniyor...")
    enriched = IndicatorsCalculator().calculate_all(df)

    # IS / OOS bolunmesi (zaman sirasiyla)
    mid = len(enriched) // 2
    split_ts = enriched.index[mid]
    df_is = enriched.iloc[:mid]
    df_oos = enriched.iloc[mid:]
    # her yarida indikator hazirlik mumlari olsun (NaN kirpma sonrasi)
    df_is = df_is.iloc[250:]
    df_oos = df_oos.iloc[250:]

    print(f"\nToplam : {len(enriched):,} bar ({enriched.index[0].date()} -> {enriched.index[-1].date()})")
    print(f"IS    : {len(df_is):,} bar ({df_is.index[0].date()} -> {df_is.index[-1].date()})")
    print(f"OOS   : {len(df_oos):,} bar ({df_oos.index[0].date()} -> {df_oos.index[-1].date()})")

    # --- 1) IS uzerinde secim ---
    print("\n[1] In-Sample parametre secimi...")
    best, m_is = search(df_is, df_is, "IS")
    if not best:
        print("IS'te uygun parametre bulunamadi.")
        return
    print(f"  Secilen: thr={best['strong_buy_threshold']} "
          f"SL={best['stop_loss_pct']*100:.1f}% TP={best['take_profit_pct']*100:.1f}% "
          f"pos={best['max_position_pct']*100:.0f}%")
    print(f"  IS sonucu: net {m_is['net']:+.2f} | roi {m_is['roi']:+.2f}% | "
          f"n={m_is['trades']} | wr={m_is['win_rate']}% | pf={m_is['profit_factor']} | "
          f"dd={m_is['equity_max_dd']}%")

    # --- 2) OOS uzerinde ayni parametreler, HIC AYAR YOK ---
    print("\n[2] Out-of-Sample dogrulamasi (ayarlanmadan)...")
    res_oos = BacktestEngine(_cfg(**best)).run(df_oos, enriched=df_oos)
    m_oos = res_oos["metrics"]
    print(f"  OOS sonucu: net {m_oos['net']:+.2f} | roi {m_oos['roi']:+.2f}% | "
          f"n={m_oos['trades']} | wr={m_oos['win_rate']}% | pf={m_oos['profit_factor']} | "
          f"dd={m_oos['equity_max_dd']}%")

    # --- 3) karsilastirma ---
    print("\n" + "=" * 66)
    print("SONUC")
    print("=" * 66)
    print(f"{'':22}{'IS':>12}{'OOS':>12}")
    print(f"{'Net PnL':22}{m_is['net']:>12.2f}{m_oos['net']:>12.2f}")
    print(f"{'ROI %':22}{m_is['roi']:>12.2f}{m_oos['roi']:>12.2f}")
    print(f"{'Islem sayisi':22}{m_is['trades']:>12}{m_oos['trades']:>12}")
    print(f"{'Kazanc orani %':22}{m_is['win_rate']:>12.1f}{m_oos['win_rate']:>12.1f}")
    print(f"{'Profit factor':22}{str(m_is['profit_factor']):>12}{str(m_oos['profit_factor']):>12}")
    print(f"{'Max drawdown %':22}{m_is['equity_max_dd']:>12.2f}{m_oos['equity_max_dd']:>12.2f}")

    print()
    degradation = m_oos["roi"] - m_is["roi"]
    print(f"OOS - IS ROI farki: {degradation:+.2f} puan")

    if m_oos["roi"] <= 0:
        print("YORUM: OOS NEGATIF -> strateji gecmis veriye uyum sagliyor (overfit).")
        print("       Bu ayarlarla canli para risk etmeye deger degil.")
    elif degradation < -m_is["roi"] * 0.5 and m_is["roi"] > 0:
        print("YORUM: OOS belirgin sekilde kotu ama pozitif -> zayif kanit.")
        print("       Yalnizca kucuk pozisyonla ve izleme amacli kullanilabilir.")
    else:
        print("YORUM: OOS pozitif ve IS'e gore belirgin kotu degil -> makul kanit.")
        print("       Yine de tek donem; farkli donemde teyit edilmelidir.")

    print()
    print("Varsayilanlari bu parametrelerle guncellemek icin:")
    print(f"  strong_buy_threshold = {best['strong_buy_threshold']}")
    print(f"  stop_loss_pct        = {round(best['stop_loss_pct'], 4)}")
    print(f"  take_profit_pct      = {round(best['take_profit_pct'], 4)}")
    print(f"  max_position_pct     = {round(best['max_position_pct'], 2)}")


if __name__ == "__main__":
    main()
