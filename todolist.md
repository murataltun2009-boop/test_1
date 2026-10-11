# TODOLIST.md — Binance Futures Canlı Teknik Analiz + Kaldıraç Simülatörü

> **Bu dosya, bu uygulamayı sıfırdan yeniden yazacak bir AI geliştirme
> platformuna (Lovable / Bolt / v0 vb.) verilecek tam kapsamlı ürün
> şartnamesidir.**
>
> Hedef platformda **web uygulaması** üretilecek; ardından Capacitor /
> React Native ile Android'e sarılacak. Python gerekmez — tüm hesaplama
> TypeScript'te yapılacak.

---

## 0. Bu Şartnameyi Kullanma Kılavuzu

Bu belge **"ne yapılacak"** tanımıdır, bir kod kopyası değildir.
Şunları dikkate al:

| Kural | Neden |
|---|---|
| **Bölüm 18 (Ölçülmüş Sonuçlar) doğrulama amaçlıdır.** Yeni kod eski sonuçları vermek zorunda değildir, ama "regresyon muhtemel" der. | Rakamlar tek bir 500 barlık örneklemden geldi |
| **Bölüm 19 (Tuzaklar) en kritik bölümdür.** Bunlar geliştirici saatler harcar. | Gerçek projede ölçülmüş hatalar |
| **Bölüm 20 (Kapsam Dışı) uygulanmamalıdır** — gerçek emir gönderme yoktur. | Güvenlik / kapsam |
| Bir kural ile ölçüm çelişirse **ölçüm kazanır** (deneyimsel karar). | Test edilmiş olan |

**Uygulama dilinde** öneriler: TypeScript + React + Vite + shadcn/ui,
grafik için **Lightweight Charts** veya **ECharts**.

---

## 1. Ürün Tanımı

Binance **Futures** piyasası için canlı teknik analiz uygulaması.
Kullanıcı mum grafiğini izler, 26 göstergeyi görür, **AL / SAT yıldızlarını**
grafik üzerinde görür ve **sanal cüzdan + kaldıraç** simülatörüyle işlem
kuralını deneyebilir.

**Para birimi:** USDT · **Piyasa:** vadeli (futures), spot değil

### Kimlere yönelik
Teknik analiz yapan, kural tabanlı otomatik işlem mantığını görsel olarak
denetlemek isteyen yatırımcı.

### Kritik kısıt
> **UYGULAMA GERÇEK EMİR GÖNDERMEZ.** Borsa hesabı taşınmaz, API anahtarı
> alınmaz, yalnızca simülasyon yapılır. Bu bir ürün kararıdır, kısıt değil.

---

## 2. Veri Kaynağı

### 2.1 REST — geçmiş mumlar (başlangıç)

```
GET https://fapi.binance.com/fapi/v1/klines
    ?symbol=BTCUSDT&interval=4h&limit=500
```

Dönen dizi sırası (BU SIRAYA DİKKAT — en sık hata kaynağı):

```
[0] bar açılış zamanı (ms)   [1] açılış   [2] en yüksek   [3] en düşük
[4] kapanış                   [5] hacim    [6] kapanış zamanı
```

### 2.2 WebSocket — canlı işlem akışı (birincil)

```
wss://fstream.binance.com/stream?streams=btcusdt@trade
```

> **ÖNEMLİ MİMARİ KARAR:** Kline akışı (`@kline_4m`) bazı ağlarda **sessiz
> kalır** (bağlanır, mesaj gelmez). Bu yüzden son mum **işlem akışından
> üretilir**. Aynı zamanda `@kline` akışı da dinlenip, gerçekten veri
> geliyorsa kullanılabilir — ama **olmazsa sistem çalışmaya devam etmelidir.**

`@trade` mesajı:
```json
{"e":"trade","E":123456789,"s":"BTCUSDT","t":123,"p":"83000.00",
 "q":"0.012","T":123456789,"m":true}
```
`p` = fiyat, `q` = miktar, `m` = alıcı piyasa yapıcı mı.

### 2.3 Son mumun işlemlerden üretilmesi

Her işlem **üç zaman diliminin üçüne birden** uygulanır.
`bar = floor(işlemZamanı / dilimMs) * dilimMs`

```ts
for (const [tf, tfMs] of TIMEFRAMES_MAP) {
  const bucket = Math.floor(trade.T / tfMs) * tfMs;
  const buf = buffers[tf];
  if (buf.length && bucket < buf[buf.length - 1].openTime) continue; // eski

  if (buf.length && bucket === buf[buf.length - 1].openTime) {
    const c = buf[buf.length - 1];
    c.high = Math.max(c.high, p);
    c.low  = Math.min(c.low,  p);
    c.close = p;
    c.volume += q;
  } else {
    buffers[tf].push({ openTime: bucket, open: p, high: p,
                       low: p, close: p, volume: q,
                       closeTime: bucket + tfMs - 1, closed: false });
  }
}
if (buffers[tf].length > 500) buffers[tf].shift();
```

### 2.4 Periyodik mutabakat
Her **60 saniyede** bir REST ile 500 mum yeniden çekilir ve buffer
değiştirilir (WebSocket kaçırmış olabilir).

### 2.5 Yeniden bağlanma
WebSocket koparsa **5 saniye** sonra yeniden bağlanılır. Kopma loglanır.

---

## 3. Veri Temizleme — ZORUNLU

Bu iki madde atlanırsa uygulama **görsel olarak bozulur**. En sık yapılan
hata budur.

### 3.1 Kline mumunda `low = 0` onarımı

Binance yeni açılan oluşan mumda **ara sıra `low=0, close=0`** gönderir.

```
ac=82790.0   yis=82795.2   dus=0.0   kap=0.0
```

**Onarım kuralı:**
```ts
if (low <= 0) { low = open;  high = Math.max(high, open);  close = open; }
if (high < low) { high = Math.max(high, low); }
if (high <= 0) { high = Math.max(open, close); }
```
Hâlâ tutarsızsa mumu **tamamen düşür**.

> **Etkisi:** Bu olmadan Y ekseni 0'a doğru uzar, tüm göstergeler bozulur ve
> "fiyat pencerenin en tabanında" kuralı anında sahte sinyal üretir.

### 3.2 Bozuk işlem fiyatı filtresi — **ÖLÇÜLDÜ**

`@trade` akışında **mesajların ~%8'i** bozuk geliyor:

```
150 sn ETHUSDT @trade izlemesi
  toplam işlem : 1579 (10,5 msg/sn)
  bozuk işlem  : 12        ← fiyat=0.0, qty=0.0
```

> Kullanıcının bu uygulamada "log'da **ETH için fiyat 13,11**" görüp
> **bir hata sandığı** vakayı bu üretmiştir. Aynı aileden, `fiyat <= 0`
> filtresinden geçen ince bozulmalar da gelir.

**Kural:**
```ts
let lastGoodPrice = 0;

function isSaneTrade(price: number): boolean {
  if (price <= 0 || !isFinite(price)) return false;
  if (lastGoodPrice > 0) {
    const drift = Math.abs(price - lastGoodPrice) / lastGoodPrice;
    if (drift > 0.25) {                 // %25 — gün içi zıplama dildiği için güvenli
      log("warning", `Bozuk işlem atlandı: ${price} (son geçerli ${lastGoodPrice}, sapma %${drift*100})`);
      return false;
    }
  }
  lastGoodPrice = price;
  return true;
}
```

> **Sembol değişiminde `lastGoodPrice = 0` yapılmalı**, yoksa yeni coinin
> bütün ilk işlemleri reddedilir.

---

## 4. Zaman Dilimleri ve Coin Seçimi

### 4.1 Zaman dilimleri

| Kod | Etiket | Saniye | Varsayılan |
|---|---|---|---|
| `15m` | 15dk | 900 | |
| `1h` | 1sa | 3600 | |
| `4h` | 4sa | 14400 | ✅ **açılışta seçili** |

- Seçilen dilime göre **grafik, gösterge değerleri ve AL/SAT yıldızları
  yeniden hesaplanır.**
- Üç dilim **aynı anda arka planda** çalışır.

### 4.2 Performans: odak dışı dilimler

`analyze()` 500 bar için **~55 ms** sürer. Üç dilimi de 0,5 sn'de bir
çalıştırmak sürekli CPU tüketir.

| Kural | Değer |
|---|---|
| Odaktaki dilim | her **0,5 sn** |
| Diğer dilimler | **4× seyrek** (2 sn) |
| Ölçülen CPU (4 çekirdek) | ~**%6** |

### 4.3 Coin listesi (10 parite)

```
BTCUSDT  ETHUSDT  SOLUSDT  BNBUSDT  XRPUSDT
DOGEUSDT ADAUSDT  AVAXUSDT LINKUSDT DOTUSDT
```

- Sembol değişince: mum geçmişi yeniden çekilir (~1 sn/dilim),
  tüm tamponlar **temizlenir**, simülatör **sıfırlanır**,
  `lastGoodPrice` sıfırlanır.
- Kullanıcı **bir listeden seçer**, serbest metin girmez.

---

## 5. Göstergeler — 11 Osilatör + 15 Hareketli Ortalama

Bileşik skor **osilatörlerin ortalaması × %50 + MA'ların ortalaması × %50**
hesaplanır. Her göstergenin **değeri** ve **yorumu (Al/Nötr/Sat)** vardır.

### 5.1 Osilatörler (11)

| # | Gösterge | Parametre | **Yorum kuralı (TradingView mantığı)** | Skor |
|---|---|---|---|---|
| 1 | Göreceli Güç Endeksi (RSI) | 14 | **Seviye:** ≥70 → Sat, ≤30 → Al | +1/−1 |
| 2 | Stokastik %K | 14, 3, 3 | %K'nın %D'yi **yukarı kesmesi → Al**, aşağı kesmesi → Sat | +1/−1 |
| 3 | Emtia Kanal Endeksi (CCI) | 20 | **≥ +100 → Sat**, ≤ −100 → Al | +1/−1 |
| 4 | Ortalama Yönsel Endeks (ADX) | 14 | **25 eşiğini yukarı kesmesi → Al** (trend gücü), aşağı → Sat | +1/−1 |
| 5 | Müthiş Osilatör (AO) | 5, 34 | **Sıfırın üstüne çıkması → Al**, altına inmesi → Sat | +1/−1 |
| 6 | Momentum | 10 | **İşaret:** >0 → Al, <0 → Sat | +1/−1 |
| 7 | MACD Seviyesi | 12, 26, 9 | **MACD çizgisi sinyalin üstünde → Al**, altında → Sat | +1/−1 |
| 8 | Stokastik RSI Hızlı | 3, 3, 14, 14 | %K'nın %D'yi kesmesi | +1/−1 |
| 9 | Williams Yüzde Aralığı | 14 | **−80'i yukarı keserse → Al**, −20'yi aşağı keserse → Sat | +1/−1 |
| 10 | Boğa Ayı Gücü | 13 | **Boğalar 0'ın üstüne çıkarsa → Al**, ayılar 0'ın altına inerse → Sat | +1/−1 |
| 11 | Nihai Osilatör (UO) | 7, 14, 28 | **≥70 → Sat**, ≤30 → Al | +1/−1 |

> **Kural 2 ve 8'in ortak notu:** Stokastik türlerinde **seviye değil
> KESİŞİM** esastır. Seviye kuralı kullanmak yanlış sinyal üretir.

### 5.2 Hareketli Ortalamalar (15)

Sıralama: her periyotta **önce EMA, sonra SMA**.

| # | Gösterge | Parametre | Yorum |
|---|---|---|---|
| 1–12 | EMA(10), SMA(10), EMA(20), SMA(20), EMA(30), SMA(30), EMA(50), SMA(50), EMA(100), SMA(100), EMA(200), SMA(200) | — | fiyat MA'nın üstünde → Al |
| 13 | İchimoku Ana Hattı | 9, 26, 52, 26 | fiyat üstünde → Al (**daha geniş ölü bölge**) |
| 14 | Hacim Ağırlıklı MA (VWMA) | 20 | fiyat üstünde → Al |
| 15 | Hull MA (HMA) | 9 | fiyat üstünde → Al |

### 5.3 MA "ölü bölge" (deadzone) — **NEDEN VAR**

Fiyat tam olarak MA çizgisi üzerindeyken her barda Al↔Sat arasında
zıplar. Bunu engellemek için oransal bir tolerans:

| MA türü | Ölü bölge | Gerekçe |
|---|---|---|
| Normal MA | **%0,02** (`0.0002`) | Fiyat çizgiye çok yakınsa Nötr |
| **İchimoku** | **%0,25** (`0.0025`) | TradingView bu satırı **bulut (senkou)** mantığıyla yorumlar; doğrudan fiyat karşılaştırması aynı sonucu vermez |

```ts
// +1, 0, -1
const up = price > ma * (1 + deadzone);
const dn = price < ma * (1 - deadzone);
```

### 5.4 Hesap formülleri (referans)

```
RSI(14)  : Wilder yumuşatması (RMA). AL=100 ise RSI=100
Stok %K  : 100 × (C − LL(14)) / (HH(14) − LL(14)), sonra 3 barlık SMA
CCI(20)  : (TP − SMA(TP,20)) / (0,015 × MeanDev(TP,20)),  TP=(H+L+C)/3
ADX(14)  : Wilder DI + DX + RMA(DX,14)
AO       : SMA((H+L)/2, 5) − SMA((H+L)/2, 34)
Momentum : C − C[n-10]
MACD     : EMA(12) − EMA(26);  sinyal = EMA(9)
StochRSI : RSI(14) üzerinde stokastik(14), sonra 3'lük SMA
Williams : −100 × (HH(14) − C) / (HH(14) − LL(14))
BoğaAyı  : EMA(13) taban;  boğa = H − taban,  ayı = L − taban
UO(7,14,28): 100 × (4·BP7 + 2·BP14 + 1·BP28) / 7
VWMA(20) : Σ(C×V,20) / Σ(V,20)
HMA(9)   : WMA( 2·WMA(C,4) − WMA(C,9), 3 )
Ichimoku : (HH(9)+LL(9)+HH(26)+LL(26)) / 4      ← 26 bar KAYDIRILMAZ
```

> **İchimoku tuzağı:** TradingView parametresi (9,26,52,26) olsa da "Ana Hat"
> **9 ve 26'nın ortalamasıdır.** Grafikte 26 bar ileriye kaydırılır;
> **karşılaştırma için kaydırılmamış değer kullanılmalıdır.**

---

## 6. Bileşik Skor ve Sinyal

### 6.1 Hesap

```
osilatör_skoru = 11 osilatör kodunun ortalaması      → −1..+1
ma_skoru       = 15 MA kodunun ortalaması           → −1..+1
bileşik        = 0.50 × osilatör_skoru + 0.50 × ma_skoru
```

### 6.2 Beşli sinyal

| Skor aralığı | Sinyal | Grafik rozet rengi |
|---|---|---|
| `≥ +0,65` | **GÜÇLÜ AL** | koyu yeşil |
| `≥ +0,40` | **AL** | açık yeşil |
| `−0,40 … +0,40` | **NÖTR** | gri |
| `≤ −0,40` | **SAT** | turuncu |
| `≤ −0,65` | **GÜÇLÜ SAT** | kırmızı |

- Eşikler **arayüzden değiştirilebilir** (üst çubukta iki sayı kutusu).
- Doğrulama: `0 < AL/SAT ≤ GÜÇLÜ ≤ 1`. Aksi halde hata göster.
- 26 göstergenin kaçının Al / Nötr / Sat dediği **rozetin yanında** özetlenir
  (ör. "Al 2 · Sat 0 · Nötr 9").

### 6.3 NEDENSELLİK ŞARTI

> Bileşik skor ve sinyaller **ileriye bakmadan** üretilmelidir.
> `signals[i]` **yalnızca i'ye kadar olan mumlara** bakar.
>
> Doğrulama testi: ilk N barı kırp, geri kalanı yeniden hesapla, sonuçlar
> **birebir aynı** olmalıdır. (Bu uygulamada 150/150 kesme testiyle doğrulandı.)
> Bu olmadan geriye dönük test anlamsızlaşır.

---

## 7. Grafik

### 7.1 Zorunlu çizimler

| Öğe | Detay |
|---|---|
| **Mumlar (candlestick)** | yeşil yükselen / kırmızı düşen |
| **Hacim** | alt bölmede, mumla aynı x ekseni, yarı saydam |
| **MA çizgileri** | İç üstteki "Ort. çizgileri" kutusu — EN, SN, İchimoku, VWMA, HMA |
| **Canlı fiyat çizgisi** | sağ kenarda yatay çizgi + etiket |
| **Sinyal yıldızları** | aşağıda |
| **Crosshair + tooltip** | imleç mumun üzerindeyken O/H/L/C + hacim + tarih |

### 7.2 Sinyal yıldızları

- **Yalnızca NÖTR olmayan** sinyaller yıldızlanır.
- Yön: AL/GÜÇLÜ AL → **aşağıdaki mumun altına**, SAT/GÜÇLÜ SAT → **üstüne**.
- Rengi sinyale göre (GÜÇLü varyantları daha koyu/doyu).
- **Minimum 3 bar boşluk:** iki yıldız arasında en az 3 bar olmalı.
  → 500 barda dilim başına ~**51–55 yıldız** çıkar. Fazlası grafik okunmaz olur.
- İnce ayar: yıldızlar ikinci fiyat eksenine değil, **kategori indeksine** bağlanır
  (zaman değerine değil). Kayan/yuvarlanan pencerede kaymaz.

### 7.3 Etkileşim

- Fare tekerleği / pinch → yakınlaştırma
- Sürükle → kaydırma
- Çift tık → sığdır
- **"Sığdır"** düğmesi → son **150 mum** gösterilir
- Grafik canlı akışta **donmadan** 60 fps güncellenmeli

### 7.4 Yaygın grafik kütüphanesi tuzakları

ECharts kullanılırsa:

| Tuzak | Doğru davranış |
|---|---|
| Hazır **yıldız sembolü yok**. `symbol:'star'` sessizce kutuya düşer. | SVG → base64 → `image://` kullan |
| `setOption(opt, true)` (notMerge) **tüm option'ı siler** → `coordinateSystem` hatası | **Her zaman merge** kullan |
| Mum dizisi sırası **OCLH**: `[open, close, low, high]` | Sunucudan gelen `[time, o, h, l, c, v]` |
| `setOption({series:[{data:[sonMum]}]})` → **400 mumu 1'e düşürür** | Tick'te **dizinin tamamını** gönder |

---

## 8. Simülatör — Sanal Cüzdan ve Kaldıraç

### 8.1 Ayarlanabilir parametreler

| Parametre | Varsayılan | Aralık |
|---|---|---|
| Cüzdan bakiyesi | 1.000 USDT | serbest |
| Kaldıraç | **10x** | 1 – 125 |
| Cüzdanın kullanılan kısmı | **%80** | >0 – 100 |
| Komisyon (tek yön) | **%0,05** | 0 – 0,1 |
| Pencere ("en taban/zirve") | **20 bar** | 3 – 200 |
| Min. bekleme (bar) | 0 | 0 – 500 |
| Dönüş teyidi | **KAPALI** | onay kutusu |
| Karar modu | `range` | aşağıda |
| SHORT kuralı | `entry` | aşağıda |

### 8.2 Pozisyon matematiği

```ts
teminat (margin)  = equity × cüzdan_oranı        // %80
pozisyon (notional) = teminat × kaldıraç
miktar (qty)        = pozisyon / fiyat
komisyon_giriş      = pozisyon × komisyon_oranı
likidasyon (LONG)   = giriş × (1 − 1/kaldıraç)
likidasyon (SHORT)  = giriş × (1 + 1/kaldıraç)
```

**Kâr hesabı:**

```ts
brüt  (LONG)  = (çıkış − giriş) × qty
brüt  (SHORT) = (giriş − çıkış) × qty
net            = brüt − komisyon_giriş − komisyon_çıkış
equity         = bakiye + açık_pozisyon_uyumsuz_kâr
```

> **Komisyon iki taraflıdır** ve **açılışta anında bakiyeden düşer.**
> Kâr/zarar **net** olarak raporlanır.

### 8.3 "En taban / zirve" nasıl ölçülür — **EN ÖNEMLİ KURAL**

> Doğrudan eşitlik **çalışmaz.** Mum kapandığında kapanış fiyatı en düşük
> noktadan **zaten ayrılmış** olur. Bu yüzden fiyatın **penceredeki konumu**
> kullanılır:

```
konum = (fiyat − pencerenin_en_düşüğü) / (zirve − dib)     → 0..1
```

| Koşul | Anlamı |
|---|---|
| `konum ≤ %12` | **en taban** → LONG fırsatı |
| `konum ≥ %88` | **zirve / düşüş başlangıcı** → SHORT fırsatı |

- Bu ölçek **bağımsızdır**: BTC, altcoin fark etmez.
- Pencere: son N barın `min(low)` ve `max(high)` değerleri.
- Savunma: `high ≤ 0` veya `high == low` ise **karar verme** (`konum = 0,5`).

### 8.4 Dönüş teyidi — varsayılan KAPALI (ölçümle gerekçelendirildi)

| Koşul | LONG tetiklenme sıklığı |
|---|---|
| Konum **tek başına** | bar başına **%9–19** → 15m'de ~2 saatte bir |
| + yeşil mum teyidi | bar başına **%1,5–4,7** → 4h'de ~**70 saatte** bir |

İkincisi **canlı izlenemeyecek kadar seyrek.** Üstelik "dibi yapan mum"
zaten düşüş yönünde kapanmıştır; yeşil mum beklemek **doğru dönüş noktasını
tamamen geçirir.** Onay kutusuyla açılabilir.

---

## 9. Karar Mekanizmaları — 4 MOD

Mod seçicisi **açık listede**, varsayılan `range`.

### 9.1 `range` — ARA / ZİRVE (varsayılan)

```ts
if (konum ≤ %12) → LONG aç
else if (konum ≥ %88 && SHORT kuralı sağlanıyor) → SHORT aç
```

- **Aksiyon yalnızca pozisyon YOKKEN.**
- Ölçülen: 4h/500 bar → **+%121**

### 9.2 `signal` — GÖSTERGE SİNYALİ (AL ⇄ SHORT)

| Sinyal | Pozisyon | İşlem |
|---|---|---|
| AL / GÜÇLÜ AL | SHORT varsa | SHORT kapat → LONG aç |
| AL / GÖÇLÜ AL | boş | LONG aç |
| SAT / GÜÇLÜ SAT | LONG varsa | LONG kapat → SHORT aç |
| SAT / GÜÇLÜ SAT | boş | SHORT aç |

- **Yalnızca sinyal DEĞİŞTİĞİNDE** işlem yap (her fiyatta değil).
- Min. bekleme süresi dolmamışsa dokunma.
- Ölçülen: 4h/500 bar → **−%5** (komisyon 30–37 işlemi yiyor)

### 9.3 `signal_long` — **SADECE LONG** (kullanıcının isteği)

```ts
if (sinyal == AL  ve pozisyon yok) → LONG aç
if (sinyal == SAT ve pozisyon LONG) → LONG kapat
// SHORT HİÇBİR ZAMAN açılmaz; arada nakitte beklenir
```

- Ölçülen: 4h/500 bar → **+%68**, 18 işlem

### 9.4 `signal_exit` — GİRİŞ ARALIKTAN, ÇIKIŞ SİNYALDEN

```ts
if (konum ≤ %12)                     → LONG aç     (giriş aralıktan)
if (sinyal == SAT ve pozisyon LONG)   → LONG kapat  (çıkış sinyalden)
```

- Ölçülen: 4h/500 bar → **−%25**

> **Sinyal blokları POZİSYON AÇIKKEN çalıştırılır.** Bu kontrol yanlış
> yere yazılırsa (pozisyon-üstü bloğun altına) sinyal bloğuna **hiç
> ulaşılamaz** ve hiçbir sinyal işlenmez. — *Bu, gerçek projede yaşanan bir hatadır.*

---

## 10. SHORT'un Zor Kuralı

Kullanıcının kuralı: **SHORT yalnızca son LONG'un fiyatının altında verilir.**

### 10.1 `entry` (varsayılan)

```ts
if (sonlong_fiyatı == null) → SHORT açma       // referans yok
if (fiyat >= sonlong_fiyatı) → SHORT açma      // LONG fiyatını geçmiş olurdu
if (konum < %88) → SHORT açma                  // zirve bölgesinde değil
→ SHORT aç
```

### 10.2 `pullback` (deneysel)

```ts
if (zirve <= 0) → SHORT açma
if (konum < %88) → SHORT açma
if (fiyat >= zirve × (1 − %0,5)) → SHORT açma  // zirveden henüz çekilmedi
→ SHORT aç
```

### 10.3 Beklenen davranış

- Aralıkta aşağı doğru tepe yapan (lower-high) oluşumlarda SHORT çalışır.
- Daha **yüksek zirve** yapan oluşumlarda yeni SHORT açılmaz (zarardan koruma).
- **İlk LONG'dan önce hiç SHORT açılmaz** (referans yok).

---

## 11. Pozisyon Kapanışı

### 11.1 Hedef — GİRİŞTE DONDURULUR

| Yön | Hedef |
|---|---|
| LONG | giriş anındaki pencerenin **zirvesi** |
| SHORT | giriş anındaki pencerenin **dibi** |

> **NEDEN DONDURULUYOR?** Yuvarlanan (kayan) pencere kullanılırsa girişten
> bir sonraki barda "dibden zirveye" zıplayabiliyor ve **her pozisyon tek
> barda kapanıyordu.** Ölçüldü: 500 barda 15m için 6 işlem — hepsi 1 barda.
> Donmuş hedefle: 500 barda 15m için 17 işlem, bar başına %12–16.

- Hedef giriş fiyatının yanında kalıyorsa kullanılmaz (anlamsız).

### 11.2 Kapanış tetikleyicileri (öncelik sırasıyla)

1. **Likidasyon** — LONG'da `fiyat ≤ lik_fiyatı`, SHORT'da `fiyat ≥ lik_fiyatı`
2. **Hedefe ulaşma** — LONG'da `fiyat ≥ hedef`, SHORT'da `fiyat ≤ hedef`
3. **Sinyal** — yalnız `signal` modunda; açık LONG + SAT sinyali vb.

---

## 12. Trade Başla / Canlı Mod — **İKİ AYRI AKIŞ**

Bu ayrım kritiktir; karıştırılırsa kullanıcı "neden hep eski işlemleri
görüyorum" diye şikâyet eder.

### 12.1 `● Trade Başla` — **YALNIZCA CANLI**

```ts
baslangic_bakiyesi = kullanıcının girdiği USDT   // reset ÖNCESİ saklanır
tüm geçmiş silinir
backtest OYNATILMAZ
başlangıç zamanı damgalanır
→ yalnızca o andan SONRAKİ hareketler sayılır
```

| Alan | Davranış |
|---|---|
| Cüzdan | Girilen USDT'ye sıfırlanır |
| İşlem listesi | Boş başlar, yalnız canlılar dolar |
| Canlı kâr/zarar | **Sıfırdan** takip edilir |
| Önceki backtest kârı | **Görünmez, karışmaz** |

> ⚠️ `reset()` bakiyeyi varsayılana çekerse kullanıcının USDT'si **kaybolur.**
> Başlangıç bakiyesi reset'ten **önce** saklanmalı.

### 12.2 `Geriye dönük test + canlı` — ESKİ AKIŞ

1. Hesap sıfırlanır
2. Grafikteki **500 mum baştan** hızlıca tekrar edilir → "bugüne kadar ne
   kazandı?" ölçülebilir
3. Ardından **canlı akış AYNI hesapla devam eder**

### 12.3 Canlı İşlem Kutusu (ayrı panel)

| Satır | İçerik |
|---|---|
| Canlı kâr/zarar | yalnız canlı işlemlerin **net** toplamı |
| Kapanan işlem | N (kazanç / kayıp) |
| Komisyon | canlı işlemlerin komisyon toplamı |
| Başlangıç | saati |
| Durum | "sinyal bekleniyor…" / "pozisyon açık · LONG" / "canlı işlem kapalı" |

> Panel **yeşil çerçeveli** ve çalışırken vurgulanmalı.

### 12.4 İşlem Listesi

Son 25 işlem, en yenisi üstte:

```
YÖN    GİRİŞ      ÇIKIŞ       NET KÂR    KOMİSYON
LONG·c 84.482,80  86.100,00   +1.234,56  1,6172
LONG·g 71.200,00  69.800,00   -400,00    0,7050
```

`·c` = canlı · `·g` = geçmiş test. Geçmiş satırlar **soluk** gösterilir.

---

## 13. Kaldıraç Çarpanı Doğrulaması (Formül Denetimi)

Test senaryoları — likidasyon fiyatı kaldıraçla **tam orantılı** olmalı:

| Kaldıraç | LONG likidasyon (giriş 100) | SHORT likidasyon |
|---|---|---|
| 1x | 0,00 | 200,00 |
| 2x | 50,00 | 150,00 |
| 10x | **90,00** | **110,00** |
| 25x | 96,00 | 104,00 |
| 125x | 99,20 | 100,80 |

---

## 14. ARAYÜZ DÜZENİ

### 14.1 Masaüstü

```
┌──────────────────────────────────────────────────────────┐
│ [COIN ▾] [15dk|1sa|4sa]  FİYAT  [ROZET]  skor  saat     │
│ GÜÇLÜ eşiği [0,65]  AL/SAT eşiği [0,40] [Uygula]       │
├───────────────────────────────────┬──────────────────────┤
│                                   │  Osilatörler (11)    │
│         MUM GRAFİĞİ               │  ad | değer | durum │
│         (ECharts)                 ├──────────────────────┤
│                                   │  Hareketli Ort. (15) │
│                                   ├──────────────────────┤
├───────────────────────────────────┤  ┌─ CANLI İŞLEM ──┐  │
│ İŞLEM DEĞİŞİM LOGU   ← grafikle  │  │ canlı kâr/zarar │  │
│ aynı genişlikte, sağda boşluk    │  │ işlem / komisyon │  │
│ bırakmadan                        │  │ başlangıç/durum  │  │
│                                   │  └─────────────────┘  │
│                                   │  [Trade Başla][Duraklat][Sıfırla]
│                                   │  [Geriye dönük test + canlı]
│                                   │  ayarlar: bakiye, kaldıraç,
│                                   │  teminat%, komisyon, pencere,
│                                   │  mod, SHORT kuralı, teyit, bekleme
│                                   │  ┌─ açık pozisyon ─┐  │
│                                   │  └─────────────────┘  │
│                                   │  işlem listesi        │
└───────────────────────────────────┴──────────────────────┘
```

> **Log, grafikle aynı genişlikte olmalı ve sağında boşluk bırakmamalı.**
> (Eski tasarımda log tam genişlikteydi ve sağında kullanılmayan alan
> kalıyordu — bu düzeltildi.)

### 14.2 Mobil (≤760 px) — **TEK SÜTUN**

Yatay düzen telefonda çalışmaz (sağ sütun 430 px sabit, grafik ~100 px'e
sıkışır). Düzen:

```
┌──────────────────────┐
│ üst bar (2 satır)   │
├──────────────────────┤
│ GRAFİK   (46vh)     │
├──────────────────────┤
│ LOG      (max 34vh) │
├──────────────────────┤
│ CANLI İŞLEM kutusu   │
├──────────────────────┤
│ düğmeler             │
├──────────────────────┤
│ ayarlar              │
├──────────────────────┤
│ osilatör / MA tabloları│
├──────────────────────┤
│ açık pozisyon        │
├──────────────────────┤
│ işlem listesi        │
└──────────────────────┘
```

- Sayfa **kendi kaydırılır** (`body { overflow: visible }`).
- Buton yüksekliği ≥ **44 px** (parmak hedefi).
- Notch için `viewport-fit=cover` + `env(safe-area-inset-*)`.
- Dokunulduğunda mavi parlama olmasın (`touch-action: manipulation`).

### 14.3 Log paneli

- Her satır: `saat · düzey · metin`
- Düzey renkleri: bilgi gri, başarı yeşil, uyarı sarı, hata kırmızı
- **Sayfa her açıldığında son 40 satır** yüklenir (panel boş kalmaz)
- **Sinyal satırı örneği:**
  ```
  19:59:28 ★ SAT [4h] NÖTR → SAT  |  skor -0.545  |  fiyat 83.706,60
  ```
- Maks. **2000** satır; yeni satırda otomatik kaydır (kullanıcı yukarı
  kaydırmışsa **kaydırma**.

---

## 15. Sunucu / Zamanlama Davranışı (WebSocket Modülasyonu)

Sistem arka planda bir **WebSocket ile tarayıcıya** bağlıdır.

### 15.1 Sunucu → İstemci mesajları

| Tip | Ne zaman | İçerik |
|---|---|---|
| `hello` | bağlantı açılışı | sembol, sembol listesi, dilimler, DB sayaçları |
| `snapshot` | bağlantı + dilim/sembol değişimi | **500 mum + MA dizileri + yıldızlar + 26 gösterge + skorlar** (~76 KB) |
| `tick` | her fiyat değişiminde | son mum + canlı fiyat + anlık sinyal |
| `wallet` | ~1 sn'de bir | **tüm** cüzdan durumu |
| `log` | olay anında | zaman damgası + düzey + metin |
| `timeframe_ack` | dilim değişikliği onayı | yeni dilim |

### 15.2 İstemci → Sunucu mesajları

```json
{"type":"set_timeframe","tf":"4h"}
{"type":"set_symbol","symbol":"ETHUSDT"}
{"type":"set_thresholds","strong":0.65,"base":0.40}
{"type":"refresh"}
```

### 15.3 ZORUNLU TASARIM KURALLARI

| Kural | Neden |
|---|---|
| **Tick'te mum dizisinin TAMAMINI gönder.** | Tek eleman göndermek 500 mumu 1'e düşürüyor |
| **Her istemcinin kendi seçili dilimi olsun.** | Dilimi göndermeyen istemci yanlış dilimi gösterir (tuzak) |
| **Snapshot/tick yalnız o dilimi gösterene gitsin.** | 3 dilim açık olsa saniyede 3×76 KB gereksiz |
| **`setOption` her zaman merge.** | notMerge `coordinateSystem` hatası verir |

---

## 16. Hata Yakalama ve Boş Durumlar

| Durum | Gösterim |
|---|---|
| WebSocket kapalı | Üst çubukta kırmızı "bağlantı yok"; otomatik yeniden deneniyor |
| Sembol geçişi sürüyor | Yükleme göstergesi; boş panel **değil** |
| <60 bar veri | Analiz çalıştırılamaz: "yetersiz veri (N/60)" |
| Grafik boş | Boş bir "yükleniyor" iskeleti, **hiçbir şey göstermemek değil** |
| Sunucu çöktü | Açılışta **tekrar bağlanma** (exponential backoff, üst sınır 30 sn) |

---

## 17. Testler — Kabul Kriterleri

### 17.1 Zorunlu birim testleri

| # | Test | Beklenen |
|---|---|---|
| 1 | Bileşik skor nedenselliği | İlk N barı kes → sonuçlar birebir aynı |
| 2 | %80 teminat | `margin == equity × 0.8` (float toleranslı) |
| 3 | Çift taraflı komisyon | Açılışta ve kapanışta **iki kez** düşülmeli |
| 4 | Likidasyon orantısı | Yukarıdaki 14. tablo |
| 5 | SHORT kuralı | SHORT açılan her işlemde `entry < son LONG fiyatı` |
| 6 | Hedef dondurma | Pozisyon açık kaldığı sürece hedef **değişmez** |
| 7 | `low=0` onarımı | Onarım sonrası `high ≥ low > 0` |
| 8 | Bozuk fiyat filtresi | 0 / 13,11 elenir; 2.499 / 2.530 geçer |
| 9 | Canlı/geri ayrımı | Backtest kârı canlı kârda **görünmez** |
| 10 | Bakiye koruma | "Trade Başla" girilen USDT'yi **kaybetmez** |
| 11 | Sembol sıfırlama | Sembol değişince pozisyon/işlem/buzuk-fiyat referansı sıfırlanır |
| 12 | Yıldız aralığı | Ardışık yıldızlar arası ≥ 3 bar |

### 17.2 Manuel doğrulama

1. Sembol değiştir → mumlar yeniden yüklenir, yıldızlar temizlenir
2. Dilim değiştir → grafik + tablo + yıldızlar birlikte değişir
3. "Trade Başla" → bakiye girilen tutar, işlem listesi **boş**, canlı kâr `0`
4. Kural tetiklenince → log satırı + pozisyon kutusu güncellenir
5. Hedef/ likidasyon → pozisyon kapanır, net kâr listeye düşer
6. Telefonda → tek sütun düzen, düğmeler parmakla tıklanabilir

---

## 18. ÖLÇÜLMÜŞ REFERANS SONUÇLAR

> ⚠️ **Tek bir 500 barlık örneklemden alınmıştır. Aşırı uyum (overfitting)
> riski yüksektir — kalıcı kârlılık kanıtı DEĞİLDİR.**
> Karşılaştırma tabanı: BTCUSDT, 4h, 500 bar, 1.000 USDT, 10x, %80 teminat, %0,05 komisyon.

### 18.1 Mod karşılaştırması

| Dilim | Mod | İşlem | Kazanç | Kayıp | Net | Getiri |
|---|---|---|---|---|---|---|
| **4h** | **aralık (varsayılan)** | 3 | 0 | 3 | +1.216,26 | **+%121,6** |
| 4h | aralık + pullback | 2 | 0 | 2 | +638 | +%64 |
| 4h | **sinyal_long** | 18 | — | — | +677,61 | **+%68** |
| 4h | sinyal | 18 | 13 | 31 | −180 | −%5,1 |
| 4h | sinyal_exit | — | — | — | −252,18 | −%25 |
| 1h | aralık | 0 | 0 | 0 | +4,00 | −%100 |
| 1h | sinyal | 18 | 19 | 37 | −641 | — |
| 15m | aralık | 6 | 8 | 35 | +295,77 | — |
| 15m | sinyal | 17 | 18 | 35 | −54 | — |

> **1h ve 15m'de hiçbir mod kalıcı kârlı değildir.**
> 4h varsayılanı +%121 ölçümü **tek örneklemden** gelmektedir.

### 18.2 Sinyal dağılımı (4h / 500 bar)

```
NÖTR 338  ·  AL 123  ·  SAT 39
```

### 18.3 "Trade Başla" (canlı mod) ölçümü

4h / 500 bar / 1.000 USDT / 10x:
```
açık LONG @ 83.706,60   (−173 zararda, hedef 86.976)
```

---

## 19. TUZAKLAR — BU UYGULAMADA GERÇEKTEN YAŞANANLAR

Bu bölüm **en değerli** kısımdır: bunlar geliştirme sırasında saatler
kaybettiren, ölçülmüş gerçek hatalardır.

| # | Tuzak | Sonuç | Çözüm |
|---|---|---|---|
| 1 | Kline'da `low=0` | Y ekseni 0'a uzar, tüm göstergeler bozulur, simülatör **anında sahte LONG açıp kapatır** | Kaynakta onar (Bölüm 3.1) |
| 2 | `@trade` akışında **%8 bozuk mesaj** | Log'da "ETH için fiyat 13,11" görünür; kullanıcı **hata sanır** | Son geçerli fiyata karşı %25 sapma filtresi (Bölüm 3.2) |
| 3 | `setOption(opt, true)` | Tüm grafik option'ı silinir, `coordinateSystem` hatası | Her zaman merge |
| 4 | Tick'te tek mum göndermek | 400 mum 1'e düşer, grafik boşalır | Dizinin tamamını gönder |
| 5 | İstemci dilimi sunucuya bildirmiyor | WebSocket ve REST arasında iki istek araya girince **yanlış dilim** test edilir | Dilimi **açıkça** gönder |
| 6 | Periyodik cüzdan mesajı seçicileri **eziyor** | Kullanıcı saniyede bir seçimini kaybeder | "Kullanıcı dokundu" bayrağı |
| 7 | Sinyal bloğu **pozisyon açıkken** hiç çalışmıyordu | Hiçbir sinyal işlenmiyordu | Sinyal bloğunu pozisyon-açık koluna taşı |
| 8 | Yuvarlanan pencere hedefi | **Her pozisyon tek barda** kapanıyordu (15m/500'de 6 işlem, hepsi 1 barda) | Hedefi girişte dondur |
| 9 | ECharts'ta `symbol:'star'` yok | Yıldızlar sessizce **kutuya** dönüyor | SVG → base64 → `image://` |
| 10 | Mum dizisi sırası | Grafik ters görünüyor | Sunucu `[t,o,h,l,c,v]`, grafik kütüphanesi `[o,c,l,h]` |

---

## 20. KAPSAM DIŞI — YAPILMAYACAK

| Öğe | Neden |
|---|---|
| ❌ **Gerçek emir gönderme** | Kapsam dışı. Borsa hesabı, API anahtarı, para riski yok |
| ❌ Kimlik doğrulama / kullanıcı hesabı | Tek kullanıcı, yerel uygulama |
| ❌ Sunucu tarafı veritabanı | Cihazda `localStorage`/`IndexedDB` yeterli |
| ❌ Bildirim (push) | Kapsam dışı |
| ❌ Portföy / varlık takibi | Sadece BTC vb. parite fiyatları |

---

## 21. Uygulama Sırası (Önerilen)

| Adım | İçerik | Bağımlılık |
|---|---|---|
| 1 | Veri katmanı: REST + WebSocket + **bozuk veri filtreleri** | — |
| 2 | Gösterge motoru (26 gösterge, Bölüm 5) | 1 |
| 3 | Bileşik skor + 5'li sinyal + **nedensellik testi** | 2 |
| 4 | Grafik: mum + hacim + MA + yıldızlar + crosshair | 3 |
| 5 | Arayüz: üst bar, tablolar, log | 4 |
| 6 | Sembol + dilim seçimi | 5 |
| 7 | **Simülatör çekirdeği** (cüzdan, kaldıraç, komisyon, likidasyon) | — |
| 8 | 4 karar modu | 7 |
| 9 | "Trade Başla" canlı mod + canlı kâr paneli | 7, 8 |
| 10 | Geriye dönük test | 7, 8 |
| 11 | **Mobil düzen** (tek sütun) | 5, 9 |
| 12 | Android paketleme (Capacitor) | 11 |

> **Sıra önemlidir:** 7. adım (simülatör) 4'ten bağımsızdır ve paralel
> yapılabilir. Ancak 2-3. adımlar **mutlaka** 1'e bağlıdır; bozuk veri
> filtresi olmadan üzerine hiçbir şey inşa edilmemelidir.

---

## 22. Teslim Kontrol Listesi

- [ ] Bozuk mum (`low=0`) onarımı çalışıyor
- [ ] Bozuk işlem fiyatı filtresi çalışıyor, log'a düşürüyor
- [ ] Sembol değişiminde `lastGoodPrice` sıfırlanıyor
- [ ] 26 gösterge hesaplanıyor, her biri Al/Nötr/Sat veriyor
- [ ] Bileşik skor nedensel (kesme testi geçiyor)
- [ ] Beşli sinyal doğru renklerle gösteriliyor
- [ ] Grafikte MA çizgileri + yıldızlar + hacim var
- [ ] Yıldızlar arası ≥ 3 bar boşluk var
- [ ] Dilim değişince grafik + tablo + yıldız birlikte değişiyor
- [ ] 10 coin seçilebiliyor
- [ ] Cüzdan, kaldıraç, komisyon, likidasyon doğru hesaplanıyor
- [ ] 4 mod çalışıyor
- [ ] "Trade Başla" geçmiş test oynatmıyor
- [ ] Canlı kâr paneli ayrı ve doğru
- [ ] Log, grafikle aynı genişlikte
- [ ] Telefonda tek sütun düzen çalışıyor
- [ ] Log sayfa açılışında son 40 satırı yüklüyor
- [ ] WebSocket kopunca otomatik yeniden bağlanıyor
- [ ] Gerçek emir gönderme **yok**

---

<div align="center">

**Şartname sonu.** Bölüm 19 (Tuzaklar) ve Bölüm 18 (Ölçümler) uygulama
sırasında referans alınsın.

</div>