# ALGORİTMA ARAŞTIRMASI — MURO

Bu belge, kullanıcının isteği üzerine geliştirilen **MURO** algoritmasının
tasarımını, ölçüm yöntemini ve **dürüst sonuçlarını** içerir.

İstek (özet):

> "En iyi long ve short noktalarını yakalayan süper bir algoritma bul. Long
> en dipten tespit etsin; long'ta elde edilen kazancı kaybetmeden short'a
> geçsin (mesela %3 kazanç sağladıkça cüzdana atsın, yeniden long'a girsin).
> Short'a zarar ederek girmesin, en optimum noktayı yakalasın. Bunları test
> ederek MURO adında bir algoritma oluştur; bunu seçerek işlem yapabileyim."

---

## 1. MURO nasıl çalışıyor

MURO üç parçadan oluşur. Üçü de `core/muro.py` içinde, **canlı akış ile
geriye dönük testin ortak kullandığı** tek kodda yaşar.

### 1.1 Yön — Supertrend(10, 3)

Fiyatın yönü Supertrend ile belirlenir (ATR bantlı trend takibi). Ölçümde
günlük (1g) dilimde en dayanıklı yön göstergesi bu çıktı.

### 1.2 Giriş — "long en dipten, short en tepeden"

Yöne uyulduğunda **hemen** işlem açılmaz. Fiyatın kısa vadeli ortalamaya
(EMA 50) **geri çekilip geri alınması** beklenir:

* Long: yukarı yön + fiyat EMA'ya çekildi (1,5×ATR bandı) + EMA'yı geri
  aldı → **dibte al**
* Short: aşağı yön + fiyat EMA'ya çekildi + EMA'yı geri kaybetti → **tepede sat**

Bu, "kırılım barında gir" (en kötü fiyat) yerine "geri çekilmede gir"
mantığıdır. Ayrıca ardışık aynı yön sinyallerini engellemek için **20 barlık
bekleme (cooldown)** vardır; aksi halde her mini geri çekilmede işlem açılır
ve komisyon birikir (ölçüm: 4 saatlikte işlem/coin 190'a çıkıyordu).

### 1.3 Kâr kilitleme — "kâr cüzdana atsın, yeniden long'a girsin"

Pozisyon açıkken fiyat girişe göre **%1** (ölçülen optimum; arayüzden
değiştirilebilir) kâra ulaşınca:

1. Pozisyon **kapatılır** → kâr **cüzdana (bakiyeye) yazılır**,
2. **Aynı yönde** yeni pozisyon açılır; bu kez stop, kilitlenen kâr
   seviyesinin hemen altındadır (baskı başa baş).

Böylece:

* Trend devam ederse kâr **birikir** (her %1'de bir cüzdana yazılır),
* Trend dönse bile **yazılan kâr cüzdanda kalır** — geri verilmez,
* Kilit sonrası bacak "bedava"dır: stop başa başta olduğu için bu bölüm
  ancak **+kâr** kapatabilir.

Trailing stop (%2) yalnızca kilitlemeden sonra devreye girer. Kilit
mesafesinden dar bir trailing, kârı kilitlemeden önce kapatıp mekanizmayı
öldürür (ölçüldü: trailing kilitten önce aktifse kâr kilidi neredeyse hiç
tetiklenmiyordu).

### 1.4 Stop, pozisyon boyutu, likidasyon

* **Stop:** yapısal — girişten sonraki en dip (long) / en tepe (short),
  %1,5–%5 aralığına sıkıştırılır (gürültü kapısı + risk kapısı).
* **Boyutlandırma:** *risk bazlı*. Pozisyon, stop mesafesi kadar ters
  gidince sermayenin `%risk` kadarı gidecek şekilde açılır:
  `notional = equity × risk / stop_mesafesi`.
* **Likidasyon koruması:** likidasyon stop'un **1,5 katından** uzakta
  tutulur, yani stop her zaman önce tetiklenir.

---

## 2. Ölçüm yöntemi

| | |
|---|---|
| Veri | Binance **Futures** (USDT perpetual), 4h ve 1g mumlar |
| Seçim coinleri (10) | BTC, ETH, SOL, XRP, BNB, DOGE, ADA, LINK, AVAX, LTC |
| Holdout coinleri (15) | SUI, TIA, ENA, 1000PEPE, FIL, UNI, HBAR, XMR, INJ, TAO, APT, DOT, ARB, ONDO, HYPE |
| Tarih | 1g: ~3,3 yıl (1200–1500 bar) · 4h: ~460 gün (3000 bar) |
| Maliyetler | komisyon %0,05 (her iki yön) + kayma %0,02 + funding %0,01/8h |
| Parametre seçimi | **sadece seçim coinlerinde**; holdout hiçbir zaman seçimde kullanılmadı |
| Doğrulama | 4 zaman dilimi (fold) + 500 barlık "uygulama penceresi" |

Araştırma aracı: `tools/research_muro.py`
(alt komutlar: `search`, `holdout`, `final`, `sens`, `best`, `sweep`).

### 2.1 Motor doğrulaması (app ↔ araştırma)

Uygulamanın backtest motoru (`core/paper.py`) ile araştırma simülatörü
(`tools/research_muro.py`) **aynı olay dizisini** üretiyor: BTC 1g üzerinde
194 olayın **194'ü de** birebir aynı (giriş, çıkış, pozisyon büyüklüğü,
bakiye). Bu süreçte 5 gerçek hata bulundu ve düzeltildi:

1. `range` modu giriş bloğu **mod kontrolü olmadan** çalışıyordu → MURO'da
   "aralık modu" pozisyonları açılıyordu.
2. **Likidasyon kontrolü stop'tan önce** geliyordu → stop'a yetişmeden
   pozisyon sıfırlanıyordu.
3. **Trailing stop, stop kontrolünden sonra** uygulanmalı (bir sonraki bar
   için) — uygulamada aynı barda uygulanıyordu.
4. Takip eden stop **bir önceki barın kapanısına** göre hesaplanmalı.
5. `unrealized` **açılış komisyonunu iki kez** düşüyordu → equity ~%0,1
   eksik, pozisyon boyutu küçük kalıyordu.

Bu düzeltmelerden sonra iki motor birebir aynı sonucu üretiyor.

---

## 3. Sonuçlar (1 gün dilimi, ölçülen ayarlar)

Ayar: Supertrend(10,3) · EMA50 geri çekilme (1,5×ATR) · kâr kilitleme %1 ·
trailing %2 · stop %1,5–%5 · cooldown 20 bar · **risk %2** · kaldıraç tavanı 20x.

| Set | medyan | ortalama | kazanan coin | med. DD | PF | gerçek kaldıraç |
|---|---|---|---|---|---|---|
| **Seçim (10 coin, 3,3 yıl)** | **+%47,6** | +%96,3 | %90 | %29,2 | 1,52 | 1,41x |
| **Holdout (15 coin, 3,3 yıl)** | **+%118,6** | +%140,7 | %93 | %25,4 | 2,18 | 1,30x |
| Seçim — son 500 bar (1,3 yıl) | +%14,5 | +%15,6 | %90 | %11,9 | 1,98 | 1,36x |
| Holdout — son 500 bar | +%4,7 | +%15,1 | %60 | %13,7 | 1,39 | 1,27x |

Risk seviyesi etkisi (medyan):

| risk | Seçim | Holdout | Seçim 500 | Holdout 500 | PF (seçim/hold) |
|---|---|---|---|---|---|
| %1 | +%8,3 | +%6,2 | — | — | 1,56 / 1,38 |
| %2 | +%47,6 | +%118,6 | +%14,5 | +%4,7 | 1,52 / 2,18 |
| %3 | +%44,6 | +%121,5 | +%20,3 | +%6,4 | 1,35 / 1,98 |
| %5 | +%47,0 | +%137,9 | +%29,2 | +%8,3 | 1,20 / 1,55 |
| %10 | +%13,3 | +%7,3 | — | — | 1,07 / 1,07 |

**Önerilen: risk %2** (PF yüksek, DD kontrollü). %5'te getiri artmıyor,
PF düşüyor.

### 3.1 Zaman dayanıklılığı (4 fold, risk %2)

| Fold | Seçim | Holdout |
|---|---|---|
| 1 (en eski) | −%25,0 | +%1,7 |
| 2 | +%15,4 | +%53,0 |
| 3 | +%18,7 | +%48,0 |
| 4 (en yeni) | +%35,6 | +%11,6 |

Edge **tüm dönemlerde eşit değil**: seçim kümesinde ilk fold negatiftir.
Holdout kümesinde dört fold da pozitiftir, ama 1. fold neredeyse sıfırdır.

### 3.2 Duyarlılık (tek parametre değişimi, risk %2)

| Kâr kilitleme | %0,8 | %1 | %1,5 | %2 | %3 | %5 |
|---|---|---|---|---|---|---|
| Seçim | +%94,3 | +%74,6 | +%40,2 | +%6,3 | −%4,7 | −%15,2 |
| Holdout | +%82,1 | +%35,6 | +%4,7 | +%0,7 | −%3,6 | −%12,0 |

**Kritik bulgu:** kâr kilitleme mesafesi **%1 olmalı**. Kullanıcının
örneği olan %3 bu stratejide **negatife** döner. Sebep: %3'e kadar bekleyen
pozisyon, stop'a (veya yön değişimine) yakalanıyor; kâr hiç realize edilmiyor.

Diğer parametrelerde "bıçak ağızı" yok: Supertrend periyodu 8–20, çarpanı
2,0–4,0, EMA 20–200, cooldown 5–30, stop kapısı %3–%8 aralıklarında
**tümü pozitif** sonuç verdi.

---

## 4. Dürüst sonuçlar ve sınırlar

1. **"10x–20x kaldıraç" bu stratejide kullanılamaz.**
   Kaldıraç sabit 20x ile (cüzdanın %80'i teminat) test: **hesap −%99,9**
   (likidasyon). 4 saatlik dilimde sabit kaldıraç: **−%61,6**.
   MURO'da kaldıraç **üst sınırdır**; risk bazlı boyutlandırmada gerçekte
   kullanılan kaldıraç **1,3–1,4x**'tir. 10x'i "gerçekten" kullanmak isteyen
   kullanıcı, işlem başına %100+ risk alıyor demektir.

2. **Geçiş kalitesi (kullanıcının "kârı kaybetmeden geç" isteği)**
   mekanizma olarak sağlanıyor, istatistik olarak **zayıf**:
   * Kilitleme kârı cüzdana yazılır ve **geri verilmez** (yapısal garanti).
   * Ancak "tüm yön dönemi" (cycle) bazında ölçüldüğünde yön değişimlerinin
     yalnızca **%31–41**'i kârlı; kâr kilidi tetiklenmiş döngülerde
     **%40–47**'si kârlı (holdout medyan ≈ 0).
   * Sebep: kilitlemeden önceki kaybeden bacaklar, kilitlemeden sonraki
     kazancı geçebiliyor. "Aynı yönde art arda 2 kayıptan sonra dur"
     kuralı denendi — getiriyi ve geçiş kalitesini düzeltmedi, **kullanılmadı**.

3. **Edge yoğunlaşıyor.** 1. fold negatif; son iki fold pozitif. 500
   barlık uygulama penceresinde holdout getirisi +%4,7 (PF 1,39) —
   yani "şu an" güçlü bir trend piyasası değil.

4. **App ile araştırma arasındaki fark.** Uygulama kayma (slippage) ve
   funding maliyetini **modellemez** (bu, diğer tüm modlar için de
   geçerlidir). Bu yüzden uygulamadaki "geriye dönük test" sonucu araştırma
   tablosundan **biraz daha iyi** görünür. Araştırma tablosu doğru
   referansıdır.

5. **Deneyseldir.** 25 coin, 3,3 yıl, iki küme. Geçmiş performans geleceği
   garanti etmez; özellikle 1 günlük dilimde pozisyonlar günlerce açık
   kalır.

---

## 5. Uygulamada kullanımı

1. **Dilim:** `1g` (1 Gün) seçilir. MURO 1g'de ölçüldü; 4h'de çalışmıyor.
2. **Mod:** kârdıraç panelindeki mod listesinden **"MURO — kâr kilitlemeli
   (1 gün)"**.
3. **İşlem başına risk:** %2 (varsayılan). Aralık %1–%50.
4. **Kâr kilitleme:** %1 (varsayılan, ölçülen optimum). Aralık %0,5–%10.
   %3'e çıkarılırsa strateji negatif çalışır.
5. **Kaldıraç:** 10–20x girilebilir; MURO risk bazlı boyutlandırma
   kullandığı için gerçekte kullanılan kaldıraç ~1,3x olur. Ekranda
   "efektif kaldıraç" gösterilir.

### Log çıktısı

```
LONG açıldı @ 29.988,50 · efektif 1,41x · teminat 30,00 · stop 28.489,07 ·
kâr kilidi %1,0 · risk %2,0 · AL (Supertrend + geri çekilme)
Kâr kilidi — LONG 1.0% kâr cüzdana yazıldı, aynı yönde yeniden açıldı
LONG kapandı — yapı kırıldı (MURO)
```

---

## 6. Diğer modlarla karşılaştırma (aynı ölçüm)

| Algoritma | Seçim (1g) | Holdout (1g) | Not |
|---|---|---|---|
| Supertrend (trend modu) | +%5,0 / fold | +%5,3 / fold | ATR stop, risk bazlı |
| **MURO** | **+%47,6 / 3,3 yıl** | **+%118,6 / 3,3 yıl** | kâr kilitleme + geri çekilme |
| RSI-2 / Bollinger ort. dönüş | negatif | negatif | ölçüldü, elendi |
| Yapısal kırılım-retest (MURO varyantı) | negatif (PF ~1,0) | negatif | çok fazla işlem, komisyon yiyor |

---

## 7. CANLI SORUN: "LONG/SHORT ARASI DEFALARCA İŞLEM" (HYPE/USDT)

Kullanıcı canlı log raporladı:

> "Karar mekanizması Supertrend seçtim. HYPE/USDT coininde gün içinde
> long pozisyon açtı gayet güzel kâr yapmaya başladı. Fakat düşmeye
> başlayınca kazancı eritti; hele ki long short geçişi arasında defalarca
> pozisyon açtı kapattı ki tüm kazanç ve fazlası komisyona gitti."

Log'daki örnek: 18:31:18 SHORT açıldı → 18:31:19 SHORT kapandı → LONG
açıldı → 18:31:29 LONG kapandı → SHORT açıldı… **10 saniyede 4 işlem**,
her biri ~1,6-2,0 USDT komisyonla.

### 7.1 Kök nedenler (üçü ölçüldü)

| # | Sorun | Kanıt |
|---|---|---|
| **1** | **Sinyal oluşan (kapanmamış) bardan hesaplanıyordu.** Supertrend yönü bar içinde fiyat oynadıkça tik tik değişiyor; analiz 0,5 sn'de bir çalıştığı için simülatör her değişimde pozisyon değiştiriyordu. | Canlı benzetimi: 400 tick'te **51 olay** (LONG/SHORT) |
| **2** | **Stop sonrası aynı sinyalle anında yeniden giriş.** `_close()` her kapanışta `last_signal`'ı temizliyordu → stop'a yakılan pozisyon bir sonraki tick'te aynı fiyattan tekrar açılıp tekrar stop oluyoruyordu (stop avcısı döngüsü). | BTC 1g: **33 yerine 171 işlem**; komisyon 59,6 USDT (bakiyenin %6'sı) |
| **3** | **Likidasyon stop'tan önce kontrol ediliyordu** ve gap (bar açılışı) durumunda likidasyon fiyatı uygulanmıyordu. | İki motor aynı veride 3 kat farklı işlem sayısı çıkarıyordu |

### 7.2 Düzeltmeler

1. **Sinyal yalnızca kapanmış barlardan** (`core/paper.py::_kapali_mumlar`,
   `core/service.py`). Grafikte oluşan bar gösterilmeye devam eder, ama
   *karar* kapanmış bardan gelir.
2. **Pozisyon değişiminde 5 dakika bekleme** (`PAPER_FLIP_COOLDOWN_SEC`).
   Yön değişimi, stop ve likidasyon sonrası yeni pozisyon açılmaz; sinyal
   o süre sonunda **yeniden değerlendirilir** (yön neyse o açılır).
3. **Stop/likidasyon sonrası sinyal temizlenmiyor** (`reset_signal=False`):
   sinyal değişmediyse pozisyon yeniden açılmaz → stop döngüsü biter.
4. **Gap likidasyonu** borsa davranışına uyduruldu: bar stop'un ötesinde
   açılıp likidasyon seviyesinin altındaysa pozisyon likidasyon
   fiyatında kapanır.
5. **Kâr kilitleme** (aşağıda) — kullanıcı isteği.

### 7.3 Ölçüm (canlı benzetimi: 400 tick, sessiz piyasa)

| Kip | Olay | İşlem | Bakiye |
|---|---|---|---|
| ESKİ (oluşan bar, bekleme yok) | 51 | 25 | 691,69 (**−%31**) |
| YENİ (kapanmış bar + 5 dk bekleme) | 2 | 1 | **996,25** |

Regresyon testi eklendi: `test_paper.py` → *"CANLI: yön titremesi yok"*.

### 7.4 Trend modunun (Supertrend) ölçümü — düzeltmelerden sonra

App'in **kendi** backtest motoruyla (1 gün, risk %5, komisyon %0,05 dahil;
kayma/funding modellenmez, bu yüzden biraz iyimserdir):

| Kâr kilitleme | Seçim (10 coin) | Holdout (15 coin) | Seçim 500 bar | Holdout 500 bar | İşlem |
|---|---|---|---|---|---|
| **%0 (kapalı)** | **+%24,5** (%90 poz.) | **+%31,7** (%87) | **+%11,1** (%100) | **+%7,2** (%67) | 350 |
| %2 (korumali yeniden giriş) | −%45,8 (%20) | −%79,6 (%27) | — | — | 5.087 |
| **%3 (kullanıcı isteği)** | **−%10,4** (%0) | +%3,9 (%60) | +%3,6 (%80) | +%2,2 (%60) | 2.287 |
| %5 | −%5,0 (%30) | +%1,0 (%60) | — | — | 1.561 |
| %8 | −%10,3 (%20) | +%5,1 (%67) | — | — | 1.066 |
| %12 | +%1,9 (%50) | +%6,8 (%60) | — | — | 796 |

### 7.5 Kâr kilitleme hakkında dürüst not

Kullanıcının isteği **uygulandı**: "%3 kazanç sağlandığında pozisyon
durdurulur, kâr cüzdana aktarılır, 1-2 dakika beklenir ve pozisyon yeniden
değerlendirilir" (her iki yönde de).

Ama **ölçüm, bu kuralın trend modunda sonucu DÜŞÜRDÜĞÜNÜ** gösteriyor:

* Supertrend(10,3) günler/haftalar boyunca pozisyon taşıyan bir trend
  takipçisidir. %3'te kârı kesip yeniden girmek, **güvenli kârı bırakıp
  riski tekrar alan** bir davranıştır ("kazananı sat, kaybedeni tut").
* İşlem sayısı 350'den 2.287'ye (6,5 kat) çıkıyor; komisyon kârı götürüyor.
* Aynı sonuç MURO'da çıkmıyor — çünkü MURO'nun girişleri seyreltilmiştir
  (geri çekilme) ve kâr kilidi %1'dir (ölçülen optimum).

Bu yüzden:

* **Trend modunda** kâr kilitleme alanı **0 yapılınca** (varsayılan
  ölçülen en iyi sonucu verir) ya da istenirse %3 yapılabilir.
* **MURO modunda** kâr kilitleme zaten vardır ve ölçülmüştür (%1 → seçim
  +%47,6 · holdout +%118,6).

Arayüzde bu ölçüm trend modunun açıklamasında yazılıdır; kilitleme
alanının yanında "0 = kapalı" ipucu vardır.

### 7.6 MURO motor doğrulaması (düzeltmelerden sonra)

Uygulama backtest motoru ↔ araştırma simülatörü: BTC 1g'de **194 olayın
194'ü de birebir aynı** (giriş, çıkış, pozisyon büyüklüğü, bakiye).
Son bakiye: uygulama **1928,40** = araştırma **1928,40**.

---

## 8. Yeniden üretim

```bash
python tools/research_muro.py search 1d 150 0.02 20 trend   # parametre arama
python tools/research_muro.py holdout 1d 0.02 20 trend      # holdout + 500 bar
python tools/research_muro.py final 1d trend 0.02 20 30     # iki küme birlikte
python tools/research_muro.py sens 1d trend 0.02 20         # duyarlılık
python test_paper.py                                        # 63 test
```
