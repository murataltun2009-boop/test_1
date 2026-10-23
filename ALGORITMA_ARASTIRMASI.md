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

## 9. KULLANICININ 2. TUR ŞİKÂYETLERİ VE ÇÖZÜMLERİ

### 9.1 "Coin değişiminde Bozuk işlem atlandı hataları devamlı"

**Neden:** WebSocket thread'i `recv()` içinde uzun süre bloklanabiliyor;
`stop()` 2 sn bekleyip vazgeçiyor ve **eski coinin akışı yeni coinin
mumlarına yazmaya devam ediyordu**. Bozuk-veri filtresi eski coinin
fiyatını referans alıyor, yeni coinin her işlemi "%25 sapma" diye
reddediliyordu → log sürekli aynı hatayı tekrarlıyordu.

**Çözüm (3 katman):**
1. Akış kendi sembolünü etiketler; sembol değiştiyse o akışın işlemleri
   **sessizce** düşürülür (yeni coinin mumları bozulmaz).
2. Sapma büyükse işlem doğrudan reddedilmez; **REST referansına**
   (yeni coinin son kapanışı) bakılır — tutuyorsa referans yenilenir ve
   log'a yazılmaz.
3. "Bozuk işlem" logu **30 saniyede bir** yazılır (spam olmaz).

### 9.2 "Kâr kilitleme çalışmıyor"

**Gerçek neden (beklenenden farklı):** Kâr kilitleme zaten **pozisyonun
kendi giriş fiyatına** bakıyordu (hesabın toplamına değil). Asıl sorun,
**stop'a yakılan pozisyondan sonra yeni pozisyonun hiç açılmamasıydı**:
`_close()` her kapanışta `last_signal`'ı temizlediği için sinyal "aynı"
sayılıyor, `signal == last_signal` kontrolü girişi engelliyordu → yeni
pozisyon yok → kâr kilitleme tetiklenmiyordu.

**Çözüm:** Stop sonrası aynı yöne girmek için fiyatın **stop seviyesini
geri alması (reclaim)** şart. Reclaim olmadan girilmez → hem stop
döngüsü kurulmaz hem de "kaybedeni hemen değiştir" tuzağı olmaz.
Reclaim gerçekleşince yeni pozisyon açılır ve **kendi +%3'ünde** kilitlenir
(hesabın toplamı zararda olsa bile).

Regresyon testleri: *"MURO/TREND: kâr kilitleme pozisyon bazlı (toplam
zararda bile)"* ve *"TREND: stop sonrası reclaim şart (döngü yok)"*.

### 9.3 "1 dakikalık işlem listesi"

`1m` dilimi eklendi (`15m`'nin yanına): `config.TIMEFRAMES =
["1m", "15m", "1h", "4h", "1d"]`. Arayüzde "1dk" düğmesi olarak çıkar.
Not: 5 dilim arka planda aynı anda hesaplanır (odak 0,5 sn'de bir, diğerleri
2 sn'de bir) → CPU yükü ~%10 artar.

### 9.4 "İlk pozisyon daha kararlı olsun; tepede long / dipte short açmasın"

**Kural (uygulandı):**
* **Optimum nokta filtresi:** Long için fiyat son N barın zirvesine
  **ATR cinsinden çok yakınsa girilmez**; short için dibe yakınsa girilmez.
  Ölçü: `PAPER_TREND_PULL_ATR` (ATR birimi) — arayüzden ayarlanır.
* **Güçlü sinyal bypass'ı:** Bileşik skorda **GÜÇLÜ AL / GÜÇLÜ SAT**
  varsa filtre atlanır → "güçlü sinyalde hemen gir" kuralı.
* Karar mantığı `core/trend.py::decide_series` içinde: canlı akış ve geri
  dönük test **aynı** fonksiyonu kullanır.

**Ölçüm (trend modu, 1g, risk %5, kilitleme kapalı):**

| Optimum nokta filtresi | Seçim (10 coin) | Holdout (15 coin) | 500 bar (seçim/holdout) |
|---|---|---|---|
| **kapalı (0)** | **+%24,5** (%90 poz.) | **+%31,7** (%87) | +%11,1 / +%7,2 |
| 0,3 ATR | +%17,6 (%70) | +%21,8 (%80) | +%12,1 / +%5,3 |
| 0,6 ATR | +%12,1 (%60) | +%27,6 (%80) | +%16,6 / +%3,7 |
| 1,0 ATR | +%14,8 (%80) | +%24,0 (%87) | +%14,5 / +%3,2 |

**Dürüst okuma:** filtre 1g'de ölçülmüş sonucu **düşürüyor**; 4h'de de
nötr. Bu yüzden **varsayılan KAPALI** bırakıldı (ölçülen en iyi) ama
arayüzden açılabilir — kullanıcı canlıda kendi gözlemine göre
değerlendirebilsin. "Tepe/dipte girme" davranışının ölçülmüş olarak
pozitif çıktığı algoritma **MURO**'dur (geri çekilme girişi: seçim
+%47,6 · holdout +%118,6).

---

## 10. Yeniden üretim

```bash
python tools/research_muro.py search 1d 150 0.02 20 trend   # parametre arama
python tools/research_muro.py holdout 1d 0.02 20 trend      # holdout + 500 bar
python tools/research_muro.py final 1d trend 0.02 20 30     # iki küme birlikte
python tools/research_muro.py sens 1d trend 0.02 20         # duyarlılık
python test_paper.py                                        # 63 test
```


## EVRENSEL KURALLAR — TÜM ALGORITMALAR (kullanıcı kuralı)

İstek: açılan pozisyonun kendi +si kazançta nakde çevir, sonra
pozisyonu tekrar kontrol et; en uygun long/short girişinde devam et.
Pozisyon zarara geçmeden (giriş fiyatına dönmeden) kapatılır; kazanılan
para cüzdanda kalır, komisyonla erimesin.

Koddaki adları (core/paper.py::_on_price):

1b-4) EVRENSEL KÂR BANKASI (PAPER_BANK_PCT=0.02): açık pozisyonun KENDİ
giriş fiyatına göre +%2 fiyat hareketinde limit gibi kapatılır; kâr
cüzdana yazılır. ma_only/osc_only/signal*/range/1m modlarının tek kâr
çıkışı budur; trend ve muro kendi kilid bloklarını kullanır — üçünün
varsayılanı da %2ye eşitlendi. Arayüzdeki kâr kilidi değeri hepsini
eşler. Kapanış sonrası 90 sn bekleme, sinyal yeniden değerlendirilir,
en uygun yonde girilir (devam et).

1b-5) BAŞABAŞ KORUMASI (PAPER_BREAKEVEN_BUF=0.0012): pozisyon asla
zarara geçemez; fiyat giriş fiyatına (komisyon payı +-%0.12 kadar önce)
dönüp dokunursa kapatılır. Çıkış fiyatı kademeli: gap→bar açılışı,
bar içi dokunuş→eşik (limit), canlı tik→anlık fiyat. Giriş barında
devre dışı (Position.entry_bar). Kapanış sinyali temizler + kısa
bekleme; trend/1m ayrıca RECLAIM ister (döngü yok).

1m MODU İŞLEME BAĞLANDI: eskiden 1m modunun _on_priceta hiç
giriş/çıkış bloğu yoktu (pozisyon açamıyordu). Artık sinyal bloklarına
eklendi; _open kendi mode_1m_* parametreleriyle risk-bazlı
boyutlandırıyor (ATR stop + trail). Evrensel kurallarla tam döngü:
giriş → +%2 banka → yeniden giriş.

Testler (75): BE (LONG/SHORT/trend-reclaim), evrensel banka (+%2
hedeften önce, iki komisyonla net doğrulama), 1m modu (giriş + banka +
devam) testleri eklendi; eski hedef/kilit testleri yeni doktrine
(banka hedeften ÖNCE) uyarlandı.

## PP-SUPERTREND (PPT) MODU + 5 DAKIKA DILIMI (yeni)

Kullanici istegi: "5 dk'lik bir periyot ekle; karar mekanizmasinda
Pivot Point Supertrend indikatoru ekle; 5 dk'lik pozisyon +%2 kar
yaptiginda kapansin, indikator tekrar izlenip uygunsa pozisyon acilsin."

### Indikator matematisi (core/ppst.py)
PP-Supertrend (TradingView "PP SuperTrend") nedensel olarak yeniden
yazildi (orijinal pandas uygulamasindaki `center=True` penceresi
gelecege baktigi icin center=False ile):
- Donen pivot: pp = (max(h,10) + min(l,10) + close) / 3
- Diren varyantlari: R1=2pp-lo, R2=pp+(h-l), R3=hi+2(pp-lo)
  (R3 > R1 > R2 onceligi; seviye bandin disindaysa donen uca cakilir)
- Dayanma varyantlari: S1=2pp-hi, S2=pp-(h-l), S3=lo-2(hi-pp)
- Temel bantlar: inter_res = secilen_res - 3xATR(profil periyodu),
  inter_sup = secilen_sup + 3xATR
- Klasik Supertrend kilit dongusu (yalnizca ONCEKI barin bantlari):
  close > onceki final_res -> +1 (AL); close < onceki final_sup -> -1 (SAT)
- Kesme testi ile nedensellik dogrulandi (ilk 45 bar ayni).

### Karar serisi (ppst.decide_series)
trend.decide_series sozlesmasinin birebir aynisi: yon + optimum nokta
filtresi (pull_atr/pull_bars) + GUCCLU sinyal bypass. Canli akis ile
geriye donuk test AYNI fonksiyonu kullaniyor (service._signal_for_mode
ve paper._build_signal_series ikisi de decide_series).

### 5m davsranisi (kullanicinin yazdigi uyulama)
PPT modu trend ailesindedir:
- GIRIS: PP-Supertrend AL/SAT (kapanmis bar), stop = 3xATR
  (min %0,3 / maks %5), trail 5xATR, risk %3, maks kaldirc 10x.
- KAR KILIDI: +%2 (trend_lock_pct) seviyesine limit emir; dokununca
  pozisyon kapanir, kar cuzdana yazilir, 90 sn bekleme ("wait & re-evaluate")
  sonrasinda indikator yeniden okunur ve sinyal uygunsa AYNI/EN UYGUN
  yonde pozisyon yeniden acilir. Stop/likidasyon/BASABAS/reclaim/flip
  bekleme trend ile ayni.
- 5m dilimi config.TIMEFRAMES'e eklendi (TF_LABELS "5 Dakika",
  TF_SECONDS 300); arayuzde "5dk" etiketiyle kullanilir.

Dogrulama: test_paper.py toplam 81 test (6 yeni: 5m dilimi, PPST
nedensellik, karar kumesi, PPT giris+stop, PPT %2 kilit + yeniden
giris, PPT yon degisiminde bekleme). tools/check_mode_markers.py ppT
serisini canli BTCUSDT verisinde hizali uretiyor.

### PPT parametre olcumu (tools/research_ppt.py — uretim motoru ile)
Uygulanacak motorun kendisi (PaperTrader.backtest) kullanilarak olculdu;
veriler BTC/ETH/SOL 5m x1500 (~5 gun) ve BTCUSDT 1h x1500 (~2 ay) taze
Binance verisi. Kaldi: %2, risk %3, maks kaldirac 10x sabit.

Bulunanlar (dustukler net degerlerle):
1. OPTIMUM NOKTA FILTRESI (pull_atr) SART: kapaliyken ayni pencere
   -%2..-%9 NET; pull 0.5-1.0 arasi (atr cinsinden) sonucu isaret
   degistiriyor. pull=1.25 fazla kati (misallanmis, giris skacar).
   Varsayilan: pull_atr = 1.0.
2. BANT GENISLIGI: mult=3.5 en iyi denge. mult 2.0-3.0 bantlar 150-350
   islem uretir (%72-78 kazan oranina ragmen NET KAYIP — komisyon gitgidi);
   mult 4.0 5m'de katkisi olumlu ama istikrarsiz. Varsayilan: 3.5.
3. PIVOT DONEMI: period=10 dogru; 14/20 islem sayisini buyutse de
   NET daha kotu (pivot penceresi uzayinca bantlar sicrar).
4. STOP/TRAIL: 3xATR / 5xATR uygun; 4-5xATR stoplar yalniz ETH
   penceresinde daha iyi, genel etki dusuk. DeGISMEZ.
5. KAR KILIDI ESIGI: 5m'de %1..%4 arasi hicbaglaymadi (gozlemlenen
   tum cikislari zaten stop/trail aliyor). 1h'de %1 kilit (%2 yerine)
   daha calisik cikti ama kullanici kurali %2 hicbir modda degismez.

Uygulanan degisim: PAPER_PPT_MULT 3.0 -> 3.5, PAPER_PPT_PULL_ATR
0.0 -> 1.0. Testler 81/81.

Ucuncu saglik notu: BTC/ETH/SOL 5m ~5 gun penceresinde pozitif olan
yapilandiirmalar aslinda dayanikli olsa da ETH 5m bu pencerede her
ayrindaya gunlukti; 5m borsade kayip periyotlari gorunur. Sonuc:
PPT "5 dk" rafinajidir ve Supertrend taban cizgisine karsi net olarak
daha iyi (ayni pencerede ST(10,3): BTC -%9.7 / ETH -%2.0 / SOL -%3.4;
PPT(P=10,m=3.5,pull=1.0): BTC +%0.5..%1.8 / SOL +%0.1..%0.8) ama
garantili kar SISTEMI degil; 1h ust dilimde klasik Supertrend daha iyi.
