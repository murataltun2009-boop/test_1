"""
BTCUSDT Canlı Teknik Analiz — WEB arayüzü (birincil giriş noktası).

  python main.py

Sunucuyu başlatır ve varsayılan tarayıcıda açar.
Arayüz tarayıcıda (ECharts) çizildiği için grafik güncellemesi anlıktır.

Masaüstü (Tkinter) arayüzü hâlâ mevcuttur:
  python main_desktop.py
"""
from __future__ import annotations

import argparse
import logging
import socket
import sys
import threading
import time
import webbrowser
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
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)
    try:
        fh = RotatingFileHandler(config.LOG_FILE, maxBytes=2_000_000,
                                 backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError:
        pass


def find_free_port(preferred: int) -> int:
    """Tercih edilen portu dener, doluysa boş bir port bulur."""
    for port in [preferred] + list(range(preferred + 1, preferred + 40)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return preferred


def main() -> int:
    setup_logging()

    ap = argparse.ArgumentParser(description="BTCUSDT canlı teknik analiz (web)")
    ap.add_argument("--port", type=int, default=8765, help="port (varsayılan 8765)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-browser", action="store_true",
                    help="tarayıcıyı otomatik açma")
    args = ap.parse_args()

    root = config.BASE_DIR
    if root not in sys.path:
        sys.path.insert(0, root)

    import uvicorn
    from core.paper import PaperTrader
    from core.service import MarketService
    from core.store import SignalStore
    from web.server import create_app

    store = SignalStore()

    # Kaldirac simulasyonu: cuzdan motoru. Servis her mum guncellemesinde
    # odaktaki dilim icin besler, sunucu anlik durumu tarayiciya yayar.
    # NOT: gercek emir gonderilmez, borsa hesabi tasinmaz.
    paper = PaperTrader(symbol=config.SETTINGS.symbol)

    service = MarketService(config.SETTINGS, store, paper=paper)
    app = create_app(service, store, paper=paper)

    port = find_free_port(args.port)
    url = f"http://{args.host}:{port}/"

    print("=" * 68)
    print(f"  BTCUSDT {config.ACTIVE_TIMEFRAME.upper()} — Canlı Teknik Analiz")
    print(f"  Binance Futures · {config.SETTINGS.symbol}")
    print("=" * 68)
    print(f"  Adres     : {url}")
    print(f"  Durdurmak : Ctrl+C")
    print("=" * 68)

    if not args.no_browser:
        def open_browser() -> None:
            time.sleep(1.2)
            try:
                webbrowser.open(url)
            except Exception:      # noqa: BLE001
                pass
        threading.Thread(target=open_browser, daemon=True).start()

    try:
        uvicorn.run(app, host=args.host, port=port, log_level="warning",
                    access_log=False)
    except KeyboardInterrupt:
        print("\nKapatılıyor...")
    finally:
        try:
            service.stop()
            store.close()
        except Exception:      # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())