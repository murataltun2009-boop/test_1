"""
Grafik arayuzu acmadan cekirdek dogrulama.

  python selftest.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Windows konsolu varsayilan olarak cp1252; Turkce karakterler icin UTF-8 gerekli.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:      # noqa: BLE001
            pass

import numpy as np

import config
from core.analysis import analyze
from core.binance_client import BinanceFuturesClient
from core.store import SignalStore


def fmt_tr(x: float) -> str:
    return f"{x:,.2f}"


def main() -> int:
    print("=" * 74)
    print(f"Binance Futures  ·  {config.SYMBOL}  ·  canli veri dogrulamasi")
    print("=" * 74)

    client = BinanceFuturesClient(config.SYMBOL)
    store = SignalStore(os.path.join(config.DATA_DIR, "selftest.db"))

    failures = 0
    for tf in config.TIMEFRAMES:
        try:
            candles = client.fetch_klines(tf, config.CANDLE_LIMIT)
        except Exception as exc:      # noqa: BLE001
            print(f"\n[SKIP] {tf}: veri alinamadi -> {exc}")
            failures += 1
            continue

        try:
            res = analyze(
                symbol=config.SYMBOL, timeframe=tf,
                open_times=[c.open_time for c in candles],
                o=[c.open for c in candles], h=[c.high for c in candles],
                l=[c.low for c in candles], c=[c.close for c in candles],
                v=[c.volume for c in candles], close_times=[c.close_time for c in candles],
                strong_threshold=config.STRONG_THRESHOLD,
                base_threshold=config.BASE_THRESHOLD,
            )
        except Exception as exc:      # noqa: BLE001
            print(f"\n[HATA] {tf}: analiz basarisiz -> {exc}")
            failures += 1
            continue

        print(f"\n{'-'*74}")
        print(f"{config.TF_LABELS[tf]}  ({tf})   son fiyat: {fmt_tr(res.price)}")
        print(f"{'-'*74}")
        print(f"{'Osilatörler':<44} {'Değer':>14}  {'İşlem detayı':<12}")
        for row in res.oscillator_rows:
            print(f"{row.label:<44} {row.value_text:>14}  {row.verdict.label:<12}")
        print()
        print(f"{'Hareketli Ortalamalar':<44} {'Değer':>14}  {'İşlem detayı':<12}")
        for row in res.ma_rows:
            print(f"{row.label:<44} {row.value_text:>14}  {row.verdict.label:<12}")

        print("-" * 74)
        print(f"Osilatör skoru  : {res.oscillator_scores[-1]:+.3f}")
        print(f"Hareketli ort.  : {res.ma_scores[-1]:+.3f}")
        print(f"BİLEŞİK SKOR    : {res.composite_value:+.3f}")
        print(f"SİNYAL          : {res.signal.value}")

        markers = res.marker_indices()
        print(f"Grafikteki yıldız: {len(markers)} bar "
              f"(görünen {min(len(markers), config.VISIBLE_CANDLES)}/{len(markers)})")
        tail = markers[-6:]
        for i in tail:
            print(f"    bar {i}  {res.signals[i].value:<11} fiyat {res.c[i]:,.2f}")

        # --- veri bütünlüğü kontrolleri ---------------------------------
        problems = []
        if not np.isfinite(res.price):
            problems.append("son fiyat NaN")
        if not np.all(np.isfinite(res.composite)):
            problems.append("bilesik skor icinde NaN var")
        if len(res.signals) != res.c.size:
            problems.append("sinyal sayisi bar sayisiyla uyusmuyor")
        if len(res.oscillator_rows) != 11:
            problems.append(f"osilator sayisi {len(res.oscillator_rows)} (11 olmali)")
        if len(res.ma_rows) != 15:
            problems.append(f"hareketli ort. sayisi {len(res.ma_rows)} (15 olmali)")

        if problems:
            print("\n  [UYARI] " + "; ".join(problems))
            failures += 1
        else:
            print("  [OK] veri bütünlüğü kontrolleri geçti")

    # --- veritabanı testi ------------------------------------------------
    print(f"\n{'-'*74}")
    try:
        detail = [{"ad": r.label, "deger": r.value_text, "islem": r.verdict.label}
                  for r in res.rows]
        rid = store.record_signal(
            symbol=config.SYMBOL, timeframe="1h", candle_open_time=res.open_time,
            signal=res.signal.value, previous_signal="NÖTR",
            composite=res.composite_value, price=res.price,
            osc_score=float(res.oscillator_scores[-1]),
            ma_score=float(res.ma_scores[-1]),
            osc_counts={1: 5, 0: 4, -1: 2}, ma_counts={1: 9, 0: 3, -1: 3},
            details=detail)
        n = store.count_signals()
        print(f"[OK] veritabanına yazıldı (id={rid}), toplam kayıt: {n}")
        rows = store.recent_signals(3)
        print(f"[OK] son kayıt okundu: {len(rows)} satır")
        print("     istatistik:", store.stats_by_timeframe())
        store.reset()
        print(f"[OK] veritabanı sıfırlandı, kalan: {store.count_signals()}")
    except Exception as exc:      # noqa: BLE001
        print(f"[HATA] veritabanı testi: {exc}")
        failures += 1
    finally:
        store.close()

    print("=" * 74)
    print("SONUÇ:", "TÜM TESTLER GEÇTİ" if failures == 0 else f"{failures} SORUN")
    print("=" * 74)
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())