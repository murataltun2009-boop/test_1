import sys
sys.path.insert(0, '.')

from signals.hareketli_yeni import HareketliYeniEngine, HAREKETLI_YENI_MODE
from data.fetcher import DataFetcher
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")

fetcher = DataFetcher()
df = fetcher.fetch_ohlcv(timeframe='5m', limit=2000)
print(f"Veri: {len(df)} mum")

# Test 1: Cift yonlu (varsayilan)
print("\n=== TEST 1: CIFT YONLU (TWO_WAY) ===")
engine1 = HareketliYeniEngine()
engine1.generator.mode = HAREKETLI_YENI_MODE.TWO_WAY
result1 = engine1.run(df)
m1 = result1["metrics"]
print(f"  Trades: {m1['trades']} (LONG: {m1['long_trades']}, SHORT: {m1['short_trades']})")
print(f"  ROI: {m1['roi']:.2f}%")
print(f"  Win Rate: {m1['win_rate']:.1f}%")

# Test 2: Sadece LONG
print("\n=== TEST 2: SADECE LONG (LONG_ONLY) ===")
engine2 = HareketliYeniEngine()
engine2.generator.mode = HAREKETLI_YENI_MODE.LONG_ONLY
result2 = engine2.run(df)
m2 = result2["metrics"]
print(f"  Trades: {m2['trades']} (LONG: {m2['long_trades']}, SHORT: {m2['short_trades']})")
print(f"  ROI: {m2['roi']:.2f}%")
print(f"  Win Rate: {m2['win_rate']:.1f}%")

# Test 3: Sadece SHORT
print("\n=== TEST 3: SADECE SHORT (SHORT_ONLY) ===")
engine3 = HareketliYeniEngine()
engine3.generator.mode = HAREKETLI_YENI_MODE.SHORT_ONLY
result3 = engine3.run(df)
m3 = result3["metrics"]
print(f"  Trades: {m3['trades']} (LONG: {m3['long_trades']}, SHORT: {m3['short_trades']})")
print(f"  ROI: {m3['roi']:.2f}%")
print(f"  Win Rate: {m3['win_rate']:.1f}%")

print("\n=== TUM TESTLER TAMAMLANDI ===")