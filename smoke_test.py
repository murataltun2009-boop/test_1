"""
Arayuz duman (smoke) testi.

Pencereyi acar, canli Binance verisiyle doldurur, etkilesimleri test eder,
yerlesimi olcer ve ekran goruntusu alir.

  python smoke_test.py
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:      # noqa: BLE001
            pass

import customtkinter as ctk  # noqa: E402

import config  # noqa: E402
from core.service import MarketService  # noqa: E402
from core.store import SignalStore  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402

SHOT = os.path.join(config.LOG_DIR, "arayuz.png")
TIP_SHOT = os.path.join(config.LOG_DIR, "ipucu.png")
TF = config.ACTIVE_TIMEFRAME


class _Ev:
    """Tekerlek olayi icin basit tasima."""

    def __init__(self, x, y, delta):
        self.x, self.y, self.delta = x, y, delta


def main() -> int:
    print("Arayuz baslatiliyor...")

    store = SignalStore()
    service = MarketService(config.SETTINGS, store)

    app = MainWindow(config.SETTINGS, service, store)
    app.update()
    print(f"Pencere acildi: {app.winfo_width()}x{app.winfo_height()}", flush=True)

    t0 = time.perf_counter()
    app.warm_up()
    print(f"warm_up suresi: {time.perf_counter()-t0:.2f} s", flush=True)

    t0 = time.perf_counter()
    app._on_start()
    print(f"Canli akis baslatildi ({time.perf_counter()-t0:.2f} s), "
          f"14 saniye bekleniyor...", flush=True)

    deadline = time.time() + 14.0
    iter_no = 0
    slow = []
    while time.time() < deadline:
        iter_no += 1
        t_idle = time.perf_counter()
        app.update_idletasks()
        dt_idle = time.perf_counter() - t_idle
        t0 = time.perf_counter()
        app.update()
        dt = time.perf_counter() - t0
        if dt > 0.25 or dt_idle > 0.25:
            slow.append((iter_no, dt_idle, dt))
        time.sleep(0.05)

    app.update()
    ok = True

    # ==================================================================
    print("--- etkilesim ---", flush=True)
    from matplotlib.backend_bases import MouseEvent

    ch = app.chart
    total = len(ch._last_res.c)
    w, h = ch.widget.winfo_width(), ch.widget.winfo_height()

    def view():
        return ch.view_range

    print(f"  gorunum: {view()} (toplam {total} bar, grafik {w}x{h} px = "
          f"{w*h:,} piksel)", flush=True)

    # 1) Tekerlek ile yakinlastirma
    before = view()
    ch._on_wheel(_Ev(int(w * 0.35), int(h * 0.5), 120))
    after = view()
    zoomed = (after[1] - after[0]) < (before[1] - before[0])
    print(f"  tekerlek yakinlastirdi : {before} -> {after}  "
          f"[{'OK' if zoomed else 'HATA'}]", flush=True)
    ok &= zoomed

    # 2) Uzaklastirma
    ch._on_wheel(_Ev(int(w * 0.35), int(h * 0.5), -120))
    back = view()
    unzoomed = (back[1] - back[0]) > (after[1] - after[0])
    print(f"  tekerlek uzaklastirdi : {after} -> {back}  "
          f"[{'OK' if unzoomed else 'HATA'}]", flush=True)
    ok &= unzoomed

    # 3) Surukleyerek kaydirma
    ax_x0, ax_y0, ax_w, ax_h = ch._axes_rect_tk()
    px_per_bar = ax_w / max(1e-9, ch.ax.get_xlim()[1] - ch.ax.get_xlim()[0])
    start_px = ax_x0 + ax_w * 0.35
    mid_py = ax_y0 + ax_h * 0.5
    ch._on_press(MouseEvent("button_press_event", ch.canvas,
                            int(start_px), int(mid_py), 1))
    ev = None
    for step in range(1, 8):
        ev = MouseEvent("motion_notify_event", ch.canvas,
                        int(start_px + step * 5 * px_per_bar), int(mid_py), 1)
        ch._on_motion(ev)
    ch._on_release(ev)
    panned = view()
    moved = panned[1] < back[1]
    print(f"  surukleyerek kaydirma : {back} -> {panned}  "
          f"[{'OK' if moved else 'HATA'}]", flush=True)
    ok &= moved

    # 4) Sigdir
    app._fit_chart()
    app.update()
    fitted = view()
    fitted_ok = fitted[1] == total and \
        (fitted[1] - fitted[0]) == config.VISIBLE_CANDLES
    print(f"  Sigdir dugmesi         : {panned} -> {fitted}  "
          f"[{'OK' if fitted_ok else 'HATA'}]", flush=True)
    ok &= fitted_ok

    # 5) Imlec ustune gelince capraz + ipucu
    res = ch._last_res
    mid_bar = fitted[0] + (fitted[1] - fitted[0]) // 2
    lo, hi = ch.ax.get_xlim()
    px = ax_x0 + (mid_bar - lo) / (hi - lo) * ax_w
    py = ax_y0 + ax_h * 0.5

    app.update()
    app.event_generate("<Motion>", warp=True, x=4, y=4)   # grafigen uzaklastir
    app.update()
    ch._hide_cursor_layer()

    ch._on_motion(MouseEvent("motion_notify_event", ch.canvas, px, py, 1))
    app.update_idletasks()
    tip_vis = bool(ch._tip.winfo_ismapped())
    cross = bool(ch._vline.winfo_ismapped()) and bool(ch._hline.winfo_ismapped())
    tip_text = str(ch._tip.cget("text"))
    print(f"  capraz dikey/yatay    : {cross}   ipucu gorunur: {tip_vis}", flush=True)
    for line in tip_text.splitlines():
        print(f"      | {line}", flush=True)
    ok &= tip_vis and cross and bool(tip_text.strip())

    # 6) REGRESYON: imlec ipucunun UZERINDEYKEN bilgi kaybolmamali
    #    (kullanici "yildizlarin uzerine gelince kayboluyor" diyordu)
    tip_x = ch._tip.winfo_rootx()
    tip_y = ch._tip.winfo_rooty()
    tip_w = ch._tip.winfo_width()
    tip_h = ch._tip.winfo_height()
    inside = (tip_w > 0 and tip_h > 0)
    if inside:
        app.event_generate(
            "<Motion>", warp=True,
            x=tip_x + tip_w // 2 - app.winfo_rootx(),
            y=tip_y + tip_h // 2 - app.winfo_rooty())
        app.update()
        still = bool(ch._tip.winfo_ismapped())
        print(f"  imlec ipcunun uzerinde: tip {tip_w}x{tip_h}, "
              f"gorunur={still}  [{'OK' if still else 'HATA'}]", flush=True)
        ok &= still

    # 6b) Ipucu gorunurken ekran goruntusu
    try:
        from PIL import ImageGrab
        x, y = app.winfo_rootx(), app.winfo_rooty()
        w2, h2 = app.winfo_width(), app.winfo_height()
        ImageGrab.grab(bbox=(x, y, x + w2, y + h2)).save(TIP_SHOT)
        print(f"  ipucu ekran goruntusu: {TIP_SHOT}", flush=True)
    except Exception as exc:      # noqa: BLE001
        print(f"  ipucu goruntusu alinamadi: {exc}", flush=True)

    # 7) Imlec GERCEKTEN grafikten cikinca gizlenmeli
    #    Once imleci grafigin disina tasi, sonra canvas'a <Leave> olayini
    #    uret. Boylece "imlec hala grafik alaninda mi?" kontrolu de
    #    gercekten farkli bir yoldan gecmis olur.
    app.event_generate("<Motion>", warp=True, x=4, y=4)
    app.update()
    ch.widget.event_generate("<Leave>")
    app.update()
    app.update_idletasks()
    hidden = not ch._tip.winfo_ismapped()
    print(f"  imlec grafigi birakince gizli: {hidden}  "
          f"[{'OK' if hidden else 'HATA'}]", flush=True)
    ok &= hidden

    # ==================================================================
    print("--- canlilik ---", flush=True)
    snap = service.snapshot()
    r = snap["analyses"].get(TF)
    if r is None:
        print(f"  [HATA] {TF} icin analiz yok")
        ok = False
    else:
        print(f"  dilim {TF}  fiyat={r.price:,.2f}  skor={r.composite_value:+.3f}  "
              f"sinyal={r.signal.value}  yildiz={len(r.marker_indices())}", flush=True)
    print(f"  son cizim suresi      : {ch.last_draw_ms:.0f} ms  -> "
          f"yenileme araligi {max(ch.last_draw_ms * app.chart_headroom, app.chart_min_interval):.0f} ms",
          flush=True)
    print(f"  dongu: {iter_no}, yavas olan ({len(slow)}):", flush=True)
    for n, ti, tf_ in slow[:8]:
        print(f"     #{n:<4} idletasks {ti*1000:7.0f} ms | update {tf_*1000:7.0f} ms",
              flush=True)

    # ==================================================================
    print("--- yerlesim ---", flush=True)
    print(f"ekran {app.winfo_screenwidth()}x{app.winfo_screenheight()} | "
          f"pencere {app.winfo_width()}x{app.winfo_height()} | "
          f"pencere_kok {app.winfo_rootx()},{app.winfo_rooty()}", flush=True)
    sw = app.winfo_screenwidth()
    for name, widget in [("sembol", app.symbol_entry), ("db_lbl", app.db_lbl),
                         ("baslat", app.start_btn)]:
        rx = widget.winfo_rootx()
        right = rx + widget.winfo_width()
        visible = rx >= 0 and right <= sw
        print(f"  {name:<7} ekran_x={rx:>5} sag={right:>5}  "
              f"[{'OK' if visible else 'EKRAN DISI'}]", flush=True)
        ok &= visible
    print(f"  grafik alani          : {w}x{h} px", flush=True)
    print(f"  gosterge tablolari    : {app.tables.osc_table.winfo_width()} + "
          f"{app.tables.ma_table.winfo_width()} px", flush=True)
    for name, widget in [("cubuk", app.symbol_entry.master.master),
                         ("log", app.log), ("durum", app.status),
                         ("grafik cerceve", ch.widget.master)]:
        print(f"  yukseklik {name:<14}: {widget.winfo_height():>4} px "
              f"(y={widget.winfo_rooty()})", flush=True)

    # --- genel ekran goruntusu -------------------------------------------
    try:
        from PIL import ImageGrab
        x, y = app.winfo_rootx(), app.winfo_rooty()
        w2, h2 = app.winfo_width(), app.winfo_height()
        ImageGrab.grab(bbox=(x, y, x + w2, y + h2)).save(SHOT)
        print(f"Ekran goruntusu kaydedildi: {SHOT} ({w2}x{h2})", flush=True)
    except Exception as exc:      # noqa: BLE001
        print(f"Ekran goruntusu alinamadi: {exc}", flush=True)

    service.stop()
    app._on_close()

    print("SONUC:", "ARAYUZ CALISIYOR" if ok else "SORUN VAR", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())