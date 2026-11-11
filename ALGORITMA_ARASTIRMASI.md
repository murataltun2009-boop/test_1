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


## AUTO FIB RETRACEMENT (trend + muro; hibrit dönüş yakalama)

Kullanıcı isteği: "nokta atışı dönüş yerlerini yakalayabilsin, hibrit
çalışsın." Uygulama: core/fib.py — her bar için son `window=160` bara
bakıp salınım uçlarını (argmax/argmin) ve yönünü bulur; geri çekilme
derinliğini theta olarak yazar (0 = uca dokunmuş, 0.618 = altın oran).
Nedenseldir: pencere yalnızca geçmiş + şimdiki barı görür (gelecek yok).

Karar etkisi (iki kural):
  * ALTIN CEBE BYPASS: theta 0.44 - 0.678 bandına gelince yön uygunsa
    GÜÇLÜ sinyal; trend.decide_series'de optimum nokta (pull) filtresini
    atlar, muro.actions_trend'de pull_strong şartını atlar.
  * UÇ ENGELİ: theta < 0.15 veya > 0.85 (salınım ucunun %15'ine daha
    yakın) DEVAM girişi engellenir — tepe alma / dip satmaya karşı.

Ölçüm (tools/research_fib.py; motor backtest'in kendisi; BTC/ETH/SOL
5m x1500 (~5 gün) + BTC 1h x1500 (~2 ay)):

  TREND fib=KAPALI pull=0.0: BTC -121.7$ | fib AÇIK: -113.1$  (+1.0 puan)
                             ETH -78.5$  |        -81.5$ (-0.3 puan)
                             SOL -58.6$  |        -53.1$ (+0.6 puan)
                             BTC 1h +5.2$|        -15.9$ (NET BOZULUR)
  TREND pull=1.0:   BTC -47.8$/-57.5$ | ETH -48.5$/-96.5$ (NET BOZULUR)
                    SOL -27.8$/-48.2$ | BTC 1h -53.3$/-42.3$ (+1.1)
  TOPLAM: kapalı -402$ vs açık -427$ -> trend'de fib NET OLUMSUZ.

  MURO fib=KAPALI: BTC -4.8$ | ETH +0.7$ | SOL -10.1$ | BTC 1h -41.5$
  MURO fib=AÇIK:   BTC -4.8$ | ETH -4.9$ | SOL  -7.1$ | BTC 1h -15.8$
  TOPLAM: kapalı -55.6$ vs açık -27.4$ -> muro'da fib NET POZİTİF.

Karar:
  * MURO: fib AÇIK (PAPER_MURO_FIB_ON = True). 1h diliminde bariz iyi
    (-4.15% -> -1.57%); "dönüş yakalama" hedefine doğrudan hizmet eder.
  * TREND: fib KAPALI (PAPER_FIB_ON = False). Özellikle 1h penceresinde
    net bozucu; klasik Supertrend güçlü. Kod parametrik: config.py'de
    PAPER_FIB_ON=True ile her an açılabilir.
  * PPT (PP-Supertrend, ppst.py) kendi karar hattını kullanır; fib
    entegre EDİLMEDİ (ölçülen optimum parametre setini bozmamak için).

Testler: fib nedensel salınım, trend golden-pocket bypass + uç engel,
muro gate, bar_info izleme paneli -> 86/86.


## İZLEME MODU (grafikte nokta atışı inceleme)

Kullanıcı isteği: "izleme butonuna tıklayınca canlı trade durdurulsun;
grafikte tıkladığım noktanın osilatör ve hareketli ortalamalardaki tüm
değerleri görüntülensin."

Uygulama:
  * "👁 İzle" butonu: bir tıklamada /api/paper/stop ile canlı simülasyon
    durdurulur ve izleme moduna geçilir (grafik ve analiz ÇALIŞMAYA
    DEVAM eder; yalnızca işlem motoru durur). Tekrar tıklama kapatır.
  * Grafikte (mobil dokunuş dahil) bir muma tıklayınca:
      - sunucuya GET /api/bar_info?tf=&ts= sorulur (bar açılış zamanı),
      - o bardaki DEĞERLER listelenir:
          OHLC + hacim,
          bileşik + osilatör + MA skorları, bileşik kararı,
          AKTİF ALGORİTMANIN o bardaki kararı (mode_signal),
          11 osilatör (RSI, Stoch, CCI, ADX, AO, Momentum, MACD,
          Stoch RSI, Williams %R, Bull-Bear, UO),
          15 hareketli ortalama (EMA/SMA 5..200, Ichimoku, VWMA, HMA),
          AUTO FIB seviyeleri + salınım yönü + theta.
      - tıklanan bara sarı kesikli dikey çizgi konur.
  * Sunucu tarafı: analysis.py osc_series (11 seri bar bazlı) ve
    service.bar_info() (fib serisi versiyon bazlı cache). Değerler bar
    bazlı hesaplandığından geçmiş mum için de NEDENSELDİR.

Notlar:
  * markLine çakışMASI: mum serisinin markLine'ı CANLI FİYAT çizgisi
    için kullanılıyor; izleme çizgisi yıldız serisine (index 9,
    id=starsBuy) sparse series patch'iyle bağlanır (birbirini silmez).
  * sw VERSION ta-v11 -> ta-v12 (PWA ön bellek yenilenmesi).


## AUTO FIB — SKOR TABANLI + ARALIK PENCERE MOTORU (2. tur)

Kullanici istegi: "sadece hareketli ortalamalar, sadece osilatorler,
sinyal (sadece long) ve aralik pencere tabanli mekanizmalarda da Auto
Fib'i dene, sonuclari gorelim."

Uygulama:
  * core/fib.py::gate_labels — skor serilerine (ma_only / osc_only /
    signal / signal_long / signal_exit) fib gate:
      - AL aralik ZIRVESINE yakin (yer > 0.85) -> NÖTR (tepe alma engel),
        SAT aralik TABANINA yakin (yer < 0.15) -> NÖTR (dipe satma engel);
      - yukari salinimda altin cebe -> GÜÇLÜ AL, asagi salinimda altin
        cebe -> GÜÇLÜ SAT (dönüs yakalama).
  * paper._build_signal_series backtest'te, service.mode_signal_series
    canlida AYNI fonksiyonu cagirir (test/canli tutarsizligi yok).
  * Araalık pencere motoru (range): taban sarti yetmedikce ALTIN CEBE
    giris izni (fib_range_on) — _long_signal/_short_signal
    (_fib_state: pencere icinde leg + theta).

Olcum (tools/research_fib2.py; 4 pencere: BTC/ETH/SOL 5m ~5 gun +
BTC 1h ~2 ay; toplam NET):

  MOD          | KAPALI    | ACIK      | FARK
  ma_only      | -1313.9$  |  -793.6$  | +520.3$   (islem 601->391 vb.)
  osc_only     |  -606.8$  |  -557.3$  |  +49.5$
  signal       |  -863.3$  |  -526.1$  | +337.2$
  signal_long  |  -336.7$  |  -151.2$  | +185.5$ (BTC 1h +1.3% -> +4.3%)
  range        |  -159.9$  |  -671.3$  | -511.4$  (islem 3-4 KAT artar)

KARAR:
  * Skor tabanli modlarda fib ACIK (PAPER_FIB_SCORE_ON = True). Uc
    engel komisyon yiyen tepe-yakin girisleri kesiyor; islem sayisi
    duserken kazanma orani korunuyor.
  * Araalik pencere motorunda fib KAPALI (PAPER_FIB_RANGE_ON = False).
    Altin-cebe giris izni giris sayisini 3-4 kat sisiyor ve komisyon
    net zarara donusturuyor; motorun KENDISI (taban/zirve konumu) zaten
    sekme tabanli bir退缩 filtresidir.
  * izleme modu /bar_info bu modlar icin de fib alanlarini gosterir.

Testler: gate_labels zirve-tabanlandirma + altin cebe guc -> 87/87.

---

## DÜZELTİCİ (corr) — zarar-redüktör katmanı

İstek: fib düzeltmesinden sonra hâlâ zararda olan skor tabanlı sonuçları
(ma_only / osc_only / signal / signal_long) **kâr bölgesine taşımak**.
Yaklaşım: matematiksel teshis → her adım ölçümle karar (hiçbir politika
ölçüm olmadan değişmedi).

### Teshis — zararın anatomisi (tools/research_teshis.py, damp_trade.py)

* **Zarar kumalı:** son kârlı işlemden SONRA gelen işlemler ortalama
  **−7,5$**; temiz serideki işlemler **+1,6$**. Dört mod × dört pencerede
  tutarlı (4.990 işlemde ana bulgu). Başabaş gap çıkışı sonrası piyasa
  chop rejiminde ve aynı sinyal yeniden giriş üretiyor ("azap değirmeni").
* **Komisyon yuvarlak-trip:** taban yapılandırmada kazanan +1,6$ (net),
  kaybeden −8,0$ (net) — tam roundtrip komisyonu. %83 kazanma oranı
  gerekiyor; gerçek ~%75.
* **Kâr bankası (+2%) hiç vuramıyor:** skor modlarında pozisyon, bankaya
  varmadan mikro-klip (başabaş +0,12%) ile kesiliyor.

### Yakalanan yanlış ölçümler (dürüstlük yamaları)

1. **Mikro-klip hayali dolumu:** eski BE modeli `bar_low <= be_px`
   tetiklemesiyle, barın HIGH'ı hiç eşiğe ulaşmadığında bile +buf
   seviyeden dolum tanıyordu → "BE +0,4%=para makinesi" illüzyonu
   (415 milyar $ gibi saçma sonuçlar). Yamayıp `be_px` yalnızca barın
   [low, high] ARALIĞINDA ise dolduğu kabul edildi; bar eşik ÖTAŞINDA
   açıldıysa dolum olur (market). 5m'de ~%0,1 bar aralığı +buf eşiğini
   kapsayamadığı için mikro-klip 5m'de meşru getiri üretmiyor.
2. **Duvar saati zamanı:** `opened_at=time.time()` sim zamanına çevrildi
   (`candles[-1].open_time`); saat/ATR analizleri artık veri sağlıyor.
3. **Komisyon ayırışı:** limit-dolumlu çıkışlar (başabaş klip dokunması,
   kâr kilidi, kâr bankası) resting emirdir → **maker %0,02**; NÖTR-flip /
   stop / likidasyon market → **taker %0,05** (PAPER_MAKER_RATE).

### Düzeltici bileşenler (üretim default'ları, "GUC8REV")

| Bileşen | Config | Açıklama |
|---|---|---|
| Seri kilidi | `PAPER_CORR_ON=1`, `PAPER_CORR_PAUSE_BARS=8` | Zarar bitince K bar yeni giriş yok (çıkış/stop/banka her zaman serbest) |
| ARM | `PAPER_CORR_ARM_ON=1` | K dolunca bile zarar yönüne TERS sinyal gelmeden giriş yok |
| GÜÇLÜ-only | `PAPER_CORR_STRONG_ONLY=1` | Zayıf AL/SAT → NÖTR (giriş açmaz); kapsamı skor modları (muro aksiyon akışı korunur) |
| GÜÇLÜ-öncelik | `PAPER_CORR_STRONG_FIRST=1` | Zayıf-yazımı ARM gate ÖNCESİNE uygula (ARM zayıf sinyalle düşmez) |
| TF-mikro-klip | `PAPER_CORR_BE_BUF=0.004`, `PAPER_CORR_TFS={1h,15m}` | Sadece bar aralığının tamponu kapsayabildiği TF'lerde meşru |
| Maker çıkış | `PAPER_MAKER_RATE=0.0002` | Yalnız limit-dolumlu çıkışlarda |

### Ölçüm (sabit stake, 4 pencere, dürüst dolum) — tools/research_karar3.py

```
MOD          TABAN    GUCREV(K6)  GUC8REV*   iyileşme
signal      -4037$     -345$       -349$       %91
signal_long -3683$     -185$       -183$       %95
osc_only    -3801$     -307$       -307$       %92
ma_only     -4038$    -1783$      -1156$       %71
```
* BTC 1h penceresinde ma_only **+78$ pozitif**; GUC10'da signal −17$'a
  kadar. GUC8REV (K8) kombinasyonu seçildi: tüm modlarda en dengeli.

### Üretim kontrolü (compounding'li, tools/research_uretim.py)

9 modun HEPSI tabanından iyileşiyor; hiçbir mod zarar görmüyor:
```
MOD         KAPALI    AÇIK
ma_only     -3767$    -955$   (BTC 1h: +54.0$ POZİTİF)
osc_only    -2807$    -295$
signal      -3384$    -336$
signal_long -2423$    -180$
range       -1596$   -1188$
trend       -1888$    -674$
muro         -247$    -145$
1m          -1615$    -705$
ppt         -1953$     -130$
```

### Ulaşamadığını ne söylemek doğru olur

Durum hâlâ toptan **negatif** (−130$..−1188$ aralığı) — düzeltici zararı
%65-95 kesti ama sıfırın üstüne hiçbir skor modunu 5m'de çıkaramadı.
Neden: 0,05% taker × notional ücreti, 5m/1h musterebince (maya) drifti
(−0,15%/giriş ort.) ve sinyal kalitesinin ötesindeki yapısal
faktörler. 1h + ma_only kombinasyonu pozitife geçti. Kullanıcının
+2% kâr bankası kuralı hiç değişmedi; mikro-klip/kâr kilidi/düzeltici
stopu bunlardan bağımsız düzelticilerdir.

Testler: 90/90 (duzeltici 3 mikro-test dahil: seri kilidi / ARM /
sadece-GÜÇLÜ).

## TIK (tk) MODU - super-hizli TAMAMEN-LIMIT scalper (2026-10-25)

Istek: 1m/5m/15m/1h'de "az az kazanc biriktirmek": long ac -> kari al ->
short ac... tamamen LIMIT (maker) emirli, fib + talep yogunlugu kullanan
hizli ac-kapa motoru. Komisyonu minimuma indirmek icin piyasa emri YOK.

### Tasarim (core/paper.py `_tk`, mode="tk")

* LONG: yukari salinim leg'i sonrasi altin cebe (%44-67.8) pasif BUY
  LIMIT (fill 0.55 mandali). SHORT: asagi leg'te pasif SAT LIMIT.
* TP: resting SELL/BUY LIMIT (maker). SL: stop-market (taker).
* Talep onayi: son 3 bar volume max >= pencere ort. (zayif salinim
  elenir; knob vol_mult olcumde etkisiz, 1.0 birakildi).
* DURUST DOLUM: buy limit yalnizca bar seviyeye INERKEN dolarsa
  (open>=L ve low<=L) maker; open eSikin altindaysa marketable ->
  SKIPTIR. TP bar araligindaysa dolu; stop acilis/ stop-seviyesi taker.
* Canli yol: service on_price bar_low/high gecmez -> tik-dal fallback
  eklendi (giris doldu-kosulu, SL tick-dal, TP tick-dal).

### Hatalar ve duzeltmeler (olcum sirasi)

1. `configure(mode="tk")` SESSIZCE yok sayilip ma_only default'a
   donebiliyordu (beyaz-listede "tk" eksik) - ilk tarama aslinda
   ma_only girisli BE-klip cikislarindan olusuyordu. Beyaz-listeye
   "tk" eklendi; 2. tarama GERCEK tik motorunu confirm etti.
2. Taban BE-klip tik pozisyonunu gaspetme riski yok: mode="tk" ise
   _on_price direk _tk'ye return ediyor (routing), taban mantigi
   tik pozisyonuna ulasmayan (tasarimla + olcumle dogrulandi).
3. Trend filtresi (SMA200 uyumu) tik setup populasyonunda ETKISIZ
   (veto edecek setup'lar zaten dolu pozisyon anlarina denk geliyor).
   Knob PAPER_TK_TREND default kapali (olcumle gerekcesiz).

### Taramalar (taze veri, 1500 bar, honest-fill)

1. pas (tp-sl izgarasi): 3 coin x 4 TF x 9 kombinasyon -> yalnizca
   SOL 1m (tp 2-3%, sl 5%) ve BTC 5m (tp3, sl5) pozitif.
2. pas (knob tarama theta_max/vol/fill/trend): THETA<=0.85 + FILL=0.55
   en iyi; vol1.5 ve fill0.45 iyilestirmiyor; trend etkisiz.
3. pas (pencere-gucu: 3x500 dikey):
   SOL 1m tp3/sl5:      +134.8 / -13.1 / -3.8 -> TOPLAM +117.9$
   BTC 5m tp3/sl5 th0.678: +30.6 / +9.7 / +15.2 -> TOPLAM +55.5$
   (3/3 pencere POZITIF - en dayanikli aday)
4. URETIM YOLU dogrulamasi (configure(mode="tk") hook):
   BTC 5m:  +125.2 / +9.7 / +15.2 -> TOPLAM +150.1$ (3/3 pozitif)
   SOL 1m:  +141.2 / -13.9 / -3.8 -> TOPLAM +123.5$

### Uretim kararı

* mode="tk" UI'ye eklendi ("TIK — hızlı limit scalper"): configure()
  SEMBOLE GORE iki karakter uygular (research_tk4/5 olcumu,
  2026-10-25 ikinci tur):
  - BTC 5m SECIKICI: tp %3 sl %5 theta 0.44-0.678 fill 0.55 — 3/3
    pencere pozitif (+150$). YOGUN varyantlarin TAMAMI BTC'de negatif
    (16 deneme: thmin 0-0.44, fill 0.3-0.55, tp 0.08-2%): BTC'de
    frekans komisyona kayiyor; secikici mod korundu.
  - SOL 1m YOGUN (kullanici hedefi: SIK islem + az az kazanc):
    tp %2 sl %3 theta 0-0.85 fill 0.40 — bugunku 3x500 pencerede
    +77.9$ / ~23 islem/gun / WR %79 (K19/Z5). Varyant tp3/sl4 ise
    +125.6$ (ama ~17/gun)。
  - Diger (HYPE vb.) ayni YOGUN parametre — UI'de "deney" etiketi;
    HYPE 3 pencerede -526$ ile ONERILMEZ.
* Config default'lari olcumle hizalandi: PAPER_TK_TP=0.003,
  PAPER_TK_SL=0.005, PAPER_TK_WIN=60, THETA_MAX=0.85, VOL_MULT=1.0,
  FILL=0.55, TREND=0.
* 90/90 test gecti (tik degisikligi mevcut test akislerini bozmuyor).

### COIN TARAMASI - tik 1m yogun mod, uygulamanin 36 coinnin tamami
(2026-10-25 ikinci tur; tools/research_tk6.py tek cekim + research_tk7.py
6x500 dogrulama)

Tek cekim (3x500, ~25 saat) POZITIF: ERA (+558) ENA (+472) HBAR (+37)
UNI (+35) LINK (+6). Diger 31 coin negatif; SOL +78 -> -60 PENCERE
KAYDIGINCA tersine dondu (yogun mod secerli).

6x500 pencere dogrulamasi (~3 gun):
  HBAR  +172$  POZ-PENCERE 5/6  ** EN STABIL YOGUN ADAY **
  ERA  +2112$  4/6 (iki dev pencere getirdi; patlayici-alt riski)
  ENA   +170$  2/6 (son pencere tek kari bagimli; kararsiz)
  UNI   -247$  2/6 | LINK -44$ 3/6 | SOL -51$ 2/6 | DOGE -204$ 2/6
  ADA   -142$  2/6

Not: yogun mod coin-coin buyuk dagilim gosteriyor; HBAR haric tek
cekim kazananlar pencere kaydiginda donuyor. BTC hook (secici) sadece
BTCUSDT'de; BTC icin grafik dilimi 5m OLMALI (1m'de yogun mod
kapanma; secikici 5m +150$/3 pencere).

### CANLI HBAR DEBUG - tik yogun cogor teshisi (2026-10-26, 36 pozisyon)
Kullanici canli verisi: 22K / 14Z / -133.9$.
  * Kazanc ort +12.7 (TP%2), kayip ort -28 (SL%3 taker): asimetri 2.2x
  * Breakeven WR %69.5; gercek %61 -> -134$. Motor matematigi calisti,
    EGMONOMI kaybetti.
Cogor desenleri: (1) stop -> HEMEN ters-yon giris -> stop (azap
degirmeni canli); (2) ayni cebe arka-arkaya cift giris (komisyon
israfi); (3) kayiplarin TAMAMI SL yendi - orta cikis yok.

Duzeltici KNOB'lar (core/paper.py _tk; config PAPER_TK_PAUSE_BARS /
PAPER_TK_BE / PAPER_TK_BE_TRIG / PAPER_TK_BE_LOCK / PAPER_TK_LEG_FLIP):
  * PAUSE k bar: stop-sonrasi giris yok. Tek basinda etkisiz (motor
    pencerelerinde hizli cogor nadir; canlida gelir).
  * BE-klip trig 0.5 + LOCK: TP'ye kaci yol + geri donen dalgadan
    yarim-kar klip (honest bar-dolum, maker). HBAR -300 -> -180$.
  * LEG_FLIP: ayni-leg yeniden giris engeli. HOZUR karisik (ERA'da
    yikici): default kapali.
  * SL kisaltma: WR-esigi dusurur ama stop sayisini artirir - bir mesaja.

36 varyant x 4 coin (research_tk8/9/10, 6x500 pencere):
  HBAR en iyi: tp%2.5 sl%3 be_lock0.5 pause3 -> -70$ (baseline -300)
  ADA: tp%3 (sl3, lock .5) -> +27.9$ tek pozitif kombinasyon
  DOGE/SOL: hepsi negatif. YOGUN MOD COCU COINDE 3 GUNLUK PENCEREDE
  NEGATIF — sadece (ERA +271..+292, ENA +394/+563 flip ile) pozitif.

URETIM: dense hook = tp0.0025 sl0.003 be(trig.5 lock.5) pause3
flip0. BTC secici hook korunur. Kulaniciya acik soyle: yogun mod
regim-dayanikli DEGIL; 1 gunluk pencere-kazi-pandiklara itibar etme
 kayit: HBAR +37 (tek cekim) sonra 6 pencere -180..-300.

### TIK2 — 1h yildiz-kararli tamamen-limit scalper (2026-10-27)
Kullanici kurali (1h grafigin yildizlarina bakilarak):
  * yesil yildiz (AL / GUCLO AL) -> LONG ac
  * kirmizi yildiz (SAT / GUCLO SAT) -> SHORT ac
  * gri yildiz (NOTR) -> TERS pozisyona gec
  * girişler LIMIT (maker) — maliyet dusuk; flip taker (zaruri).

Uygulama (core/paper.py `_tk2`, mode "tk2"; config PAPER_TK2_TP/SL):
  * Yildiz = komple skor sinyal serisi (res.signals; chart ile ayni).
  * TIK cikis altyapisi yeniden: TP klip/BE klip/SL stop.
  * ARM: yildiz anindaki fiyata pasif limit; dolum dokunma aninda
    maker; dolmazsa yeni barda fiyata yeniden armlanir.
  * Girisi yalnizca 1h diliminde (diger dilimler pasif).
  * BE klip trig 0.5 + lock 0.5 acik (1h goldsunda kayip klip).

OLCUM KRITIK: bir kez "bedava yaris" deligi yakaladin — 1h momentum
bacagi TP'yi TEK barda asti; honest model "dokunma yok" deyip
pozisyonu +5.8% bedava birakti (UNI pencere-4 +11.883$ FIZIK DISI).
Fix: TP resting pass (fiyat TP'yi gectiyse resting emir maker
doldurulmus sayilir, TP fiyatindan klips) -> ayni pencere +10.5$.

TP/SL ekonomisi (tools/research_tk13, 8 coin x 5 pencere):
  tp3/sl4 -3528$ | tp4/sl4 -474$ | TP5/sl4 +2005$ (25/40 pencere) |
  tp4/sl5 -2414$ | tp6/sl5 +519$  -> URETIM tp %0.5 / sl %0.4.

Uretim hook (10 pencere dogrulama, research_tk12, tp5/sl4):
  UNI +286 (3/6) HBAR +382 (3/6) ADA -129 (3/6) ENA +216 (3/6)
  DOGE +656 (4/6) BTC -130 (3/6) SOL +176 (3/6) ETH +548 (3/6)
  WR ~%60-65; breakeven ~%46 -> kenar gercek. Pencere-kaymasina
  dikkat: 90/90 test + islem frekansi ~35-40/pencere (2 haftalik).

### TK tamamen yeniden yazildi — yildiz-kararli ac/kapa (2026-10-28)
Kullanici kurali: TIK karar mekanizmasi 1m DOGE'da yildizlari guzel
yakaliyor fakat giris acmiyordu. Istenen: yildiz HESAPLAMASI ayni kal;
ac/kapa kurali yildiz gecisine baglanr:
  * yesil yildiz (AL/GUCLO AL) -> uzun pozisyon ac, yildiz degisene KAL
  * kirmizi (SAT/GUCLO SAT) -> kisa pozisyon ac, yolda kal
  * gri (NOTR) -> mevcut pozisyonun TERSINE gec (flip)
  * ac+kapa LIMIT (maker) — komisyon az

Seed uygulama (paper.py `_tk` yeniden yazin):
  * boyle: res.signals (komple skor yдldız) — chart ile ayni.
  * ARM: yildiz anindaki fiyata pasif limit; dolum dokunurken maker;
    dolmayinca yeni barda ARM fiyata guncellenir (kovalamaca ARM).
  * FLIP: yildiz gecisi kapan ARM — close da LIMIT (maker); do
    dalgsan SL (taker) once ceker (koruyucu).
  * TP/BE KLIP KAPALI (kullanici: pozisyon yildiz degisene kadar
    kalsin). BORELLEM dikkat: tp close verdigini goruldu —
    tk_tp=0 iken q.tk_tp=L yazilmis ve K0/Z36 (tum islem komisyona
    kaybetmsiler) — FIX: tp=0 iken attr sifir.
  * SL: 0.5% BTC / 0.3% diger; stop-sonrasi 3 bar giris yok.

OLCUM (research_tk14, 5 pencere DOGE 1m, tp kapali):
  DOGE -22$ (3/6) ETH +19$ (3/6) ADA +21$ (2/6) BTC -68$ (2/6)
  UNI -107$ ENA -239$ HBAR -367$ — WHOBUM: komisyon-beraberlik;
  rumble ekonoi yildiz frekansina bagli; pozisyonlar artik yildiz
  gecisiyle kapaniyor (istenen goruntü gerçek хват).


### TK canli senkron fix + 1 dk bekleme (2026-10-28, oturum 2)
KULLANICI SIKAYETI: canlida yildizlar ile pozisyonlar uymuyor; "yesil
yildiz ciktiginda hic pozisyon acmamis yada ters pozisyon acmis";
4/4 kayip (SHORT -16.01 / LONG -8.12 / SHORT -2.16 / LONG -13.28,
komisyon 12.63$). Ek istek: her ac/kapadan sonra 1 dk bekle.

KOK NEDENLER (canli = on_price(bar_low/balbar_high=None) TIK modu):
  1) CORR ZARAR-SONRASI GATE (`PAPER_CORR_PAUSE_BARS=8`): _close()
     icinde net<0 -> _corr_until=_bars_held+8; kapsam kontrolu YOKTU.
     TK dahil her modda her zarardan sonra 8 BAR (1m'de 8 dk) giris
     yasak -> "yesil yildiz var, pozisyon yok". 4/4 kayip oturumunda
     her zarardan sonra engel devredeydi. FIX: gate artik TK modunda
     atlanir (`self.mode != "tk"`) — TK kendi 60-sn kullaniyor.
  2) TIK dolum sarti eski mum ACILISI (60 sn bayat) ile yapiliyordu;
     bar acilisi ARM fiyatinin ters tarafindaysa dolum o bar icinde
     imkanlagi: ARM son una kadar dolmuyordu. FIX: canli tik modunda
     giris/kapanis ANINDA (limit seviyesi = anlik fiyat, maker);
     gerib donor testte bar modu dokunma dolumu korunur.
  3) Bayat ARM: yildiz degistiginde bekleyen eski-yon limit ters
     pozisyon acabiliyordu. FIX: yon uyumsuzlugunda ARM dusurulur.
  4) Flip kapanisi bar-kilitte gecikiyordu (kirmizi yildizda LONG
     kalmis goruntusu). FIX: mismatch-driven kapanis + tık anında.

YENI KURALLAR (paper.py _tk):
  * Pozisyon-yildiz esitligi HER TIKTE kontrol edilir
    (mismatch-driven): sinyal olayi kacirilsa bile pozisyon son
    yildizla esitlenir -> ACKL, glosser belirtesinde pozisyon
    her zaman son yildizin tarafinda acik.
  * HER ac/kapadan sonra 1 dk bekle (PAPER_TK_AFTER_SEC=60):
    yeni acilis/kapanis engellenir; koruyucu SL yine calisir.
    Bekleme bitince pozisyon kalintisi esitlenir.
  * Whipsaw iptali: yildiz geri donduyse (RED->GRI->RED) bayat
    kapatirma emri iptal — ayni yonde ucret-israf kapanisi yok.

OLCUM (research_tk14, 6x500 pencere, 1m, TP kapali):
  UNI +113$ ETH +74$ ADA +129$ ENA +424$ BTC +33$
  DOGE -55$ HBAR -302$ — toplam ~+420$. Canli oncesi:
  mismatch mekanizmasi + 60 sn bekleme， pozisyonlar grafik
  yildizlarina BIREBIR hizali.

### TK yildiz SETTLE kurali (2026-10-28, oturum 3)
KULLANICI ISTEGI: "yesil/kirmizi/gri yildiz TAM OTURMADAN pozisyona ac/
kapa yapma; yildiz sabitlensin once. Ozellikle long->short gecerken
kirmizi mumun SABITLENMESINI bekle."

防水NEMI: 1m'de yildiz OLUSAN bar icinde belirip kaybolabiliyor (analiz
0,5 sn'de bir yenileniyor; skor esik uzerinde gezinebiliyor). Motor
canlida res.signal.value (OLUSAN bar dahil) okuyordu -> anlik yildiz
ile pozisyon zararli flip.

FIX (service._signal_for_mode, yalnizca mode=="tk"):
  * Motor okumasi KAPANMIS bara cekildi:
    sig = res.signals[len(_kapali_mumlar(candles)) - 1]
  * Yildiz HESABI (res.signals) ve GRAFIK yildizlari dokunulmadi —
    sadece motorun okudugu nokta sabitlenen cifra cekildi. Trend/1m/
    ppt modlarindaki "sinyal yalnizca kapanmis bardan" kuralinin
    aynisi.
  * Sonuc: kirmizi mum KAPANINCA long->short; anlik yildiz (mum
    icinde cikip kaybolan) hicbir aksiyon uretmez; 1-dk bekleme +
    mismatch-driven esitleme ile birlikte yildiz/pozsiyon uyumu
    tam.

TEST: settle testi (olusan bar SAT gezinirken motor AL okur;
kirmizi mum kapana kadar aksiyon yok) gecti; 90/90 gecti.

### TK +2% kâr bankasi + 2-bar yildiz sabitleme (2026-10-28, oturum 4)
KULLANICI ISTENGEMLERI:
  1) Acik pozisyonun kari +%2'yi gectiginde kazanci cuzdana yaz,
     pozisyonu KAPAT; bu kapanis 1-dk bekleme kuralina GIRMESIN.
  2) Kirmizi yildiz sabitlenmeden short aciliyor — "yildiz
     sabitlenmeyen islem acma"; yuksek kar eriyor.

UYGULAMA:
  * Banka TK'ya eklendi (_tk pozisyon blogu basi; evrensel
    PAPER_BANK_PCT=0.02 ile ayni semantik, maker dolum).
    Kapanis etiketi "TK: kar bankasi +%2 (maker)". MODELLIK NOT:
    banka kapanisi _tk_son_islem_t muhurlemez — bekleme atlanir;
    ayni tik'te yildiz hala gecerliyse hemen yeniden giris acilabilir
    (kullanici kurali).
  * Sabitleme CONFIRM (PAPER_TK_CONFIRM_BARS=2): yildiz tarihi
    bar-bazli tutulur (_kapali_mumlar ile son 2 kapali barin yildizi).
    Yon degisikligi yalnizca son 2 kapali bar AYNI yondeyse islenir.
    Tek mumluk yildiz (yesil->kirmizi direk gecis) bekleme yapar;
    NÖTR->kirmizi dizisi de istikrar saysin diye NÖTR ters kandinal
    haritalanir (gri=TERS kurali). SETTLE (mum kapan maths) ile
    birlikte: anlik yildiz.folden mum kapanmadi + 2 bar ayni yon
    olmadan flip yok.

OLCUM (research_tk14, 6x500, 1m, tp kapali):
                confirm=2      confirm=1      (bankasiz, sadece
                +banka         +banka         referans, onceki oturum)
  DOGE          -247           -11            -55
  HBAR          -475           -316           -302
  UNI           -756           -481           +113
  BTC           -458           -172           +33
  ETH           -435           -79            +74
  ENA           -297           +115           +424
  ADA           -650           +64            +129
  TOPLAM        ~-3030         ~-1050         ~+420

YORUM: (a) 2-bar sabitleme her flip'i 1 bar geciktirip ters yonde
ek pozisyon tutuyor -> chop'taki flip maliyeti artiyor ve toplami
dusuru. (b) Banka chop'ta pahali: +2% fiyat hareketinde bankalanan
pozisyonun ayni yildizla aninda yeniden girisi, geri donen dalgada
stopla teselli ucreti yapiyor (dogrulama: bankasiz confirm=2 olcumu
-1026; bankali -3030).
KARAR: Ikisida KULLANICI ISTEĞI olarak KURULUDU (banda + confirm=2
varsayilanla). Kulanici canli actikca:
  * kirsa yildiz hala yeterince erken geciliyor hissi varsa
    PAPER_TK_CONFIRM_BARS++ degil... — belirli serbertlik yok, dogru
    veriyle canilida K/Ze olcume baglanmali.
  * Banka cok pahaliysa cozum: banka sonrasi girisine YENI sabit
    yildar bekleme kurali (ayni yildiz icin yeniden girma yok) —
    olcumle karar vertiler.

### TK kâr bankasi DÜZELTMESI — para bazli esik (2026-10-28, oturum 5)
KULLANICI DUZELTMESI: onceki "+%2 fiyat bankasi" YANLIS anlasilmisti.
Dogru kural: ACIK POZISYONUN PARA CINSINDEN KARI bakiyenin
PAPER_TK_BANK_PCT kadrini gectiginde (varsayilan %2.5; bakiye 1000$
-> +25$) pozisyon KAPATILIR ve kazanc CUZDANA yazilir. Cikis LIMIT
(maker) — resting emir seviyeye dokundukca/gectikce dolar, taker
ucret yok. Sonraki giris yildiz kurallariyla KONTROLLU.

YANLISTOR: kulanici testinde "+2% kâr oluyordu ama cuzdana atmiyor"
diye rapor etti — eski esik FIYAT-%2 (10x kaldiracta +20% marj =
nadir vuru) idi; yeni esik BAKIYE-%2.5 (por-cinsinden) — tikta
guvenilir vuru.

Knoblar (config.py):
  PAPER_TK_BANK_PCT    : bakiye oran esigi (0 = banka KAPALI)
  PAPER_TK_CONFIRM_BARS: yildiz sabitleme kapali bar sayisi
  PAPER_TK_AFTER_SEC   : islem sonrasi bekleme (banka istisna)

OLCUM (research_tk14, 6x500, confirm=2 + para-bank):
  DOGE -395 HBAR -327 UNI -845 BTC -573 ETH -574 ENA -397 ADA -486
  TOPLAM ~ -3600 (bankasiz confirm=2: ~ -1026)
  NOT: 1m chorup pencelerinde para-esik bankasi + aninda yeniden
  giris zinciri komisyon sisiyor. Caninwu goruntuye bakip
  gerekiyorsa: (a) esigi buyut, (b) banka sonrasinda girise YENI
  sabit yildiz beklet, (c) PAPER_TK_BANK_PCT=0 ile banka kapali.

### TK mum-yildiz uyusmazlik gate + banka muhr (2026-10-28, oturum 6)
KULLANICI ISTENMEYENI (duzeltme istegi):
  * "Yildiz yesil olup kirmizi mum uzerinde cikiyor, bu SHORT
    pozisyonda LONG kalmasina sebep oluyor" — yildiz-mum celiskisinde
    flip YAPILMAMALI (bekle).
  * "Kar satisi oldugunda 1 dakika beklemeyi yap" — banka kapanisi da
    1 dk beklemeye GIRSIN (oturum 5'teki "girmesin" kuralini hareket
    gecerli kildi).

UYGULAMA (core/paper.py _tk):
  1) MUM-YILDIZ UYUSMAZLIGI GATE (hedef-gunceleme blogunda):
     confirm (2-bar istikrar) gectikten sonra YON DEGISIKLIGI
     ancak sabitlenmis yildizin mumu ile yildiz AYNI yondeyse
     islenir. yesil yildiz + kirmizi mum -> bekle; kirmizi yildiz +
     yesil mum -> bekle. isaretler (close >= open).
  2) BASKA GERCEK HATA NASIL BULUNDU (debug): SHORT stop olduktan
     sonra yildiz yesile donup (henuz sabitlenmeden) motor hedef
     -1 ile POZISYON YOK dalinda YESEL yildiz varken SHORT aciyordu.
     POSISYON-YOK girisine "taze yildiz-hedef uyum" gate eklendi:
     yeni != tk_hedef ise giris YOK. Sabitlemedigis yildiz ile
     giris artik mumkun degil (kullanicinin "yildiz sabitlenmeden
     islem acma" talebinin son parcasi).
  3) BANKA MUHRU: banka kapanisi _tk_son_islem_t'ye mohur basar
     (bar_t) — sonraki giris 1 dk beklemede. Banka tetiklenmesi
     beklemeye zaten girmez (stop/banka herzaman serbest).

DOGRULAMA (tk_sanity, tum adimlar OK):
  yesil yildiz->LONG · yesil yildiz+kirmizi mum: LONG kalir ·
  tek kirmizi yildiz: flip yok · 2. kirmizi: flip kapanis ·
  beklemede giris yok · sure sonrasi SHORT giris ·
  yesil yildiz kirmizi mumda SHORT korunur (gate) ·
  banka +17$ cuzdana, muhr basar, sure sonrasi kontrollu giris.
  test_paper: 90/90 gecti.

OLCUM (research_tk14, 6x500, 1m; confirm=2 + para-bank %2.5 +
uyusmazlik gate + giris-uyum gate + banka muhru):
  DOGE +146 (113 islem)  HBAR -35  UNI -242  BTC -157  ETH -141
  ENA +371  ADA -177   TOPLAM ~ -235$
  KARSILASTIRMA: oturum 5 (muhr/gate yok) ~ -3600$, oturum 4
  (fiyat-bank) ~ -3030$. Uyusmazlik gate + giris-uyum gate islem
  sayisini dusurup chop kaybini buyuk olcude kiriti. Kalan negatif
  UNI/BTC/ETH/ADA'da cilizin kendisi; canli veri ile tekrar bakilir.

### TK gri-yildiz TERS kurali + mum-yonu giris gate (2026-10-28, oturum 7)
KULLANICI ISTENGEMLERI:
  * Pozisyon kapandiktan sonra bekleme suresi doldugunda EVVELKI
    SABIT YILDIZ yönünden devam (res = ayni yonde yeniden giris).
  * Onceki yildiz GRI ise griden onceki pozisyonun TERSINI al.
  * "kirmizi mum atarken long acmak cok mantiksiz" — giris mum
    yonuyle ayni yonde olmali.
  * "grafikte kirmizi ve yesil yildiz olmadan poziyon ac kapa
    yapma" — gri yildiz tek basina (pozisyon yokken) islem yapmaz.

UYGULAMA (core/paper.py _tk):
  1) tk_hedef_kaynak eklendi: hedefi hangi yildiz etiketi kurdu,
     kayit tutulur (gri dizisi TEK GECERLILIK icin gereki).
  2) GRI KURALI: NÖTR hedefi yalnizca (a) ACIK pozisyon varken,
     (b) gri 2 ARDISIK KAPALI bar SABITLENMISken (confirm=2 kurali),
     (c) bu gri dizisi zaten cevirmemisse -> TERSINE cevirir
     (SHORT<->LONG).哼 Pozisyon yokken gri hicbir sey yapmaz.
  3) POZISYON-YOK GIRIS gate'i genisletildi:
     - taze yildiz hedefle ayni yonde DEGILSE giris yok
       (sabitlenme/mum-uyusma bekleniyor);
     - KIRMIZI mumda LONG giris YOK, YESIL mumda SHORT giris YOK
       (giris kapali mum ile ayni yonde olmali);
     - istisna: hedefi gri-cevirme kurduysa (kaynak=NÖTR) TERS giris
       mum yonunden bagimsiz (gri karari TERS istegi).
  4) Res/devam: pozisyon kapandiktan (banka/flip/stop) sonra bekleme
     sure dolunca motor son sabit yildiz yönünden giris kurar
     (yildiz+kirmizi/yesil mum ayni yonda ise).

DOGRULAMA (tk_sanity tum adimlar OK + test paper 90/90):
  yesil->LONG · yesil yildiz kirmizi mumda koru · tek kirmizi flip
  yok · 2. kirmizi flip + bekleme + SHORT · banka muhr · poz yokken
  gri dokunmaz · YESIL mumda SAT giris engellendi · kirmizi mumda
  giris · yesil yildiz kirmizi mumda SHORT korunur · gri 2 bar ->
  TERS cevirme (SHORT->LONG) · gri girisi tek gecerli (3. gri
  yeniden cevirmiyor).

OLCUM (research_tk14, 6x500, 1m; confirm=2 + para-bank %2.5 +
tum gate'ler):
  DOGE +41.6   HBAR -168.1  UNI -0.3  BTC -263.5
  ETH -16.2    ENA +507.0  ADA +56.0    TOPLAM ~ +157.3$
  KARSILASTIRMA dizi: -3600 (oturum 5) -> -235 (oturum 6) -> +157.
  4/7 coin pozitif; BTC/HBAR/ETH chop'ta hafif negatif. Banka +
  kapilar birlikte ilk kez net pozitif — canli dogrulama icin
  30-40 islem kaydi bekli.

### TK stop->ters (SAR) + trend filtresi — ENA dusus yakalama (oturum 8, 2026-10-29)
KULLANICI ISTEGI: ENA'da LONG sinyalinden sonra 0.2141 -> 0.2094
dususunde hic short/nort yildiz cikmadigi icin motor dususu
yakalayamamis, long'a geri girişlerle kayip biriktirmis.
"En azindan nort durumu yakalamali, pozisyonu tersine cevirmeli."

CANLI VERI (kullanicinin ENA kayitlari, 7 islem):
  SHORT -29.17 | LONG -31.55 | LONG -31.86 | LONG -32.41 |
  LONG +22.98 | LONG +22.49 | LONG -32.86
  NET -112.38$ + komisyon ~-36$ = ~-148$ — chop bandinda long
  zinciri (besi ard arda ~%0.3 stop) ve tek short (dip cevresinde)
  bitti. Banka gize +22$ istisna. Veri: blanket TERS acilim
  chop'ta ziyan (motorun oturum-7 olcum uyumu ile ayni).

UYGULAMA (core/paper.py _tk_sar_ac, config PAPER_TK_SAR/SAR_MEAN/SAR_MINPCT):
  1) STOP->TERS: SL stop kaybinda pozisyon ters yonde acilir
     (maker, TP/SL yeniden kurulur), hedef ve tk_hedef_kaynak=STOP
     ters kaydedilir — taze yildiz eski yonde olse bile pozisyon-yok
     girisi eski yonde ZINCIR OLAZ (giris kapisi taze yildiz-hedef
     uyumu ister). Dusus boyunca motor short tutuyor.
  2) TREND FILTRESI (canli veri adam yaniti): ters acilim yalnizca
     yeni yon fiyat <- son N=10 kapali bar kapanis ortalamasinin
     10%0.4-altindaysa (SHORT) veya ustundeyse (LONG) gecerli;
     aksi halce DUZ stop (flat) — chop whipsaw alti pahali
     (blanket SAR olcümü: toplam -1329$).
     Knoplar: PAPER_TK_SAR (true), PAPER_TK_SAR_MEAN=10,
     PAPER_TK_SAR_MINPCT=0.004.

AYAR ITINERAMI (research_tk14, 6x500, 1m):
  SAR yok (oturum 7)        : toplam +157  ENA +507
  SAR blanket (filtre yok)  : toplam -1329 ENA -296
  SAR MEAN=10               : toplam -515  ENA +363
  SAR MEAN=5                : toplam -678  ENA +119
  SAR MEAN=20               : toplam -826  ENA +331
  SAR MEAN=10+MINPCT=0.2%   : toplam -406  ENA +400
  SAR MEAN=10+MINPCT=0.4%   : toplam +158  ENA +536  <- secileni
 dogrulama: tk_sanity tum adimlar OK (giris rozizma/ gri / bank / SAR
 TERS / dususte bank / takili AL'de giris yok / SAT+kirmizi giris);
 test_paper 90/90.

### TK grafik cizgi sirasi (MA ribbon) trend kilidi (oturum 9, 2026-10-30)
KULLANICI ISTEGI: "Yukselis trendinde grafikteki renkli cizgiler
kirmizi>yesil>sari dizilirken hep LONG tut; dususte mavi en ustte,
altinda sari/turuncu iken SHORT ac. Bu kurallari indikatore ekleyip
long/short giris-cikis noktalarini ayarla."

CANLI GECE VERISI (28.10): 75 islem (37K/38Z), net -109,07$,
komisyon 296,08$ (brut ~+187$). Islemlerin cogu chop bandinda
(0,1960-0,2015) stop/banka donusu; yon filtre edilmedigi icin hem
long hem short zinciri kurulmus.

UYGULAMA (core/paper.py _ma_ribbon/_tk_ribbon/_tk_rib_flip):
  * Ribbon = KAPALI mumlardan EMA20 / EMA50 / EMA200 dizilimi:
      EMA20 > EMA50 > EMA200 -> +1 (yalniz LONG)
      EMA20 < EMA50 < EMA200 -> -1 (yalniz SHORT)
      karisik/isinma          ->  0 (eski yildiz kurali)
    Yildiz hesabina (res.signals) DOKUNULMADI; yildiz yalnizca
    zamanlama verir, yon trende kilitlenir.
  * GIRIS KAPISI: dizilim yukari iken SHORT, asagi iken LONG girisi
    yok (trende karsi pozisyon acilmaz).
  * TRENDE TERS POZISYON: aninda kapatilip trend yonunde yeniden
    acilir (maker); hedef "CIZGI" kaynagi ile sabitlenir. Boylece
    yildiz (orn. ENA'da AL) takili kalsa bile dusus yakalanir.
  * STOP->TERS (SAR) de trende ters yonde calismaz (ribbon kapisi).
  * Knoplar: PAPER_TK_RIBBON=True, PAPER_TK_RIBBON_FLIP=True.

BACKTEST ALTYAPISI DUZELTMESI (kritik): geriye-donuk test motora
yalnizca `lookback`=20 bar veriyordu; EMA200 hic hesaplanamiyor,
ribbon olcumu sessizce 0 cikiyordu. Pencere artik 260 barlik isinma
gecmisiyle besleniyor (karar modlari yine son 20 bari kullanir).

OLCUM (research_tk14, 6x500, 1m, ayni gun arka arkaya):
  ribbon KAPALI            : toplam +3673  (DOGE 387, HBAR 521,
                             UNI 840, BTC 22, ETH 218, ENA 1259, ADA 426)
  ribbon ACIK + FLIP acik  : toplam +4551  (DOGE 513, HBAR 555,
                             UNI 799, BTC 395, ETH 361, ENA 1476, ADA 453)
  ribbon ACIK + FLIP kapali: toplam +4612  (islem sayisi biraz daha az;
                             FLIP acik secildi — kullanici kurali "hep
                             trend yonunde tut", fark ~%1,3)
  Not: onceki oturumun +158 rakami 20-bar pencere kisitindan
  etkilenmisti; rakamlar bugunku veriyle yeniden uretildi.

DOGRULAMA: tk_sanity tum adimlar OK (13: yukari dizilimde SAT ile
SHORT yok, AL ile LONG; 14: dusus diziliminde LONG aninda SHORT'a
cevrilir, kaynak CIZGI; 15: dususte AL SHORT'u bozamaz); test_paper
90/90. sw ta-v23.

### IZLEME MODU — BAR BAZLI AL/SAT/NÖTR KARARI (oturum 13, 2026-11-03)
KULLANICI ISTEGI: "izleme modunda grafikte bir muma tikladigimda
osilator ve hareketli ortalamalar tablosundaki SAYISAL degerler
degisiyor ama her indikatorun karsisindaki AL/Sat/Nötr (Detay)
sutunu degismiyor. Kontrol et ve duzelt."

KOK NEDEN: sag sutundaki tablolar yalnizca CANLI snapshot'tan
(res.oscillator_rows / res.ma_rows = SON barin karari) doluyordu;
tıklanan mumun PER-INDIKATOR kararlari sunucudan hic gonderilmiyordu.
Izleme panelindeki sayilar (j.osc/j.ma) dogru bardan geliyordu ama
tablonun Detay sutunu (ve Al/Sat/Nötr sayaclari) canli son bare
kilitli kaliyordu.

DUZELTME (uc katman):
  * core/analysis.py: TimeframeAnalysis'a osc_codes/ma_codes alanlari
    (etiket -> bar-bazina karar ham kodu dizisi, _rsi_v vb. zaten
    uretiyordu; rows'a yalnizca son bar yaziliyordu).
  * core/service.py bar_info(): tıklanan barin karar etiketleri
    ("Al"/"Nötr"/"Sat") osc_vad/ma_vad dict olarak cevaba eklendi.
  * web/static/app.js: fillWatchRows() + countLabels() eklendi;
    renderWatch tiklanmada oscTable/maTable'i TIKLANAN BARIN
    deger+karariyla doldurur, sayaclara "(mum)" etiketi konur;
    applySnapshot canli veriyi lastIndicators/lastCounts olarak
    saklar ve izlemedeyken tabloları EZMEZ; izlemeden cikista
    renderTables(lastIndicators, lastCounts) ile tablolar son canli
    duruma geri doner.

DOGRULAMA: test_paper 90/90 (İZLEME testi genisletildi: bar_info
artik osc_vad/ma_vad döndurur; bar 75 ve bar 60 kararları analyze()
kod serileriyle assert; bayat son-bar karari yakalanamaz). node
--check app.js OK; py_compile analysis/service OK. sw ta-v29 ->
ta-v30.

### IZLEME MODU — MUM SECIMI HEP EN ESKI BARA GIDIYORDU (devam, 2026-11-03)
KULLANICI ISTEGI: "mouse ile grafikte tikladigimda secim islemi
yapilmiyor; mum uzerine tikladigimda o mumun sonuclarini gostermeli."

KOK NEDEN (tarayicida canli teyit edildi): x ekseni CATEGORY tipinde
olan grafikte convertFromPixel KATEGORI INDEKSI dondurmektedir; eski
chartClickToBar bu kucuk indeksi mum saniyesiyle (~1.7e9)
karsilastiriyordu. Tum mumlar esit derecede "uzak"tigindan en-yakin-
mum hesabi HEP state.candles[0] (en eski bar, 29.08.2026) donuyordu:
tiklama calisiyor gibi gorup DEGERLER asla hareket etmiyordu.

DUZELTME: chartClickToBar convertFromPixel yerine kesin SLOT
geometrisiyle hesaplar:
  * gorunur pencere: chart.getOption().dataZoom[0] start/end (%)
    -> vStart=floor(N*s/100), vEnd=ceil(N*e/100)-1
  * slot = plotW / vCount (grid sabitleri left=62, right=86;
    boundaryGap: true, her mum slotun merkezinde)
  * k = floor((tık-piksel - left) / slot), idx = vStart + k
CANLI TEST (tarayici ticaret sunucu + ECharts instance):
  * tiklamalar monoton: %30 -> 15.10 23:00, %55 -> 25.10 03:00,
    %85 -> 03.11 (olusan bar, penumbra clamp)
  * tooltip ile cakisan x'teki eksen etiketi ile watch MUM basligi
    BIREBIR eslesir (%55: "25.10.2026 03:00" == "MUM · 25.10 03:00")
  * tablolar + sayaclari tıklanan barin kararlarini gosterir "(mum)"
  * "(olusuyor)" etiketi sunucu/istemci uzunluk farkindan her bare
    cikiyordu; j.index yerine j.time >= son-candle zamanla kiyas
    (yalniz gercekten olusan bar icin). sw ta-v31.

### TK cizgi KESISIMI referansi (oturum 10, 2026-10-30)
KULLANICI KURALI (netlestirme): "kirmizi>yesil>turuncu: kirmizi ile
yesilin ILK KESISTIGI nokta short cikis / long giris; yesil>kirmizi>
turuncu: ilk kesisme long cikis / short giris noktasi."

UYGULAMA: ribbon artik tam dizilim yerine EMA20 (hizli/kirmizi) ile
EMA50 (yavas/yesil) KESISIMINI tetik alir:
  EMA20 > EMA50 -> +1: SHORT kapanir, LONG acilir
  EMA20 < EMA50 -> -1: LONG kapanir, SHORT acilir
Kesisim aninda pozisyon ters cevrilir (maker); hedef "CIZGI"
kaynagiyla sabitlenir. EMA200 (turuncu) yon filtresi olarak
kullanilmaz (kullanici siralamasinda her iki rejimde de altta).
Knop: PAPER_TK_RIBBON_MODE = "cross" | "cross200" | "stack".

OLCUM (research_tk14, 6x500, 1m, ayni gun arka arkaya):
  cross (EMA20/50, secilen): toplam +3954, islem 68-138
      DOGE 320 HBAR 759 UNI 823 BTC 481 ETH -10 ENA 1338 ADA 243
  cross200 (+EMA200 tarafi) : toplam +3377, islem 85-139
  stack (EMA20>50>200)      : toplam +4551, islem 82-160
Not: cross islem sayisini ~%35 azaltir (komisyon avantaji); stack
net getirisi daha yuksek ama kesismeden gec tetikler. Kullanici
kurali kesisme oldugu icin cross varsayilan; istenirse
PAPER_TK_RIBBON_MODE="stack" ile eski davranisa donulur.

DOGRULAMA: tk_sanity tum adimlar OK; test_paper 90/90. sw ta-v24.

### TK canli zarar duzeltmesi (oturum 11, 2026-10-31)
CANLI TESHIS (kullanici islem kaydi): 66 islem (32K/34Z), net -330,12$
(-%33,01), komisyon 254,97$ (~3,86$/islem), brut ~-75$. Kayiplar
-21..-27$, kazanclar +14..+19$ -> R:R < 1 ve kazanma orani %48.

KOK NEDEN: SL %0,3 x 10x x %80 teminat -> stop kaybi ~bakiyenin
%2,4'u (+komisyon); banka hedefi bakiyenin %2,5'i -> brut R:R ~1:1.
Komisyon eklenince beklenti negatif. Chop bandi (0,1890-0,1929, ~%2)
icinde stop/banka dongusu.

DUZELTME (yildiz hesabi DEGISMEDI; res.signals yalnizca okunur):
  * PAPER_TK_FRACTION = 0.50 — TK pozisyonu cuzdan fraksiyonunun
    yarisina iner. Stop kaybi ~%1,2'ye, komisyon ~yarıya iner; banka
    hedefi (bakiyenin %2,5'i) ayni kalir -> net R:R ~1,7-2,0.
  * PAPER_TK_BANK_RR = 1.8 — banka esigi = max(bakiye*BANK_PCT,
    stop_riski*RR). Stop genis secilirse hedef otomatik uzar; 0=kapali.
  * PAPER_TK_PAUSE_BARS = 3 — zararli kapanistan sonra AYNI yonde 3
    bar yeni giris yok (karsi yon serbest: trend donusu kacmaz).
  * stop->ters (SAR) ve cizgi flip girisleri de fraksiyonla kuculur.

OLCUM (research_tk16, 8x500, 1m, 7 coin, ayni veri):
  eski f1.0            : +4055$, 926 islem, K581/Z345, kaz 22,6 /
                         kay -26,2, en kotu pencere -157$
  f0.4 (bp2.5 rr1.8 p3): +1666$, 645 islem, K255/Z390, 22,1/-10,2,
                         en kotu -66$   (DOGE +183)
  f0.5 (secilen)       : +1824$, 684 islem, K293/Z391, 23,2/-12,7,
                         en kotu -81$   (DOGE +184)
  f0.6                 : +2148$, 721 islem, K332/Z389, 24,3/-15,2,
                         en kotu -90$   (DOGE +231)
Not: fraksiyon kuculdukce mutlak $ dogal olarak duser; risk birimi
de ayni oranda kuculur (normalize getiri eskiyle ayni). Secim f0.5:
kullanici banka kurali (%2,5) korunur, islem basi stop ~%1,2 ve
kazanc/kayip orani ~1,8; f0.4 daha guvenli ama toparlanma yavas.

6x500 duyarlilik (ayni gun): rr2.2 (f1.0) +3688 vs eski +2654;
pause3 tek basina trendli ornekte notr (chop'ta canli fayda icin
korundu). Capraz kontrol: 6x500'de f0.5 bp2.5 p3 +1713 / f0.45 +1687
/ f0.4 +1322 — farklar veri kaymasina bagli, hepsi eskiye gore daha
dusuk varyansli.

DOGRULAMA: test_tk_fix.py 12/12 (fraksiyon boyutu, R:R tabanli banka,
zarar-sonrasi bekleme, karsi yon muafiyeti); tk_sanity 15 adim OK;
test_paper 90/90. sw ta-v25. UI metinleri (server.py, app.js) yeni
kural setiyle senkron.

### TK 2. tur: ters pozisyon noktalari + kazanc/kayip dengesi (oturum 11b)
CANLI (duzeltme sonrasi ilk oturum): 27 islem (10K/17Z), net -25,74$,
komisyon 63,40$. Kazanclar +23,2..24,1$ (banka %2,5), kayiplar
-8,6..-16,8$ (cogunlukla stop -15/-16). Kazanma %37, R:R ~1,5 ->
basabas icin %40 gerekli; beklenti hala negatif.

TESHIS: (a) banka hedefi kucuk kaldigi icin kazanc kaybi ancak 1,5x
karsiliyor; (b) EMA20/EMA50 mikro-kesismeleri 1-2 dk'da yon cevirip
girisleri donus tepelerine oturtuyor (ters pozisyon noktalari);
(c) islem sikligi komisyonu sisiriyor (27 islemde 63$).

DUZELTME:
  * PAPER_TK_BANK_PCT = 0.035 (kazanc ~+33$, kayip ~-14$ -> R:R ~2,3;
    basabas kazanma orani ~%30'a iner).
  * PAPER_TK_RIB_CONFIRM = 2 — EMA kesisimi ancak 2 KAPALI bar ayni
    yonde kalirsa gecerli (tek bar donusu yon degistirmez; sticky).
  * PAPER_TK_RIB_DEADBAND = 0.0002 — |EMA20-EMA50| fiyatin %0,02'sinden
    kucukse kesisme SAYILMAZ (chop mikro-kesisme filtresi).
  * PAPER_TK_ENTRY_OFFSET = 0.0 — "yildiz yonunde X ilerleme tetigi"
    olculdu ama zararli (asagi) bulundu; knop olarak duruyor.
  * SAR on/off olcumde ayni sonuc (bu pencerelerde trend filtresi
    tetiklemiyor); SAR acik birakildi.

OLCUM (8x500, 4500 bar / 6x500, 3000 bar, f0.5, 7 coin):
  bp2.5 cf1           : 8w +2028 / 6w +1155, en kotu -101 / -101
  bp3.0 cf2           : 8w +2503 / 6w +1267, en kotu  -74 /  -77
  bp3.0 cf2 db0.02    : 8w +2504 / 6w +1673, en kotu  -82 /  -51
  bp3.5 cf2 db0.02    : 8w +2749 / 6w +1855, en kotu  -69 /  -37
      (kazanc ~32$/kayip ~14$, kazanma %42-43, islem ~300-520)
  giris tetigi +0.05% : 8w +1154 (zararli), +0.10%: +834
Not: bp3.5 en iyi mutlak + en dusuk pencere kaybi; islem sayisi
~%25-55 azaldigi icin komisyon da belirgin duser.

DOGRULAMA: test_tk_fix 18/18 (deadband + confirm senaryolari dahil);
tk_sanity 15 adim OK; test_paper 90/90. sw ta-v26.

### TK 3. tur: pullback limit girisi + trend zorunlulugu (oturum 11c)
CANLI (2. tur sonrasi): 3 islem (0K/3Z), net -45,13$, komisyon 8,28$.
Uc kayip da ~%0,31 ters hareket: SHORT 0,1906->0,1912, LONG
0,1925->0,1919, SHORT 0,1910->0,1916. Girisler donus tepelerine denk
geliyor; stop girisden hemen sonra tetikleniyor.

TESHIS: yildiz/EMA kesisiminin verdiGi sinyal fiyati hareketin
TUKENMIS ucudur. Aninda girmek en kotu fiyati veriyor (27 islemlik
seride de ayni desen: girisler donus tepelerinde).

DUZELTME (yildiz hesabi DEGISMEDI; res.signals yalnizca okunur):
  * PAPER_TK_ENTRY_OFFSET = -0.0005 — giris artik ANINDA degil:
    sinyal fiyatinin %0,05 GERISINE pasif limit (pullback) konur.
    Fiyat geri dokunursa daha iyi fiyattan dolar, dokunmazsa giris
    olmaz (tukenmis harekete girilmez). Limit KOVALANMAZ (seviye
    sabit). Pozitif deger = breakout tetigi (olculdu, zararli),
    0 = eski aninda davranis.
  * PAPER_TK_REQUIRE_TREND = True — EMA20/EMA50 ayrisMAMISSA (olu
    bant icinde, rib=0) yildiz tek basina giris acmaz; yatay bant
    chop'un ana kaynagiydi.
  * PAPER_TK_RIB_DEADBAND 0.0002 -> 0.0005 (%0,05).
  * Bar modu dolum kodu: off<0 LIMIT (dokunma), off>0 STOP tetigi,
    off==0 eski davranis; yalniz off==0'da limit yeni barda fiyata
    tasinir (pullback/stop tetigi sabit kalir).

OLCUM (research_tk19, 8x500 / 6x500, bp3.5 cf2 REQ, 7 coin, 1m):
  off  0 (eski)   : 8w +3262 (424 islem, %46, en kotu -120)
                    6w +1554 (%43, -120)
  off -0.02%      : 8w +3021 (381, %47, -63) / 6w +1669 (%45, -63)
  off -0.03%      : 8w +2653 (340, %46, -63) / 6w +1321 (%44, -63)
  off -0.05% (sec): 8w +2555 (278, %49, -45) / 6w +1478 (%47, -45)
  off -0.10%      : 8w +1735 (130, %56, -55) / 6w +1257 (%56, -55)
Not: mutlak $ off=0'da en yuksek; ancak pullback kazanma oranini
+3-5 puan, islem basi ortalamayi +%15-20 artiriyor, en kotu pencere
kaybini ~2,5x kisiyor ve komisyonu ~%35 dusuruyor (272 vs 424 islem).
Kullanici sikayeti "ters pozisyon noktalari + zarar > kar" oldugu
icin -0.05% secildi.

VARSAYILAN DOGRULAMA (yalniz config, ayni gun): 8w +2402$ (272 islem,
%49, en kotu -66) / 6w +1272$ (170 islem, %46, -66). Onceki varsayilan:
8w +3080 (522 islem, %44, -149) / 6w +1673 (323 islem, %45, -51).

DOGRULAMA: test_tk_fix 25/25 (pullback dolum/kovalamama + trend
zorunlulugu senaryolari dahil); tk_sanity 15 adim OK; test_paper
90/90. sw ta-v27. UI metinleri (server.py, app.js) senkron.

### TK 4. tur: piyasa hafizasi + pullback derlesme (oturum 11d)
CANLI (ikinci iki oturum): ENA 1m 8 islem (2K/6Z, -26$) ve IK 1m
23 islem (4K/19Z, -140,73$, komisyon 56,29$). IK deseninde
19/23 kayip TAM %0,30 stop — giris "stop-avi" oluyor; ENA deseninde
ayni seviyede ust uste kayip: LONG 0,1945/0,1944/0,1946 -> hepsi
0,1938-0,1939 stop. Uc giristeki mantik hatasi net gorunuyor:
zarar edilen seviyeye GERI donuluyor.

TESHIS: sabit %0,30 stop 1m gurultu genisligi icinde kalir; sinyal
fiyatindan aninda girmek en kotu fiyat; ayni seviyeye tekrar tekrar
girmek serbestti.

DUZELTME (yildiz hesabi DEGISMEDI):
  * PULLBACK %0,05 -> %0,10 (PAPER_TK_ENTRY_OFFSET = -0.001):
    sinyal fiyatinin %0,10 gerisine pasif limit; dolum orani dusuyor
    ama dolan islem daha iyi fiyattan acilarak R:R'yi yukaritir.
  * PIYASA HAFIZASI:
      - PAPER_TK_STREAK_N=2 / STREAK_BARS=10: arka arkaya 2 zarar
        -> TUM yonlerde 10 bar giris yok (rejim bozuk; 10 bar sonunda
        sayac sifirlanir, kalici yasak yok).
      - PAPER_TK_LEVEL_BAN=0.002 / LEVEL_BARS=15: son zararli giris
        seviyesine yakin (±%0,20) AYNI yonde 15 bar tekrar giris yok
        — ayni duvara ust uste kafa atma engeli (ENA deseni).
  * YENI KNOPlar (kod eklendi, OLCUMDE ZARARLI BULUNDU -> varsayilan
    kapali): PAPER_TK_SL_ATR (stop=max(SL, ATR14*kat)), risk-tabanli
    BE klip PAPER_TK_BE_RISK (kar >= kat*stop-mesafesi -> stop
    girise cekilir), zaman stopu PAPER_TK_TIME_BARS. Ucunde de 8w/
    6w olcumler tabandan koyu geriye gitti (BE kazanma oranini
    dusurup islem basi ortalamayi sifirladi; ATR stop kayip boyunu
    ~%50 buyutup kazanmayi artirmadi).

OLCUM (8x500 / 6x500, ayni veri, gercek varsayilanlar):
  pull .05 (eski)         : 8w +1775 (229 islem, %47, en kotu -67)
                            6w  +148  ( 69 islem, %38, -67)
  pull .10 + hafiza (YENI): 8w +1120 (107 islem, %52, en kotu -38)
                            6w  +178  ( 17 islem, %59, -29)
  pull .10 (hafiza yok)   : ~ayni (hafiza bu pencere icinde notr ama
                            canli ENA deseni buna bagli korundu)
Not: mutlak $ dusuyor (islem ~%55 azaliyor -> komisyon da ~%55
azaliyor) ama profil belirgin daha guvenli: (a) en kotu pencere
kaybi -67 -> -38 (8w) / -29 (6w); (b) kazanma orani %47/%38 -> %52/%59;
(c) islem basi ort +7,8 -> +10,5$. Canli IK desenindeki 19 tam-stop
kaybin kaynagi "her sinyale dogrudan giris" idi; pullback filtresi +
seviye hafizasi bu cift deseni buyuk olcude engelliyor.

DOGRULAMA: test_tk_fix 37/37 (seviye hafizasi, seri freni, ATR,
risk-BE, zaman stopu pullback senaryolari dahil); tools/sanity_tk
12 adim OK; test_paper 90/90. sw ta-v28.

### OTURUM 12 — TİK2: YALNIZ-SHORT yildiz durumu makinesi (kullanici kurali)

CANLI: IK 43 islem (11K/32Z, -154,87$, komisyon 99,03$). Kullanici
yeni bir kural seti istedi (2026-11-02): "TİK2 — mevcut algoritmaya
gore calissin AMA SADECE SHORT yapsin."

KURAL (kullanici, birebir uygulama):
  * KIRMIZI yildiz (SAT/GÜÇLÜ SAT) aldigi surece SHORT pozisyonda kal;
    kirmizi iken SHORT ac.
  * GRI yildiz (NÖTR) -> pozisyonu KAPAT (kirmizi-dogumlu short).
  * YESIL yildiz (AL/GÜÇLÜ AL) -> islem acmaz, bekler (kirmizi/gri
    yildizi bekler).
  * YESILDEN SONRA gelen ilk gri -> SHORT ac (gri-dogumlu short; gri
    dizisi boyunca kalir, yesil geri gelirse kapanir).
  * LONG HIC KOŞULDA ACILMAZ — cift mekanik kilit: karar makinesi
    hedefi 0/-1 disina cikmaz + SAR ve ribbon-flip configure ile
    devre-disi + SAR icinde mod-kontrol + giris yolunda yon +1
    kapisi.

UGULAMA (yildiz hesabina DOKUNULMADI, res.signals okunur):
  * mode="tk2": configure ayni TK knoplarini taze okur uzerine SAR/
    ribbon-flip kapamasi; on_price ayni _tk motorunu kullanir, karar
    blogunda _tk2_karar() cagrilir (yerlesen/KAPALI bar yildizini
    okur; TK1'in ribbon-pin ve gri-TERS kurallari tk2'de cagrilmaz).
  * Karar tablosu: kirmizi->hedef=-1 "KIRMIZI"; gri->kirmizi-dogumlu
    kapatir "TİK2-GRI-KAPA", gri-dogumlu tutulur, duz+yesil-gecmis
    ise acar "TİK2-GRI"; yesil->gri-dogumlu kapatir "TİK2-YESIL-KAPA"
    ve _tk2_yesil bayragini kurar (tekrar gri gelirse kacis girisi).
  * backtest(): sinyal-serisi build mod listesine tk2 eklendi —
    yoksa geriye-donuk testte yildiz yok sanip islem acilmiyordu
    (ilk olcumde 0 islem tespit edildi, eklendi).
  * shared knoplar TK1 ile AYNI: pullback -.10, pause 3, streak 2/10,
    level 0.002/15, rib-deadband/confirm, require-trend, banka %3,5
    + R:R x1.8, fraksiyon %50, 1 dk bekleme — hepsi tk2'de aktif.

OLCUM (gercek veri; 8x500 / 6x500; TÜM işlemler assert ile SHORT):
  aninda (ofs 0)   : 8w +191 (461 is, %45, -27) / 6w +50 (315, %43, -27)
  pull -.05        : 8w +289 (183 is, %57, -50)  / 6w +216 (127, %56, -50)
  pull -.10 (VAR)  : 8w  +94 ( 66 is, %62, -33)  / 6w  +83 ( 47, %60, -33)
  pull -.15        : 8w  +56 ( 20 is, %70, -15)  / 6w  +63 ( 16, %75,  -7)
SECIM: paylasilan PAPER_TK_ENTRY_OFFSET=-0.001 (pull -.10) ile
birakildi — mutlak kaliyor ama iki pencerede pozitif, en-kotu kayip
kucuk, kazanma %60-62; -.05 daha cok kazanc ama en-kotu -50.
DOGRULAMA: test_tk2.py 24 senaryo (kirmizi-ac/kal, gri-kapat, yesil-
bekle, yesil→gri-ac, gri-dogumlu yesil-kapat, hic-LONG-ihlali,
ribbon/SAR/flip kilitlemeleri, banka, mum-kapisi) — TAMAM;
test_tk_fix 37/37; test_paper 90/90; tools/sanity_tk 12 adim.
sw ta-v29.
UI: index.html'e "TİK2 — yalnız-SHORT" modu eklendi; server.py (iki
blok) + app.js aciklama metinleri ayri yazildi.

### OTURUM 14 — İZLEME: seçilen mumun Al/Sat/Nötr kararı (görünürlük düzeltmesi)

SIKAYET (tekrar eden): "izleme modunda seçilen noktanın al/sat/nötr
durumunu göremiyorum". Onceki turlarda karar sunucuda bar-bazlı
üretiliyordu ama kullanıcı panelde göremiyordu; iki ayri kök neden
bulundu.

1) YANLIŞ ANAHTAR EŞLEŞMESİ (MA kararları hiç chip üretmiyordu):
   res.ma_series anahtarları KISALTMA (ema10, sma20, ichimoku, vwma,
   hma), res.ma_codes anahtarları TAM Türkçe etiket ("Basit Hareketli
   Ortalama(20)"). bar_info ma_vad'i tam etiketle döndürüyordu; istemci
   j.ma[kisa] ile eşleştirdiği için 15 MA satırının HİÇBİRİNDE rozet
   çıkmıyordu. Düzeltme: core/service.py'de MA_LABEL_BY_KEY (15 kısa
   anahtar -> tam etiket); bar_info artık ma_vad'i KISALTMA anahtarla ve
   ek ma_label haritasıyla döndürür. Böylece
   bar_info["ma"]["ema10"] ile bar_info["ma_vad"]["ema10"] birebir
   eşleşir; istemci tam etiketi yalnız GÖRÜNTÜ için ma_label'dan alır.
   (Yıldız/skor hesabına dokunulmadı; yalnız okuma/eşleme.)

2) BAYAT İSTEMCİ KODU (cache-first service worker):
   SW statik varlıkları cache-first veriyor; tek yenilemede eski
   app.js çalışıyordu. Düzeltme: index.html app.js/style.css
   referansları ?v=34 sürüm parametresiyle yüklenir (sorgu dizesi
   cache.match anahtarını değiştirdiği için eski SW bile ağdan taze
   dosyayı çeker), sw.js PRECACHE'i de aynı ?v=34 URL'lerini önbelleğe
   alır ve VERSION ta-v34 olur. skipWaiting() BİLİNÇLİ OLARAK
   KULLANILMADI: canlı işlem sırasında sayfayı yarıda yenilememesi için
   sw.js tasarım notu korunur; yeni SW bir sonraki tam açılışta devreye
   girer, ?v= parametresi ise kodu hemen tazeler.

3) GÖRÜNÜRLÜK (kullanıcının asıl istediği tek bakışta karar):
   İzleme panelinin en üstüne "SEÇİLEN MUM KARARI" + "TİK2 KARARI"
   satırları eklendi; değer, büyük renkli rozetle gösterilir
   (yeşil Al / kırmızı Sat / gri Nötr). Signal değerleri büyük harf ve
   "GÜÇLÜ AL" olabildiği için sinyalChip() bunları da Al/Sat/Nötr'e
   normalize eder. Ayrıca her osilatör ve MA satırının sağında küçük
   .wkarar rozeti, bölüm başlıklarında "(Al x · Sat y · Nötr z)" özeti
   ve tablo sayaçlarında "(mum)" etiketi vardır.

4) BAR SEÇİMİ: chartClickToBar, convertFromPixel'ın kategori ekseninde
   İNDEKS döndürmesi nedeniyle hep en eski mumu seçiyordu. Artık
   dataZoom penceresi + grid slot geometrisiyle (62 px sol / 86 px sağ,
   slot = plot genişliği / görünen mum) hesaplanır. "(oluşuyor)" etiketi
   j.time (ms) ile candle[0] (sn) karşılaştırmasındaki birim hatası
   düzeltilerek x1000 ile yapılır.

DOGRULAMA: test_paper 90/90 (İZLEME testi yeni ma_vad/ma_label yapısına
göre: her osilatör ve MA için tiklanan bar 75 ve 60'ın kararı
doğrulanır), test_tk2 TAMAM, test_tk_fix 37/37, node --check app.js OK,
py_compile OK. Canlı tarayıcı (localhost:8741): panelde 11 osilatör +
15 MA = 26 renkli rozet, bölüm özetleri ve tablo sayaçları doğru;
tooltip ile seçilen mum birebir eşleşir. sw ta-v34, ?v=34.

### OTURUM 15 — TİK2 canlı zararı: pullback girişi kaldırıldı (son 500 mum ölçümü)

SIKAYET: "TİK2 karar mekanizması hep zarar ettiriyor." Yıldız hesabına
ve TİK2'nin kullanıcı kuralına (yalnız-SHORT; kırmızı=kal, gri=kapat,
yeşil=bekle, yeşil→gri=SHORT aç) DOKUNULMADI; yalnız ölçüm yapıldı.

TESHIS (BTCUSDT, gerçek Binance Futures verisi, 500 bar × 5 dilim,
PaperTrader.backtest, yıldız serisi moddan bağımsız üretildi):
  dilim   taban (pullback -%0,10)      anında giriş (offset 0)
  4h      +150$ / 17 işlem / %53       +217$ / 20 işlem / %55
  1h       -30$ / 11 işlem / %36       +201$ / 16 işlem / %69
  15m     +137$ /  7 işlem / %100       +77$ / 14 işlem / %43
  5m       -14$ /  2 işlem / %50        +95$ / 14 işlem / %71
  1m        -7$ /  1 işlem / %0         +47$ / 13 işlem / %54
  (3x500 bar tekrarı: taban 15 pencerenin 9'u pozitif, 5m/1m 0/3;
   anında 13/15 pozitif. Taban toplamı 1h +153 / 5m -27 / 1m -7;
   anında 1h +521 / 5m +119 / 1m +33.)

KÖK NEDEN: PAPER_TK_ENTRY_OFFSET = -0.001 (sinyal fiyatının %0,10
gerisine pasif limit). TK1 için faydalı olan bu pullback, TİK2'de
yıldız kuralının "o anda" mantığıyla çelişiyor:
  * Düşük dilimlerde (1m/5m) geri çekilme çoğu zaman gelmiyor →
    neredeyse hiç işlem yok (1m'de 500 barda 1 işlem).
  * Geldiğinde ise fiyat artık dönmüş oluyor → giriş kötüleşiyor.
  * Sabit %0,5 stop, sinyal kapanışını beklemeden bar içi gürültüde
    tam ±%0,5000'de vuruluyor (1h işlem listesinde 5 kaybın 5'i tam
    stop; kazançlar +%0,9 banka hedefi). Kazanma %36 + komisyon →
    R:R fiilen 1,8'den ~1,3'e düşüyor, başabaş %44 iken %36 → zarar.

DÜZELTME: config.PAPER_TK2_ENTRY_OFFSET = 0.0; configure() içinde
mode=="tk2" dalında self.tk_entry_offset bu değerden okunur. TK1
pullback'i (PAPER_TK_ENTRY_OFFSET = -0.001) AYNEN korunur. Stop,
banka (%3,5 + R:R×1,8), fraksiyon %50, bekleme, SAR/ribbon kilidi,
seri/seviye hafızası değişmedi.

DOGRULAMA: test_tk2'ye senaryo 11 eklendi (TİK2 offset 0, TK1 offset
-0.001 korunur) — TAMAM. test_tk_fix 37/37, test_paper 90/90.
Ölçüm sonrası son 500 mum: 4h +217, 1h +201, 15m +77, 5m +95, 1m +47
(5/5 dilim pozitif). sw ta-v34.


### OTURUM 16 — TİK2 karar kaynağı: kullanıcı osilatör+MA kural listesi (2026-11-06)

KULLANICI KURALI: Grafik oluşturma ve gösterge hesapları AYNEN kalacak;
TİK2 pozisyon aç/kapa kararı, verilen 74 satırlık listeden üretilecek.
Her satırda bir DURUM (AL/SAT), osilatör kümesi ve hareketli ortalama
kümesi var. SAT = SHORT, AL = LONG. Bir satırın geçerli olması için o
satırdaki TÜM osilatörler ve TÜM MA'lar satırın yönünde olmalı; satırlar
arası VEYA. Aynı barda AL ve SAT satırı birlikte tutarsa NÖTR (çakışma
-> işlem yok). Aç/kapa sonrası 2 DAKİKA bekleme. Giriş/çıkış limit
(maker) — komisyon düşük.

UYGULAMA:
  * `core/tk2_rules.py`: 74 satır normalize edilmiş kural tablosu
    (25 AL / 49 SAT, 43 tekil). Yazım hataları eşlendi:
    NUTHIS→MÜTHİŞ, SKOTASTİK→STOKASTİK, WILLAMS→WILLIAMS,
    HACIM AGIRLIK(I)→HACIM AGIRLIKLI, BOGA GUCU→BOĞA AYI,
    EMTİA/EMTİA KANAL ENDEKS→CCI, NİHAİ→Nihai Osilatör.
    MA grupları: ÜSTEL=6 EMA, BASİT=6 SMA, HULL=Hull(9),
    HACİM AĞIRLIKLI=VWMA(20), HAREKETLİ HEPSİ=15 MA.
  * `paper._build_signal_series` mode=="tk2": `tk2_rules.series(
    res.osc_codes, res.ma_codes)` — analyze() çıktısı yalnız OKUNUR.
  * `paper._tk2_karar`: AL→+1 (LONG), SAT→−1 (SHORT), NÖTR→0 (kapat).
  * `service.mode_signal_series` ve `_signal_for_mode`: tk2 kural
    serisini kullanır; grafik yıldızları ve izleme panelindeki
    `mode_signal` aynı kararı gösterir.
  * TİK2 giriş kapıları kaldırıldı: LONG yasağı, ribbon/trend yönü,
    require_trend ve mum-yönü kapıları artık TİK2'de uygulanmaz —
    tek karar kaynağı kural listesidir. Stop %0,5, banka %3,5 +
    R:R×1,8, fraksiyon %50, SAR/ribbon-flip kapalı, seri/seviye
    hafızası, maker giriş/çıkış AYNEN korundu.
  * `config.PAPER_TK2_AFTER_SEC = 120`; configure() tk2 dalında
    `tk_after_ms` bu değerden okunur (TK1 60 sn kalır).

KURAL KAPSAMI (BTCUSDT, son 500 mum, gerçek veri):
  dilim   AL      SAT     NÖTR    ort. koşu   ort. sinyal
  4h     23,8%   44,8%   31,4%   2,2 bar     2,5 bar
  1h     22,0%   44,6%   33,4%   2,0 bar     2,2 bar
  15m    22,0%   44,4%   33,6%   2,2 bar     2,2 bar
  5m     20,0%   42,6%   37,4%   2,0 bar     2,1 bar
  1m     17,6%   41,0%   41,4%   2,1 bar     2,2 bar

GERİYE DÖNÜK TEST (aynı 500 bar, 1000$, 10x, %80 teminat):
  4h  +833,69$ (+%83,37) / 80 işlem / %55 kazanma
  1h  +477,52$ (+%47,75) / 56 işlem / %62
  15m   −5,01$ (−%0,50)  / 50 işlem / %44
  5m   +25,83$ (+%2,58)  / 44 işlem / %36
  1m    +5,91$ (+%0,59)  / 29 işlem / %45
  (Tek pencere ölçümü; kullanıcı kuralı sabit olduğu için parametre
  taraması yapılmadı.)

DOĞRULAMA: `test_tk2.py` yeni kural setine göre yeniden yazıldı —
43/43 (tablo 74 satır, AL/SAT/NÖTR/çakışma, LONG/SHORT/kapat, 2 dk
bekleme açılış ve kapanışta, maker komisyon, kapı bypass, backtest
serisi = kural serisi, service.mode_signal_series/bar_info/canlı sinyal).
`test_paper` 90/90, `test_tk_fix` 37/37, `py_compile` ve
`node --check app.js` temiz. Gösterge/grafik kodu değişmedi; sw ta-v35
(app.js/index.html metinleri: TİK2 artık yalnız-SHORT değil, kural
listesi).


### OTURUM 17 — TİK2 stabilizasyon: HULL giriş kapısı + 3 bar minimum tutma (2026-11-07)

KULLANICI GERİ BİLDİRİMİ: "İki mum AL, üçüncü mum SAT olunca pozisyon
hemen bozuluyor; bekliyor, sonra aynı yönde devam ediyor. Kayıplar bu
geçişlerde ve komisyonda oluşuyor. HULL değeri LONG/SHORT yönü için
belirleyici." İstek: kural listesi dışına çıkmadan daha stabil bir
uygulama.

TEŞHİS: Ham kural serisi 1m'de ortalama ~2,1 barda bir yön değiştiriyor
(500 barda ~237 geçiş). Pozisyon aç/kapa her geçişte komisyon üretiyor;
ters sinyal çoğu zaman trend dönüşü değil, kısa süreli salınım.

ARAŞTIRMA (gerçek Binance Futures 1m verisi, `tools/research_tk2_stab.py`,
`research_tk2_cross.py`, `research_tk2_final.py`; 1000$, 10x, sabit
bahis, maker). Adaylar nedensel (yalnız o bar ve öncesi):
  * Onay (giriş/çıkış/flip için K bar) — ENA 5.000 barda çıkış onayı
    zararlı: çıkış2 −873$, çıkış3 −617$, çıkış4 −1.009$ (ham +725$).
    Bu strateji trend değil, hızlı mean-reversion; çıkışı geciktirmek
    kazancı kaçırıyor.
  * Ters sinyali 2+ bar tolere etmek (`flip2`) — ENA 4.000 barda
    −293$ (ham +318$); ciddi zararlı, terk edildi.
  * Tam HULL vetosu (açık pozisyonu da kapatır) — giriş kapısından
    daha kötü; varsayılan KAPALI.
  * Tek başına giriş onayı (`giris2`) ve oy (`vote`) — karışık;
    ENA'da iyi, BTC'de zayıf; varsayılan KAPALI.

SEÇİLEN HİBRİT (kural listesi aynen kalır):
  1) HULL GİRİŞ KAPISI: yeni AL yalnız HULL +1 iken (veya HULL nötrken),
     yeni SAT yalnız HULL −1 iken açılabilir. HULL yönü belirler, kural
     listesi zamanlama verir. Açık pozisyonun çıkışı HULL yüzünden
     GECİKTİRİLMEZ; stop/banka her zaman anında çalışır.
  2) MİNİMUM TUTMA: sinyal ters dönse de pozisyon en az 3 bar tutulur
     (NÖTR ve ters sinyal ilk 2 barda kapatmaz). Stop/banka bu kapıdan
     etkilenmez. 1m'de 2 dk bekleme zaten 2 bar tuttuğu için pratikte
     +1 bar ekler.

ÇAPRAZ DOĞRULAMA (4 sembol × 8 × 500 bar 1m; 32 dilim):
  aday            net       PF     pozitif dilim   DD
  ham             +338$     1,13   15/32           −92,60$
  HULLg+hold3     +726$     1,29   18/32           −85,83$
  Sembol bazında ham → HULLg+hold3:
    ENA  +318$ → +592$   BTC  −95$ → −55$
    ETH   +74$ → +114$   SOL  +42$ → +75$
  Dört sembolün dördünde de hamdan iyi; komisyon 1.599$ → 1.548$.
  Tek 500-barlık pencerede sıralama değişebiliyor (ör. ENA son 500:
  ham +111,55$ / HULLg+hold3 +66,77$); 8 dilimli sonuç daha güvenilir
  kabul edildi. Varyantlar arasında en tutarlı iyileşme bu adayda.

UYGULAMA:
  * `core/tk2_rules.py`: `HULL_LABEL`, `hull_direction()`,
    `stabilize()`, `series_stable()`. Gösterge hesapları ve grafik
    serileri değişmedi; `osc_codes`/`ma_codes` yalnız OKUNUR.
  * `paper._build_signal_series`, `service._signal_for_mode`,
    `service.mode_signal_series` artık `series_stable(...)` çağırır:
    canlı, geriye dönük test ve grafik yıldızları birebir aynı.
  * `config.py`: `PAPER_TK2_MIN_HOLD = 3`, `PAPER_TK2_STAB_ON = True`,
    `..._HULL_ENTRY = True`, `..._HULL_FULL = False`,
    `..._HULL_SMOOTH = 1`, `..._CONFIRM_ENTRY/EXIT/FLIP = 1`,
    `..._VOTE = 1`, `..._MIN_DWELL = 0`, `..._HULL_FAST/GOVERNOR =
    False` (araştırma anahtarları; varsayılan seçilen hibrit).
  * `paper.py`: `_tk2_min_hold` (`__init__` + `configure` reload);
    sinyal çıkışı `t2_hold`/`t2_kapan` ile 3 bara kadar geciktirilir.
  * Arayüz metni: "HULL yön kapısı + 3 bar tutma"; cache `?v=36`,
    `sw.js` `ta-v36`.

DOĞRULAMA: `test_tk2.py` 58/58 (yeni bölüm 10 HULL giriş kapısı,
bölüm 11 minimum tutma: 1./2. bar kapatmaz, 3. bar kapatır, NÖTR de
kapıya tabi, stop tutmayı deler). `test_paper` 90/90,
`test_tk_fix` 37/37, `py_compile` ve `node --check app.js` temiz.

PRODUCTION DOĞRULAMA (`tools/research_tk2_prod_check.py`, aynı 4 sembol
× 8 × 500 bar, production `series_stable` + config varsayılanları):
  ham  +338,18$  15/32 pozitif  kom 1.598,84$  DD −92,60$
  prod +726,02$  18/32 pozitif  kom 1.548,42$  DD −85,83$
Production serisi araştırma prototipiyle birebir aynı (fark 0 bar);
seçilen hibrit production kodda da doğrulandı.

---

## OTURUM 18 — HULL nötr iken pozisyonu koruma (2026-11-07)

KULLANICI KURALI (özet):
> "HULL nötr olduğunda pozisyonu kapatma; HULL nötr iken yukarı yönlü ise
> long'a, aşağı yönlü ise short'a devam et. Mevcut pozisyonları böyle koru."

Ayrıca canlı gözlem: "1 mum kırmızı iken short açılıyor, arkasındaki yeşil
mumla kapanıyor; sonra tekrar dönüyor." Bu nedenle giriş için 2 ardışık mum
onayı da aday olarak ölçüldü.

HULL NÖTR SIKLIĞI (1m, `_ma_v` ±%0,02 ölü bölge):
  ENA %14,60 · BTC %46,85 · ETH %34,60 · SOL %28,70
Kuralın kararların büyük bölümüne dokunduğu görüldü.

ÖLÇÜM (`tools/research_tk2_hullneutral.py`, 4 sembol × 8 × 500 bar 1m,
sabit lot, production 3 bar minimum tutma ile):
  Varyant                              Net        Pozitif   DD
  prod (mevcut)                        +726,02$   18/32     −85,83$
  Nötrde kapatma (yalnız sinyal NÖTR)  +105,62$   11/32     −94,02$
  Nötr + HULL eğimi uyuyorsa koru      +256,44$   15/32     −88,25$
  Nötrken hiç kapatma (freeze)         −205,29$   10/32     −105,56$
  Nötrde yönü HULL eğimi belirlesin    +105,29$   19/32     −99,64$
  Girişte 2 mum onayı                   −66,10$   14/32     −94,20$
  Giriş 2 onay + nötr koruma           −404,70$   12/32     −95,32$
  Giriş 2 onay + freeze                −607,87$    7/32     −80,06$
  Giriş 2 onay + trend                 −704,48$    8/32    −111,85$

İŞLEM BAZLI TEŞHİS (`tools/research_tk2_whipsaw.py`, prod serisi):
  tutma 6+ bar : 443 işlem  +1.192,91$
  tutma 3-5 bar: 485 işlem    −598,07$
  tutma 2 bar  :  17 işlem     −92,58$
  tutma 1 bar  :   0 işlem (3 bar minimum tutma zaten engelliyor)
Kâr yalnızca uzun tutulan trend işlemlerinden geliyor; "nötrken kapatma"
kuralı kazananı da kaybedeni de aynı sürede uzattığı için zarar tarafı daha
ağır basıyor.

PENCERE TESTİ (`tools/research_tk2_enafold.py`, ENA 8 × 500 bar):
  Nötrde-kapatma yalnız 1. ve 8. dilimde production'dan iyi; 4., 5. ve 6.
  dilimde belirgin kötü. Son 500 barda görülen iyileşme (+254,86$ / 2 dilim)
  pencereye özgü; 8 dilim toplamında +439,70$ vs prod +592,49$.

KARAR: **Production değiştirilmedi.** Kullanıcı ölçüm sonrası "production'ı
olduğu gibi bırak" seçeneğini seçti. Mevcut 3 bar minimum tutma + HULL giriş
kapısı korunuyor; tek mumluk whipsaw'ı zaten bu kapı engelliyor. Araştırma
betikleri yalnızca kayıt/teşhis amacıyla `tools/` altında bırakıldı.

---

## OTURUM 19 — TİK2 beklemesiz giriş/çıkış + işlem günlüğü (2026-11-07)

KULLANICI İSTEĞİ:
> "Long/short pozisyon kapatmalarındaki beklemeyi iptal et; bekleme
> pozisyonu kaçırmasına ve zarara sebep oluyor. Ayrıca loglarda yön,
> giriş, çıkış, kâr/zarar, komisyon ve zamanı da kaydet."

KALDIRILAN BEKLEMELER:
  * `PAPER_TK2_AFTER_SEC`: 120 -> **0** (aç/kapa sonrası 2 dk yeni işlem
    yok kuralı; hem girişi hem kapanışı geciktiriyordu).
  * `PAPER_TK2_MIN_HOLD`: 3 -> **0** (ters sinyalde kapanışı 3 bar
    geciktiren kapı).
  * Stop ve kâr bankası zaten bu kapılardan etkilenmiyordu; anında
    çalışmaya devam ediyor.
  * TK1'in `PAPER_TK_AFTER_SEC=60` değeri DEĞİŞMEDİ.

ÖLÇÜM (`tools/research_tk2_wait.py`, 4 sembol × 8 × 500 bar 1m):
  Varyant                         Net        Pozitif   DD
  prod (120 sn + hold3)           +726,02$   18/32     −85,83$
  yalnız after=0 (hold3)          +746,71$   15/32     −95,47$
  bekleme yok (0 + 0)             +649,87$   18/32     −85,25$
  yalnız hold=0 (after 120)       +427,93$   16/32     −84,58$
Bekleme tamamen kaldırıldığında toplam kâr 76$ azalıyor ama pozitif dilim
sayısı (18/32) ve DD (−85,25$) production ile aynı kalıyor. Kullanıcı
canlıda beklemenin pozisyon kaçırdığını bildirdiği için karar uygulandı.

PRODUCTION DOĞRULAMA (`tools/research_tk2_prod_check.py`):
  ham  +543,52$  17/32  kom 1.740,49$  DD −109,04$
  prod +649,87$  18/32  kom 1.746,41$  DD  −85,25$
Production serisi artık "bekleme yok (0+0)" varyantıyla birebir aynı.

İŞLEM GÜNLÜĞÜ (yeni):
  * `config.TRADE_LOG_FILE = logs/islemler.csv`
  * Her KAPANAN canlı işlem için bir satır (';' ayraçlı):
    `kapanis_zamani; acilis_zamani; sembol; mod; yon; giris; cikis; adet;
     brut_kar; komisyon; net_kar; sonuc; bakiye; tutulan_bar; sebep;
     cikis_sebebi`
  * `sonuc` = KAR / ZARAR / BASABAS; komisyon = giriş + çıkış ücreti.
  * Yalnızca canlı işlemler yazılır; geriye dönük test ve birim testleri
    günlüğü kirletmez (`_backtesting` + `_quiet`/test süreci kapısı;
    testler `trader.trade_log = True` ile açar).
  * Metin logu da zenginleştirildi: kapanış satırında artık giriş fiyatı,
    giriş zamanı ve KAR/ZARAR etiketi var; zaman damgası log ön ekinde.

DOĞRULAMA: `test_tk2.py` 64/64 (bölüm 4 beklemesiz davranış, bölüm 11
varsayılan 0, bölüm 12 CSV günlüğü: başlık, yön, zamanlar, komisyon,
sonuç, canlı olmayan işlem yazılmıyor). `test_paper` 90/90,
`test_tk_fix` 37/37, `py_compile`, `node --check app.js/sw.js` temiz.
Arayüz metni "beklemesiz giriş/çıkış" olarak güncellendi; cache `?v=37`,
`sw.js` `ta-v37`.

---

## OTURUM 20 — TİK2: HULL nötrken yeni giriş yasağı (2026-11-08)

KULLANICI KURALI:
> "HULL nötr durumdayken yeni pozisyon açma, beklemede kal hep."

UYGULAMA:
  * `tk2_rules.stabilize()` yeni parametre: `hull_neutral_block`
    (varsayılan `False` — yalnız test/araştırma için).
  * Kapı yalnızca **pozisyon yokken** (`state == 0`) ve HULL kodu `0`
    iken yeni yön sinyalini `NÖTR` yapar; yani giriş bir sonraki
    HULL yönlü bara ertelenir.
  * Açık pozisyonun çıkışı bu kapıdan **etkilenmez**: ters sinyal /
    NÖTR sinyal pozisyonu her zamanki gibi anında kapatır; stop ve
    kâr bankası zaten anındadır.
  * `config.PAPER_TK2_STAB_HULL_NEUTRAL_BLOCK = True` (production).
    `series_stable()` bu değeri okur; canlı, geriye dönük test ve
    grafik yıldızları aynı kapıyı kullanır.
  * Kural tablosu, gösterge hesapları ve grafik üretimi DEĞİŞMEDİ;
    yalnızca `res.osc_codes` / `res.ma_codes` okunuyor.

ÖLÇÜM (`tools/research_tk2_hullblock.py`, 4 sembol × 8 × 500 bar 1m,
beklemesiz production ayarlarıyla):
  Varyant            Net        Pozitif   DD        İşlem
  yasak KAPALI       +649,87$   18/32     −85,25$   1041
  yasak AÇIK         +509,35$   15/32     −93,59$   1032

  Sembol bazında (yasak kapalı -> açık):
    ENA  +468,80 -> +438,26   BTC  −71,89 -> −11,10
    ETH  +185,64 -> +11,81    SOL  +67,32 -> +70,38
  BTC'de belirgin iyileşme ve DD küçülmesi (−52,71 -> −27,59), buna
  karşılık ETH'te büyük düşüş ve toplamda 140$ daha az kâr. HULL nötr
  oranı: ENA %14,60, BTC %46,85, ETH %34,60, SOL %28,70.

KARAR: Kullanıcı kuralı açıkça istediği için yasak **production'da
AÇIK**. Ölçümde toplam kâr azalsa da kullanıcı nötr bölgede giriş
istemiyor; karar kullanıcıya aittir. Kapalıyken ölçüm betiğiyle
karşılaştırma yapılabilir.

DOĞRULAMA: `test_tk2.py` 74/74 — bölüm 13: varsayılan yasak açık;
nötr HULL'da AL engellenir ve HULL +1 olunca girer; yasak kapalıyken
aynı seri girer; açık pozisyon nötr HULL'da korunur; ters sinyal nötr
HULL'da anında kapatır; production serisinde nötr HULL barı varken
yeni giriş yok; kapı kapalıyken seri ham kural serisine eşit.
`test_paper` 90/90, `test_tk_fix` 37/37, `py_compile`,
`node --check app.js/sw.js` temiz. Arayüz metni "HULL nötrken giriş
yok" olarak güncellendi; cache `?v=38`, `sw.js` `ta-v38`.

---

## OTURUM 21 — HULL + hacim ağırlıklı MA birlikte (2026-11-08)

KULLANICI KURALI:
> "Osilatörlerin SAT'tan daha fazla AL verirken (nötr dahil değil),
> HULL SAT, hacim ağırlıklı hareketli ortalamalar ise AL veriyorsa
> SHORT pozisyon açma, LONG pozisyon açman lazım. HULL ile hacim
> ağırlıklı hareketli ortalamaları beraber değerlendir. Hacim ağırlıklı
> hareketli ortalamalar AL verirken HULL nötr ise o pozisyon tehlikeli."

UYGULAMA:
  * `tk2_rules.oscillator_majority()`: 11 osilatörün AL/SAT sayısı.
    NÖTR kodlar sayılmaz; AL fazlaysa +1, SAT fazlaysa -1, eşitse 0.
  * `tk2_rules.ma_direction()`: tek MA yönü (VWMA için kullanılır).
  * `stabilize()` yeni girdiler: `osc_major`, `vwma`,
    `vwma_hull_long`, `vwma_hull_long_neutral`, `vwma_hull_hold`,
    `vwma_hull_always`, `vwma_hull_short`.
  * Koşul: osilatör çoğunluğu AL (+1), HULL SAT (-1), VWMA AL (+1).
    Bu durumda ham kural SAT üretse bile SHORT açılmaz; LONG açılır.
  * `vwma_hull_hold=True`: LONG açıldıktan sonra koşul sürdükçe LONG
    SAT sinyaliyle kapatılmaz. Koşul bitince normal kural işler.
  * `vwma_hull_always=False`: açık SHORT'u zorla LONG'a çevirmez.
  * `vwma_hull_short=False`: simetrik SAT kuralı (kullanıcı istemedi).
  * `vwma_hull_long_neutral=False`: ham kural NÖTR iken LONG açmaz;
    yalnız "SHORT açılacakken" devreye girer.
  * VWMA AL iken HULL NÖTR ise giriş yapılmaz: mevcut
    `PAPER_TK2_STAB_HULL_NEUTRAL_BLOCK` kuralı bu tehlikeli durumu
    zaten kapsıyor. Açık pozisyonun çıkışı etkilenmez.
  * Stop/kâr bankası anında çalışmaya devam eder.

ÖLÇÜM (`tools/research_tk2_vwma_hull.py`, 4 sembol × 8 × 500 bar 1m,
HULL nötr yasağı açık):
  Varyant                    Net        Pozitif   İşlem   DD
  taban (kural)              +509,35$   15/32     1032    −93,59$
  LONG giriş                 +499,74$   14/32     1026    −93,59$
  LONG giriş + koşul sürerken koru  +276,77$  12/32  1030  −110,45$
  LONG giriş + koru + NÖTR   + 59,92$   12/32     1054    −104,88$
  LONG her durumda           +252,09$   13/32     1009    −116,84$
  simetrik giriş             +499,74$   14/32     1026    −93,59$

Koşul barları sembol başına ~75–99 kez görülüyor; çoğu 1 bar sürüyor
(ortalama 1,1; en fazla 3). Kullanıcı, ölçüm sunulduktan sonra
"koşul sürerken LONG'u koru" seçeneğini seçti. Bu nedenle production
ayarı: `VWMA_HULL_LONG=True`, `VWMA_HULL_HOLD=True`,
`VWMA_HULL_ALWAYS=False`, `VWMA_HULL_SHORT=False`,
`VWMA_HULL_LONG_NEUTRAL=False`.

PRODUCTION DOĞRULAMA (`tools/research_tk2_prod_check.py`):
  ham  +543,52$  17/32  DD −109,04$
  prod +276,77$  12/32  DD −110,45$
Production serisi, seçilen "giriş + koşul sürerken koru" varyantıyla
birebir aynı.

DOĞRULAMA: `test_tk2.py` 83/83 — bölüm 14: osilatör çoğunluğu (nötr
hariç), HULL SAT + VWMA AL + osilatör AL -> LONG, kural kapalıyken ham
SAT, osilatör çoğunluğu yoksa çevrilmez, VWMA AL + HULL NÖTR -> giriş
yok, production serisi SAT yerine AL (koşul sürdükçe), config bayrakları.
`test_paper` 90/90, `test_tk_fix` 37/37, `py_compile`,
`node --check app.js/sw.js` temiz. Arayüz metni HULL/VWMA birleşik
kuralını gösterecek şekilde güncellendi; cache `?v=39`,
`sw.js` `ta-v39`.

> **2026-11-09 — BU KATMAN KAPATILDI.** Kullanıcı `list2.xlsx` ile
> 85 satırlık yeni karar tablosu verdi ve "HULL nötr yasağı ile
> VWMA/HULL kuralı kapansın, tablo tek karar kaynağı olsun" dedi.
> `PAPER_TK2_STAB_ON`, `HULL_ENTRY`, `HULL_NEUTRAL_BLOCK`,
> `VWMA_HULL_LONG` artık `False`. Ayrıntı: OTURUM 22.

---

## OTURUM 22 — list2.xlsx: 85 satırlık durum tablosu (2026-11-09)

KULLANICI KURALI:
> "KARAR mekanizmasındaki kural listesini değiştirelim. Ekteki listede
> POZİSYON sütunu AL=LONG, SAT=SHORT pozisyonunu işaret eder. Osilatör
> ve hareketli ortalamalar sütunlarının altında pozisyonlar yer
> almaktadır. Kuralları bu şekilde güncelleyelim; bu kuralları
> BTCUSDT/5m ile topladım."

KAYNAK: `C:\Users\PC-ITENG\Downloads\list2.xlsx`, `Sayfa1`, 85 veri
satırı. Sütunlar: `POZİYON | OSİLATÖR | HAREKETLİ ORTALAMALAR | TİK2
KARARI`. Hedef sütun **POZİYON**; `TİK2 KARARI` eski motorun çıktısı
olarak değerlendirildi.

EŞLEŞME SEMANTİĞİ (kullanıcı onayı):
  * Her satırda osilatör/MA durumları açık yazılı: AL (+1), SAT (−1),
    NÖTR (0).
  * Bir satır, yazılan **tüm** göstergelerin durumu aynen sağlandığında
    geçerlidir; yazılmayan göstergeler serbesttir (wildcard).
  * Birden çok satır tutarsa **en çok gösterge belirten (en özel)**
    satır kazanır. Eşitlikte **sonraki satır** geçerlidir.
  * Hiçbir satır tutmuyorsa karar NÖTR'dür.
  * Eski "tüm göstergeler satır yönünde" biçimi de desteklenir (durum
    yazılmayan gösterge satır yönünde kabul edilir); yeni tablo bunu
    kullanmıyor.

UYGULAMA:
  * `core/tk2_rules.py`
      - `RAW_RULES`: 85 satır, `POZİYON|osilatörler(DURUM)|MA'lar(DURUM)`.
        41 AL / 44 SAT, 69 tekil desen, özgüllük 4–11 gösterge.
      - `_tokens()`: `AD(DURUM)` ayrıştırıcısı; parantez `norm()` öncesi
        ayrılır. Durumlar `AL/SAT/NOTR`; durumsuz token satır yönünde.
        Aynı gösterge bir satırda iki kez yazılırsa (ör. satır 29'da
        `WILLIAMS YUZDE(AL), WILLIAMS(NOTR)`) **son durum** kazanır.
      - `Rule.osc_states/ma_states`: (tam etiket, istenen kod) çiftleri.
      - `Rule.specificity`: koşuldaki gösterge sayısı.
      - `rule_masks()`: her kural için durum eşleşme maskesi.
      - `series()`: bar başına en yüksek özgüllük; eşitlikte son satır.
      - Alias eklemeleri: `BOGAAYI`, `MUTHISOSILATOR`,
        `NIHAIOSILATOR`, `YONSEL ENDEKS`, `YONSELENDEKS`,
        `WILLIAMS YUZDE`, `WILLIAMSYUZDE`.
  * `config.py`: `PAPER_TK2_STAB_ON=False`,
    `PAPER_TK2_STAB_HULL_ENTRY=False`,
    `PAPER_TK2_STAB_HULL_NEUTRAL_BLOCK=False`,
    `PAPER_TK2_STAB_VWMA_HULL_LONG=False`. Böylece `series_stable()`
    doğrudan `series()` döndürür; tablo tek karar kaynağıdır.
  * `PAPER_TK2_AFTER_SEC=0`, `PAPER_TK2_MIN_HOLD=0` (bekleme yok).
    Stop ve kâr bankası her zaman anında çalışır.
  * HULL/VWMA katmanının kodu silinmedi; ileride araştırma için
    parametreli duruyor, yalnız varsayılanları kapalı.

TABLOYU GERİ ÜRETME:
  * Hedef `TİK2 KARARI` seçilirse yalnız 45/85 tutuyor: aynı yazılı
    durumda farklı kararlar var (KARAR, yazılmayan göstergelere de bağlı).
    Bu yüzden hedef POZİYON seçildi.
  * POZİYON için yazılan durumlarla temsil: **83/85**. Uyuşmayan 2 satır
    bilinçli çelişki gruplarıdır:
      - Excel satır 7 (AL) / 12 (SAT) aynı desen → "son satır" SAT verir,
        satır 7 uyuşmaz.
      - Excel satır 79 (SAT) / 81 (AL) / 83 (AL) aynı desen → "son satır"
        AL verir, satır 79 uyuşmaz.
  * Not: canlı veride yazılmayan göstergelerin de değeri vardır (0 dahil).
    Tüm yazılmayanlar 0 kabul edilirse bu ek çakışmalar nedeniyle uyum
    78/85'e düşer; bu bir gerçek-veri çakışmasıdır, motor hatası değil.
    Kullanıcı "en özel + eşitlikte son satır" kuralını seçtiği için karar
    her barda deterministiktir.

BACKTEST (yeni tablo, 5m, 50.000 bar, May–Oct 2026; fixed stake
1000$, 10x, cüzdan %80, komisyon %0,05):
  Sembol   İşlem   Net        PF    DD        AL/SAT/NÖTR bar
  BTCUSDT  4735    +2272,65$  1,19  −381,17$  17281/12468/20251
  ETHUSDT  4726    +2992,07$  1,19  −346,60$  16903/12057/21040
  SOLUSDT  4898    +6383,15$  1,34  −288,47$  17387/11448/21165
  (Giriş/çıkış maker; `_quiet` açık, işlem günlüğü yazılmadı.)

PRODUCTION DOĞRULAMA (`tools/research_tk2_prod_check.py`, 4 sembol × 8 ×
500 bar 1m): production serisi ham kural serisine **birebir eşit**
(fark 0 bar). Toplam 1m: −102,27$, 10/32 pozitif, 1128 işlem,
komisyon 1882,43$, DD −114,67$. 1m negatif, 5m pozitif: tablo 5m için
toplandığından beklenen; 1m'de kullanılmamalı.

DOĞRULAMA: `test_tk2.py` 83/83 (bölüm 1: 85 satır/41 AL/44 SAT/açık
durumlar/özgüllük 4–11/aynı göstergede son durum; bölüm 2: durum
eşleşmesi, wildcard, en özel satır, eşitlikte son satır, öncelik sırası;
bölüm 13–14: HULL/VWMA katmanı kapalı, production == ham, mekanizma
testleri korunuyor).
`test_paper` 90/90, `test_tk_fix` 37/37, `py_compile` temiz.
`logs/islemler.csv` oluşmadı. Arayüz metni ve cache sürümü güncellendi.


## OTURUM 23 — list3.xlsx: 158 satır + AL-KAPAT / SAT-KAPAT (2026-11-10)

KULLANICI KURALI:
> "İlk başta kâr yaptı ama AL-LONG ve SAT-SHORT çıkış noktalarını tespit
> edemiyor, kazanç zararla sonuçlanıyordu. Veriseti kurallarını
> güncelledim, genişlettim. Artık POZİSYON sütununda AL, SAT dışında
> AL-KAPAT (long pozisyonu kapat), SAT-KAPAT (short pozisyonu kapat)
> değerleri ve kuralları var. 5 dakikalık periyotta elde ettiğim bu
> kuralları da ekle; bu değerlere ulaştığında uygun çıkış işlemini yap."

KAYNAK: `C:\Users\PC-ITENG\Downloads\list3.xlsx`, `Sayfa1`, 158 veri
satırı. İlk 85 satır `list2.xlsx` tablosunun aynısı; yeni bölüm Excel
87–159. satırlar. `POZİYON` dağılımı: **50 AL / 54 SAT / 25 AL-KAPAT /
29 SAT-KAPAT**. `TİK2 KARARI` sütunu yine yalnız denetim içindir; hedef
`POZİYON`.

EŞLEŞME SEMANTİĞİ (korunuyor + çıkış):
  * Yazılan tüm durumlar aynen; yazılmayan göstergeler serbest.
  * En çok gösterge belirten (en özel) satır kazanır; eşitlikte sonraki.
  * Hiçbiri tutmazsa NÖTR (açık pozisyonu kapatır).
  * **AL-KAPAT** yalnızca AYNI yöndeki (LONG) açık pozisyonu kapatır;
    SHORT'u kapatmaz, yeni pozisyon açmaz.
  * **SAT-KAPAT** yalnızca açık SHORT'u kapatır; LONG'a dokunmaz.
  * Pozisyon yokken KAPAT satırı **uygulanmaz**; sıradaki en özel satır
    (giriş kuralı) geçerli olur. Böylece çıkış koşulu, düz pozisyonda
    yeni girişi süresiz kilitlemez.

NEDEN "POZİSYONA DUYARLI" SEÇİM: KAPAT satırı, tabloda durum değil
**aksiyon**dur. Statik "en özel satır her zaman kazanır" okuması
ölçüldü: BTC 5m 50k barda −1000,47$ (PF 0,86). KAPAT'ı yalnız aynı
yönde uygulayıp düz pozisyonda sıradaki satıra geçen sürüm aynı veride
+815,96$ (PF 1,08). Production bu nedenle `track_position=True`.

UYGULAMA:
  * `core/tk2_rules.py`
      - `RAW_RULES`: 158 satır; 50 AL / 54 SAT / 25 AL-KAPAT /
        29 SAT-KAPAT; 140 tekil desen; özgüllük 4–14.
      - `_ACTION_BY_POSITION`: `AL`, `SAT`, `AL-KAPAT`, `SAT-KAPAT`
        (norm tireyi boşluğa çevirdiği için "AL KAPAT" da kabul).
      - `Rule.action`, `Rule.label`, `Rule.is_close`.
      - `decide_target(label, current)`: AL→+1, SAT→−1,
        AL-KAPAT→(current>0 ise 0, değilse current), SAT-KAPAT simetrik,
        NÖTR→0.
      - `series(..., track_position=False)`: eski statik seri korunur
        (araştırma/teşhis). `track_position=True`: KAPAT yalnız uygun
        yönde; durum nedensel taşınır.
      - `series_stable()` production'da `track_position=True`; KAPAT
        etiketi varsa stabilizasyon uygulanmaz (tablo tek kaynak).
      - Alias eklemeleri: `GORECELI GUC`, `GORECELI GUC ENDEKSI`, `RSI`,
        `ORTALAMA YONSEL`, `ORTALAMA YONSEL ENDEKS`, `ADX`, `ICHIMOKU`,
        `ICHIMOKU ANA HATTI`; tek periyotlu `BASIT HAREKETLI
        ORTALAMA10/20/30/50/100/200` + kullanıcı yazım hatası
        `BASIT HAREKTLI ORTALAMA...`.
  * `core/paper.py`
      - `_tk2_karar()` artık `tk2_rules.decide_target()` kullanır;
        kaynak etiketleri `TİK2-AL-KAPAT` / `TİK2-SAT-KAPAT`.
      - Stop, kâr bankası, TP/BE ve zaman stopu değişmedi; hepsi her
        zaman anında çalışır (`PAPER_TK2_MIN_HOLD=0`,
        `PAPER_TK2_AFTER_SEC=0`).
  * `core/service.py`
      - `tk2_labels(tf)`: ham TİK2 etiket serisi (cache'li). Paper
        motoru bunu alır; `mode_signal_series` grafik için
        `AL-KAPAT→SELL`, `SAT-KAPAT→BUY` eşler (MURO ile aynı görsel
        sözleşme).
  * `web/static/*`: TİK2 metni list3/158 satır + KAPAT açıklaması;
    cache `?v=42`, `ta-v42`.

BACKTEST (5m, 50.000 bar, May–Oct 2026; fixed stake 1000$, 10x,
cüzdan %80, komisyon %0,05; maker giriş/çıkış):
  Sembol   İşlem   Net         PF    DD        AL/SAT/AK/SK/NÖTR bar
  BTCUSDT  4227    +815,96$    1,08  −457,03$  16254/12281/1654/1463/18348
  ETHUSDT  4135    +1416,97$   1,10  −334,49$  15772/11948/1803/1606/18871
  SOLUSDT  4174    +5689,65$   1,37  −249,73$  16082/11290/2006/1725/18897
  Aynı veride 85 satırlık tablo: BTC +2272,65$ (PF 1,19, DD −381,17$),
  ETH +2992,07$ (1,19, −346,60$), SOL +6383,15$ (1,34, −288,47$).
  Yorum: çıkış kuralları BTC/ETH netini düşürüyor (trendde erken çıkış),
  SOL'da PF 1,34→1,37 ve DD −288→−250 ile iyileşiyor. Kullanıcı çıkış
  kurallarını açıkça istediği için üretimde açık; sonuç ölçümü budur.

PRODUCTION DOĞRULAMA (`tools/research_tk2_prod_check.py`, 4 sembol × 8 ×
500 bar 1m): production serisi `series(track_position=True)` ile
**birebir eşit** (fark 0 bar). Toplam 1m: −146,58$, 9/32 pozitif,
1033 işlem, komisyon 1719,56$, DD −102,29$. 1m negatif; tablo 5m için
toplandığından 1m'de kullanılmamalı.

DOĞRULAMA: `test_tk2.py` **107/107** (158 satır dağılımı, yeni
alias'lar, KAPAT etiketleri, pozisyona duyarlı seçim, LONG'da AL-KAPAT /
SHORT'ta SAT-KAPAT, ters yönde kapatmama, düz pozisyonda işlem açmama,
en özel satır/eşitlik, production == ham). `test_paper` 90/90,
`test_tk_fix` 37/37, `py_compile` temiz. `logs/islemler.csv` oluşmadı.


## OTURUM 24 — list3 (1).xlsx: 199 satır + 3 varyant + 10$ kâr bankası (2026-11-11)

KULLANICI KURALI:
> "Liste kurallarını güncelledim. Öncelikle POZİSYON sütunu bizim hedef
> sütunumuz, karar alma mekanizmasıdır. TİK2 sütunu sadece parametredir.
> AL, SAT, AL-KAPAT, SAT-KAPAT pozisyonlarını alacaksın. Veri setini
> genişlettim. Ayrıca bu kuralın sadece SHORT ve SHORT'tan çıkış, sadece
> LONG ve LONG'tan çıkış olarak 2 ayrı versiyonunu ekle. TİK2 için toplam
> 3 algoritmam olacak, istediğimi seçmeliyim. Hem long hem shortta
> kapatma kuralları 10 dolar olduğunda kapat, kazancı cüzdana geçir. Bu
> değeri arayüzden parametre olarak belirleyebileyim; varsayılan 10 dolar."

KAYNAK: `C:\Users\PC-ITENG\Downloads\list3 (1).xlsx`, `Sayfa1`, **199
veri satırı**. `POZİYON` dağılımı: **57 AL / 64 SAT / 36 AL-KAPAT /
42 SAT-KAPAT**. 180 tekil desen; özgüllük 4–17 gösterge. Hedef karar
sütunu `POZİYON`; `TİK2 KARARI` yalnız parametre/denetimdir. Excel
satırları ile parser çıktısı karşılaştırıldı: **0 fark**. İlk 85 satır
(`list2.xlsx`) korunmuştur.

VARYANTLAR (`core/tk2_rules.py`):
  * `tk2`       — iki yön: AL + SAT ve KAPAT satırları (önceki davranış).
  * `tk2_long`  — yalnız LONG: AL açar/korur, AL-KAPAT kapatır; SAT ve
    SAT-KAPAT yok sayılır, SHORT hiç açılmaz.
  * `tk2_short` — yalnız SHORT: SAT açar/korur, SAT-KAPAT kapatır; AL ve
    AL-KAPAT yok sayılır, LONG hiç açılmaz.
  * `TK2_MODES`, `is_tk2_mode()`, `side_for_mode()` (+1/−1/None);
    `series(..., side=...)` ve `series_stable(..., side=...)` yön
    filtresi uygular. Paper motorunda ikinci savunma hattı olarak ters
    yön etiketi `_tk2_karar()` içinde yok sayılır.

DOLAR KÂR BANKASI: `PAPER_TK2_BANK_USD = 10.0` (arayüz: `pBank`,
varsayılan 10$; 0 = kapalı). Açık pozisyonun DOLAR kârı eşiğe ulaşınca
kapanır ve kazanç cüzdana yazılır (maker çıkış). İki yönde de geçerli;
TİK2'de yüzde/R:R tabanlı `tk_bank_pct` yerine bu eşik kullanılır.
Eşik anında çalışır (`PAPER_TK2_MIN_HOLD=0`, `PAPER_TK2_AFTER_SEC=0`).

BACKTEST (5m, 50.000 bar, May–Oct 2026; fixed stake 1000$, 10x,
cüzdan %80, komisyon %0,05; maker giriş/çıkış). `tools/research_tk2_variants.py`:

  Varyant     Sembol  Banka 10$                          Banka KAPALI
  tk2         BTC     −240,22$  PF 0,98  4362 işlem      +788,59$  1,07  4239
  tk2         ETH     +288,06$  PF 1,02  4373 işlem      +1461,07$ 1,10  4166
  tk2         SOL     +2295,41$ PF 1,16  4423 işlem      +5754,37$ 1,37  4190
  tk2_long    BTC     −1001,54$ PF 0,85  2249 işlem      −63,29$   0,99  3525
  tk2_long    ETH     −501,09$  PF 0,96  3663 işlem      +1013,90$ 1,08  3519
  tk2_long    SOL     +608,81$  PF 1,04  3786 işlem      +2762,00$ 1,18  3610
  tk2_short   BTC     −1003,13$ PF 0,73  1107 işlem      −1014,27$ 0,80  1534
  tk2_short   ETH     −1002,17$ PF 0,71  851 işlem       −1001,16$ 0,80  1097
  tk2_short   SOL     −1015,08$ PF 0,69  716 işlem       −1000,19$ 0,85  1330

YORUM: 199 satırlık tablo, 158 satırlık tablonun bankasız sonuçlarını
koruyor (BTC +815,96→+788,59$, ETH +1416,97→+1461,07$, SOL
+5689,65→+5754,37$). 10$ banka, 4000$ notional'da ~%0,25 fiyat
hareketinde kapanış ürettiği için işlem sayısını ve komisyonu artırıp
neti düşürüyor (BTC −240,22$, ETH +288,06$, SOL +2295,41$). Kullanıcı
10$'ı açıkça istediği için varsayılan 10$ bırakıldı; arayüzden
yükseltilebilir veya 0 ile kapatılabilir. Yalnız-LONG, iki yöne göre
daha iyi; yalnız-SHORT üç sembolde de negatif (kısa trendlerde
komisyon/stop baskısı). Grafik eşlemesi korunuyor: `AL-KAPAT→SELL`,
`SAT-KAPAT→BUY`.

PRODUCTION DOĞRULAMA (`tools/research_tk2_prod_check.py`, 4 sembol × 8 ×
500 bar 1m): production serisi `series(track_position=True)` ile
**birebir eşit** (fark 0 bar). Toplam 1m: −158,72$, 11/32 pozitif,
1057 işlem, komisyon 1750,74$, DD −78,69$. 1m negatif; tablo 5m için
toplandığından 1m'de kullanılmamalı.

DOĞRULAMA: `test_tk2.py` **135/135** (199 satır dağılımı, 180 tekil
desen, özgüllük 4–17, ilk 85 satır korunmuş, varyant yön filtreleri,
ters yön kilidi, 10$ banka LONG/SHORT kapanışı ve 0=kapalı).
`test_paper` 90/90, `test_tk_fix` 37/37, `py_compile` temiz.
`logs/islemler.csv` oluşmadı. Arayüz cache sürümü `?v=43` / `ta-v43`.


## OTURUM 25 — Zarar koruması süreleri 1 bar (2026-11-12)

KULLANICI KARARI:
> "Arka arkaya 2 zarardan sonra tüm yönlerde 10 bar fren ve zarar edilen
> giriş seviyesine yakın aynı yönde 15 bar giriş yok — bunları 1'er bar
> olarak güncelleyelim."

DEĞİŞİKLİK:
  * `PAPER_TK_STREAK_BARS`: 10 → **1** (arka arkaya 2 zarardan sonra
    tüm yönlerde 1 bar giriş yok).
  * `PAPER_TK_LEVEL_BARS`: 15 → **1** (zarar edilen giriş seviyesine
    yakın aynı yönde 1 bar giriş yok).
  * `PAPER_TK_STREAK_N=2`, `PAPER_TK_PAUSE_BARS=3` ve
    `PAPER_TK_LEVEL_BAN=0,002` DEĞİŞMEDİ.
  * Anlam: kilit yalnızca zararın gerçekleştiği bar boyunca sürer; bir
    sonraki barda giriş serbesttir. Kârlı kapanış kilitleri zaten temizler.
  * `core/paper.py` varsayılanları (10→1, 15→1), `web/server.py` onay
    metinleri ve `web/static/app.js` açıklaması güncellendi; arayüz cache
    sürümü `?v=44` / `ta-v44`.

ÖLÇÜM (5m, 50.000 bar; fixed stake 1000$, 10x, %80, komisyon %0,05;
`tk2` iki yön):

  Sembol  Banka 10$ (önce → sonra)        Banka kapalı (önce → sonra)
  BTC     −240,22$ → −259,30$ (PF 0,98)   +788,59$ → +683,13$ (PF 1,06)
  ETH     +288,06$ → +268,82$ (PF 1,02)   +1461,07$ → +1329,37$ (PF 1,09)
  SOL     +2295,41$ → +2362,60$ (PF 1,16) +5754,37$ → +5802,67$ (PF 1,36)

Yorum: kısa fren, işlem sayısını bir miktar artırıyor; net etkisi
sembole göre küçük ve karışık (BTC/ETH hafif azalma, SOL hafif artış ve
DD iyileşmesi). Kullanıcı akışın kilitlenmemesini istediği için bu
değerler üretimde.

DOĞRULAMA: `test_tk2.py` **138/138** (yeni bölüm 17: seri freni 1 bar,
seviye yasağı 1 bar, eşik 2 zarar). `test_paper` 90/90,
`test_tk_fix` 37/37, `py_compile` temiz. `logs/islemler.csv` oluşmadı.



