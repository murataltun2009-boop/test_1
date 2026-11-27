"""
Ortalamaya donus (mean-reversion) sinyal arayisi.

NEDEN BU YON
------------
Mevcut sinyal momentum yonlu:
  - MA bileseni: "fiyat MA'nin ustunde -> Al"  = uzatilmis pozisyona giris
  - ADX, bull_power, ao -> guclu trendi OLUMLU sayar
Olcum bunun ters yonlu calistigini gosterdi (MAE > MFE), yani ortalama-donus
sinyali trend sinyali olarak kullaniliyor.

Burada CANDIDATE ortalam-donus formulleri denenir ve her birinin kenari
olculur. En iyi olan SADECE olcumde ise yurutulur.

DEGERLENDIRME
-------------
  - Ileri N bar getirisi (correlation)
  - SL/TP ile kazanma orani
  - Ucret SONRASI net beklenti (bar basina, R cinsinden)
  - IS/OOS bolunmesi ile dayaniklilik

Kullanim:  python research/mean_reversion.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from config import TRADING_CONFIG            # noqa: E402
from data.fetcher import DataFetcher         # noqa: E402
from indicators.calculator import rma, rsi, stoch  # noqa: E402

logging.basicConfig(level=logging.ERROR)

FEE = 0.0010          # giris + cikis (taker %0.05 x 2)
HORIZON = 6           # 4h icin 24 saat


# --------------------------------------------------------------------------
# Yardimcilar
# --------------------------------------------------------------------------

def true_range(df: pd.DataFrame) -> pd.Series:
    prev = df["close"].shift(1)
    return pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev).abs(),
        (df["low"] - prev).abs(),
    ], axis=1).max(axis=1)


def rolling_z(price: pd.Series, n: int) -> pd.Series:
    """(fiyat - ortalama) / std  ->  z-skoru"""
    m = price.rolling(n).mean()
    s = price.rolling(n).std()
    return (price - m) / s.replace(0.0, np.nan)


# --------------------------------------------------------------------------
# CANDIDATE sinyaller  (-1..1 : pozitif = LONG, negatif = SHORT)
# --------------------------------------------------------------------------

def sig_zscore(df, n=20, entry=1.8):
    """Z-skoru ortalamaya donus: z <= -entry -> LONG, z >= +entry -> SHORT"""
    z = rolling_z(df["close"], n)
    score = -z / entry                      # z cok dusukse +1 (LONG)
    return score.clip(-1, 1).fillna(0)


def sig_bollinger(df, n=20, k=2.0):
    """Bollinger %B: alt banda dokunmak LONG, ust banda SHORT"""
    m = df["close"].rolling(n).mean()
    s = df["close"].rolling(n).std()
    up, lo = m + k * s, m - k * s
    pb = (df["close"] - lo) / (up - lo).replace(0.0, np.nan)   # 0..1
    return (1 - pb * 2).fillna(0).clip(-1, 1)                 # 0->+1 (alt), 1->-1 (ust)


def sig_rsi2(df, lo=10, hi=90):
    """RSI(2) klasik ortalam-donus (Connors tarzi)"""
    r = rsi(df["close"], 2)
    score = pd.Series(0.0, index=df.index)
    score[r <= lo] = 1.0
    score[r >= hi] = -1.0
    return score


def sig_atr_dist(df, n=20, k=1.5):
    """Fiyatin ortalamaya uzakligi, ATR ile normalize"""
    m = df["close"].rolling(n).mean()
    a = rma(true_range(df), 14)
    z = (df["close"] - m) / a.replace(0.0, np.nan)
    return (-z / k).fillna(0).clip(-1, 1)


def sig_stoch(df, n=14, d=3, entry=20):
    """Stokastik %K asiri alim/satim"""
    k, _ = stoch(df["high"], df["low"], df["close"], k_len=n, k_smooth=d)
    score = pd.Series(0.0, index=df.index)
    score[k <= entry] = 1.0
    score[k >= 100 - entry] = -1.0
    return score


def sig_williams(df, n=14, entry=-80):
    """Williams %R: -80 altinda LONG, -20 ustunde SHORT"""
    highest = df["high"].rolling(n).max()
    lowest = df["low"].rolling(n).min()
    wr = -100 * (highest - df["close"]) / (highest - lowest).replace(0.0, np.nan)
    score = pd.Series(0.0, index=df.index)
    score[wr <= entry] = 1.0
    score[wr >= -20] = -1.0
    return score.fillna(0)


def sig_momentum_fade(df, n=10, k=1.5):
    """Momentum olcumunun TERSI: hareket sonrasi duzeltme"""
    m = df["close"] - df["close"].shift(n)
    a = rma(true_range(df), 14)
    z = m / a.replace(0.0, np.nan)
    return (-z / k).fillna(0).clip(-1, 1)


def sig_composite(df):
    """En iyi birkacinin birlesimi (esit agirlik)"""
    parts = [sig_zscore(df, 20, 1.8), sig_bollinger(df, 20, 2.0),
             sig_atr_dist(df, 20, 1.5), sig_momentum_fade(df, 10, 1.5)]
    s = sum(parts) / len(parts)
    return s.clip(-1, 1)


CANDIDATES = {
    "z-score(20)":        lambda df: sig_zscore(df, 20, 1.8),
    "z-score(50)":        lambda df: sig_zscore(df, 50, 1.8),
    "Bollinger(20,2)":    lambda df: sig_bollinger(df, 20, 2.0),
    "Bollinger(50,2.5)":  lambda df: sig_bollinger(df, 50, 2.5),
    "RSI(2) 10/90":       lambda df: sig_rsi2(df, 10, 90),
    "RSI(2) 5/95":        lambda df: sig_rsi2(df, 5, 95),
    "ATR-dist(20)":       lambda df: sig_atr_dist(df, 20, 1.5),
    "Stokastik(14,20)":   lambda df: sig_stoch(df, 14, 3, 20),
    "Williams(14,-80)":   lambda df: sig_williams(df, 14, -80),
    "Momentum-fade(10)":  lambda df: sig_momentum_fade(df, 10, 1.5),
    "COMBI(4)":           sig_composite,
}


# --------------------------------------------------------------------------
# Degerlendirme
# --------------------------------------------------------------------------

def evaluate(df: pd.DataFrame, score: pd.Series, horizon=HORIZON,
             sl=0.012, tp=0.024):
    """SL/TP ile net beklenti (bar basina)."""
    n = len(df)
    wins = losses = 0
    costs = 0.0

    for i in range(n - horizon - 1):
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
            costs += tp - FEE
        elif mae <= -sl:
            losses += 1
            costs += -sl - FEE
        else:
            pass   # zaman asimi: PnL yok, sadece komisyon

    tot = wins + losses
    wr = wins / tot if tot else 0.0
    per_bar = costs / n if n else 0.0
    return {"n": tot, "wr": wr * 100, "net_bar_pct": per_bar * 100,
            "total_pct": per_bar * 100 * n}


def corr_forward(df, score, horizon=HORIZON):
    fwd = df["close"].shift(-horizon) / df["close"] - 1
    d = pd.DataFrame({"s": score, "f": fwd}).dropna()
    if len(d) < 30 or d["s"].std() == 0:
        return float("nan")
    return float(d["s"].corr(d["f"]))


def main():
    fetcher = DataFetcher()

    for tf, bars, horizon, hours in [("4h", 1500, 6, 4), ("1h", 1500, 12, 1)]:
        raw = fetcher.exchange.fetch_ohlcv(TRADING_CONFIG.symbol, tf, limit=bars)
        df = pd.DataFrame(raw, columns=["timestamp", "open", "high",
                                       "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("timestamp", inplace=True)

        print("=" * 104)
        print(f"ORTALAMAYA DONUS ARAYISI - {tf} ({len(df)} mum, "
              f"{len(df)*hours/24:.0f} gun, ufuk {horizon} bar)")
        print("=" * 104)
        print(f"{'SINEYIL':20} {'korel.':>8} {'n':>5} {'wr %':>7} "
              f"{'bar basi %':>11} {'toplam %':>10} {'IS %':>9} {'OOS %':>9}")
        print("-" * 104)

        rows = []
        for name, fn in CANDIDATES.items():
            score = fn(df).shift(1)          # 1 bar gecikmeli: gelecege bakma yok
            corr = corr_forward(df, score, horizon)
            full = evaluate(df, score, horizon)

            mid = len(df) // 2
            is_res = evaluate(df.iloc[:mid], score.iloc[:mid], horizon)
            oos_res = evaluate(df.iloc[mid:], score.iloc[mid:], horizon)

            rows.append((name, corr, full, is_res, oos_res))
            print(f"{name:20} {corr:>8.4f} {full['n']:>5d} {full['wr']:>7.1f} "
                  f"{full['net_bar_pct']:>11.5f} {full['total_pct']:>10.2f} "
                  f"{is_res['total_pct']:>9.2f} {oos_res['total_pct']:>9.2f}")

        print()
        best = max(rows, key=lambda r: r[2]["total_pct"])
        print(f"EN IYI: {best[0]} -> toplam {best[2]['total_pct']:+.2f}% "
              f"(IS {best[3]['total_pct']:+.2f}% / OOS {best[4]['total_pct']:+.2f}%)")

        # IS'de en iyi olup OOS'ta ne yapan?
        by_is = max(rows, key=lambda r: r[3]["total_pct"])
        print(f"IS'de en iyi: {by_is[0]} -> OOS'ta "
              f"{by_is[4]['total_pct']:+.2f}% "
              f"({'korunur' if by_is[4]['total_pct'] > 0 else 'bozulur'})")
        print()


if __name__ == "__main__":
    main()