"""
Gosterge deger tablosu.

TradingView "Technicals" sayfasindaki iki tabloyu birebir taklit eder:
Osilatörler (Ad / Deger / Islem detayi) ve Hareketli Ortalamalar.

Hucresi tek tek guncellemek icin tkinter Text yerine etiket nesneleri
saklanir; boylece 26 satirlik tablo her 200 ms'de de sorunsuz calisir.
"""
from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from core.analysis import TimeframeAnalysis, Verdict

VERDICT_COLOR = {
    Verdict.BUY: "#00c853",
    Verdict.NEUTRAL: "#8fa3b8",
    Verdict.SELL: "#ff5252",
}

BG = "#111a26"
HEAD = "#18232f"
BORDER = "#22303f"


class IndicatorTable(ctk.CTkFrame):
    """Tek bir bolumun (Osilatorler / Hareketli Ortalamalar) tablosu."""

    def __init__(self, parent, title: str, fg_color=BG):
        super().__init__(parent, fg_color=fg_color, corner_radius=6,
                         border_width=1, border_color=BORDER)
        self._labels: dict[str, tuple[tk.Label, tk.Label]] = {}

        head = ctk.CTkLabel(self, text=title, font=ctk.CTkFont(size=10, weight="bold"),
                            text_color="#8fb3d9", anchor="w")
        head.grid(row=0, column=0, columnspan=3, sticky="ew", padx=6, pady=(4, 2))

        for col, text in enumerate(("Adı", "Değer", "Detay")):
            lbl = tk.Label(self, text=text, anchor="w", bg=HEAD, fg="#7f93a8",
                           font=("Segoe UI", 7, "bold"), padx=4, pady=0)
            lbl.grid(row=1, column=col, sticky="ew", padx=1)
        self.grid_columnconfigure(0, weight=5, minsize=136)
        self.grid_columnconfigure(1, weight=2, minsize=62)
        self.grid_columnconfigure(2, weight=2, minsize=44)

    # ------------------------------------------------------------------
    def ensure_rows(self, rows) -> None:
        """Satirlari ilk seferde olusturur; mevcut olanlara dokunmaz."""
        if len(self._labels) == len(rows):
            return
        self._labels.clear()
        for i, row in enumerate(rows):
            r = i + 2
            name = tk.Label(self, text=row.label, anchor="w", bg=BG, fg="#c9d6e4",
                            font=("Segoe UI", 7), padx=4, pady=0)
            value = tk.Label(self, text="—", anchor="e", bg=BG, fg="#e8eef6",
                             font=("Consolas", 8))
            verdict = tk.Label(self, text="Nötr", anchor="center", bg=BG,
                               fg=VERDICT_COLOR[Verdict.NEUTRAL],
                               font=("Segoe UI", 7, "bold"))
            name.grid(row=r, column=0, sticky="ew", padx=1)
            value.grid(row=r, column=1, sticky="ew", padx=1)
            verdict.grid(row=r, column=2, sticky="ew", padx=1)
            self._labels[row.label] = (value, verdict)

    # ------------------------------------------------------------------
    def update_rows(self, rows) -> None:
        self.ensure_rows(rows)
        for row in rows:
            pair = self._labels.get(row.label)
            if pair is None:
                continue
            value_lbl, verdict_lbl = pair
            value_lbl.configure(text=row.value_text)
            verdict_lbl.configure(text=row.verdict.label,
                                  fg=VERDICT_COLOR[row.verdict])


class TablesColumn(ctk.CTkFrame):
    """Osilatorler + Hareketli Ortalamalar tablolarini yan yana tutar."""

    def __init__(self, parent):
        super().__init__(parent, fg_color="transparent")
        self.osc_table = IndicatorTable(self, "Osilatörler")
        self.ma_table = IndicatorTable(self, "Hareketli Ortalamalar")
        self.osc_table.grid(row=0, column=0, sticky="nsew", padx=(0, 3))
        self.ma_table.grid(row=0, column=1, sticky="nsew", padx=(3, 0))
        self.grid_columnconfigure(0, weight=3, uniform="t")
        self.grid_columnconfigure(1, weight=3, uniform="t")
        self.grid_rowconfigure(0, weight=1)

    def update(self, res: TimeframeAnalysis) -> None:
        self.osc_table.update_rows(res.oscillator_rows)
        self.ma_table.update_rows(res.ma_rows)