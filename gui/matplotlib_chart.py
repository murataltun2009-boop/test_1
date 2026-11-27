"""
Matplotlib yedek grafik: mum grafigi + LONG/S_SHORT isaretleri + panel analizleri.
WebView yoksa veya kullanilabilir degilse bu kullanilir.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.collections import PolyCollection
from matplotlib.lines import Line2D


DARK_BG = "#0b1220"
AX_BG = "#111c31"
GRID = "#1c2942"
UP = "#26a69a"
DOWN = "#ef5350"


def _style_axes(ax):
    ax.set_facecolor(AX_BG)
    ax.grid(True, color=GRID, linewidth=0.6, alpha=0.7)
    ax.tick_params(colors="#8a99b3", labelsize=8)
    for spine in ax.spines.values():
        spine.set_color(GRID)
    ax.xaxis.label.set_color("#8a99b3")
    ax.yaxis.label.set_color("#8a99b3")


def _plot_candles(ax, df: pd.DataFrame, width_days: float = 0.6):
    """Mum grafigi."""
    opens = df["open"].to_numpy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    closes = df["close"].to_numpy()
    x = np.arange(len(df))

    up = closes >= opens
    down = ~up

    # govde: VectorizedCollection ile tek cagri (Rectangle tekil eklenemez)
    body_low = np.minimum(opens, closes)
    body_height = np.abs(closes - opens)
    flat = body_height == 0
    if flat.any():
        rng = (highs - lows)[flat]
        body_height[flat] = np.where(rng > 0, rng * 0.05, 1e-9)
    body_height = np.where(body_height > 0, body_height, 1e-9)

    colors = np.where(up, UP, DOWN)
    verts = np.empty((len(df), 4, 2), dtype=float)
    verts[:, 0, 0] = x - width_days / 2      # sol-alt
    verts[:, 1, 0] = x + width_days / 2      # sag-alt
    verts[:, 2, 0] = x + width_days / 2      # sag-ust
    verts[:, 3, 0] = x - width_days / 2      # sol-ust
    verts[:, 0, 1] = body_low
    verts[:, 1, 1] = body_low
    verts[:, 2, 1] = body_low + body_height
    verts[:, 3, 1] = body_low + body_height

    collection = PolyCollection(
        verts, facecolors=colors, edgecolors=colors, linewidths=0.6, alpha=0.92
    )
    ax.add_collection(collection)

    # fitiller
    ax.vlines(x[up], lows[up], highs[up], color=UP, linewidth=0.9)
    ax.vlines(x[down], lows[down], highs[down], color=DOWN, linewidth=0.9)

    ax.set_xlim(-1, len(df))
    ax.set_ylim(df["low"].min() * 0.999, df["high"].max() * 1.001)


def _time_labels(ax, df: pd.DataFrame, step: int):
    ticks = np.arange(0, len(df), max(1, step))
    labels = [df.index[i].strftime("%H:%M") for i in ticks]
    ax.set_xticks(ticks)
    ax.set_xticklabels(labels, rotation=0)


def _plot_trades(ax, df: pd.DataFrame, markers: List[Dict[str, Any]]):
    """LONG/SHORT noktalarini isaretle."""
    if not markers or df.empty:
        return

    for m in markers:
        px = m.get("price")
        side = m.get("side")
        kind = m.get("kind")
        if px is None:
            continue

        # x konumu: tarihe en yakin mum
        try:
            pos = df.index.get_indexer([pd.Timestamp(m["time"])], method="nearest")[0]
        except Exception:
            continue
        if pos < 0:
            continue

        if kind == "entry":
            if side == "LONG":
                y = px * 0.9975
                ax.plot(pos, y, marker="^", markersize=11, color=UP,
                        markeredgecolor="white", markeredgewidth=0.8, zorder=6)
                score = m.get("score")
                txt = f"LONG {px:,.0f}" + (f"\n{score:+.2f}" if score is not None else "")
                ax.annotate(txt, (pos, y), textcoords="offset points",
                            xytext=(0, -26), ha="center", fontsize=7,
                            color=UP, weight="bold")
            else:
                y = px * 1.0025
                ax.plot(pos, y, marker="v", markersize=11, color=DOWN,
                        markeredgecolor="white", markeredgewidth=0.8, zorder=6)
                score = m.get("score")
                txt = f"SHORT {px:,.0f}" + (f"\n{score:+.2f}" if score is not None else "")
                ax.annotate(txt, (pos, y), textcoords="offset points",
                            xytext=(0, 12), ha="center", fontsize=7,
                            color=DOWN, weight="bold")
        else:
            pnl = m.get("pnl", 0) or 0
            color = UP if pnl >= 0 else DOWN
            ax.plot(pos, px, marker="o", markersize=6, color="none",
                    markeredgecolor=color, markeredgewidth=1.6, zorder=5)
            ax.plot([pos], [px], marker="x", markersize=7, color=color, zorder=6)
            ax.annotate(f"{pnl:+,.0f}", (pos, px), textcoords="offset points",
                        xytext=(14, 0), ha="left", fontsize=7, color=color)


def _plot_overlays(ax, df: pd.DataFrame):
    """EMA/SMA + VWMA + Hull cizgileri (x = bar sirasi, mum grafigiyle hizalı)."""
    x = np.arange(len(df))
    overlays = [
        ("ema_20", "#f0b90b", "EMA20"),
        ("sma_50", "#7c8cff", "SMA50"),
        ("ema_200", "#ff7ac6", "EMA200"),
        ("vwma", "#5ad1c8", "VWMA20"),
        ("hull_ma", "#ffa14a", "Hull9"),
    ]
    for col, color, label in overlays:
        if col in df.columns and df[col].notna().any():
            ax.plot(x, df[col].to_numpy(),
                    color=color, linewidth=1.0, label=label, alpha=0.85)


def _plot_pivot_levels(ax, df: pd.DataFrame):
    """Pivot seviyelerini yatay cizgi olarak goster."""
    last = df.iloc[-1]
    levels = [
        ("r3", "#ef535077"), ("r2", "#ef535055"), ("r1", "#ef535077"),
        ("pivot", "#f0b90b88"), ("s1", "#26a69a77"), ("s2", "#26a69a55"),
        ("s3", "#26a69a77"),
    ]
    for key, color in levels:
        val = last.get(key)
        if val is None or pd.isna(val):
            continue
        ax.axhline(val, color=color, linewidth=0.8, linestyle="--", alpha=0.8)


def _panel_score(ax, df: pd.DataFrame, weight_label: str):
    """Bilesik skor grafigi (x = bar sirasi)."""
    x = np.arange(len(df))
    comp = df["composite"].to_numpy()
    ax.plot(x, comp, color="#7c8cff", linewidth=1.1, label=weight_label)
    ax.axhline(0, color="#5a6b85", linewidth=0.8)
    for lvl, color in ((0.55, "#26a69a"), (-0.55, "#ef5350"),
                       (0.30, "#26a69a66"), (-0.30, "#ef535066")):
        ax.axhline(lvl, color=color, linewidth=0.7, linestyle=":")
    ax.fill_between(x, 0, comp, where=comp >= 0, color="#26a69a33")
    ax.fill_between(x, 0, comp, where=comp < 0, color="#ef535333")
    ax.set_xlim(0, len(df))
    ax.set_ylim(-1.05, 1.05)


def _panel_rsi(ax, df: pd.DataFrame):
    if "rsi" not in df.columns:
        return
    x = np.arange(len(df))
    ax.plot(x, df["rsi"].to_numpy(), color="#f0b90b", linewidth=1.0)
    ax.axhline(70, color="#ef535077", linestyle="--", linewidth=0.7)
    ax.axhline(30, color="#26a69a77", linestyle="--", linewidth=0.7)
    ax.axhline(50, color="#5a6b85", linewidth=0.6)
    ax.set_ylim(0, 100)
    ax.set_ylabel("RSI", color="#8a99b3", fontsize=8)


def _panel_equity(ax, equity_curve: Optional[pd.DataFrame], bar_count: int):
    """Ozsermaye egrisi; x ekseni bar sirasi ile hizali."""
    if equity_curve is None or equity_curve.empty:
        ax.text(0.5, 0.5, "Özsermaye verisi yok", transform=ax.transAxes,
                ha="center", color="#8a99b3")
        return
    eq = equity_curve["equity"]
    x = np.arange(len(eq))
    ax.plot(x, eq.to_numpy(), color="#7c8cff", linewidth=1.3, label="Özsermaye")
    ax.fill_between(x, eq.min() * 0.999, eq.to_numpy(), color="#7c8cff22")
    ax.plot(x, eq.cummax().to_numpy(), color="#8a99b3",
            linewidth=0.7, linestyle="--", label="tepe")
    ax.set_xlim(0, max(1, bar_count))
    ax.set_ylabel("Özsermaye", color="#8a99b3", fontsize=8)
    ax.legend(loc="upper left", fontsize=7, facecolor=AX_BG,
              edgecolor=GRID, labelcolor="#c9d4e4")


def build_figure(df: pd.DataFrame,
                 markers: Optional[List[Dict[str, Any]]] = None,
                 signal=None,
                 equity_curve: Optional[pd.DataFrame] = None,
                 signals: Optional[pd.DataFrame] = None,
                 limit: int = 320):
    """Grafik figurunu olusturur.

    signals: SignalGenerator.generate_series ciktisi (skor paneli icin).
             Verilmezse veya 'composite' sutunu yoksa skor paneli atlanir.
    """
    if df is None or df.empty:
        return None

    data = df.tail(limit).copy()
    markers = markers or []
    # isaretleri pencereye kirp
    if data.index[0] is not None:
        markers = [m for m in markers
                   if pd.Timestamp(m.get("time")) >= data.index[0]]

    matplotlib.rcParams["figure.facecolor"] = DARK_BG
    matplotlib.rcParams["axes.facecolor"] = AX_BG

    fig, axes = plt.subplots(
        4, 1, figsize=(19, 13), sharex=True,
        gridspec_kw={"height_ratios": [3.4, 1.1, 1.0, 1.0], "hspace": 0.08},
    )
    ax_price, ax_score, ax_rsi, ax_eq = axes

    for ax in axes:
        _style_axes(ax)

    # 1) Mum + indikator cizgileri + isaretler
    _plot_candles(ax_price, data)
    _plot_overlays(ax_price, data)
    _plot_pivot_levels(ax_price, data)
    _plot_trades(ax_price, data, markers)

    title = "BTCUSDT · 1m Futures"
    if signal is not None:
        color = "#26a69a" if signal.composite > 0 else (
            "#ef5350" if signal.composite < 0 else "#8a99b3")
        title += f"   |   {signal.signal.value}   |   SKOR {signal.composite:+.3f}"
        ax_price.set_title(title, color=color, fontsize=14, weight="bold", pad=12)
    else:
        ax_price.set_title(title, color="#e6edf7", fontsize=14, weight="bold", pad=12)

    legend_handles = [
        Line2D([], [], color=UP, marker="^", linestyle="", label="LONG giriş"),
        Line2D([], [], color=DOWN, marker="v", linestyle="", label="SHORT giriş"),
        Line2D([], [], color="#9aa7bd", marker="o", linestyle="", label="Çıkış"),
    ]
    ax_price.legend(handles=legend_handles, loc="upper left", fontsize=8,
                    facecolor=AX_BG, edgecolor=GRID, labelcolor="#c9d4e4")

    # 2) Skor (sinyal serisinden; yoksa hesaplanmis kolon)
    score_df = data
    if signals is not None and not signals.empty and "composite" in signals.columns:
        sc = signals[["composite"]].reindex(data.index).dropna()
        if len(sc) > 1:
            score_df = sc
    if "composite" in score_df.columns and len(score_df) > 1:
        _panel_score(ax_score, score_df, "bileşik skor")
        # sinyal barini renklendir
        if "signal" in signals.columns and signals is not data:
            srow = signals["signal"].reindex(data.index)
            for i, sname in enumerate(srow):
                if sname == "STRONG_BUY":
                    ax.axvspan(i - 0.5, i + 0.5, color="#26a69a", alpha=0.16, zorder=0)
                elif sname == "STRONG_SELL":
                    ax.axvspan(i - 0.5, i + 0.5, color="#ef5350", alpha=0.16, zorder=0)
    else:
        ax_score.text(0.5, 0.5, "Skor verisi yok", transform=ax_score.transAxes,
                      ha="center", color="#8a99b3")
    ax_score.set_ylabel("Skor", color="#8a99b3", fontsize=8)

    # 3) RSI
    _panel_rsi(ax_rsi, data)

    # 4) Equity (bar sirasi ile hizali)
    ec = None
    if equity_curve is not None and not equity_curve.empty:
        ec = equity_curve[equity_curve.index >= data.index[0]]
        if ec.empty:
            ec = equity_curve
    _panel_equity(ax_eq, ec, len(data))

    _time_labels(ax_eq, data, step=max(1, len(data) // 12))
    ax_eq.set_xlabel("Zaman", color="#8a99b3", fontsize=9)

    fig.suptitle("BTCUSDT Futures Trading Bot — İşlem Grafiği",
                 color="#e6edf7", fontsize=16, weight="bold", y=0.995)
    return fig


def show_chart(df: pd.DataFrame,
               markers: Optional[List[Dict[str, Any]]] = None,
               signal=None,
               equity_curve: Optional[pd.DataFrame] = None,
               signals: Optional[pd.DataFrame] = None,
               limit: int = 320):
    """Grafik penceresini acar."""
    fig = build_figure(df, markers, signal, equity_curve, signals, limit)
    if fig is None:
        return
    plt.show()
