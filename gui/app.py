"""
CustomTkinter tabanli ana GUI.

Bolumler:
  - Kontrol paneli (mod secimi, baslat/durdur, ayarlar)
  - Sinyal ozeti (TradingView Technicals formati)
  - Indikator tablolari (osilator / hareketli ortalamalar)
  - Cuzdan + acik pozisyon + islem gecmisi
  - Log konsolu
  - Grafik penceresi (Lightweight Charts veya matplotlib yedek)
"""
from __future__ import annotations

import logging
import queue
import threading
import time
import traceback
from typing import Any, Dict, List, Optional

import pandas as pd
import tkinter as tk
from tkinter import ttk, messagebox

import customtkinter as ctk

from config import GUI_CONFIG, TRADING_CONFIG
from data.fetcher import DataFetcher
from indicators.calculator import IndicatorsCalculator
from signals.generator import Signal, SignalGenerator  # noqa: F401
from trading.engine import Side, TradingEngine

logger = logging.getLogger(__name__)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

VERDICT_COLORS = {"buy": "#26a69a", "sell": "#ef5350", "neutral": "#8a99b3"}
SIGNAL_COLORS = {
    Signal.STRONG_BUY: "#00c853", Signal.BUY: "#26a69a",
    Signal.NEUTRAL: "#8a99b3", Signal.SELL: "#ef5350",
    Signal.STRONG_SELL: "#d32f2f",
}


class BotGUI(ctk.CTk):
    """Ana pencere."""

    def __init__(self):
        super().__init__()

        self.title(GUI_CONFIG["title"])
        self._fit_to_screen()

        # --- durum ---
        self.mode = tk.StringVar(value="canli")           # canli | backtest
        self.running = tk.BooleanVar(value=False)
        self.log_queue: "queue.Queue[tuple[str, str]]" = queue.Queue()
        self._stop_flag = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._closing = False
        self._log_job: Optional[str] = None
        self._warm_ready: Optional[pd.DataFrame] = None

        self.fetcher = DataFetcher()
        self.calc = IndicatorsCalculator()
        self.generator = SignalGenerator()
        self.engine = TradingEngine()

        self.last_df: Optional[pd.DataFrame] = None
        self.last_signal = None
        self.last_signals: Optional[pd.DataFrame] = None   # skor serisi
        self.last_equity: Optional[pd.DataFrame] = None
        self.live_price: Optional[float] = None   # anlik son islem fiyati
        self.mark_price: Optional[float] = None   # vadeli islem PnL fiyati
        self.index_price: Optional[float] = None  # endeks fiyati
        self.funding_rate: Optional[float] = None # 8 saatlik fonlama orani
        self._tick = 0

        # grafik
        self.chart_window = None
        self._init_chart_backend()

        # borsa baglantisini arka planda isit: ilk tick 18s suruyordu
        threading.Thread(target=self._warmup, daemon=True).start()

        self._build_layout()
        self._log("Arayuz hazir. Mod secin ve 'Baslat' deyin.", "info")
        self._log_job = self.after(120, self._drain_logs)

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    def _fit_to_screen(self) -> None:
        """Pencere boyutunu ekrana sigdirir.

        Dekorasyon (baslik cubugu + kenarlik) ve Windows gorev cubugu icin
        guvenli pay birakilir; boylece pencere hicbir zaman ekran disinda
        kalmaz.
        """
        self.update_idletasks()

        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()

        # gorev cubugu yuksekligini hesapla: ekranin alt kenarindaki
        # "Start" cubugu ~40px. Onun kadarini isletim.
        taskbar = 48 if sh <= 900 else 0
        work_w = int(sw * 0.96)
        work_h = int((sh - taskbar) * 0.97)

        # icerik yerlesiminin minimum ihtiyaci
        min_w, min_h = 980, 640

        width = min(GUI_CONFIG["width"], work_w)
        height = min(GUI_CONFIG["height"], work_h)

        # ekran kucukse minimumu da zorlamadan kucult
        width = max(width, min(min_w, work_w))
        height = max(height, min(min_h, work_h))

        self.geometry(f"{width}x{height}")
        self.minsize(min(min_w, work_w), min(min_h, work_h))

        # pencereyi calisabilir alanda ortala (gorev cubugunun ustunde kalsin)
        try:
            x = max(0, (sw - width) // 2)
            y = max(0, (sh - taskbar - height) // 2)
            self.geometry(f"+{x}+{y}")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    def _warmup(self):
        """Arka planda marketleri yukler ve ilk 5000 mumu indirir.

        Boylece 'Baslat' tikinde 18 saniyelik gecikme olmaz.
        """
        try:
            self.fetcher.exchange            # marketleri yukle
            df = self.fetcher.fetch_ohlcv()  # ilk tarihsel veri
            enriched = self.calc.calculate_all(df)
            self._warm_ready = enriched
            self._log("Hazır: piyasa verisi arka planda yüklendi.", "good")
        except Exception as exc:
            logger.warning("Isitma basarisiz: %s", exc)

    # ------------------------------------------------------------------
    def _init_chart_backend(self):
        try:
            from gui.chart_window import ChartWindow
            self.chart_window = ChartWindow("BTCUSDT - Lightweight Charts")
        except Exception as exc:  # pragma: no cover
            logger.warning("Grafik arka ucu yuklenemedi: %s", exc)
            self.chart_window = None

    def _has_lwc(self) -> bool:
        return self.chart_window is not None and getattr(self.chart_window, "available", False)

    # ==================================================================
    # ARAYUZ
    # ==================================================================
    def _build_layout(self):
        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=4)
        # satirlar: 0=baslik, 1=kontrol, 2=paneller (buyur), 3=altbilgi
        self.grid_rowconfigure(0, weight=0, minsize=56)
        self.grid_rowconfigure(1, weight=0)
        self.grid_rowconfigure(2, weight=1)   # buyutulebilir icerik
        self.grid_rowconfigure(3, weight=0, minsize=28)

        self._build_header()
        self._build_controls()
        self._build_left_panel()
        self._build_right_panel()
        self._build_footer()

    # ------------------------------------------------------------------
    def _build_header(self):
        bar = ctk.CTkFrame(self, height=56, corner_radius=0,
                           fg_color="#111c31")
        bar.grid(row=0, column=0, columnspan=2, sticky="ew")
        bar.grid_propagate(False)

        ctk.CTkLabel(bar, text="₿  BTCUSDT Futures Bot",
                     font=ctk.CTkFont(size=21, weight="bold")).pack(side="left", padx=18)

        self.lbl_price = ctk.CTkLabel(bar, text="Fiyat: —",
                                      font=ctk.CTkFont(size=17, weight="bold"),
                                      text_color="#26a69a")
        self.lbl_price.pack(side="left", padx=14)

        self.lbl_mark = ctk.CTkLabel(bar, text="Mark: —",
                                     font=ctk.CTkFont(size=12),
                                     text_color="#8a99b3")
        self.lbl_mark.pack(side="left")

        self.lbl_signal = ctk.CTkLabel(bar, text="Sinyal: —",
                                       font=ctk.CTkFont(size=17, weight="bold"))
        self.lbl_signal.pack(side="left", padx=14)

        self.lbl_score = ctk.CTkLabel(bar, text="Skor: —",
                                      font=ctk.CTkFont(size=15))
        self.lbl_score.pack(side="left", padx=14)

        self.lbl_threshold = ctk.CTkLabel(
            bar, text=f"Eşik: ±{TRADING_CONFIG.strong_buy_threshold:.2f}",
            font=ctk.CTkFont(size=12), text_color="#8a99b3")
        self.lbl_threshold.pack(side="right", padx=18)

        self.lbl_status = ctk.CTkLabel(bar, text="● DURAKLATILDI",
                                       font=ctk.CTkFont(size=14, weight="bold"),
                                       text_color="#8a99b3")
        self.lbl_status.pack(side="right", padx=18)

    # ------------------------------------------------------------------
    def _build_controls(self):
        ctl = ctk.CTkFrame(self, corner_radius=0, fg_color="#0e1729")
        ctl.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 0))
        ctl.grid_columnconfigure(0, weight=1)

        # --- satir 1: mod + baslat/durdur ---
        row1 = ctk.CTkFrame(ctl, corner_radius=0, fg_color="transparent")
        row1.grid(row=0, column=0, sticky="ew", pady=(6, 0))

        ctk.CTkLabel(row1, text="Mod:").pack(side="left", padx=(18, 6))
        ctk.CTkSegmentedButton(
            row1, values=["canlı", "backtest"], variable=self.mode,
            width=190, height=32,
        ).pack(side="left")

        # Algoritma seçimi
        ctk.CTkLabel(row1, text="  Algoritma:").pack(side="left", padx=(18, 6))
        self.algo_var = tk.StringVar(value="composite")
        ctk.CTkOptionMenu(row1, values=["composite", "hareketli_yeni", "hareketli_yeni_long", "hareketli_yeni_short"],
                          variable=self.algo_var, width=160, height=32,
                          command=self._on_algo_change
                          ).pack(side="left")

        self.btn_start = ctk.CTkButton(row1, text="▶  Başlat", width=125,
                                       height=36, font=ctk.CTkFont(size=15, weight="bold"),
                                       command=self._toggle_start)
        self.btn_start.pack(side="left", padx=12)

        ctk.CTkLabel(row1, text="Kaldıraç:").pack(side="left", padx=(10, 4))
        self.lev_var = tk.StringVar(value=str(TRADING_CONFIG.leverage))
        # degerler string olmali: CTkOptionMenu etiketlerde .ljust() cagirir
        ctk.CTkOptionMenu(row1, values=[str(v) for v in (1, 2, 3, 5, 10, 20, 25, 50, 75, 100)],
                          variable=self.lev_var, width=76, height=32
                          ).pack(side="left")

        ctk.CTkLabel(row1, text="SL %:").pack(side="left", padx=(10, 4))
        self.sl_var = tk.StringVar(value=str(round(TRADING_CONFIG.stop_loss_pct * 100, 2)))
        ctk.CTkEntry(row1, textvariable=self.sl_var, width=62, height=32).pack(side="left")

        ctk.CTkLabel(row1, text="TP %:").pack(side="left", padx=(8, 4))
        self.tp_var = tk.StringVar(value=str(round(TRADING_CONFIG.take_profit_pct * 100, 2)))
        ctk.CTkEntry(row1, textvariable=self.tp_var, width=62, height=32).pack(side="left")

        # kar kilidi: acik/kapali (varsayilan kapali - TP'den kucuk olmali)
        self.lock_var = tk.StringVar(
            value="kilit" if TRADING_CONFIG.profit_lock_enabled else "—")
        ctk.CTkSegmentedButton(
            row1, values=["—", "kilit"], variable=self.lock_var,
            command=self._on_lock_toggle,
            width=110, height=32,
        ).pack(side="left", padx=10)
        self._lock_pct = TRADING_CONFIG.profit_lock_pct
        self.lbl_lock = ctk.CTkLabel(row1, text=f"%{self._lock_pct*100:.0f}",
                                     font=ctk.CTkFont(size=11), text_color="#8a99b3")
        self.lbl_lock.pack(side="left", padx=(2, 0))
        self.lbl_lock.bind("<Button-1>", lambda e: self._bump_lock(-0.01))
        self.lbl_lock.bind("<Button-3>", lambda e: self._bump_lock(+0.01))

        # --- satir 2: manuel emirler + grafik ---
        row2 = ctk.CTkFrame(ctl, corner_radius=0, fg_color="transparent")
        row2.grid(row=1, column=0, sticky="ew", pady=(6, 8))

        self.btn_long = ctk.CTkButton(row2, text="Manuel LONG", width=120, height=32,
                                      fg_color="#1b7f5f", hover_color="#26a69a",
                                      command=lambda: self._manual(Side.LONG))
        self.btn_long.pack(side="left", padx=(18, 5))

        self.btn_short = ctk.CTkButton(row2, text="Manuel SHORT", width=120, height=32,
                                       fg_color="#9c2b2b", hover_color="#ef5350",
                                       command=lambda: self._manual(Side.SHORT))
        self.btn_short.pack(side="left", padx=5)

        self.btn_close = ctk.CTkButton(row2, text="Pozisyon Kapat", width=126, height=32,
                                       fg_color="#3a4459", hover_color="#4c5871",
                                       command=self._manual_close)
        self.btn_close.pack(side="left", padx=5)

        self.btn_chart = ctk.CTkButton(row2, text="Grafik", width=100, height=32,
                                       command=self._open_chart)
        self.btn_chart.pack(side="left", padx=5)

        self.btn_reset = ctk.CTkButton(row2, text="↺ Sıfırla", width=96, height=32,
                                       fg_color="#3a4459", hover_color="#4c5871",
                                       command=self._reset)
        self.btn_reset.pack(side="left", padx=5)

    # ------------------------------------------------------------------
    def _build_left_panel(self):
        left = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        left.grid(row=2, column=0, sticky="nsew", padx=(10, 5), pady=10)
        left.grid_columnconfigure(0, weight=1)
        # 0=ozet, 1=cuzdan, 2=pozisyon, 3=gecmis -> yalnizca gecmis buyur.
        # minsize verilmez: icerik pencereye sigmiyorsa gecmis tablosu
        # kuculur (kaydirma cubugu ile erisilir), tasma olusmaz.
        left.grid_rowconfigure(0, weight=0)
        left.grid_rowconfigure(1, weight=0)
        left.grid_rowconfigure(2, weight=0)
        left.grid_rowconfigure(3, weight=1)

        # Özet (TradingView Technicals benzeri)
        summary = ctk.CTkFrame(left, corner_radius=10)
        summary.grid(row=0, column=0, sticky="ew")
        summary.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkLabel(summary, text="TEKNİK ÖZET",
                     font=ctk.CTkFont(size=13, weight="bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(7, 4))

        self.lbl_osc = ctk.CTkLabel(summary, text="Osilatörler: —", anchor="w",
                                    font=ctk.CTkFont(size=11))
        self.lbl_osc.grid(row=1, column=0, sticky="ew", padx=14, pady=2)

        self.lbl_ma = ctk.CTkLabel(summary, text="Hareketli Ort.: —", anchor="w",
                                   font=ctk.CTkFont(size=11))
        self.lbl_ma.grid(row=2, column=0, sticky="ew", padx=14, pady=2)

        self.lbl_pv = ctk.CTkLabel(summary, text="Pivotlar: —", anchor="w",
                                   font=ctk.CTkFont(size=11))
        self.lbl_pv.grid(row=3, column=0, sticky="ew", padx=14, pady=2)

        self.lbl_comp = ctk.CTkLabel(summary, text="BİLEŞİK SKOR: —",
                                     font=ctk.CTkFont(size=14, weight="bold"))
        self.lbl_comp.grid(row=4, column=0, sticky="ew", padx=14, pady=(4, 8))

        self.lbl_osc_detail = ctk.CTkLabel(summary, text="", anchor="w",
                                           justify="left",
                                           font=ctk.CTkFont(size=10))
        self.lbl_osc_detail.grid(row=5, column=0, sticky="ew", padx=14, pady=(0, 4))

        # Cüzdan
        wallet = ctk.CTkFrame(left, corner_radius=10)
        wallet.grid(row=1, column=0, sticky="ew", pady=8)
        wallet.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkLabel(wallet, text="TEST CÜZDANI",
                     font=ctk.CTkFont(size=13, weight="bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(7, 2))

        self.wallet_labels: Dict[str, ctk.CTkLabel] = {}
        rows = [
            ("equity", "Özsermaye"), ("balance", "Bakiye"),
            ("available", "Kullanılabilir"), ("unrealized", "Açık PnL"),
            ("realized", "Kapanan PnL"), ("fees", "Toplam Ücret"),
            ("trades", "İşlem / Kazanç"), ("win_rate", "Kazanç Oranı"),
            ("roi", "ROI %"), ("max_dd", "Max DD %"),
        ]
        for i, (key, label) in enumerate(rows):
            r = i // 2 + 1
            c = (i % 2)
            ctk.CTkLabel(wallet, text=label, anchor="w", text_color="#8a99b3",
                         font=ctk.CTkFont(size=10)).grid(row=r, column=c, sticky="w",
                                                          padx=14, pady=1)
            lbl = ctk.CTkLabel(wallet, text="—", anchor="e",
                               font=ctk.CTkFont(size=11, weight="bold"))
            lbl.grid(row=r, column=c, sticky="e", padx=14, pady=1)
            self.wallet_labels[key] = lbl

        # Açık pozisyon
        openf = ctk.CTkFrame(left, corner_radius=10)
        openf.grid(row=2, column=0, sticky="ew", pady=8)
        openf.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(openf, text="AÇIK POZİSYON",
                     font=ctk.CTkFont(size=13, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=14, pady=(7, 2))

        self.lbl_position = ctk.CTkLabel(openf, text="Pozisyon yok",
                                         anchor="w", justify="left",
                                         font=ctk.CTkFont(size=11))
        self.lbl_position.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 6))

        # İşlem geçmişi
        hist = ctk.CTkFrame(left, corner_radius=10)
        hist.grid(row=3, column=0, sticky="nsew", pady=(6, 0))
        hist.grid_columnconfigure(0, weight=1)
        hist.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(hist, text="İŞLEM GEÇMİŞİ",
                     font=ctk.CTkFont(size=13, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=14, pady=(7, 2))

        self._build_trade_tree()
        scroll = ttk.Scrollbar(hist, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=1, column=0, sticky="nsew", padx=(14, 6), pady=(0, 12))
        scroll.grid(row=1, column=1, sticky="ns", padx=(0, 10), pady=(0, 12))

    # ------------------------------------------------------------------
    def _build_trade_tree(self):
        """İşlem geçmişi tablosunu algoritma bazlı kolonlarla yeniden oluşturur."""
        # Mevcut tree'ı temizle
        if hasattr(self, 'tree'):
            self.tree.destroy()
        
        hist = self.tree.master  # hist frame'i parent'ı
        
        # Algoritma bazlı kolonlar
        algo = self.algo_var.get()
        is_hareketli_yeni = algo.startswith("hareketli_yeni")
        
        if is_hareketli_yeni:
            columns = ("side", "entry", "exit", "pnl", "roi", "reason",
                       "ma_al_e", "ma_sat_e", "ma_notr_e",
                       "ma_al_x", "ma_sat_x", "ma_notr_x")
            col_defs = (
                ("side", "Yön", 50), ("entry", "Giriş", 70),
                ("exit", "Çıkış", 70), ("pnl", "PnL", 65),
                ("roi", "ROI %", 55), ("reason", "Sebep", 80),
                ("ma_al_e", "AL↓", 35), ("ma_sat_e", "SAT↓", 35), ("ma_notr_e", "NÖTR↓", 40),
                ("ma_al_x", "AL↑", 35), ("ma_sat_x", "SAT↑", 35), ("ma_notr_x", "NÖTR↑", 40),
            )
        else:
            columns = ("side", "entry", "exit", "pnl", "roi", "reason")
            col_defs = (
                ("side", "Yön", 58), ("entry", "Giriş", 76),
                ("exit", "Çıkış", 76), ("pnl", "PnL", 70),
                ("roi", "ROI %", 58), ("reason", "Sebep", 88),
            )
        
        self.tree = ttk.Treeview(hist, columns=columns, show="headings", height=6)
        for col, head, w in col_defs:
            self.tree.heading(col, text=head)
            self.tree.column(col, width=w, anchor="center", stretch=True)
        
        self.tree.tag_configure("long", foreground="#26a69a")
        self.tree.tag_configure("short", foreground="#ef5350")

    # ------------------------------------------------------------------
    def _build_right_panel(self):
        right = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        right.grid(row=2, column=1, sticky="nsew", padx=(5, 10), pady=10)
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(0, weight=3)
        right.grid_rowconfigure(1, weight=2)

        # İndikatör tabloları
        tabs = ctk.CTkTabview(right, corner_radius=10)
        tabs.grid(row=0, column=0, sticky="nsew", pady=(0, 8))

        for name, key in (("Osilatörler", "osc"), ("Hareketli Ort.", "ma"),
                          ("Pivotlar", "pv")):
            tab = tabs.add(name)
            tab.grid_columnconfigure(0, weight=1)
            tab.grid_rowconfigure(0, weight=1)
            cols = ("value", "verdict")
            tree = ttk.Treeview(tab, columns=cols, show="headings", height=14)
            tree.heading("value", text="Değer")
            tree.heading("verdict", text="İşlem Detayı")
            tree.column("value", width=140, anchor="e")
            tree.column("verdict", width=140, anchor="center")
            tree.tag_configure("buy", foreground="#26a69a")
            tree.tag_configure("sell", foreground="#ef5350")
            tree.tag_configure("neutral", foreground="#8a99b3")
            tree.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
            setattr(self, f"tree_{key}", tree)

        # Log
        logf = ctk.CTkFrame(right, corner_radius=10)
        logf.grid(row=1, column=0, sticky="nsew")
        logf.grid_columnconfigure(0, weight=1)
        logf.grid_rowconfigure(1, weight=1)

        head = ctk.CTkFrame(logf, corner_radius=10, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(head, text="KONSOL", font=ctk.CTkFont(size=14, weight="bold")
                     ).pack(side="left", padx=14, pady=(10, 2))
        ctk.CTkButton(head, text="Temizle", width=80, height=26,
                      command=self._clear_log).pack(side="right", padx=14)

        self.txt_log = ctk.CTkTextbox(logf, font=ctk.CTkFont(family="Consolas", size=11))
        self.txt_log.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self.txt_log.configure(state="disabled")

    # ------------------------------------------------------------------
    def _build_footer(self):
        bar = ctk.CTkFrame(self, height=28, corner_radius=0, fg_color="#0e1729")
        bar.grid(row=3, column=0, columnspan=2, sticky="ew")
        bar.grid_propagate(False)

        self.lbl_engine = ctk.CTkLabel(bar, text="Borsa: —", anchor="w",
                                       font=ctk.CTkFont(size=11), text_color="#8a99b3")
        self.lbl_engine.pack(side="left", padx=18)

        self.lbl_chart_mode = ctk.CTkLabel(
            bar, text="Grafik: matplotlib yedek", anchor="w",
            font=ctk.CTkFont(size=11), text_color="#8a99b3")
        self.lbl_chart_mode.pack(side="right", padx=18)

        if self._has_lwc():
            self.lbl_chart_mode.configure(text="Grafik: Lightweight Charts ✓")

    # ==================================================================
    # LOG
    # ==================================================================
    def _ui(self, fn, *args):
        """Ana (Tk) is parcaciginda fonksiyon calistirir.

        Kapanis sirasinda veya Tk arayuzu yoksa sessizce gecersiz olur.
        """
        if self._closing:
            return
        try:
            self.after(0, fn, *args)
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _log(self, message: str, level: str = "info"):
        self.log_queue.put((message, level))

    def _drain_logs(self):
        try:
            while True:
                msg, level = self.log_queue.get_nowait()
                self._append_log(msg, level)
        except queue.Empty:
            pass
        if not self._closing:
            self._log_job = self.after(150, self._drain_logs)

    def _append_log(self, message: str, level: str):
        colors = {"info": "#c9d4e4", "good": "#26a69a", "bad": "#ef5350",
                  "warn": "#f0b90b", "trade": "#7c8cff"}
        stamp = time.strftime("%H:%M:%S")
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", f"[{stamp}] {message}\n", colors.get(level, "#c9d4e4"))

        lines = int(self.txt_log.index("end-1c").split(".")[0])
        if lines > GUI_CONFIG["log_lines"]:
            self.txt_log.delete("1.0", "100.0")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _clear_log(self):
        self.txt_log.configure(state="normal")
        self.txt_log.delete("1.0", "end")
        self.txt_log.configure(state="disabled")

    # ==================================================================
    # KONTROL
    # ==================================================================
    def _on_lock_toggle(self):
        if self.lock_var.get() == "kilit":
            self._log(f"Kâr kilidi AÇIK: ROI %{self._lock_pct*100:.0f}'e ulaşınca "
                      f"pozisyon kapanır, kâr cüzdanı yazılır.", "info")
        else:
            self._log("Kâr kilidi kapalı.", "info")

    def _bump_lock(self, delta: float):
        """Kilit yuzdesini sol tik (-) / sag tik (+) ile degistirir."""
        self._lock_pct = round(max(0.02, min(0.95, self._lock_pct + delta)), 2)
        self.lbl_lock.configure(text=f"%{self._lock_pct*100:.0f}")
        self.engine.config.profit_lock_pct = self._lock_pct
        self._log(f"Kâr kilidi hedefi: ROI %{self._lock_pct*100:.0f}", "info")

    def _on_algo_change(self, value: str):
        """Algoritma değiştiğinde işlem geçmişi tablosunu yeniden oluşturur."""
        self._log(f"Algoritma değiştirildi: {value}", "info")
        self._build_trade_tree()
        self._update_trades()

    # ------------------------------------------------------------------
    def _apply_settings(self):
        """Arayuz ayarlarini global config ve motor config'ine uygular."""
        try:
            leverage = int(self.lev_var.get())
            sl = float(self.sl_var.get().replace(",", ".").strip()) / 100.0
            tp = float(self.tp_var.get().replace(",", ".").strip()) / 100.0
        except ValueError:
            messagebox.showerror("Hata", "Kaldıraç, SL ve TP sayı olmalı.")
            return False

        if not (1 <= leverage <= 125):
            messagebox.showerror("Hata", "Kaldıraç 1–125 aralığında olmalı.")
            return False
        if not (0 < sl < 0.5) or not (0 < tp < 1.0):
            messagebox.showerror("Hata", "SL %0–50, TP %0–100 aralığında olmalı.")
            return False

        # kar kilidi ROI hedefi (TP'den kucuk olmali, yoksa asla calismaz)
        lock = self.lock_var.get() == "kilit"
        lock_pct = self._lock_pct

        # global config (backtest motoru bunu okur)
        TRADING_CONFIG.leverage = leverage
        TRADING_CONFIG.stop_loss_pct = sl
        TRADING_CONFIG.take_profit_pct = tp
        TRADING_CONFIG.profit_lock_enabled = lock
        TRADING_CONFIG.profit_lock_pct = lock_pct

        # aktif motorun kopyasi
        self.engine.config.leverage = leverage
        self.engine.config.stop_loss_pct = sl
        self.engine.config.take_profit_pct = tp
        self.engine.config.profit_lock_enabled = lock
        self.engine.config.profit_lock_pct = lock_pct

        # kilit TP'den buyukse uyar
        if lock and lock_pct * 100 >= tp * 100 * leverage:
            self._log(f"UYARI: Kâr kilidi %{lock_pct*100:.0f} ROI, TP'nin "
                      f"({tp*100*leverage:.1f}% ROI) üstünde — kilit asla tetiklenmez.",
                      "warn")
        return True

    def _toggle_start(self):
        if self.running.get():
            self._stop()
        else:
            self._start()

    def _start(self):
        if not self._apply_settings():
            return

        self._stop_flag.clear()
        self.running.set(True)
        self.btn_start.configure(text="⏸  Durdur", fg_color="#9c2b2b", hover_color="#c0392b")
        self.lbl_status.configure(text="● ÇALIŞIYOR", text_color="#26a69a")

        mode = self.mode.get()
        self._log(f"Başlatıldı → mod: {mode} | kaldıraç: {TRADING_CONFIG.leverage}x "
                  f"| SL {TRADING_CONFIG.stop_loss_pct:.2%} "
                  f"| TP {TRADING_CONFIG.take_profit_pct:.2%}", "info")

        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _stop(self):
        self._stop_flag.set()
        self.running.set(False)
        self.btn_start.configure(text="▶  Başlat", fg_color="#1f6fb2", hover_color="#2b7fc4")
        self.lbl_status.configure(text="● DURAKLATILDI", text_color="#8a99b3")
        self._log("Durduruldu.", "warn")

    def _reset(self):
        self._stop()
        self.engine.reset()
        self.tree.delete(*self.tree.get_children())
        for key in self.wallet_labels:
            self.wallet_labels[key].configure(text="—")
        self.lbl_position.configure(text="Pozisyon yok")
        self.last_equity = None
        self._log("Cüzdan sıfırlandı.", "info")

    # ------------------------------------------------------------------
    def _loop(self):
        mode = self.mode.get()
        try:
            if mode == "backtest":
                self._run_backtest()
            else:
                self._run_live()
        except Exception as exc:  # pragma: no cover
            logger.exception(traceback.format_exc())
            self._log(f"HATA: {exc}", "bad")
        finally:
            self._ui(self._mark_stopped)

    def _mark_stopped(self):
        self.running.set(False)
        self.btn_start.configure(text="▶  Başlat", fg_color="#1f6fb2", hover_color="#2b7fc4")
        self.lbl_status.configure(text="● DURAKLATILDI", text_color="#8a99b3")

    # ==================================================================
    # CANLI MOD
    # ==================================================================
    def _run_live(self):
        """Canlı mod: iki hızlı döngü.

        - FİYAT DÖNGÜSÜ (varsayilan 3 sn): anlik fiyat + mark price çekilir,
          PnL/SL-TP/kâr kilidi canlı fiyatla değerlendirilir. Emirler
          mum kapanışına değil, o anki gerçek fiyata girilir.
        - GÖSTERGE DÖNGÜSÜ (varsayilan 10 sn): yalnızca YENİ mumlar alınır
          (0.3s), göstergeler yeniden hesaplanır, sinyal güncellenir.

        Vadeli işlemde PnL mark price ile degerlendirilir; likidasyon
        borsanin kullandigi mark fiyatina gore hesaplanir.
        """
        price_every = max(1, TRADING_CONFIG.price_poll_seconds)
        ind_every = max(price_every, TRADING_CONFIG.indicator_refresh_seconds)

        self._log(f"Canlı mod: fiyat {price_every}s, gösterge {ind_every}s "
                  f"periyotla. Emirler canlı fiyattan girilir.", "info")

        last_ind = 0.0

        while not self._stop_flag.is_set():
            tick_start = time.time()

            try:
                # ---- 1) ANLIK FIYAT (her tick) ----
                # 2 istek: premiumIndex (mark+index+funding) + tickerPrice
                mark_price, index_price, funding = self.fetcher.get_market_info()
                last_price = self.fetcher.get_last_price()
                if last_price is None:
                    self._stop_flag.wait(price_every)
                    continue
                mark_price = mark_price or last_price

                self.live_price = last_price
                self.mark_price = mark_price
                self.index_price = index_price
                self.funding_rate = funding

                # ---- 2) GOSTERGE (periyodik, sadece yeni mumlar) ----
                need_indicators = (time.time() - last_ind) >= ind_every
                if need_indicators:
                    if self.last_df is None or self.last_df.empty:
                        # isitmadan gelmis veriyi kullan (yoksa cek)
                        df = self._warm_ready if self._warm_ready is not None \
                            else self.fetcher.fetch_ohlcv()
                    else:
                        df = self.fetcher.fetch_new_candles(self.last_df.index[-1])
                        if df.empty:
                            df = self.last_df          # yeni bar kapandi mi?
                        else:
                            df = pd.concat([self.last_df, df])
                            df = df[~df.index.duplicated(keep="last")].sort_index()
                            df = df.tail(TRADING_CONFIG.lookback_candles)

                    if df is not None and not df.empty:
                        enriched = self.calc.calculate_all(df)
                        self.last_df = enriched
                        signal = self.generator.generate(enriched)
                        self.last_signal = signal
                        try:
                            self.last_signals = self.generator.generate_series(enriched)
                        except Exception:
                            self.last_signals = None
                        last_ind = time.time()

                signal = self.last_signal
                ts = (self.last_df.index[-1] if self.last_df is not None
                      and not self.last_df.empty else pd.Timestamp.utcnow())

                if signal is not None:
                    # son tamamlanan barin high/low (ic fitiller) + canli fiyat
                    high = low = last_price
                    if self.last_df is not None and not self.last_df.empty:
                        high = max(float(self.last_df["high"].iloc[-1]), last_price)
                        low = min(float(self.last_df["low"].iloc[-1]), last_price)

                    self._decide(signal, last_price, ts, high=high, low=low,
                                 mark_price=mark_price)
                    self._ui(self._update_signal_ui, signal, last_price)
                    self._ui(self._update_wallet)
                    self._ui(self._update_position)
                    self._ui(self._update_trades)

                # grafik daha seyrek (her 5 tick)
                self._tick = getattr(self, "_tick", 0) + 1
                if self._tick % 5 == 0:
                    self._ui(self._push_chart)

                elapsed = time.time() - tick_start
                self._stop_flag.wait(max(0.5, price_every - elapsed))

            except Exception as exc:
                logger.exception(traceback.format_exc())
                self._log(f"Veri hatası: {exc}", "bad")
                self._stop_flag.wait(10)

    def _decide(self, signal, price: float, ts, high=None, low=None,
                mark_price=None):
        """Sinyale gore long/short karari.

        price  : ANLIK son islem fiyati (emir bu fiyattan girilir)
        mark_price : vadeli islemde PnL degerlendirme fiyati
        high/low : son barin ic fiyatlari (SL/TP wick kontrolu icin)
        """
        gen = self.generator
        high = price if high is None else high
        low = price if low is None else low
        open_pos = self.engine.open_positions[0] if self.engine.open_positions else None

        if open_pos:
            by_signal = gen.should_close(signal, open_pos.side.value.lower())
            reason_label = gen.close_reason(signal, open_pos.side.value.lower())
            if (not by_signal
                    and self.engine.config.exit_on_neutral_profit
                    and signal.signal == Signal.NEUTRAL):
                open_pos.update(mark_price or price, self.engine.config.taker_fee)
                if open_pos.unrealized_pnl > 0:
                    by_signal, reason_label = True, "notr-karda"

            reason = self.engine.manage_position(
                open_pos, price, ts, high=high, low=low,
                should_close_by_signal=by_signal,
                signal_reason=reason_label or "sinyal")

            if reason:
                colors = {"take-profit": "good", "kar-kilidi": "good",
                          "stop-loss": "bad", "basaba-stop": "warn",
                          "sinyal": "info", "sinyal-sogudu": "warn",
                          "ters-guclu-sinyal": "warn", "notr-karda": "info"}
                self._log(f"{reason} @ {price:,.2f} | "
                          f"PnL {open_pos.realized_pnl:+,.2f} USDT "
                          f"({open_pos.roi_pct:+.2f}%)", colors.get(reason, "info"))
            else:
                # PnL mark price uzerinden degerlendirilir
                self.engine.mark_to_market(mark_price or price)
            return

        if self.engine.wallet.available_margin <= 0:
            return

        if gen.should_open_long(signal):
            pos = self.engine.open_position(Side.LONG, price, ts, signal=signal)
            if pos:
                self._log(f"▶ LONG açıldı @ {price:,.2f} | {pos.quantity} BTC | "
                          f"skor {signal.composite:+.3f} ({signal.signal.value})", "trade")
        elif gen.should_open_short(signal):
            pos = self.engine.open_position(Side.SHORT, price, ts, signal=signal)
            if pos:
                self._log(f"▶ SHORT açıldı @ {price:,.2f} | {pos.quantity} BTC | "
                          f"skor {signal.composite:+.3f} ({signal.signal.value})", "trade")

    # ==================================================================
    # BACKTEST
    # ==================================================================
    def _run_backtest(self):
        from backtest.engine import BacktestEngine

        self._log("Backtest başlıyor: geçmiş veri çekiliyor...", "info")
        df = self.fetcher.fetch_range(TRADING_CONFIG.backtest_start,
                                      TRADING_CONFIG.backtest_end)
        if df is None or len(df) < 210:
            self._log("Backtest için yeterli veri yok.", "bad")
            return

        algo = self.algo_var.get()
        self._log(f"{len(df)} mum yüklendi. Strateji çalıştırılıyor... (Algoritma: {algo})", "info")
        result = BacktestEngine(TRADING_CONFIG, mode=algo).run(df)

        engine = result["engine"]
        self.engine = engine
        self.last_df = result["data"]
        self.last_equity = result["equity_curve"]
        self.last_signals = result.get("signals")

        # Son sinyal için generator kullan (görüntüleme için)
        signal = self.generator.generate(result["data"])
        self.last_signal = signal

        m = result["metrics"]
        price = float(result["data"]["close"].iloc[-1])
        self._ui(self._update_signal_ui, signal, price)
        self._ui(self._update_tables, signal)
        self._ui(self._update_wallet)
        self._ui(self._update_trades)
        self._ui(self._push_chart)

        self._log("── BACKTEST SONUCU ──", "info")
        for key in ("net", "roi", "trades", "win_rate", "profit_factor",
                    "max_dd", "fees", "expectancy", "long_trades", "short_trades"):
            self._log(f"  {key:16}: {m.get(key)}", "info")
        self._log(f"Grafik için 'Grafik' butonuna basın.", "info")

    # ==================================================================
    # MANUEL ISLEM
    # ==================================================================
    def _manual(self, side: Side):
        # emir fiyati ANLIK son islem fiyatidir (mum kapanisi degil)
        price = self.live_price or self.fetcher.get_last_price()
        if price is None:
            self._log("Fiyat alınamadı.", "bad")
            return

        ts = self.last_df.index[-1] if self.last_df is not None else pd.Timestamp.utcnow()
        pos = self.engine.open_position(side, price, ts, signal=self.last_signal)
        if pos:
            self._log(f"MANUEL {side.value} @ {price:,.2f} | {pos.quantity} BTC", "trade")
            self._ui(self._update_wallet)
            self._ui(self._update_position)
            self._ui(self._push_chart)
        else:
            self._log("Manuel emir reddedildi.", "warn")

    def _manual_close(self):
        if not self.engine.open_positions:
            self._log("Kapatılacak açık pozisyon yok.", "warn")
            return
        pos = self.engine.open_positions[0]
        price = self.live_price or self.fetcher.get_last_price() or pos.entry_price
        ts = self.last_df.index[-1] if self.last_df is not None else pd.Timestamp.utcnow()

        self.engine.close_position(pos, price, ts, "manuel")
        self._log(f"MANUEL CLOSE @ {price:,.2f} | PnL {pos.realized_pnl:+,.2f} USDT",
                  "good" if pos.realized_pnl > 0 else "bad")
        self._ui(self._update_wallet)
        self._ui(self._update_position)
        self._ui(self._update_trades)
        self._ui(self._push_chart)

    # ==================================================================
    # ARAYUZ GUNCELLEMELERI
    # ==================================================================
    def _update_signal_ui(self, signal, price: float):
        if signal is None:
            return

        color = SIGNAL_COLORS.get(signal.signal, "#8a99b3")
        self.lbl_price.configure(text=f"Fiyat: {price:,.2f}")
        if self.mark_price:
            delta = price - self.mark_price
            extra = ""
            if self.funding_rate is not None:
                extra = f" · fonl. {self.funding_rate*100:+.4f}%"
            self.lbl_mark.configure(
                text=f"Mark: {self.mark_price:,.2f} ({delta:+,.2f}){extra}")
        self.lbl_signal.configure(text=f"Sinyal: {signal.signal.value}", text_color=color)
        self.lbl_score.configure(text=f"Skor: {signal.composite:+.3f}")

        self.lbl_osc.configure(
            text=f"Osilatörler:  Al {signal.osc_counts.get('buy',0)}  ·  "
                 f"Sat {signal.osc_counts.get('sell',0)}  ·  "
                 f"Nötr {signal.osc_counts.get('neutral',0)}   ({signal.oscillator_score:+.2f})")
        self.lbl_ma.configure(
            text=f"Hareketli Ort.:  Al {signal.ma_counts.get('buy',0)}  ·  "
                 f"Sat {signal.ma_counts.get('sell',0)}  ·  "
                 f"Nötr {signal.ma_counts.get('neutral',0)}   ({signal.ma_score:+.2f})")
        self.lbl_pv.configure(
            text=f"Pivotlar:  Al {signal.pivot_counts.get('buy',0)}  ·  "
                 f"Sat {signal.pivot_counts.get('sell',0)}  ·  "
                 f"Nötr {signal.pivot_counts.get('neutral',0)}   ({signal.pivot_score:+.2f})")
        self.lbl_comp.configure(
            text=f"BİLEŞİK SKOR: {signal.composite:+.3f}  →  {signal.signal.value}",
            text_color=color)

        self._update_tables(signal)
        self._update_wallet()
        self._update_position()

    def _update_tables(self, signal):
        for tree, rows in ((self.tree_osc, signal.oscillators),
                           (self.tree_ma, signal.moving_averages),
                           (self.tree_pv, signal.pivots)):
            tree.delete(*tree.get_children())
            for row in rows:
                tree.insert("", "end", values=(row.value_str, row.verdict_tr),
                            tags=(row.verdict,))

        detail = [f"Osilatör: {r.name.split('(')[0].strip()} {r.value_str}"
                  for r in signal.oscillators[:4]]
        self.lbl_osc_detail.configure(text="\n".join(detail))

    def _update_wallet(self):
        stats = self.engine.wallet.stats(self.engine.open_positions)
        display = {
            "equity": f"{stats['equity']:,.2f}",
            "balance": f"{stats['balance']:,.2f}",
            "available": f"{stats['available']:,.2f}",
            "unrealized": f"{stats['unrealized']:+,.2f}",
            "realized": f"{stats['realized']:+,.2f}",
            "fees": f"{stats['fees']:,.2f}",
            "trades": f"{stats['trades']} / {stats['wins']}",
            "win_rate": f"{stats['win_rate']:.1f}%",
            "roi": f"{stats['roi']:+.2f}%",
            "max_dd": f"{stats['max_dd']:.2f}%",
        }
        for key, text in display.items():
            lbl = self.wallet_labels.get(key)
            if not lbl:
                continue
            color = "#e6edf7"
            if key in ("unrealized", "realized", "roi", "net"):
                try:
                    color = "#26a69a" if float(text.replace(",", "").replace("+", "")) > 0 else "#ef5350"
                except ValueError:
                    pass
            lbl.configure(text=text, text_color=color)

    def _update_position(self):
        positions = self.engine.open_positions
        if not positions:
            self.lbl_position.configure(text="Pozisyon yok")
            return

        pos = positions[0]
        cfg = self.engine.config
        pnl_color = "#26a69a" if pos.unrealized_pnl >= 0 else "#ef5350"
        self.lbl_position.configure(
            text=(f"{pos.side.value}  {pos.quantity} BTC @ {pos.entry_price:,.2f}"
                  f"  |  {pos.leverage}x  |  SL {pos.stop_loss:,.0f}"
                  f"  |  TP {pos.take_profit:,.0f}\n"
                  f"Açık PnL: {pos.unrealized_pnl:+,.2f} USDT"
                  f"  ({pos.roi_pct:+.2f}%)"
                  f"   →  Kâr kilidi %{cfg.profit_lock_pct * 100:.0f}"
                  f"{'  [başa-baş açık]' if pos.breakeven_moved else ''}"),
            text_color=pnl_color)

    def _update_trades(self):
        self.tree.delete(*self.tree.get_children())
        
        algo = self.algo_var.get()
        is_hareketli_yeni = algo.startswith("hareketli_yeni")
        
        for pos in self.engine.closed_positions[-60:]:
            if is_hareketli_yeni:
                # MA sayıları (giriş)
                ma_e = getattr(pos, 'ma_counts_entry', {})
                ma_al_e = ma_e.get('buy', 0)
                ma_sat_e = ma_e.get('sell', 0)
                ma_notr_e = ma_e.get('neutral', 0)
                
                # MA sayıları (çıkış)
                ma_x = getattr(pos, 'ma_counts_exit', {})
                ma_al_x = ma_x.get('buy', 0)
                ma_sat_x = ma_x.get('sell', 0)
                ma_notr_x = ma_x.get('neutral', 0)
                
                self.tree.insert(
                    "", "end",
                    values=(pos.side.value,
                            f"{pos.entry_price:,.0f}",
                            f"{pos.exit_price:,.0f}" if pos.exit_price else "—",
                            f"{pos.realized_pnl:+,.1f}",
                            f"{pos.roi_pct:+.1f}%",
                            pos.exit_reason,
                            ma_al_e, ma_sat_e, ma_notr_e,
                            ma_al_x, ma_sat_x, ma_notr_x),
                    tags=(pos.side.value.lower(),))
            else:
                self.tree.insert(
                    "", "end",
                    values=(pos.side.value,
                            f"{pos.entry_price:,.0f}",
                            f"{pos.exit_price:,.0f}" if pos.exit_price else "—",
                            f"{pos.realized_pnl:+,.1f}",
                            f"{pos.roi_pct:+.1f}%",
                            pos.exit_reason),
                    tags=(pos.side.value.lower(),))

    # ==================================================================
    # GRAFIK
    # ==================================================================
    def _signal_payload(self) -> Dict[str, Any]:
        if self.last_signal is None:
            return {}
        s = self.last_signal
        return {
            "composite": round(s.composite, 4),
            "signal": s.signal.value,
            "oscillator_score": round(s.oscillator_score, 3),
            "ma_score": round(s.ma_score, 3),
            "pivot_score": round(s.pivot_score, 3),
            "osc_counts": f"Al {s.osc_counts.get('buy',0)} · Sat {s.osc_counts.get('sell',0)}",
            "ma_counts": f"Al {s.ma_counts.get('buy',0)} · Sat {s.ma_counts.get('sell',0)}",
            "pivot_counts": f"Al {s.pivot_counts.get('buy',0)} · Sat {s.pivot_counts.get('sell',0)}",
            "price": s.price,
        }

    def _push_chart(self):
        if self.chart_window is not None and self.chart_window.window is not None:
            self.chart_window.update(
                df=self.last_df,
                signal=self._signal_payload(),
                markers=self.engine.markers,
                equity_curve=self.last_equity,
            )

    def _open_chart(self):
        if self.last_df is None or self.last_df.empty:
            self._log("Önce veri yükleyin (Başlat'a basın).", "warn")
            return

        if self._has_lwc():
            opened = self.chart_window.open(
                df=self.last_df,
                signal=self._signal_payload(),
                markers=self.engine.markers,
                equity_curve=self.last_equity,
            )
            if opened:
                self._log("Lightweight Charts penceresi açıldı.", "good")
                return
            self._log("WebView açılamadı, matplotlib'a düşülüyor.", "warn")

        self._open_matplotlib()

    def _open_matplotlib(self):
        try:
            from gui.matplotlib_chart import show_chart
        except Exception as exc:
            self._log(f"Grafik modülü hatası: {exc}", "bad")
            return

        show_chart(
            df=self.last_df,
            markers=self.engine.markers,
            signal=self.last_signal,
            equity_curve=self.last_equity,
            signals=self.last_signals,
        )
        self._log("Matplotlib grafik açıldı.", "info")

    # ------------------------------------------------------------------
    def on_close(self):
        self._closing = True
        self._stop_flag.set()
        try:
            self.after_cancel(self._log_job)
        except Exception:
            pass
        if self.chart_window is not None:
            self.chart_window.close()
        self.destroy()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    )
    app = BotGUI()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()


if __name__ == "__main__":
    main()
