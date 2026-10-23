"""Mod bazli sinyal serilerini canli veriyle dogrular (bagimsiz)."""
import sys
sys.path.insert(0, r"C:\Users\PC-ITENG\Documents\BTCUSDT_TA_Live")
import os
os.chdir(r"C:\Users\PC-ITENG\Documents\BTCUSDT_TA_Live")

from collections import Counter
import config
from core.binance_client import BinanceFuturesClient
from core.analysis import analyze, marker_indices_from
from core.service import MarketService
from core.paper import PaperTrader

TF = "15m"

cl = BinanceFuturesClient("BTCUSDT")
candles = cl.fetch_klines(TF, 400)
res = analyze("BTCUSDT", TF,
              [c.open_time for c in candles],
              [c.open for c in candles], [c.high for c in candles],
              [c.low for c in candles], [c.close for c in candles],
              [c.volume for c in candles], [c.close_time for c in candles])

cfg = config.Settings()
paper = PaperTrader(cfg)
paper.running = True
paper.start_balance = 1000.0
paper.balance = 1000.0

service = MarketService(cfg, store=None, paper=paper)
service._started = True
service._buffers[TF] = candles
service._analyses[TF] = res
service._versions[TF] = 1

print("res.signals uz:", len(res.signals))
for mode in ["signal", "ma_only", "osc_only", "trend", "muro", "1m", "ppt"]:
    paper.mode = mode
    try:
        ser = service.mode_signal_series(TF)
    except Exception as exc:
        print(f"{mode:>9}: HATA {exc}")
        continue
    cnt = Counter(s.value for s in ser)
    idxs = marker_indices_from(ser)
    mcnt = Counter(ser[i].value for i in idxs)
    uz = len(ser)
    hiz = "Evet" if uz == len(res.signals) else "HAYIR"
    print(f"{mode:>9}: uz={uz} hizali={hiz} | seri={dict(cnt)} | "
          f"marker={len(idxs)} {dict(mcnt)}")
