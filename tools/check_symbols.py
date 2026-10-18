"""config.SYMBOLS listesindeki HER coin gercekten calisiyor mu?

Liste hacim olcutuyle uretildi; ama Binance bazi sozlesmeleri
listeden sonra askiya alabilir ya da kline gecmisi hic donmeyebilir.
Bu test listeyi canli API'ye sorar:

  * 3 zaman dilimi icin yeterli mum geliyor mu (>= 60 bar)?
  * Analiz hata veriyor mu?
  * Bozuk fiyat (0) siziyor mu?

    python tools/check_symbols.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config                                            # noqa: E402
from core.analysis import analyze                       # noqa: E402
from core.binance_client import BinanceFuturesClient    # noqa: E402

MIN_BARS = 60          # analyze() icin gereken en az bar
BAD_PRICE = 0          # mumda 0 fiyat varsa onarim devrede demektir


def main() -> int:
    print(f"{len(config.SYMBOLS)} coin canli API ile sinaniyor...\n")
    ok = bad = repaired = 0
    hatalar: list[str] = []

    for sym in config.SYMBOLS:
        client = BinanceFuturesClient(sym)
        sorunlar: list[str] = []
        toplam_bar = 0

        for tf in config.TIMEFRAMES:
            try:
                candles = client.fetch_klines(tf, config.CANDLE_LIMIT)
            except Exception as exc:                    # noqa: BLE001
                sorunlar.append(f"{tf}: cekilemedi ({exc})")
                continue

            n = len(candles)
            toplam_bar += n
            if n < MIN_BARS:
                sorunlar.append(f"{tf}: yetersiz mum ({n}/{MIN_BARS})")
                continue

            sifir = sum(1 for c in candles
                        if c.low <= 0 or c.high <= 0 or c.close <= 0)
            if sifir:
                repaired += sifir
                sorunlar.append(f"{tf}: {sifir} bozuk fiyatli mum")

            try:
                analyze(
                    symbol=sym, timeframe=tf,
                    open_times=[c.open_time for c in candles],
                    o=[c.open for c in candles], h=[c.high for c in candles],
                    l=[c.low for c in candles], c=[c.close for c in candles],
                    v=[c.volume for c in candles],
                    close_times=[c.close_time for c in candles],
                )
            except Exception as exc:                    # noqa: BLE001
                sorunlar.append(f"{tf}: analiz hatasi ({exc})")

        if sorunlar:
            bad += 1
            hatalar.append(f"{sym}: " + "; ".join(sorunlar))
            print(f"  [HATA] {sym:<16} {'; '.join(sorunlar)}")
        else:
            ok += 1
            son = candles[-1].close if candles else 0
            print(f"  [ OK ] {sym:<16} {toplam_bar:>5} bar  son fiyat {son:,.6g}")

    print()
    print("=" * 66)
    print(f"calisan : {ok} / {len(config.SYMBOLS)}")
    print(f"hatali  : {bad}")
    if repaired:
        print(f"bozuk fiyatli mum (otomatik onarildi): {repaired}")
    if hatalar:
        print("\nHATALI COINLER (config.py'den cikarilmali):")
        for h in hatalar:
            print("  - " + h)
    print("=" * 66)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())