"""
Log ekrani.

Islem ve sistem degisimleri tarih/saat damgasiyla listelenir. Renk kodlari:
  yesil  = AL / GÜÇLÜ AL
  kirmizi= SAT / GÜÇLÜ SAT
  gri    = NÖTR
  sari   = uyari, kirmizi = hata
"""
from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

import config

BG = "#0b121b"
TEXT = "#c3d0de"

LEVEL_COLORS = {
    "info":    "#8fa3b8",
    "ok":      "#26a69a",
    "warning": "#ffb300",
    "error":   "#ff5252",
    "signal":  "#e8eef6",
}

TAG_COLORS = {
    "GÜÇLÜ AL":  ("#00e676", "#00e676"),
    "AL":         ("#66bb6a", "#66bb6a"),
    "NÖTR":       ("#9aa8b8", "#9aa8b8"),
    "SAT":        ("#ffa726", "#ffa726"),
    "GÜÇLÜ SAT":  ("#ff1744", "#ff1744"),
}

FONT = ("Consolas", 9)

LOG_HEIGHT = config.LOG_HEIGHT      # gorunen satir sayisi


class LogPanel(ctk.CTkFrame):
    def __init__(self, parent, on_toggle=None):
        super().__init__(parent, fg_color=BG, corner_radius=6,
                         border_width=1, border_color="#22303f")
        self._on_toggle = on_toggle

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, columnspan=4, sticky="ew", padx=8, pady=(4, 1))
        ctk.CTkLabel(head, text="İşlem Değişim Logu",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color="#8fb3d9").pack(side="left")

        self.count_lbl = ctk.CTkLabel(head, text="0 satır",
                                      font=ctk.CTkFont(size=8),
                                      text_color="#6b7c8f")
        self.count_lbl.pack(side="left", padx=10)

        self.toggle_btn = ctk.CTkButton(head, text="Logu gizle", width=72, height=20,
                                        font=ctk.CTkFont(size=8),
                                        command=self._toggle)
        self.toggle_btn.pack(side="right")

        ctk.CTkButton(head, text="Temizle", width=56, height=20,
                      font=ctk.CTkFont(size=8), command=self.clear).pack(side="right")
        ctk.CTkButton(head, text="Kaydet…", width=56, height=20,
                      font=ctk.CTkFont(size=8), command=self.export).pack(side="right", padx=4)
        ctk.CTkButton(head, text="Sona git", width=66, height=20,
                      font=ctk.CTkFont(size=8), command=self.scroll_to_end
                      ).pack(side="right")

        self.text = tk.Text(self, bg=BG, fg=TEXT, font=FONT, relief="flat",
                            wrap="none", height=LOG_HEIGHT, insertbackground=TEXT,
                            selectbackground="#2b4a6f", selectforeground="#ffffff",
                            highlightthickness=0, bd=0)
        self.text.grid(row=1, column=0, columnspan=3, sticky="nsew",
                       padx=6, pady=(0, 5))
        sb = ctk.CTkScrollbar(self, command=self.text.yview, width=12,
                              height=max(40, LOG_HEIGHT * 14),
                              button_color="#2b3a4a",
                              button_hover_color="#3a4c5f")
        sb.grid(row=1, column=3, sticky="ns", padx=(0, 4), pady=(0, 5))
        self.text.configure(yscrollcommand=sb.set)

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._count = 0
        self._lock_scroll = False
        self._init_tags()
        self.text.bind("<MouseWheel>", self._on_wheel)

    # ------------------------------------------------------------------
    def _init_tags(self) -> None:
        """Etiket renkleri bir kez kurulur."""
        for name, (fg, _tag) in TAG_COLORS.items():
            self.text.tag_configure(name, foreground=fg)
        for level, color in LEVEL_COLORS.items():
            self.text.tag_configure(level, foreground=color)

    # ------------------------------------------------------------------
    def _on_wheel(self, event) -> None:
        """Kullanici yukarida geziyorsa otomatik kayma dursun."""
        try:
            at_bottom = self.text.yview()[1] >= 0.98
        except Exception:      # noqa: BLE001
            at_bottom = True
        self._lock_scroll = not at_bottom

    # ------------------------------------------------------------------
    def add_system(self, stamp: str, level: str, message: str) -> None:
        self._append(f"{stamp}  [{level.upper():<7}] {message}", level)

    def add_signal(self, stamp: str, signal_value: str, text: str) -> None:
        tag = signal_value if signal_value in TAG_COLORS else "signal"
        self._append(f"{stamp}  \u2605 {signal_value:<11} {text}", tag)

    # ------------------------------------------------------------------
    def _append(self, line: str, tag: str) -> None:
        self.text.insert("end", line + "\n", tag)
        self._count += 1

        # Uzunluk siniri
        lines = int(self.text.index("end-1c").split(".")[0])
        if lines > config.LOG_MAX_LINES:
            self.text.delete("1.0", f"{lines - config.LOG_MAX_LINES}.0")

        if not self._lock_scroll:
            self.text.see("end")
        self._refresh_count()

    # ------------------------------------------------------------------
    def _refresh_count(self) -> None:
        try:
            lines = int(self.text.index("end-1c").split(".")[0])
        except Exception:      # noqa: BLE001
            lines = self._count
        self.count_lbl.configure(text=f"{lines} satır")

    def clear(self) -> None:
        self.text.delete("1.0", "end")
        self._count = 0
        self._refresh_count()

    # ------------------------------------------------------------------
    def _toggle(self) -> None:
        if self._on_toggle:
            self._on_toggle()

    def set_toggle_text(self, visible: bool) -> None:
        self.toggle_btn.configure(text="Logu gizle" if visible else "Logu aç")

    def scroll_to_end(self) -> None:
        self._lock_scroll = False
        self.text.see("end")

    def export(self) -> None:
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Metin dosyasi", "*.txt"), ("Tum dosyalar", "*.*")],
            title="Logu kaydet",
        )
        if not path:
            return
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self.text.get("1.0", "end"))