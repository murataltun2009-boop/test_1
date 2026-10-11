"""
BTCUSDT Canlı Teknik Analiz — MASAÜSTÜ (Tkinter) arayüzü.

  python main_desktop.py

Bu sürüm grafikleri matplotlib ile çizer ve ~400-500 ms çizim maliyeti
yüzünden arayüz zaman zaman kasılır. Varsayılan ve önerilen arayüz **web**
sürümüdür:

  python main.py

İkisi aynı çekirdeği (core/) kullanır; yalnızca görüntüleme katmanı farklıdır.
"""
from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
from logging.handlers import RotatingFileHandler

import config


def setup_logging() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:      # noqa: BLE001
                pass

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    root.addHandler(logging.StreamHandler(sys.stdout))
    try:
        fh = RotatingFileHandler(config.LOG_FILE, maxBytes=2_000_000,
                                 backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError:
        pass


def main() -> int:
    setup_logging()

    ap = argparse.ArgumentParser(description="BTCUSDT canlı teknik analiz (masaüstü)")
    ap.add_argument("--no-warmup", action="store_true",
                    help="açılışta sentetik veriyle ısınma yapma")
    args = ap.parse_args()

    root_dir = config.BASE_DIR
    if root_dir not in sys.path:
        sys.path.insert(0, root_dir)

    import customtkinter as ctk

    from core.service import MarketService
    from core.store import SignalStore
    from ui.main_window import MainWindow

    store = SignalStore()
    service = MarketService(config.SETTINGS, store)
    service.start()

    ctk.set_appearance_mode("dark")
    window = MainWindow(config.SETTINGS, service, store)

    if not args.no_warmup:
        # Pencere birkac kare bos gorunmesin diye arka planda isiitir.
        threading.Thread(target=lambda: (time.sleep(0.35), window.warm_up()),
                         daemon=True).start()

    try:
        window.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            service.stop()
            store.close()
        except Exception:      # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())