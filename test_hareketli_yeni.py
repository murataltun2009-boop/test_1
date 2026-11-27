import sys
sys.path.insert(0, '.')

from signals.hareketli_yeni import HareketliYeniEngine
from data.fetcher import DataFetcher
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")

fetcher = DataFetcher()
df = fetcher.fetch_ohlcv(timeframe='5m', limit=2000)
print(f"Veri: {len(df)} mum")

engine = HareketliYeniEngine()
result = engine.run(df)

print("\n=== METRIKLER ===")
for k, v in result['metrics'].items():
    print(f"  {k:18}: {v}")

# Son sinyalleri göster
signals = result["signals"].tail(10)
print("\n--- Son 10 Sinyal ---")
for ts, row in signals.iterrows():
    print(f"  {ts} | {row['direction']:7} | AL={row['ma_al']:2d} SAT={row['ma_sat']:2d} NÖTR={row['ma_notr']:2d} | skor={row['composite']:+.3f}")