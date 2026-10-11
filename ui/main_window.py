"""
Ana pencere - TEK zaman dilimi (4 saat) icin buyuk grafik.

Yerlesim:
  +---------------------------------------------------------------+
  | Kontrol cubugu: sembol | esikler | yenileme | DB | baslat       |
  +-----------------------------------------+---------------------+
  |                                         |  Osilatörler       |
  |            BUYUK GRAFIK                 |  (11 satir)        |
  |                                         +---------------------+
  |                                         |  Hareketli Ort.    |
  |                                         |  (15 satir)        |
  +-----------------------------------------+---------------------+
  | Islem degisim logu (kucuk, gizlenebilir)                      |
  +---------------------------------------------------------------+
  | durum cubugu                                                 |
  +---------------------------------------------------------------+

Once 3 zaman dilimi yan yana gosteriliyordu; kullanici tek 4 saatlik
dilim istedi ve grafigin buyuk olmasini soyledi. Log paneli de kuculdu ki
grafik yer kazansin.
"""
from __future__ import annotations

import os
import tkinter as tk
import time
from datetime import datetime
from tkinter import messagebox

import customtkinter as ctk

import config
from core.analysis import Signal, TimeframeAnalysis
from core.service import MarketService
from ui.chart_panel import ChartPanel, SIGNAL_TEXT
from ui.log_panel import LogPanel
from ui.tables_panel import TablesColumn

BG = "#0a1017"
PANEL_BG = "#111a26"
BORDER = "#22303f"
LIVE_COLOR = "#ffd54f"

SIGNAL_BADGE_BG = {
    Signal.STRONG_BUY:  "#0d3b22",
    Signal.BUY:         "#12291c",
    Signal.NEUTRAL:     "#1c2531",
    Signal.SELL:        "#2e2312",
    Signal.STRONG_SELL: "#3b1417",
}

# Gösterge tablosunun sabit genisligi: grafik kalan yerleri alir.
#
# Iki tablo yan yana duruyor ve her biri 3 sutun istiyor
# (Ad 136 + Değer 62 + Detay 44 = 242 px). 430 px verildiginde "Detay"
# sutunu kirpiliyordu - ki o sutun kullaniciya gore "işlem detayı" en
# onemli bilgi. 500 px iki tabloya da 248 px verir, kirpma olmaz.
TABLES_WIDTH = 500


def _counts(rows) -> dict:
    out = {1: 0, 0: 0, -1: 0}
    for r in rows:
        out[r.verdict.value] += 1
    return out


class MainWindow(ctk.CTk):
    def __init__(self, settings: config.Settings, service: MarketService, store):
        super().__init__()
        self.settings = settings
        self.service = service
        self.store = store
        # Aktif dilimi tercih et. config.TIMEFRAMES sirali oldugu icin
        # timeframes[0] 15m'ye dustugu icin liste basi kullanilmaz.
        self.timeframe = settings.active_timeframe \
            if settings.active_timeframe in settings.timeframes \
            else (settings.timeframes[0] if settings.timeframes
                  else config.ACTIVE_TIMEFRAME)

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self.title(f"{self.timeframe} {self.settings.symbol} · Canlı Teknik "
                   f"Analiz · Binance Futures")
        self._fit_to_screen(1500, 950)
        self.configure(fg_color=BG)

        self._latest_snap: dict | None = None
        self._rendered_version = -1
        self._last_db_refresh = 0.0
        self._badge_signal: Signal | None = None
        self.chart_headroom = config.CHART_HEADROOM
        self.chart_min_interval = config.CHART_MIN_INTERVAL_MS

        self._build_toolbar()
        self._build_body()
        self._build_log()

        self.status = ctk.CTkLabel(self, text="Hazır", anchor="w",
                                   font=ctk.CTkFont(size=9), text_color="#6b7c8f")
        self.status.grid(row=3, column=0, sticky="ew", padx=12, pady=(2, 4))

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(config.GUI_TICK_MS, self._pump)
        self.after(700, self._chart_tick)

    # ==================================================================
    # Kurulum
    # ==================================================================
    def _fit_to_screen(self, want_w: int, want_h: int) -> None:
        """
        Pencereyi EKRANA SIGDIRIR ve ortalar.

        Sabit geometry vermek tehlikeli: 1366x768 bir ekranda 1400px pencere
        acilinca sag taraf ekran disinda kalir ve "Baslat" / "DB Sifirla"
        butonlarina erisilemez (olculdu: ekran 1366, butonlar x=1420-1524).
        """
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w = max(960, min(want_w, sw - 20))
        h = max(560, min(want_h, sh - 90))
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(min(1024, w), min(560, h))

    # ------------------------------------------------------------------
    def _build_toolbar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="#0f1721", corner_radius=0,
                           border_width=0)
        bar.grid(row=0, column=0, sticky="ew")
        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.grid(row=0, column=0, sticky="ew", padx=10, pady=6)
        bar.grid_columnconfigure(0, weight=1)

        lbl = ctk.CTkFont(size=8)
        small = ctk.CTkFont(size=10)
        col = 0

        # --- sembol -------------------------------------------------------
        ctk.CTkLabel(inner, text="SEMBOL", font=lbl,
                     text_color="#6b7c8f").grid(row=0, column=col, sticky="w")
        self.symbol_entry = ctk.CTkEntry(inner, width=96, height=26,
                                         font=ctk.CTkFont(size=11, weight="bold"))
        self.symbol_entry.insert(0, self.settings.symbol)
        self.symbol_entry.grid(row=1, column=col, sticky="w")
        col += 1

        # --- zaman dilimi (SABIT - kullanici tek dilim istedi) -------------
        ctk.CTkLabel(inner, text="ZAMAN DİLİMİ", font=lbl,
                     text_color="#6b7c8f").grid(row=0, column=col, sticky="w",
                                               padx=(12, 0))
        tf_label = ctk.CTkLabel(inner, text=config.TF_LABELS[self.timeframe],
                                width=104, height=26, corner_radius=4,
                                fg_color="#1b2836", text_color="#e8eef6",
                                font=ctk.CTkFont(size=11, weight="bold"))
        tf_label.grid(row=1, column=col, sticky="w", padx=(12, 0))
        col += 1

        # --- esikler -------------------------------------------------------
        ctk.CTkLabel(inner, text="GÜÇLÜ", font=lbl,
                     text_color="#6b7c8f").grid(row=0, column=col, sticky="w",
                                               padx=(12, 0))
        self.strong_entry = ctk.CTkEntry(inner, width=54, height=26, font=small)
        self.strong_entry.insert(0, f"{self.settings.strong_threshold:.2f}")
        self.strong_entry.grid(row=1, column=col, sticky="w", padx=(12, 0))
        col += 1

        ctk.CTkLabel(inner, text="AL/SAT", font=lbl,
                     text_color="#6b7c8f").grid(row=0, column=col, sticky="w",
                                               padx=(6, 0))
        self.base_entry = ctk.CTkEntry(inner, width=54, height=26, font=small)
        self.base_entry.insert(0, f"{self.settings.base_threshold:.2f}")
        self.base_entry.grid(row=1, column=col, sticky="w", padx=(6, 0))
        col += 1

        ctk.CTkButton(inner, text="Uygula", width=60, height=26, font=small,
                      command=self._on_apply_thresholds).grid(
            row=1, column=col, padx=(8, 0))
        col += 1

        # --- anahtarlar ----------------------------------------------------
        opts = ctk.CTkFrame(inner, fg_color="transparent")
        opts.grid(row=1, column=col, sticky="w", padx=(12, 0))
        self.overlay_switch = ctk.CTkSwitch(opts, text="Ort. çizgileri",
                                            font=small, width=38,
                                            command=self._on_toggle_overlay)
        self.overlay_switch.select()
        self.overlay_switch.grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.neutral_switch = ctk.CTkSwitch(opts, text="NÖTR'ü kaydet",
                                            font=small, width=38,
                                            command=self._on_toggle_neutral)
        self.neutral_switch.grid(row=0, column=1, sticky="w")
        col += 1

        # --- yenileme ------------------------------------------------------
        ctk.CTkLabel(inner, text="YENİLEME", font=lbl,
                     text_color="#6b7c8f").grid(row=0, column=col, sticky="w",
                                               padx=(12, 0))
        self.refresh_combo = ctk.CTkComboBox(
            inner, values=list(config.REFRESH_MODES.keys()), width=104, height=26,
            state="readonly", font=small, command=self._on_refresh_mode)
        self.refresh_combo.set(config.DEFAULT_REFRESH_MODE)
        self.refresh_combo.grid(row=1, column=col, sticky="w", padx=(12, 0))
        self.refresh_lbl = ctk.CTkLabel(inner, text="", font=lbl,
                                        text_color="#5c6b7c", anchor="w")
        self.refresh_lbl.grid(row=0, column=col, sticky="w", padx=(12, 0),
                              pady=(12, 0))
        col += 1

        # --- sag taraf -----------------------------------------------------
        right = ctk.CTkFrame(inner, fg_color="transparent")
        right.grid(row=0, column=col, rowspan=2, sticky="e")
        inner.grid_columnconfigure(col, weight=1)

        self.db_lbl = ctk.CTkLabel(right, text="", anchor="e", font=lbl,
                                   text_color="#6b7c8f")
        self.db_lbl.grid(row=0, column=0, sticky="e")

        actions = ctk.CTkFrame(right, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="e")
        ctk.CTkButton(actions, text="DB Sıfırla", width=84, height=26,
                      font=small, fg_color="#8b3a3f", hover_color="#a4464c",
                      command=self._on_reset_db).grid(row=0, column=0, padx=(0, 6))
        self.start_btn = ctk.CTkButton(actions, text="Başlat", width=80, height=26,
                                       font=ctk.CTkFont(size=10, weight="bold"),
                                       fg_color="#1f6f4a", hover_color="#27855a",
                                       command=self._on_start)
        self.start_btn.grid(row=0, column=1)
        self._refresh_db_label()

    # ------------------------------------------------------------------
    def _build_body(self) -> None:
        """Grafik (buyuk) + gosterge tablolari."""
        body = ctk.CTkFrame(self, fg_color=PANEL_BG, corner_radius=8,
                            border_width=1, border_color=BORDER)
        body.grid(row=1, column=0, sticky="nsew", padx=8, pady=(8, 0))

        # --- ust serit ------------------------------------------------------
        head = ctk.CTkFrame(body, fg_color="transparent")
        head.grid(row=0, column=0, columnspan=2, sticky="ew", padx=12,
                  pady=(8, 0))

        self.title_lbl = ctk.CTkLabel(
            head, text=f"{config.TF_LABELS[self.timeframe]} · {self.timeframe}",
            font=ctk.CTkFont(size=15, weight="bold"), text_color="#e8eef6")
        self.title_lbl.pack(side="left")

        self.badge = ctk.CTkLabel(head, text="NÖTR", width=96, height=24,
                                  corner_radius=12,
                                  fg_color=SIGNAL_BADGE_BG[Signal.NEUTRAL],
                                  text_color="#9aa8b8",
                                  font=ctk.CTkFont(size=11, weight="bold"))
        self.badge.pack(side="left", padx=12)

        self.price_lbl = ctk.CTkLabel(head, text="—",
                                      font=ctk.CTkFont(size=16, weight="bold"),
                                      text_color="#e8eef6")
        self.price_lbl.pack(side="left")

        self.score_lbl = ctk.CTkLabel(head, text="skor —", font=ctk.CTkFont(size=11),
                                      text_color="#8fa3b8")
        self.score_lbl.pack(side="left", padx=14)

        # Canli saat: uygulamanin gercekten canli oldugunu gosterir.
        # (Kullanicinin "realtime gostermiyor" izlenimi buradan cozulur:
        #  saat 19.00 yazan bar bizim yerel saatimizde 19:00-23:00 arasi
        #  OLUŞAN bardir, veri sapmasi degil.)
        self.clock_lbl = ctk.CTkLabel(head, text="--:--:--", font=ctk.CTkFont(size=11),
                                      text_color=LIVE_COLOR)
        self.clock_lbl.pack(side="left", padx=(18, 0))

        # Grafik gezinme dugmeleri: fare hassasiyeti olmadan da calisir.
        nav = ctk.CTkFrame(head, fg_color="transparent")
        nav.pack(side="right")
        nav_btn = {"width": 28, "height": 24, "font": ctk.CTkFont(size=10),
                   "fg_color": "transparent", "border_width": 1,
                   "border_color": BORDER, "text_color": "#8fa3b8"}
        ctk.CTkButton(nav, text="◀◀", command=lambda: self.chart.pan_bars(25),
                      **nav_btn).pack(side="left")
        ctk.CTkButton(nav, text="◀", command=lambda: self.chart.pan_bars(5),
                      **nav_btn).pack(side="left", padx=2)
        ctk.CTkButton(nav, text="▶", command=lambda: self.chart.pan_bars(-5),
                      **nav_btn).pack(side="left", padx=2)
        ctk.CTkButton(nav, text="▶▶",
                      command=lambda: self.chart.pan_bars(-25),
                      **nav_btn).pack(side="left")
        ctk.CTkButton(nav, text="+", command=lambda: self.chart.zoom(0.65),
                      **nav_btn).pack(side="left", padx=(8, 2))
        ctk.CTkButton(nav, text="−", command=lambda: self.chart.zoom(1 / 0.65),
                      **nav_btn).pack(side="left", padx=2)
        ctk.CTkButton(nav, text="Sığdır", command=self._fit_chart,
                      **nav_btn).pack(side="left", padx=(8, 0))

        # --- grafik + tablolar ----------------------------------------------
        content = ctk.CTkFrame(body, fg_color="transparent")
        content.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=8,
                     pady=(6, 8))
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=1)     # grafik yer kaplar
        content.grid_columnconfigure(1, weight=0, minsize=TABLES_WIDTH)

        self.chart = ChartPanel(content, self.timeframe)
        self.chart.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")

        right = ctk.CTkFrame(content, fg_color="transparent", width=TABLES_WIDTH)
        right.grid(row=0, column=1, sticky="ns", padx=(8, 0))
        right.grid_rowconfigure(0, weight=1)
        right.grid_columnconfigure(0, weight=1)
        right.configure(width=TABLES_WIDTH)
        right.grid_propagate(False)

        self.tables = TablesColumn(right)
        self.tables.grid(row=0, column=0, sticky="nsew")

        body.grid_rowconfigure(1, weight=1)
        body.grid_columnconfigure(0, weight=1)

    # ------------------------------------------------------------------
    def _build_log(self) -> None:
        self.log = LogPanel(self, on_toggle=self._toggle_log)
        self.log.grid(row=2, column=0, sticky="nsew", padx=8, pady=(6, 0))

    def _toggle_log(self, show: bool = None) -> None:
        visible = self.log.grid_info() != ()
        if show is None:
            show = not visible
        if show:
            self.log.grid(row=2, column=0, sticky="nsew", padx=8, pady=(6, 0))
        else:
            self.log.grid_remove()
        self.log.set_toggle_text(show)

    # ==================================================================
    # Olaylar
    # ==================================================================
    def _on_start(self) -> None:
        sym = self.symbol_entry.get().strip().upper()
        if not sym:
            messagebox.showwarning("Hata", "Sembol boş olamaz.")
            return

        errors = self._read_thresholds()
        if errors:
            messagebox.showwarning("Hata", "\n".join(errors))
            return

        self.settings.symbol = sym
        self.service.settings.symbol = sym
        self.service.client.symbol = sym
        self.service.start()
        self.start_btn.configure(text="Durdur", command=self._on_stop,
                                 fg_color="#a4464c", hover_color="#c0555c")

    def _on_stop(self) -> None:
        self.service.stop()
        self.start_btn.configure(text="Başlat", command=self._on_start,
                                 fg_color="#1f6f4a", hover_color="#27855a")

    def _read_thresholds(self) -> list[str]:
        try:
            strong = float(self.strong_entry.get().replace(",", "."))
            base = float(self.base_entry.get().replace(",", "."))
        except ValueError:
            return ["Eşikler sayı olmalı."]

        if not (0 < base < 1):
            return ["AL/SAT eşiği 0 ile 1 arasında olmalı."]
        if not (base <= strong <= 1):
            return ["GÜÇLÜ eşiği AL/SAT eşiğinden küçük ve 1'den büyük olamaz."]

        self.strong_entry.delete(0, "end")
        self.strong_entry.insert(0, f"{strong:.2f}")
        self.base_entry.delete(0, "end")
        self.base_entry.insert(0, f"{base:.2f}")
        return []

    def _on_apply_thresholds(self) -> None:
        errors = self._read_thresholds()
        if errors:
            messagebox.showwarning("Hata", "\n".join(errors))
            return
        strong = float(self.strong_entry.get())
        base = float(self.base_entry.get())
        self.service.update_thresholds(strong, base)
        self._push_log(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "info",
                       f"Eşikler güncellendi: GÜÇLÜ ±{strong:.2f}, "
                       f"AL/SAT ±{base:.2f}")

    def _on_toggle_overlay(self) -> None:
        self.settings.show_ma_overlay = bool(self.overlay_switch.get())
        self._rendered_version = -1        # yeniden cizilsin

    def _on_toggle_neutral(self) -> None:
        self.service.set_record_neutral(bool(self.neutral_switch.get()))

    def _on_refresh_mode(self, value: str) -> None:
        """Yenileme katsayisini degistirir."""
        headroom, min_ms, analysis_s = config.REFRESH_MODES.get(
            value, (config.CHART_HEADROOM, config.CHART_MIN_INTERVAL_MS,
                    config.ANALYSIS_INTERVAL))
        self.chart_headroom = headroom
        self.chart_min_interval = min_ms
        self.service.set_analysis_interval(analysis_s)
        self._push_log(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "info",
                       f"Yenileme modu: {value}")

    def _fit_chart(self) -> None:
        self.chart.fit()

    # ------------------------------------------------------------------
    def _on_reset_db(self) -> None:
        n_sig = self.store.count_signals()
        n_log = self.store.count_logs()
        ok = messagebox.askyesno(
            "Veritabanını sıfırla",
            f"{n_sig} sinyal kaydı ve {n_log} log satırı silinecek.\n\n"
            "Bu işlem geri alınamaz. Devam edilsin mi?",
            icon="warning", default="no")
        if not ok:
            return

        removed = self.store.reset()
        total = sum(removed.values())
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._push_log(stamp, "warning",
                       f"VERİTABANI SIFIRLANDI — {total} kayıt silindi "
                       f"(sinyal: {removed['signal_events']}, log: {removed['app_log']})")
        self._refresh_db_label()

    def _refresh_db_label(self) -> None:
        try:
            n = self.store.count_signals()
            kb = self.store.disk_size_kb()
            self.db_lbl.configure(text=f"Kayıt: {n}  ·  {kb} KB  ·  "
                                       f"{os.path.basename(config.DB_PATH)}")
        except Exception:      # noqa: BLE001
            self.db_lbl.configure(text=os.path.basename(config.DB_PATH))

    # ==================================================================
    # Event akisi
    #
    # Iki kademeli yenileme:
    #   _pump (100 ms)  -> yalnizca kuyrugu bosaltir ve UCUZ etiketleri
    #                      gunceller (fiyat, sinyal rozeti, skor, sayimlar)
    #   _chart_tick     -> grafigi ve tablolari yeniler; aralik SON CIZIMIN
    #                      GERCEK SURESIYLE UYARLANIR (config.CHART_HEADROOM)
    # ==================================================================
    def _pump(self) -> None:
        service = self.service
        latest: dict | None = None

        try:
            while True:
                event = service.events.get_nowait()
                kind = event[0]
                if kind == "log":
                    _, stamp, level, _cat, msg = event
                    self._push_log(stamp, level, msg)
                elif kind == "signal_log":
                    _, stamp, sig, _tf, text = event
                    self.log.add_signal(stamp, sig.value, text)
                elif kind == "status":
                    _, level, msg = event
                    self.status.configure(text=msg)
                    self._push_log(datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                   level, msg)
                elif kind == "snapshot":
                    # Kuyrukta birikmis birden fazla anlik goruntu varsa
                    # yalnizca EN SONUNCU islenir.
                    latest = event[1]
        except Exception:      # noqa: BLE001  (kuyruk bos)
            pass

        if latest is not None:
            self._latest_snap = latest
            self._apply_light(latest)

        self.after(config.GUI_TICK_MS, self._pump)

    # ------------------------------------------------------------------
    def _apply_light(self, snap: dict) -> None:
        """Yalnizca ucuz etiketler (grafik/tabloya dokunmaz)."""
        res: TimeframeAnalysis = snap.get("analyses", {}).get(self.timeframe)
        if res is None:
            return
        price = snap.get("price", float("nan"))
        self._update_labels(res, price)
        self.clock_lbl.configure(text=datetime.now().strftime("%H:%M:%S"))
        # Canli fiyat cizgisi 10 Hz'de hareket eder (mumlar ~2 Hz)
        self.chart.set_live_price(price)

        now = time.monotonic()
        if now - self._last_db_refresh >= 3.0:
            self._last_db_refresh = now
            self._refresh_db_label()

    # ------------------------------------------------------------------
    def _update_labels(self, res: TimeframeAnalysis, price: float) -> None:
        p = price if price == price else res.price
        sig = res.signal

        if self._badge_signal is not sig:
            self.badge.configure(text=sig.value,
                                 fg_color=SIGNAL_BADGE_BG[sig],
                                 text_color=SIGNAL_TEXT[sig])
            self._badge_signal = sig

        self.price_lbl.configure(text=f"{p:,.2f}")
        self.score_lbl.configure(
            text=f"bileşik {res.composite_value:+.3f}   "
                 f"osil. {res.oscillator_scores[-1]:+.2f}   "
                 f"ort. {res.ma_scores[-1]:+.2f}")

    # ------------------------------------------------------------------
    def _chart_tick(self) -> None:
        snap = self._latest_snap
        if snap is not None:
            res = snap.get("analyses", {}).get(self.timeframe)
            version = snap.get("versions", {}).get(self.timeframe, 0)
            if res is not None and version != self._rendered_version:
                try:
                    price = snap.get("price", float("nan"))
                    self.chart.update(res, price,
                                      bool(self.overlay_switch.get()))
                    self.tables.update(res)
                    self._rendered_version = version
                except Exception as exc:      # noqa: BLE001
                    self.status.configure(text=f"Çizim hatası: {exc}")

        # Son cizimin gercek suresine gore bir sonraki yenilemeyi planla.
        last = self.chart.last_draw_ms
        if last > 1:
            self.refresh_lbl.configure(
                text=f"çizim {last:.0f} ms → {last * self.chart_headroom:.0f} ms")
        delay = max(self.chart_min_interval,
                    int(self.chart.last_draw_ms * self.chart_headroom))
        self.after(delay, self._chart_tick)

    # ------------------------------------------------------------------
    def _push_log(self, stamp: str, level: str, message: str) -> None:
        self.log.add_system(stamp, level, message)

    # ==================================================================
    def warm_up(self) -> None:
        """
        Acilista arayuzu bir kez gercek kod yolundan gecirir.

        Sorun: pencerenin ilk kez dolu icerikle boyanmasi ve grafigin ilk
        cizimi uzun suruyor. Bu maliyet kullanici "Baslat" dedikten sonra
        olursa arayuz donuyor.

        Cozum: sentetik veriyle gercek analiz/cizim/tablo kodunu calistirip
        butun maliyeti acilista odemek.
        """
        import numpy as np

        from core.analysis import analyze

        self.status.configure(text="Grafik hazırlanıyor…")
        self.update_idletasks()
        self.update()

        n = 300
        rng = np.random.default_rng(7)
        base = 81000.0 + np.cumsum(rng.normal(0.0, 45.0, n))
        o = base
        c = base + rng.normal(0.0, 14.0, n)
        h = np.maximum(o, c) + rng.uniform(5.0, 90.0, n)
        l = np.minimum(o, c) - rng.uniform(5.0, 90.0, n)
        v = rng.uniform(20.0, 900.0, n)
        open_times = np.arange(n, dtype=np.int64) * 14_400_000
        close_times = open_times + 14_400_000

        try:
            res = analyze(
                symbol=self.settings.symbol, timeframe=self.timeframe,
                open_times=open_times, o=o, h=h, l=l, c=c, v=v,
                close_times=close_times,
                strong_threshold=self.settings.strong_threshold,
                base_threshold=self.settings.base_threshold,
            )
            self.chart.update(res, float(c[-1]), True)
            self.tables.update(res)
        except Exception as exc:      # noqa: BLE001
            self.status.configure(text=f"Isıtma hatası: {exc}")

        self._rendered_version = -1     # gercek veri geldiginde yeniden ciz
        self.update_idletasks()
        self.update()
        self.status.configure(
            text="Hazır — Başlat'a basarak canlı akışı başlat")

    # ==================================================================
    def _on_close(self) -> None:
        try:
            self.service.stop()
            self.store.close()
        finally:
            self.destroy()