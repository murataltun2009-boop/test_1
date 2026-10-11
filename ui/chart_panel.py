"""
Canli mum grafik paneli.

Tek bir zaman dilimini gosterir: mumlar, hareketli ortalama cizgileri ve
AL/SAT/GÜÇLÜ AL/GÜÇLÜ SAT isaretleri (yildiz).

Uc yetenek:
  1. Gorunum yonetimi : tekerlek ile yakinlastirma, surukleyerek kaydirma,
                        "Sigdir" ile varsayilan gorunume donme
  2. Imlec katmani    : imlecin altindaki barin tarih/fiyat bilgisi
  3. Canli yildizlar  : sinyalin ilk ortaya ciktigi barlar

PERFORMANS NOTU (olculdu, bu makinede):
  matplotlib Agg cizimi : ~135 ms   <- asil darboz
  matplotlib Tk blit'i  : ~11 ms
  bu yuzden:
    * Veri yenilemesi (~160 ms/panel) kontrollu aralikla yapilir.
    * Imlec takibi (capraz + ipucu) matplotlib'E HIC GIRMEZ; dogrudan Tk
      widget'lari cizilir, bu yuzden anlik hareket eder.
"""
from __future__ import annotations

import time
import tkinter as tk
from datetime import datetime, timezone

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.collections import LineCollection, PolyCollection
from matplotlib.figure import Figure
from matplotlib.transforms import blended_transform_factory

import config
from core.analysis import Signal, TimeframeAnalysis

# -- renkler ----------------------------------------------------------------
BG = "#0e1621"
GRID = "#1e2a3a"
UP = "#26a69a"
DOWN = "#ef5350"
MUTED = "#7b8da4"
CROSS = "#6f8ba8"
TIP_BG = "#0a1017"
TIP_BORDER = "#3d5570"

SIGNAL_STYLE = {
    Signal.STRONG_BUY:  ("#00e676", 320),
    Signal.BUY:         ("#66bb6a", 130),
    Signal.SELL:        ("#ffa726", 130),
    Signal.STRONG_SELL: ("#ff1744", 320),
}

SIGNAL_TEXT = {
    Signal.STRONG_BUY:  "#00e676",
    Signal.BUY:         "#66bb6a",
    Signal.NEUTRAL:     "#9aa8b8",
    Signal.SELL:        "#ffa726",
    Signal.STRONG_SELL: "#ff1744",
}

# Grafikte cizilen hareketli ortalamalar (hepsi cizilirse okunmaz olur)
OVERLAY_SERIES = [
    ("ema20",  "EMA 20",  "#f7a35c"),
    ("ema50",  "EMA 50",  "#4fc3f7"),
    ("ema200", "EMA 200", "#b07cff"),
    ("sma200", "SMA 200", "#8d9db0"),
    ("hma",    "Hull 9",  "#ff8fb1"),
    ("vwma",   "VWMA 20", "#7dd6a0"),
]

MIN_VISIBLE = 25

# Fare tekerlegi adimi: factor < 1 yakinlastirir.
# 1.18 cok yavas kaliyordu (150 bardan 25 bara inmek icin ~13 tik);
# 1.35 ile yarisi kadar tik yetiyor.
WHEEL_ZOOM_STEP = 1.35

# Surukleyerek kaydirirken cizim suresi ~440 ms. Her fare hareketinde
# cizmek arayuza "kilitlenmis" hissi veriyordu; bu yuzden cizim
# debounce edilir: en gec DRAG_REDRAW_MS aralikla bir kez yapilir ve
# parmak birakilinca hemen son hali cizilir.
DRAG_REDRAW_MS = 160

# Canli fiyat cizgisi
LIVE_COLOR = "#ffd54f"


class _WheelEvent:
    """Tk <MouseWheel> olayindan turetilen basit tekerlek olayı."""

    __slots__ = ("x", "y", "delta")

    def __init__(self, tk_event, delta: int):
        self.x = tk_event.x
        self.y = tk_event.y
        self.delta = delta


def _fmt_datetime(ms: int, timeframe: str) -> str:
    """Yerel saat dilimine gore tarih/saat."""
    dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).astimezone()
    if timeframe == "1d":
        return dt.strftime("%d.%m.%Y %H:%M")
    return dt.strftime("%d.%m.%Y %H:%M")


def _fmt_num(x: float) -> str:
    return f"{x:,.2f}"


def _fmt_vol(x: float) -> str:
    if x >= 1000:
        return f"{x:,.0f}"
    return f"{x:,.2f}"


class ChartPanel:
    """Tek zaman dilimi icin matplotlib grafik + Tk imlec katmani."""

    def __init__(self, parent, timeframe: str):
        self.parent = parent
        self.timeframe = timeframe

        # --- gorunum durumu ----------------------------------------------
        self._view_count = config.VISIBLE_CANDLES
        self._view_offset = 0        # son bardan kac bar gerideyiz (0 = en son)

        # --- son veri (Sigdir icin tekrar cizmek icin) --------------------
        self._last_res: TimeframeAnalysis | None = None
        self._last_price = float("nan")
        self._last_overlay = True
        self.last_draw_ms = 0.0     # son cizimin gercek suresi
        self._draw_t0 = 0.0

        self.fig = Figure(figsize=(5.6, 2.6), dpi=100)
        self.fig.patch.set_facecolor(BG)
        self.ax = self.fig.add_subplot(111)
        # Sagda canli fiyat etiketi icin yer ac (etiket ~70 px; 0.88 ile
        # grafik alanindan tasmadan yerlestirilir)
        self.fig.subplots_adjust(right=0.88)
        self._style_axes()

        self.canvas = FigureCanvasTkAgg(self.fig, master=parent)
        self.widget = self.canvas.get_tk_widget()
        self.widget.pack(fill="both", expand=True)

        self._wicks: LineCollection | None = None
        self._bodies: PolyCollection | None = None
        self._markers = None
        self._ma_lines: dict[str, object] = {}
        self._dataset_id = -1

        # --- Tk imlec katmani ----------------------------------------------
        self._vline = tk.Frame(parent, bg=CROSS, width=1, cursor="sb_h_double_arrow")
        self._hline = tk.Frame(parent, bg=CROSS, height=1, cursor="sb_v_double_arrow")
        self._tip = tk.Label(
            parent, text="", bg=TIP_BG, fg="#e8eef6", justify="left",
            font=("Consolas", 8), bd=1, relief="solid",
            highlightthickness=0, padx=6, pady=4)
        self._tip.configure(highlightbackground=TIP_BORDER)

        # ---- canli fiyat cizgisi (Tk katmani) --------------------------
        # Mum grafigi saniyede ~1 kez yeniden cizilir (matplotlib cizimi
        # bu makinede ~500 ms). Fiyat cizgisi ise 10 Hz hareket etmeli ki
        # "canli" hissi kaybolmasin; bu yuzden matplotlib'a cizilmez,
        # dogrudan Tk widget'i olarak konumlandirilir (~0 ms).
        self._live_line = tk.Frame(parent, bg=LIVE_COLOR, height=2)
        self._live_tag = tk.Label(parent, text="", bg=LIVE_COLOR,
                                  fg="#0e1621", font=("Consolas", 8, "bold"),
                                  padx=3)
        self._live_price = float("nan")

        self._drag_from: float | None = None
        self._drag_offset: int = 0
        self._drag_after: str | None = None
        self._last_drag_draw = 0.0
        self._tick_key: tuple | None = None

        self.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.canvas.mpl_connect("figure_leave_event", self._on_leave)
        self.canvas.mpl_connect("button_press_event", self._on_press)
        self.canvas.mpl_connect("button_release_event", self._on_release)

        # Tekerlek ve cift tik Tk seviyesinde baglanir; matplotlib'in
        # scroll_event'i sadece fare tekerlegi geldiginde calisir ve
        # pencere odak degilken hic gelmez.
        self.widget.bind("<MouseWheel>", self._on_wheel)
        self.widget.bind("<Button-4>", lambda e: self._on_wheel(_WheelEvent(e, 120)))
        self.widget.bind("<Button-5>", lambda e: self._on_wheel(_WheelEvent(e, -120)))
        self.widget.bind("<Double-Button-1>", lambda _e: self.fit())
        self.widget.configure(cursor="crosshair")

        # Ipucunun uzerine gelindiginde de takip sursun
        self._tip.bind("<Motion>", self._on_tip_motion)
        self._tip.bind("<Leave>", lambda _e: None)

        # Klavye kisayollari (fare kullanmadan da gezilebilsin)
        self.widget.bind("<Left>", lambda _e: (self.pan_bars(-10), "break")[1])
        self.widget.bind("<Right>", lambda _e: (self.pan_bars(10), "break")[1])
        self.widget.bind("<plus>", lambda _e: (self.zoom(0.7), "break")[1])
        self.widget.bind("<equal>", lambda _e: (self.zoom(0.7), "break")[1])
        self.widget.bind("<minus>", lambda _e: (self.zoom(1 / 0.7), "break")[1])
        self.widget.bind("<Home>", lambda _e: (self.fit(), "break")[1])

    # ==================================================================
    # Eksen / cizim
    # ==================================================================
    def _style_axes(self) -> None:
        self.ax.set_facecolor(BG)
        self.ax.grid(True, color=GRID, linewidth=0.6, alpha=0.55)
        self.ax.set_axisbelow(True)
        for spine in self.ax.spines.values():
            spine.set_color(GRID)
        self.ax.tick_params(colors=MUTED, labelsize=7)
        for lbl in self.ax.get_xticklabels() + self.ax.get_yticklabels():
            lbl.set_color(MUTED)

    @staticmethod
    def _safe_remove(artist) -> None:
        """Cizim nesnesini kaldirir.

        matplotlib Artist.remove(), sanatci zaten eksenlerden cikarilmissa
        ValueError firlatir. Panel yeniden kuruldugunda veya bar sayisi
        arka arkaya degistiginde bu normal; testte oldugu gibi hatayi
        yutuyoruz.
        """
        if artist is None:
            return
        try:
            artist.remove()
        except (ValueError, NotImplementedError):
            pass

    def _rebuild(self, n_total: int) -> None:
        """Bar sayisi degisti: tum cizim nesnelerini bastan kur."""
        self._safe_remove(self._wicks)
        self._safe_remove(self._bodies)
        self._safe_remove(self._markers)
        for line in self._ma_lines.values():
            self._safe_remove(line)
        self._ma_lines.clear()

        self._wicks = LineCollection([], linewidths=0.8, zorder=2)
        self._bodies = PolyCollection([], linewidths=0.0, zorder=2)
        self.ax.add_collection(self._wicks)
        self.ax.add_collection(self._bodies)

        self._markers = self.ax.scatter([], [], s=[], marker="*", zorder=6,
                                        linewidths=0.9, edgecolors=BG)
        self._dataset_id = n_total

    # ==================================================================
    # Gorunum yonetimi
    # ==================================================================
    @property
    def view_range(self) -> tuple[int, int]:
        """Gosterilen bar araligi [bas, bitis)."""
        if self._last_res is None:
            return 0, config.VISIBLE_CANDLES
        n = int(self._last_res.c.size)
        count = max(MIN_VISIBLE, min(self._view_count, n))
        end = n - self._view_offset
        end = max(count, min(end, n))
        start = end - count
        return start, end

    def fit(self) -> None:
        """Varsayilan gorunume don: son 120 bar, saga yasli."""
        self._view_count = config.VISIBLE_CANDLES
        self._view_offset = 0
        self.redraw()

    def zoom(self, factor: float, anchor_x: float | None = None) -> None:
        """
        factor < 1  -> yakinlastir (daha az bar gorunur)
        factor > 1  -> uzaklastirir
        anchor_x verilirse imlecin altindaki bar sabit kalir.
        """
        n = int(self._last_res.c.size) if self._last_res is not None else 0
        if n == 0:
            return

        start, end = self.view_range
        if anchor_x is None:
            anchor_x = (start + end) / 2.0

        # imlecin gorunum icindeki normalize konumu (0 = sol, 1 = sag)
        span = max(1, end - start)
        rel = min(1.0, max(0.0, (anchor_x - start) / span))

        new_count = int(round(max(MIN_VISIBLE, min(n, self._view_count * factor))))
        # imlec yine ayni bari gosterecek sekilde kaydir
        new_end = int(round(anchor_x + (1.0 - rel) * new_count))
        new_start = new_end - new_count

        new_start = max(0, min(new_start, n - new_count))
        new_end = new_start + new_count

        self._view_count = new_count
        self._view_offset = n - new_end
        self.redraw()

    def pan(self, delta_bars: float) -> None:
        n = int(self._last_res.c.size) if self._last_res is not None else 0
        if n == 0:
            return
        start, end = self.view_range
        count = end - start
        new_start = int(round(start + delta_bars))
        new_start = max(0, min(new_start, n - count))
        self._view_offset = n - (new_start + count)
        self.redraw()

    def pan_bars(self, delta_bars: int) -> None:
        """Ok tuslari / dugmeler icin: sabit bar sayisi kadar kaydir."""
        self.pan(delta_bars)

    def redraw(self) -> None:
        if self._last_res is None:
            return
        self.update(self._last_res, self._last_price, self._last_overlay)

    # ==================================================================
    # Imlec olaylari
    # ==================================================================
    def _on_wheel(self, event) -> str:
        """Tekerlek: imlecin altindaki bar sabit kalacak sekilde yakinlastir."""
        if self._last_res is None or self._last_res.c.size == 0:
            return "break"
        fw = max(1.0, self._fig_px()[0])
        rel = min(1.0, max(0.0, event.x / fw))
        lo, hi = self.ax.get_xlim()
        span = hi - lo
        anchor = lo + span * rel
        # zoom() icin factor < 1 yakinlastirir (bar sayisi azalir).
        # Tekerlek yukarı (delta > 0) -> yakinlastir.
        self.zoom(1 / WHEEL_ZOOM_STEP if event.delta > 0 else WHEEL_ZOOM_STEP,
                  anchor)
        return "break"

    def _on_motion(self, event) -> None:
        if self._drag_from is not None:
            self._handle_drag(event)
            self._hide_cursor_layer()
            return
        if self._last_res is None:
            self._hide_cursor_layer()
            return
        self._point_at(float(event.x), float(event.y))

    def _on_tip_motion(self, _event) -> None:
        """Ipucunun uzerine gelindiginde de capraz takibi surdurur."""
        if self._last_res is None:
            return
        px = self.widget.winfo_pointerx() - self.widget.winfo_rootx()
        py = self.widget.winfo_pointery() - self.widget.winfo_rooty()
        self._point_at(float(px), float(py))

    def _point_at(self, px: float, py: float) -> None:
        """Eksen koordinatindaki (px, py) noktasina gore ipucunu guncelle."""
        ax_x0, ax_y0, ax_w, ax_h = self._axes_rect_tk()
        if not (ax_x0 <= px <= ax_x0 + ax_w and ax_y0 <= py <= ax_y0 + ax_h):
            self._hide_cursor_layer()
            return

        lo, hi = self.ax.get_xlim()
        xdata = lo + (px - ax_x0) / max(1e-9, ax_w) * (hi - lo)

        start, end = self.view_range
        idx = int(round(xdata))
        if idx < start or idx >= end or idx >= self._last_res.c.size:
            self._hide_cursor_layer()
            return

        self._show_cursor_layer(px, py, idx)

    # ------------------------------------------------------------------
    def _on_leave(self, _event) -> None:
        """
        Imlec grafikten cikinca ipucunu gizle.

        ONEMLI: Tk, imlec HAREKETINI seyreltir (coalesce) - iki olay
        arasinda imlec 20-40 piksel ziplayabilir. Ipucu kutusu imlecin
        14 piksel yanina yerlestirildigi icin imlec kutunun USTUNE
        girebilir; o zaman canvas <Leave> alir ve ipucu kendini siler
        (kullanici "yildizlarin uzerine gelince bilgilendirme kayboluyor"
        diyordu).

        Cozum: cikis olayinda imlecin gercekten grafik alaninin disinda
        olup olmadigina bakilir. Icidedirsa hicbir sey yapilmaz.
        """
        px = self.widget.winfo_pointerx() - self.widget.winfo_rootx()
        py = self.widget.winfo_pointery() - self.widget.winfo_rooty()
        if 0 <= px <= self.widget.winfo_width() and \
                0 <= py <= self.widget.winfo_height():
            return          # imlec hala grafik alaninda (ipucunun uzerinde)
        self._hide_cursor_layer()

    def _on_press(self, event) -> None:
        if event.inaxes is not self.ax or event.xdata is None:
            return
        self._drag_from = float(event.xdata)
        self._drag_offset = self._view_offset
        self._hide_cursor_layer()

    def _on_release(self, _event) -> None:
        self._drag_from = None
        # Bekleyen debounce varsa iptal et ve son hali hemen ciz.
        if self._drag_after is not None:
            try:
                self.widget.after_cancel(self._drag_after)
            except Exception:      # noqa: BLE001
                pass
            self._drag_after = None
        self.redraw()

    def _handle_drag(self, event) -> None:
        if event.xdata is None or self._last_res is None:
            return
        delta = float(event.xdata) - self._drag_from
        n = int(self._last_res.c.size)
        count = max(MIN_VISIBLE, min(self._view_count, n))
        # SAGA suruklemek (delta > 0) gecmise dogru kaydirir.
        new_start = (n - self._drag_offset - count) - delta
        new_start = max(0.0, min(new_start, float(n - count)))
        self._view_offset = int(round(n - (new_start + count)))
        self._schedule_drag_redraw()

    # ------------------------------------------------------------------
    def _schedule_drag_redraw(self) -> None:
        """Surukleme sirasinda cizimi debounce et."""
        now = time.monotonic()
        if self._drag_after is not None:
            if (now - self._last_drag_draw) * 1000.0 < DRAG_REDRAW_MS:
                return                      # henuz yeterli zaman gecmedi
            try:
                self.widget.after_cancel(self._drag_after)
            except Exception:      # noqa: BLE001
                pass
        self._last_drag_draw = now
        self._drag_after = self.widget.after(1, self._drag_redraw)

    def _drag_redraw(self) -> None:
        self._drag_after = None
        self.redraw()

    # ==================================================================
    # Tk capraz + ipucu
    # ==================================================================
    def _fig_px(self) -> tuple[float, float]:
        return (self.fig.get_figwidth() * self.fig.dpi,
                self.fig.get_figheight() * self.fig.dpi)

    def _axes_rect_tk(self) -> tuple[float, float, float, float]:
        """Eksen alaninin Tk koordinatlari: (x0, y0, genislik, yukseklik)."""
        # matplotlib 3.x get_position() Bbox donuyor
        x0f, y0f, wf, hf = self.ax.get_position().bounds
        fw, fh = self._fig_px()
        x0 = x0f * fw
        w = wf * fw
        h = hf * fh
        y0 = fh - (y0f + hf) * fh              # Tk'de y asagi
        return x0, y0, w, h

    def _show_cursor_layer(self, px: float, py: float, idx: int) -> None:
        res = self._last_res
        sig = res.signals[idx]

        rising = res.c[idx] >= res.o[idx]
        ohlc_color = UP if rising else DOWN

        sig_text = ""
        if sig is not Signal.NEUTRAL:
            sig_text = f"\u2605 {sig.value}"

        lines = [
            _fmt_datetime(int(res.open_times[idx]), self.timeframe),
            f"AC  {_fmt_num(res.o[idx])}    Y\u0130 {_fmt_num(res.h[idx])}",
            f"KAP {_fmt_num(res.c[idx])}    D\u0130\u015f {_fmt_num(res.l[idx])}",
            f"Hacim {_fmt_vol(res.v[idx])}",
        ]
        if sig_text:
            lines.append(sig_text)

        self._tip.configure(text="\n".join(lines), fg=ohlc_color)

        ax_x0, ax_y0, ax_w, ax_h = self._axes_rect_tk()
        cw = max(1, self.widget.winfo_width())
        ch = max(1, self.widget.winfo_height())

        cx = min(max(px, ax_x0), ax_x0 + ax_w)
        cy = min(max(py, ax_y0), ax_y0 + ax_h)

        self._vline.place(x=int(cx), y=int(ax_y0), width=1, height=int(ax_h))
        self._hline.place(x=int(ax_x0), y=int(cy), width=int(ax_w), height=1)

        self._vline.lift()
        self._hline.lift()

        # ipucu kutusu: imlecin sagina, yoksa soluna
        self._tip.update_idletasks()
        tw = self._tip.winfo_reqwidth()
        th = self._tip.winfo_reqheight()
        tx = cx + 14
        if tx + tw > cw:
            tx = cx - tw - 14
        tx = max(2, min(tx, cw - tw - 2))
        ty = cy - th - 12
        if ty < 2:
            ty = min(cy + 14, ch - th - 2)
        self._tip.place(x=int(tx), y=int(ty))
        self._tip.lift()

    def _hide_cursor_layer(self) -> None:
        self._vline.place_forget()
        self._hline.place_forget()
        self._tip.place_forget()

    # ==================================================================
    # Canli fiyat cizgisi (Tk, anlik)
    # ==================================================================
    def set_live_price(self, price: float) -> None:
        """
        Canli fiyat cizgisini guncelle.

        Arayuz 10 Hz'de cagririr. matplotlib'in cizim suresi ~500 ms
        oldugu icin mumlar ancak ~2 Hz tazelenir; bu cizgi aradaki boslukta
        fiyatin gercekten hareket ettigini gosterir.
        """
        self._live_price = price
        self._place_live_line()

    def _place_live_line(self) -> None:
        price = self._live_price
        if (self._last_res is None or not np.isfinite(price)
                or self.widget.winfo_width() < 10):
            self._live_line.place_forget()
            self._live_tag.place_forget()
            return

        lo, hi = self.ax.get_ylim()
        if not (lo <= price <= hi):
            self._live_line.place_forget()
            self._live_tag.place_forget()
            return

        ax_x0, ax_y0, ax_w, ax_h = self._axes_rect_tk()
        _, py = self.ax.transData.transform((0.0, float(price)))

        self._live_line.place(x=int(ax_x0), y=int(py) - 1,
                              width=int(ax_w), height=2)
        self._live_tag.configure(text=f" {price:,.2f} ")
        self._live_tag.update_idletasks()
        self._live_tag.place(x=int(ax_x0 + ax_w) + 2, y=int(py) - 9)
        self._live_line.lift()
        self._live_tag.lift()

    # ==================================================================
    # Ana cizim
    # ==================================================================
    def update(self, res: TimeframeAnalysis, price: float,
               show_overlay: bool = True) -> None:
        n_total = int(res.c.size)
        if n_total == 0:
            return

        self._last_res = res
        self._last_price = price
        self._last_overlay = show_overlay

        if n_total != self._dataset_id:
            self._rebuild(n_total)

        start, end = self.view_range
        x = np.arange(start, end)
        o, h, l, c = res.o[start:end], res.h[start:end], res.l[start:end], res.c[start:end]

        # ---- mumlar -------------------------------------------------------
        body_color = np.where(c >= o, UP, DOWN)
        self._wicks.set_segments([((xi, hi), (xi, li)) for xi, hi, li in zip(x, h, l)])
        self._wicks.set_colors(body_color)

        half = 0.34
        hgt = np.maximum(np.abs(c - o), (h.max() - l.min()) * 0.0005 + 1e-9)
        body_low = np.minimum(o, c)
        self._bodies.set_verts([
            [(xi - half, y0), (xi + half, y0), (xi + half, y0 + y1), (xi - half, y0 + y1)]
            for xi, y0, y1 in zip(x, body_low, hgt)
        ])
        self._bodies.set_facecolors(body_color)
        self._bodies.set_edgecolors(body_color)

        # ---- hareketli ortalamalar ---------------------------------------
        self._update_overlay(res, start, show_overlay)

        # ---- sinyal isaretleri -------------------------------------------
        self._update_markers(res, start)

        # ---- eksenler -----------------------------------------------------
        pad = max(1.0, (x[-1] - x[0] + 1) * 0.06)
        lo_p, hi_p = float(l.min()), float(h.max())
        span = (hi_p - lo_p) or 1.0
        self.ax.set_xlim(x[0] - pad, x[-1] + pad)
        self.ax.set_ylim(lo_p - span * 0.12, hi_p + span * 0.14)

        self._update_time_ticks(res, start, end)

        # ---- canli fiyat cizgisi -----------------------------------------
        live = price if price == price else float(c[-1])
        self._live_price = live
        self._place_live_line()

        sig = res.signal
        off = self._view_offset
        view_note = "" if off == 0 else f"   \u2190 {off} bar geride"
        self.ax.set_title(
            f"{config.TF_LABELS.get(self.timeframe, self.timeframe)}   "
            f"{self._trend_arrow(res.composite)}   {sig.value}{view_note}",
            color=SIGNAL_TEXT[sig], fontsize=9, fontweight="bold",
            loc="left", pad=6,
        )

        self.canvas.draw_idle()
        self._mark_draw()

    # ------------------------------------------------------------------
    def _mark_draw(self) -> None:
        """
        Cizimin GERCEK suresini olcer.

        draw_idle() aninda cizim yapilmaz; Tk bos zamanda yapar. Bu yuzden
        cizim istegi verildigi an ile bos zamandaki geri donus arasindaki
        fark olculur. Donus degerine gore ana pencere yenileme araligini
        kendisi ayarlar (bkz. config.CHART_HEADROOM).

        NOT: geri donus `after_idle` ile planlanir, `after(0)` ile degil.
        Tk bos zaman gorevleri FIFO isledigi icin once cizim, sonra bizim
        geri donusumuz calisir. `after(0)` bir zamanlayicidir ve cizimden
        ONCE tetiklenip sureyi 1 ms gibi olcuyordu.
        """
        self._draw_t0 = time.perf_counter()
        self.widget.after_idle(self._on_drawn)

    def _on_drawn(self) -> None:
        if self._draw_t0:
            self.last_draw_ms = (time.perf_counter() - self._draw_t0) * 1000.0
            self._draw_t0 = 0.0

    # ------------------------------------------------------------------
    @staticmethod
    def _trend_arrow(composite: np.ndarray) -> str:
        """Bilesik skorun yonunu tek okla gosterir."""
        if composite.size < 6:
            return ""
        now = float(composite[-1])
        ago = float(composite[-6])
        if not (np.isfinite(now) and np.isfinite(ago)):
            return "?"
        if now > ago + 0.05:
            return "Yükseliş ▲"
        if now < ago - 0.05:
            return "Düşüş ▼"
        return "Yatay ►"

    # ------------------------------------------------------------------
    def _update_overlay(self, res: TimeframeAnalysis, start: int, show: bool) -> None:
        if not show:
            for line in self._ma_lines.values():
                line.set_visible(False)
            return

        x = np.arange(start, int(res.c.size))
        for key, label, color in OVERLAY_SERIES:
            series = res.ma_series.get(key)
            if series is None:
                continue
            y = series[start:]
            line = self._ma_lines.get(key)
            if line is None:
                (line,) = self.ax.plot(x, y, color=color, linewidth=1.0,
                                      label=label, alpha=0.85, zorder=3)
                self._ma_lines[key] = line
            else:
                line.set_data(x, y)
                line.set_visible(True)

    # ------------------------------------------------------------------
    def _update_markers(self, res: TimeframeAnalysis, start: int) -> None:
        idx = [i for i in res.marker_indices() if i >= start]
        if not idx:
            self._markers.set_offsets(np.empty((0, 2)))
            self._markers.set_sizes(np.empty((0,)))
            return

        span = float(res.h.max() - res.l.min()) or 1.0
        margin = span * 0.015

        xs, ys, sizes, colors = [], [], [], []
        for i in idx:
            sig = res.signals[i]
            color, size = SIGNAL_STYLE[sig]
            push = margin * (1.0 + 1.1 * (abs(sig.strength) - 1))
            y = (float(res.l[i]) - push) if sig.strength > 0 \
                else (float(res.h[i]) + push)
            xs.append(i)
            ys.append(y)
            sizes.append(size)
            colors.append(color)

        self._markers.set_offsets(np.column_stack([xs, ys]))
        self._markers.set_sizes(np.array(sizes, dtype=float))
        self._markers.set_facecolors(colors)

    # ------------------------------------------------------------------
    def _update_time_ticks(self, res: TimeframeAnalysis, start: int, end: int) -> None:
        count = end - start
        step = max(1, count // 6)
        positions = list(range(start, end, step))
        if positions and positions[-1] != end - 1:
            positions.append(end - 1)
        labels = [_fmt_datetime(int(res.open_times[i]), self.timeframe)
                  for i in positions]

        # Metin yerlesimi pahalidir (~100 ms). Konumlar ve etiketler
        # degismediyse hiç dokunma.
        key = (tuple(positions), tuple(labels))
        if key == self._tick_key:
            return
        self._tick_key = key
        self.ax.set_xticks(positions)
        self.ax.set_xticklabels(labels, fontsize=6, color=MUTED, rotation=0)

    # ------------------------------------------------------------------
    def legend_text(self) -> str:
        if not self._ma_lines:
            return "Ortalama cizgileri kapali"
        return "   ".join(label for _, label, _ in OVERLAY_SERIES)
