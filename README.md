# BTCUSDT Futures Trading Bot

TradingView 1dk teknik analiz mantığını birebir Python'da hesaplayan, **test
cüzdanı** ile çalışan kaldıraçlı vadeli işlem botu. Grafikte LONG/SHORT
noktaları işaretlenir, tüm maliyetler (komisyon, SL/TP, likidasyon) hesaba
katılır.

## Kurulum

```bash
pip install -r requirements.txt
python main.py
```

`pywebview` kurulu değilse grafik matplotlib'a düşer (otomatik).

## Kullanım

```bash
python main.py                    # GUI aç
python main.py --backtest         # konsol backtest + grafik
python main.py --tune             # parametre taraması
python backtest/oos_test.py       # walk-forward doğrulaması (OOS)
```

> Parametre taramasının çıktısı **en iyi** sonucu gösterir, doğrulanmış
> sonucu değil. `--tune` çıktısındaki en iyi ayarların gerçekte işe
> yarayıp yaramadığını `oos_test.py` söyler.

GUI'de **canlı** ya da **backtest** modu seçilir. `Başlat` ile akış başlar.

## Sinyal algoritması

TradingView'in "Technicals" sayfasındaki üç bölümün ağırlıklı ortalaması:

| Bölüm | Ağırlık | İçerik |
|---|---|---|
| Osilatörler | %40 | RSI(14), Stokastik %K(14,3,3), CCI(20), ADX(14), Müthiş Osilatör, Momentum(10), MACD(12,26), Stokastik RSI(3,3,14,14), Williams %R(14), Boğa Ayı Gücü, UO(7,14,28) |
| Hareketli Ortalamalar | %40 | EMA+SMA (10, 20, 30, 50, 100, 200), İchimoku Tenkan/Kijun, VWMA(20), Hull MA(9) |
| Pivotlar | %20 | Klasik P, R1/R2/R3, S1/S2/S3 |

Her osilatör TradingView ile aynı eşiklerle `Al / Sat / Nötr` yorumuna
çevrilir, sonra bölüm skoru `(al − sat) / toplam` ile −1..1 arasına
normalize edilir. Bileşik skor:

```
bileşik = 0.40 × osilatör + 0.40 × hareketli_ort + 0.20 × pivot
```

| Skor | Sinyal | İşlem |
|---|---|---|
| ≥ +0.65 | **GÜÇLÜ AL** | LONG aç |
| ≥ +0.40 | AL | bekle |
| ≤ −0.65 | **GÜÇLÜ SAT** | SHORT aç |
| ≤ −0.40 | SAT | bekle |
| arası | NÖTR | bekle |

Sadece **güçlü** sinyaller emir açar; orta sinyaller pozisyon kapatmada
devreye girmez. Kapatma kuralı için aşağıdaki bölüme bakın.

## Sinyal mantığı (önemli)

Sadece **güçlü** sinyaller emir açar. Pozisyon açıkken kapatma kuralı da
serttir: **yalnızca ters yön güçlü sinyal** kapatır.

Bu tasarım bilinçlidir. Başlangıçta "skor nötre dönerse kapat" kuralı
denendi ve backtest **−%11** getirdi: skor 1 dakikalık periyotta o kadar sık
nötr↔güçlü salınıyor ki her pozisyon SL/TP'ye uğramadan kapanıyordu. Kanıt:
SL %0.6 ile SL %1.5 ayarları *birebir aynı* sonucu veriyordu, yani SL/TP hiç
işlev görmüyordu. Kuralı değiştirince aynı periyotta kazanç oranı %20 → %44,
profit factor 0.70 → 1.29 oldu.

Kuralı gevşetmek sürekli gir-çık (whipsaw) üretir. Eşiği ve SL/TP'yi değiştirip
`python main.py --tune` ile ölçün.

## Backtest sonuçları ve dürüst uyarı

Varsayılan ayarlar (eşik ±0.65, SL %1.0, TP %1.8, 5x kaldıraç, marjinin
%20'si) **66 günlük** gerçek Binance verisinde:

| Metrik | Değer |
|---|---|
| Net PnL | +846.82 USDT (+%8.47) |
| İşlem | 49 |
| Kazanç oranı | %46.9 |
| Profit factor | 1.36 |
| Max drawdown | %9.0 |

**Bunu bir başarı olarak sunmak yanlış olur.** 49 işlem, %0.10 komisyon
yükünde, 1 dakikalık veride istatistiksel olarak zayıf bir kanıt. Profit
factor 1.36 "başa baş" ile "belirgin kâr" arasında; üstelik sürtünme,
kayma (slippage) ve gecikme gerçekte daha kötüdür.

### Walk-forward doğrulaması

`backtest/oos_test.py` veriyi ikiye böler: parametreler ilk yarıda seçilir,
ikinci yarıda **hiç ayar yapılmadan** çalıştırılır. "Güzel sonucu tarama mı
üretti?" sorusunun tek dürüst cevabı budur.

| Metrik | IS (Ağu–Eyl) | OOS (Eyl–Eki) |
|---|---|---|
| Net PnL | +2119.81 | +457.45 |
| ROI | +%21.20 | +%4.57 |
| İşlem | 20 | 23 |
| Kazanç oranı | %60.0 | %47.8 |
| Profit factor | 2.11 | **1.22** |
| Max drawdown | %5.80 | %15.75 |

**Strateji hâlâ pozitif ama kanıt zayıf.** OOS getirisi IS'in beşte biri;
profit factor 2.11'den 1.22'ye düşmüş; drawdown 2.7 kat artmış. Klasik
aşırı uyum (overfitting) imzası: 160 kombinasyondan seçilen en iyi parametre,
seçildiği dönemin şanslı bir ürünü.

Tutarlı bir çelişki daha: 21 günlük taramada en iyi sonucu **eşik 0.55**
verdi (+%20.25) — ama aynı eşik 66 günde **−%9.43** veriyor. Tek dönemin
en iyisi, diğerinde zarar ettiriyor. `--tune` çıktısındaki "en iyi" satırları
bir sinyal olarak değil, bir arama sonucu olarak okuyun.

### Gerçekçi olalım

- 43 işlem, %0.10 komisyon yükünde, 1 dakikalık veride zayıf istatistik
- Profit factor 1.22'ye kayma ve gecikme eklendiğinde kolayca 1'in altına iner
- 1 dakikalık BTC yalnızca %0.05–0.10 aralığında salınır; %1.0 SL bu
  hareketin içinde, komisyon ise kârın beşte biri kadar

Bu araç bir **eğitim ve gözlem** aracıdır. Gerçek parayla kullanmadan önce
kendi verinizde `oos_test.py` çalıştırın; OOS negatifse hiç çalıştırmayın.

```bash
python backtest/oos_test.py
```

## Maliyetler

- Taker komisyonu: giriş **%0.05**, çıkış **%0.05** (ayrı ayrı uygulanır)
- Pozisyon boyutu: kullanılabilir marjin × `max_position_pct` × kaldıraç
- Stop-loss / take-profit: kâr üzerinden değil, **fiyat üzerinden** yüzde
- Likidasyon tahmini: marjin oranı %0.4'ün altına düşerse
- Gerçekleşen PnL = brüt PnL − giriş ücreti − çıkış ücreti
- Özsermaye = bakiye + açık PnL; drawdown tepe özsermayeye göre

Arayüzde **SL %**, **TP %** ve **kaldıraç** alanlarından değiştirilebilir.
Pozisyon boyutu kasıtlı olarak küçük tutulur: 1 dakikalık BTC'de %0.05
çift yönlü komisyon, %1.0 SL'nin beşte birini yiyor.

## Dosya yapısı

```
config.py                    ayarlar (kaldıraç, SL/TP, ücret, eşikler)
main.py                      giriş noktası
data/fetcher.py              CCXT ile Binance Futures verisi
indicators/calculator.py     tüm teknik indikatorler (saf pandas/numpy)
signals/generator.py         bilesik skor + sinyal üretimi
trading/engine.py            test cüzdanı, pozisyon, PnL, likidasyon
backtest/engine.py           bar-bar backtest motoru
backtest/tune.py             parametre ızgarası
backtest/oos_test.py         walk-forward doğrulaması (en önemli test)
gui/app.py                   CustomTkinter ana pencere
gui/chart.html               Lightweight Charts (ayrı webview penceresi)
gui/chart_window.py          pywebview sarmalayıcı
gui/matplotlib_chart.py      yedek grafik (mum + LONG/SHORT + paneller)
```

## Grafik

**Lightweight Charts** (varsayılan) mum grafiği, RSI paneli, özsermaye eğrisi
ve LONG ▲ / SHORT ▼ giriş işaretleri + çıkış dairelerini gösterir.

**Matplotlib** yedeğinde 4 panel bulunur: mum + EMA/SMA/VWMA/Hull + pivot
seviyeleri + LONG/SHOT işaretleri, bileşik skor, RSI, özsermaye.

## Uyarı

Bu bir **eğitim/test** aracıdır; gerçek parayla işlem yapmaz. Yüksek
kaldıraç futures işlemleri ciddi para kaybına yol açabilir.
