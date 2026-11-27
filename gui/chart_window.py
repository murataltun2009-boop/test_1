"""
Lightweight Charts penceresi (pywebview) - ayri pencere icinde grafik.

pywebview kurulu degilse ya da WebView2 bulunamazsa None doner;
GUI bu durumda matplotlib yedek grafigine duser.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

CHART_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chart.html")


def _to_lightweight(df: pd.DataFrame, limit: int = 400) -> List[Dict[str, Any]]:
    """OHLCV DataFrame -> lightweight-charts candle listesi."""
    if df is None or df.empty:
        return []

    data = df.tail(limit).copy()
    data["time"] = data.index.astype("int64") // 10**9   # unix saniye

    rows: List[Dict[str, Any]] = []
    for ts, r in data.iterrows():
        rows.append({
            "time": int(ts.timestamp()),
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
            "volume": float(r["volume"]) if "volume" in r else 0.0,
        })
    rows.sort(key=lambda x: x["time"])
    return rows


def _rsi_series(df: pd.DataFrame, limit: int = 400) -> List[Dict[str, Any]]:
    if df is None or "rsi" not in df.columns or df.empty:
        return []
    out = []
    for ts, v in df["rsi"].tail(limit).items():
        if pd.notna(v):
            out.append({"time": int(ts.timestamp()), "value": round(float(v), 2)})
    return out


def _equity_series(equity_curve: Optional[pd.DataFrame], limit: int = 400) -> List[Dict[str, Any]]:
    if equity_curve is None or equity_curve.empty:
        return []
    out = []
    for ts, v in equity_curve["equity"].tail(limit).items():
        if pd.notna(v):
            out.append({"time": int(ts.timestamp()), "value": round(float(v), 2)})
    return out


def _group_markers(markers: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    entries, exits = [], []
    for m in markers:
        ts = pd.Timestamp(m.get("time"))
        if ts is None or pd.isna(ts):
            continue
        if m.get("kind") == "entry":
            entries.append({"time": int(ts.timestamp()),
                            "price": m.get("price"), "side": m.get("side"),
                            "score": m.get("score")})
        else:
            exits.append({"time": int(ts.timestamp()),
                          "pnl": m.get("pnl"), "side": m.get("side")})
    entries.sort(key=lambda x: x["time"])
    exits.sort(key=lambda x: x["time"])
    return {"entry": entries, "exit": exits}


class ChartWindow:
    """Lightweight Charts tabanli grafik penceresi."""

    def __init__(self, title: str = "BTCUSDT Grafik"):
        self.title = title
        self.window = None
        self.webview = None
        self._lock = threading.Lock()
        self._latest_js: Optional[str] = None
        self._available = self._check_webview()

    # ------------------------------------------------------------------
    @staticmethod
    def _check_webview() -> bool:
        try:
            import webview  # noqa: F401
            return True
        except Exception as exc:  # pragma: no cover
            logger.warning("pywebview yok (%s) - matplotlib grafik kullanilacak", exc)
            return False

    @property
    def available(self) -> bool:
        return self._available

    # ------------------------------------------------------------------
    def open(self, df: pd.DataFrame = None,
             signal: Dict[str, Any] = None,
             markers: List[Dict[str, Any]] = None,
             equity_curve: Optional[pd.DataFrame] = None) -> bool:
        """Grafik penceresini acar ve ilk veriyi yukler."""
        if not self._available:
            return False

        self._publish(df, signal, markers, equity_curve)

        try:
            import webview
        except Exception as exc:  # pragma: no cover
            logger.error("webview import hatasi: %s", exc)
            self._available = False
            return False

        def on_loaded():
            self._push()

        try:
            self.window = webview.create_window(
                self.title, CHART_HTML, js_api=None,
                width=1400, height=820,
                background_color="#0b1220",
            )
            self.webview = webview

            def start():
                self.window.events.loaded += on_loaded
                webview.start()

            threading.Thread(target=start, daemon=True).start()
            return True

        except Exception as exc:  # pragma: no cover
            logger.error("WebView penceresi acilamadi: %s", exc)
            self._available = False
            return False

    # ------------------------------------------------------------------
    def _publish(self, df, signal, markers, equity_curve) -> None:
        with self._lock:
            self._latest_js = self._build_js(df, signal, markers, equity_curve)

    @staticmethod
    def _build_js(df, signal, markers, equity_curve) -> str:
        payload = {
            "candles": _to_lightweight(df) if df is not None else [],
            "rsi": _rsi_series(df) if df is not None else [],
            "equity": _equity_series(equity_curve),
            "signal": signal or {},
            "markers": _group_markers(markers or []),
        }
        data_json = json.dumps(payload, default=str)
        return (
            f"window.__candles = {json.dumps(payload['candles'])};"
            f"window.__rsi = {json.dumps(payload['rsi'])};"
            f"window.__equity = {json.dumps(payload['equity'])};"
            f"window.__signal = {json.dumps(payload['signal'], default=str)};"
            f"markerData = {json.dumps(payload['markers'])};"
            "apply();"
        )

    # ------------------------------------------------------------------
    def update(self, df: pd.DataFrame = None,
               signal: Dict[str, Any] = None,
               markers: List[Dict[str, Any]] = None,
               equity_curve: Optional[pd.DataFrame] = None) -> None:
        """Acik pencereye yeni veri gonderir."""
        if self.window is None:
            return
        self._publish(df, signal, markers, equity_curve)
        self._push()

    def _push(self) -> None:
        with self._lock:
            js = self._latest_js
        if not js or self.window is None:
            return
        try:
            self.window.evaluate_js(js)
        except Exception as exc:  # pragma: no cover
            logger.debug("JS gonderilemedi: %s", exc)

    # ------------------------------------------------------------------
    def close(self) -> None:
        try:
            if self.window is not None:
                self.window.destroy()
        except Exception:  # pragma: no cover
            pass
        finally:
            self.window = None
