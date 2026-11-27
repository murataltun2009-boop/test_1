"""
SL/TP duyarli sinyal arayisi (trenden -> ortalamaya donusu -> SL/TP).

Onceki arayista SL/TP sabitti (1.2/2.4) ve hicbir sinyal karli cikmadi.
Burada:
  1) Her sinyal icin SL/TP ızgarasi taranir
  2) Saf momentum (devam) sinyali de eklenir - iki yonlu test
  3) IS/OOS bolunmesi ile dayaniklilik olculur
  4) Ucret sonrasi net beklenen deger esigi %0 olarak raporlanir

Kullanim:  python research/signal_matrix.py
"""
from __future__ import annotations

import itertools
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from config import TRADING_CONFIG            # noqa: E402
from data.fetcher import DataFetcher         # noqa: E402
from indicators.calculator import rma, rsi, stoch  # noqa: E402
from research.mean_reversion import (        # noqa: E402
    sig_zscore, sig_bollinger, sig_atr_dist, sig_momentum_fade,
    sig_rsi2, rolling_z, true_range,
)

logging.basicConfig(level=logging.ERROR)

FEE = 0.0010


# --------------------------------------------------------------------------
# Ek sinyaller
# --------------------------------------------------------------------------

def sig_momentum_cont(df, n=10, k=1.5):
    """SAF MOMENTUM: fiyat yukari gidiyorsa LONG (ortalama-donusun TERSI)"""
    return -sig_momentum_fade(df, n, k)      # momentum_fade'in tersi


def sig_breakout(df, n=20, k=1.0):
    """Donem ici en yuksek/en dusuk kirilimi"""
    hi = df["high"].rolling(n).max().shift(1)
    lo = df["low"].rolling(n).min().shift(1)
    score = pd.Series(0.0, index=df.index)
    score[df["close"] > hi * (1 + k * 0.001)] = 1.0
    score[df["close"] < lo * (1 - k * 0.001)] = -1.0
    return score


def sig_trend_ma(df, n=50):
    """MA trendi: fiyat uzerindeyse LONG, altindaysa SHORT (saf trend)"""
    m = df["close"].rolling(n).mean()
    a = rma(true_range(df), 14)
    z = (df["close"] - m) / a.replace(0.0, np.nan)
    return z.replace(0.0, np.nan).fillna(0).clip(-1, 1)


SIGNALS = {
    "ort-donus z(20)":  lambda df: sig_zscore(df, 20, 1.8),
    "ort-donus BB(50)": lambda df: sig_bollinger(df, 50, 2.5),
    "ort-donus RSI2":   lambda df: sig_rsi2(df, 10, 90),
    "ort-donus ATRdist": lambda df: sig_atr_dist(df, 20, 1.5),
    "ort-donus momfade": lambda df: sig_momentum_fade(df, 10, 1.5),
    "MOMENTUM mom(10)": lambda df: sig_momentum_cont(df, 10, 1.5),
    "MOMENTUM mom(30)": lambda df: sig_momentum_cont(df, 30, 1.5),
    "MOMENTUM MA(50)":  lambda df: sig_trend_ma(df, 50),
    "BREAKOUT(20)":     lambda df: sig_breakout(df, 20, 1.0),
}

SL_TP = [(0.006, 0.012), (0.008, 0.016), (0.010, 0.020), (0.012, 0.024),
         (0.015, 0.030), (0.020, 0.040), (0.025, 0.050), (0.010, 0.030),
         (0.015, 0.045), (0.020, 0.060)]


def backtest(df, score, sl, tp, horizon):
    """Sonuc: (islem, kazanma, net yuzde, max drawdown)"""
    cash = 1.0
    peak = 1.0
    mdd = 0.0
    wins = losses = 0

    for i in range(len(df) - horizon - 1):
        s = score.iloc[i]
        if pd.isna(s) or s == 0:
            continue
        entry = df["close"].iloc[i]
        w = df.iloc[i + 1: i + 1 + horizon]

        if s > 0:
            mfe = (w["high"].max() / entry - 1)
            mae = (w["low"].min() / entry - 1)
        else:
            mfe = (entry / w["low"].min() - 1)
            mae = (entry / w["high"].max() - 1)

        if mfe >= tp and mae > -sl:
            wins += 1
            cash *= (1 + tp - FEE)
        elif mae <= -sl:
            losses += 1
            cash *= (1 - sl - FEE)
        else:
            cash *= (1 - FEE)          # zaman asiminda sadece komisyon

        if cash > peak:
            peak = cash
        dd = (peak - cash) / peak
        if dd > mdd:
            mdd = dd

    return {"n": wins + losses, "wins": wins, "losses": losses,
            "ret": (cash - 1) * 100, "mdd": mdd * 100,
            "cash": cash}


def main():
    fetcher = DataFetcher()

    for tf, bars, horizon, hours in [("4h", 1500, 6, 4), ("1h", 1500, 12, 1)]:
        raw = fetcher.exchange.fetch_ohlcv(TRADING_CONFIG.symbol, tf, limit=bars)
        df = pd.DataFrame(raw, columns=["timestamp", "open", "high",
                                       "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("timestamp", inplace=True)

        mid = len(df) // 2

        print("=" * 100)
        print(f"SINYEL x SL/TP MATRISI - {tf} ({len(df)} mum, ufuk {horizon} bar)")
        print("=" * 100)
        print(f"{'SINYIL':20} {'SL':>6} {'TP':>6} {'n':>5} {'wr%':>6} "
              f"{'IS %':>8} {'OOS %':>8} {'DD %':>7} {'IS+OOS':>8}")
        print("-" * 100)

        all_rows = []
        for name, fn in SIGNALS.items():
            score = fn(df).shift(1)          # 1 bar gecikme: gelecege bakma
            score_is = score.iloc[:mid]
            score_oos = score.iloc[mid:]
            df_is = df.iloc[:mid]
            df_oos = df.iloc[mid:]

            for sl, tp in SL_TP:
                r_is = backtest(df_is, score_is, sl, tp, horizon)
                r_oos = backtest(df_oos, score_oos, sl, tp, horizon)
                tot = (r_is["cash"] * r_oos["cash"] - 1) * 100
                wr = (r_is["wins"] + r_oos["wins"]) / max(1, r_is["n"] + r_oos["n"]) * 100
                all_rows.append({
                    "name": name, "sl": sl, "tp": tp,
                    "is": r_is["ret"], "oos": r_oos["ret"],
                    "total": tot, "wr": wr, "mdd": max(r_is["mdd"], r_oos["mdd"]),
                    "n": r_is["n"] + r_oos["n"],
                })
                print(f"{name:20} {sl*100:>5.1f}% {tp*100:>5.1f}% "
                      f"{r_is['n']+r_oos['n']:>5d} {wr:>6.1f} "
                      f"{r_is['ret']:>+8.2f} {r_oos['ret']:>+8.2f} "
                      f"{max(r_is['mdd'],r_oos['mdd']):>7.1f} {tot:>+8.2f}")

        print()
        print("-" * 100)
        all_rows.sort(key=lambda r: r["total"], reverse=True)
        print("EN IYI 10 (IS+OOS birlikte)")
        print("-" * 100)
        for r in all_rows[:10]:
            flag = "OK" if (r["is"] > 0 and r["oos"] > 0) else "  "
            print(f"{flag} {r['name']:20} SL{r['sl']*100:.1f}% TP{r['tp']*100:.1f}% "
                  f"IS {r['is']:+8.2f}% OOS {r['oos']:+8.2f}% "
                  f"toplam {r['total']:+8.2f}% dd {r['mdd']:.1f}% n={r['n']}")

        both = [r for r in all_rows if r["is"] > 0 and r["oos"] > 0]
        print()
        if both:
            print(f"HER IKI DONEMDE DE KARLI: {len(both)} / {len(all_rows)}")
        else:
            print(f"HER IKI DONEMDE DE KARLI OLAN YOK (0 / {len(all_rows)}).")
            print("Bu, bu sinyallerin ve SL/TP kombinasyonlarinin")
            print("sampnada karli olmadigini gosterir.")
        print()


if __name__ == "__main__":
    main()