# BTCUSDT — Canlı Teknik Analiz

Binance **Futures**'tan (`fapi.binance.com`) anlık BTCUSDT verisi çeken,
TradingView'in "Technicals" mantığını uygulayan **web tabanlı** canlı analiz
aracı.

**Üç zaman dilimi: 15 dakika · 1 saat · 4 saat.** Üstteki düğmelerden seçim
yapılır; **grafik, gösterge değerleri ve AL/SAT yıldızları seçilen dilime
göre yeniden hesaplanır.** Ayrıca **coin seçimi** (10 parite) ve **kaldıraç
simülatörü** vardır. Grafik tarayıcıda çizilir, her işlem anında ekrana
yansır.

```
┌──────────────────────────────────────────────┬─────────────┐
│ BTC/USDT  15dk 1sa 4sa   82.543,10  [NÖTR]   │             │
├──────────────────────────────────────────────┤ Osilatörler │
│                                              │  11 satır   │
│              GRAFİK (log da aynı genişlikte) ├─────────────┤
│                                              │ Hareketli O.│
│                                              │  15 satır   │
│                                              ├─────────────┤
├──────────────────────────────────────────────┤ SANAL CÜZDAN│
│  İşlem Değişim Logu          anlık tik: 140 │  + kaldıraç │
│                                              │  simülatörü │
└──────────────────────────────────────────────┴─────────────┘
```

```
┌──────────────���───────────────────────────────────┐
│  BTCUSDT  82.543,10  [NÖTR]   00:09:14           │  başlık + kontroller
├──────────────────────────────────────┬───────────┤
│                                      │ Osilatörler│
│   mum grafiği + ortalamalar          │  11 satır │
│   + yıldız işaretleri                ├───────────┤
│   + sarı canlı fiyat çizgisi         │ Hareketli │
│                                      │ ortalama  │
│   hacim + bileşik skor şeridi        │  15 satır │
├──────────────────────────────────────┴───────────┤
│  İşlem Değişim Logu        anlık tik: 140 · 0,1 sn │
└──────────────────────────────────────────────────┘
```

---

## Kurulum ve çalıştırma

```bash
pip install -r requirements.txt
python main.py
```

Sunucu `http://127.0.0.1:8765` adresinde açılır ve tarayıcı otomatik gelir.

| Komut | Sonuç |
|---|---|
| `python main.py` | sunucuyu başlatır, tarayıcıyı açar |
| `python main.py --port 9000` | başka port |
| `python main.py --no-browser` | tarayıcıyı otomatik açmaz |
| `python main_desktop.py` | eski masaüstü (Tkinter) arayüzü |

---

## Android'e kurma (Termux + PWA)

Uygulama bir web arayüzü; bu yüzden APK yerine **PWA** (ana ekrana
yüklenebilen web uygulaması) kullanılıyor. Sunucu **telefonun kendisinde**
(Termux) çalışır, arayüz telefondaki Chrome ile ona bağlanır.

### 1. Termux kur

Play Store'daki Termux sürümü genellikle **salt-okunur** ve `pkg`
çalışmaz. Bu durumda F-Droid sürümünü kullan:

- <https://f-droid.org/packages/com.termux/>

### 2. Betiği çalıştır

Telefonda proje klasöründe (GitHub'dan indirip açtıysanız burada):

```bash
bash setup-termux.sh
```

Betik `python`, `numpy`, `starlette`, `uvicorn`, `websockets` ve `tmux`
kurulmasını otomatik yapar.

### 3. Başlat

```bash
./start.sh          # tmux oturumunda arka planda
./start.sh log      # günlüğü izle
./start.sh durdur   # durdur
```

`tmux` kullanılmasının sebebi: Android ekranı kapandığında Termux arka
plan sürecini öldürür ve grafik donar. tmux oturumu bunu önler, geri
bağlanmak için `tmux attach -t ta`.

### 4. Ana ekrana ekle

1. Termux'u arka planda açık bırakın
2. Chrome'da `http://localhost:8765` adresini açın
3. **⋮ → Ana ekrana ekle (Add to Home screen)**

Artık uygulama tam ekran, adı **"TA Futures"**, ikonu candlestick
şeklinde. Durum çubuğu ve adres çubuğu gizlenir.

### Notlar

- **Ekran sönerken akış durur.** `termux-wake-lock` ile önlenir
  (kurulum betiği `start.sh` içinde çağırır).
- **Pil:** arka planda sürekli WebSocket + analama çalışır, pil yer.
  Simülatörü durdurup sadece grafiği izleyebilirsiniz.
- Sunucu `127.0.0.1` üzerinden dinler (sadece o telefon erişir). Telefonu
  `--host 0.0.0.0` ile dışarıya açarsanız aynı Wi-Fi'daki herkes
  bağlanabilir — **sanal cüzdan olsa da dikkat edin.**
- PWA çevrimdışı çalışmaz (canlı veri çeker), ama arayüz önbelleğe
  alındığı için açılış hızlıdır.

### Gerçek APK istenirse

PWA Chrome'da "Ana ekrana ekle" ile aynı deneyimi verir. Dağıtılabilir
tek dosyalık `.apk` gerekirse bu proje bir WebView sarmalayıcıyla
(Bubblewrap / Trusted Web Activity) sarılabilir; PWA manifest'i ve
ikonları zaten hazır. Android SDK + Gradle kurulumu gerekir
(~1-2 GB), bu yüzden varsayılan olarak yapılmadı.

---

## Neden web arayüzüne geçildi

Kullanıcı "anlık durum anlık grafiğe çizilsin" diye istedi. Masaüstü sürümde
ölçülen tablo şuydu:

| İşlem | Süre |
|---|---|
| matplotlib Agg çizimi (806×406 grafik) | **~400–500 ms** |
| matplotlib Tk blit'i | ~11 ms |
| `analyze()` (500 bar) | ~55 ms |

Çizim maliyeti **görünüm alanıyla orantılı** (~0,9 µs/piksel). Yani grafik ne
kadar büyükse arayüz o kadar kasılıyor; mumlar saniyede birkaç kez gelse bile
arada "donma" oluyordu.

Web arayüzünde çizim tarayıcının canvas'ında yapılır: güncelleme maliyeti
ağ gecikmesinden gelir, piksel işleminden değil. Sonuç:

- Her işlem (~4,5 msg/sn) doğrudan ekrana düşer.
- Yıldız işaretleri için gerçek bir `star` sembolü kullanılabilir (matplotlib
  için ayrı çizim katmanı gerekirdi).
- Çapraz çizgi ve tooltip tarayıcının kendi canvas'ı sayesinde akıcı.
- Yakınlaştırma/kaydırma/sığdırma hazır geliyor, ayrı kod gerekmiyor.

---

## Zaman dilimleri

**`15m` · `1h` · `4h` · `1d`** — üstteki düğmelerden seçilir. Seçim değiştiğinde:

1. Grafik anında boşaltılır (eski dilimin mumları yanlış bilgi vermesin).
2. Sunucuya `set_timeframe` gönderilir; istemci o dilimin anlık görüntüsünü
   ister.
3. O dilimin gösterge tablosu, bileşik skoru ve **AL/SAT yıldızları** o
   dilime göre yeniden hesaplanır ve gelir.

Ölçülen sonuç (500 mum/dilim):

| Dilim | Tarih aralığı | AL yıldız | SAT yıldız | Bileşik skor |
|---|---|---|---|---|
| **15m** | 5 gün | 18 | 33 | −0,354 |
| **1h** | 17 gün | 23 | 29 | −0,345 |
| **4h** | 67 gün | 42 | 13 | −0,345 |

Aynı anda açık olan 500 barın oluşan (kapanmamış) barı her üç dilimde de
canlı işlemlerle güncellenir; bar açılış zamanı kendi dilimine göre hizalıdır
(ölçüldü: 15m → 22:00, 1h → 22:00, 4h → 20:00 UTC).

### Arka planda üç dilim aynı anda çalışır

Trade akışı **tek** bağlantıdır ve her işlem üç kovaya birden yazılır
(`core/service.py` → `_ws_loop`). Bu, mumun sıfırdan kurulması anlamına
gelir: kline akışı bu ağda sessiz olduğu için zaten bu yol kullanılıyordu.

`analyze()` 500 bar için **~55 ms** sürer. Üç dilimi de 0,5 sn'de bir
çalıştırmak tek çekirdeğin üçte birini sürekli yiyordu. Bu yüzden:

- **Odaktaki dilim** (kullanıcının baktığı) her 0,5 sn'de hesaplanır.
- **Diğer dilimler** 4 kat seyrek (`config.BACKGROUND_REFRESH_FACTOR`).

Ölçülen CPU: 4 çekirdekli makinede ~%6 (0,24 çekirdek).

Sunucu ayrıca her istemcinin hangi dilime baktığını bilir; 76 KB'lık anlık
görüntü ve tikler **yalnızca o dilimi gosteren istemciye** gönderilir. Üçü bir
den açıksa bile trafik üç katına çıkmaz.

---

## Coin seçimi

Üst soldaki açılır listeden 10 parite seçilebilir (`config.SYMBOLS`):
BTC, ETH, SOL, BNB, XRP, DOGE, ADA, AVAX, LINK, DOT.

Sembol değişince servis **sıfırdan kurulur**: yeni istemci oluşturulur,
eski tamponlar/analizler atılır, 3 dilimin mum geçmişi (~1 sn/dilim) yeniden
çekilir. Simülatör de sıfırlanır (yeni coin, yeni cüzdan).

Geçersiz bir sembol seçilirse sunucu önce Binance'e sorar; hata varsa
listeden **geri alınır** ve log'a yazılır.

---

## Kaldıraç simülatörü (sanal cüzdan)

> **Bu bir eğitim aracıdır.** Gerçek emir gönderilmez, borsa hesabı
> açılmaz, API anahtarı kullanılmaz. Yalnızca oluşan mumlardan karar verip
> sanal bir cüzdan tutulur (`core/paper.py`).

Sağ paneldeki **Sanal Cüzdan & Kaldıraç** kutusu; **▶ Simülatörü Başlat**
düğmesiyle çalışır. Cüzdan saniyede bir güncellenir (açık pozisyonun
kâr/zararı her işlemle değişir).

### "Grafiğin başından başlat" — geriye dönük test

Simülatörü başlatırken **Grafiğin başından başlat** kutusu işaretliyse
(varsayılan) hesap **grafikteki ilk mumdan başlar**:

1. Cüzdan başlangıç değerine sıfırlanır.
2. 500 mum tek tek canlandırılır (her mumun kapanışında karar verilir).
3. Hesap **bugünkü** bakiyeye gelir: *"bugüne kadar ne kazanırdı?"* ölçülmüş
   olur.
4. Aynı hesap **canlı akışla devam eder**; açık kalan pozisyon canlı
   yönetilir.

Cüzdan kutusunda geçmiş testin özeti çıkar (işlem sayısı, brüt, komisyon,
bugünkü bakiye, net kâr ve yüzde). İşlem listesinde geçmiş işlemler soluk
ve `LONG·g` / `SHORT·g` ile, canlı işlemler `·c` ile işaretlenir.

**Ölçülen sonuçlar** (1.000 USDT, x10, %80 teminat, %0,05 komisyon,
500 mum, canlı veri):

| Dilim | Tarih aralığı | İşlem | Net | Bugünkü bakiye |
|---|---|---|---|---|
| **15m** | 05.10 → 10.10 | 0 tamamlanan (LONG açık) | **−244,64** | 996,00 |
| **1h** | 20.09 → 10.10 | 0 tamamlanan (LONG açık) | **−104,08** | 996,00 |
| **4h** | 22.07 → 10.10 | 3 (3 kazanç) | **+1.204,17** | 2.386,37 |

Süre: **1–9 ms**. Aynı veri iki kez koşturulunca aynı sonucu verir
(deterministik, test edildi).

> **Bu tek yönlü bir tektardır.** Her mumun kapanışında karar verilir; mum
> içi fiyat hareketi simüle edilmez, gerçek emir kaydı yoktur, slippage ve
> fonlama (funding) maliyeti yoktur. Sonuçlar gerçek getiri değildir.
> Dikkat çeken nokta: 500 mumluk örneklemde **4h kârlı, 15m ve 1h zararlı**
> çıktı — aynı kural farklı dilimlerde tamamen farklı sonuç veriyor.

### Kurallar (doğrudan kullanıcı tanımından)

| Kural | Uygulama |
|---|---|
| **LONG** | fiyat **grafiğin en taban noktasında** alınır |
| **SHORT** | fiyat **düşüş eğilimine girdiği noktada** (pencere zirvesi) verilir, **ama en son LONG fiyatını geçmemek zorundadır** |
| **Teminat** | cüzdanın **%80'i** (ayarlanabilir) |
| **Kaldıraç** | 1–125x (varsayılan 10x) |
| **Komisyon** | Binance Futures taker %0,05; hem girişte hem çıkışta düşülür |

### Karar mekanizması: aralık ↔ sinyal

> **Varsayılan onaylı sürümdür.** Aşağıdaki "Sinyal" modu ve "tepeden
> geri çekilme" kuralı **deneyseldir, ölçümde daha kötü çıkmıştır** ve
> kapalıdır. Varsayılanlarla 4h'de ölçülen sonuç **+%121**.

| Mod | Kararı ne verir | 4h ölçümü |
|---|---|---|
| **Aralık** (varsayılan) | fiyat pencerenin tabanında LONG; SHORT yalnızca son LONG'un altındaysa | **+1.212,92 (+%121)** — açık LONG @83.706,60 (−173 zararla) |
| **Sadece LONG** | AL sinyaliyle girer, SAT sinyaliyle **kapanır**, arada nakitte bekler. **SHORT açılmaz.** | +677,61 (+%68) — açık pozisyon yok |
| Aralık + sinyal çıkış | giriş aralık kuralı, çıkış SAT sinyali | −252,18 (−%25) |
| Sinyal | AL ↔ SHORT dönüşümlü | −46,13 (−%5) |

### MURO algoritması — yeni (deneysel, ölçülmüş)

> Kullanıcı isteği: *"En iyi long ve short noktalarını yakalayan algoritma;
> long en dipten tespit etsin; long'daki kazancı kaybetmeden short'a geçsin
> (%3 kazanç sağladıkça cüzdana atsın, yeniden long'a girsin); short'a zarar
> ederek girmesin."*

MURO modu bunu üç parçayla yapar (tamamı `core/muro.py`):

| Parça | Ne yapar |
|---|---|
| **Yön** | Supertrend(10, 3) — 1 günlük dilimde ölçüldü |
| **Giriş** | Yön uyumluyken fiyat **EMA50'ye geri çekilip geri alınır** → long dibte, short tepede açılır. Kırılım barında girilmez (en kötü fiyat). 20 barlık bekleme ile tekrarlar engellenir. |
| **Kâr kilitleme** | Fiyat **%1** kâra ulaşınca pozisyon kapanır, kâr **cüzdana yazılır** ve **aynı yönde yeniden** pozisyon açılır (stop = kilit seviyesi). Kâr trend dönse bile cüzdanda kalır. |

Ölçüm (25 coin, 1 gün, komisyon + kayma + funding dahil, 3,3 yıl):

| Set | medyan | kazanan coin | med. DD | PF |
|---|---|---|---|---|
| Seçim (10 coin) | **+%47,6** | %90 | %29,2 | 1,52 |
| Holdout (15 coin) | **+%118,6** | %93 | %25,4 | 2,18 |
| Seçim — son 500 bar | +%14,5 | %90 | %11,9 | 1,98 |
| Holdout — son 500 bar | +%4,7 | %60 | %13,7 | 1,39 |

**Kaldıraç gerçeği:** MURO **risk bazlı** boyutlandırma kullanır (varsayılan
işlem başına %2). Ekranda "efektif kaldıraç" ~1,3x görünür. Sabit 20x
kaldıraçla test: **hesap −%99,9** (likidasyon). 10x/20x burada **üst
sınırdır**, kullanılan değil.

**Kâr kilitleme mesafesi kritik:** ölçüldü — %0,8 → +%94, **%1 → +%75**,
%1,5 → +%40, %2 → +%6, **%3 → −%5 (negatif)**, %5 → −%15. Kullanıcının
örneği olan %3 bu stratejide işe yaramıyor; varsayılan **%1**'dir.

Ayrıntılı ölçüm, duyarlılık analizi ve sınırlar:
**[ALGORITMA_ARASTIRMASI.md](ALGORITMA_ARASTIRMASI.md)**

### Canlı sorun: "LONG/SHORT arası defalarca işlem" (düzeltildi)

Kullanıcı canlı log raporladı: HYPE/USDT'de Supertrend modunda long açtı,
kâr yapmaya başladı; düşünce **long↔short geçişi arasında defalarca
pozisyon açıp kapattı, tüm kâr ve fazlası komisyona gitti** (10 saniyede
4 işlem).

**Üç kök neden bulundu ve düzeltildi:**

| Sorun | Düzeltme |
|---|---|
| Sinyal **oluşan (kapanmamış) bardan** hesaplanıyordu → Supertrend yönü bar içinde tik tik değişiyor, simülatör saniyede pozisyon değiştiriyordu | Sinyal artık **yalnızca kapanmış barlardan** üretilir (`core/paper.py::_kapali_mumlar`) |
| **Stop sonrası aynı sinyalle anında yeniden giriş** (stop avcısı döngüsü) → BTC 1g'de 33 yerine **171 işlem** | Stop/likidasyon sonrası sinyal temizlenmiyor: sinyal değişmedikçe pozisyon yeniden açılmaz |
| Likidasyon stop'tan önce kontrol ediliyordu, gap durumunda likidasyon fiyatı uygulanmıyordu | Sıra düzeltildi: **stop önce**, gap liq (likidasyon fiyatında) |

Ek olarak **pozisyon değişiminde 5 dakika bekleme** var
(`PAPER_FLIP_COOLDOWN_SEC`): yön değişiminden sonra yeni pozisyon açılmaz,
süre sonunda **sinyal yeniden değerlendirilir** (yön neyse o açılır).

Canlı benzetimi (400 tick): **51 olay → 2 olay**, bakiye kaybı
**−%31 → −%0,4**. Regresyon testi: `test_paper.py` → *"CANLI: yön titremesi yok"*.

### 2. tur şikâyetler ve çözümleri

| Şikâyet | Çözüm |
|---|---|
| Coin değişiminde "Bozuk işlem atlandı" hataları **devamlı** | Eski WS akışı yeni coinin mumlarına yazıyordu. Akış artık sembolünü etiketliyor (eskisi sessizce düşürülüyor), sapma büyükse REST referansına bakılıyor, log 30 sn'de bir yazılıyor. |
| "Kâr kilitleme çalışmıyor" | Kilit zaten **pozisyonun kendi kârına** bakıyordu; asıl sorun **stop sonrası yeni pozisyonun hiç açılmamasıydı** (bayat sinyal). Artık stop sonrası aynı yöne girmeden önce fiyat **stop seviyesini geri almalı (reclaim)** → yeni pozisyon açılır ve kendi +%3'ünde kilitlenir. |
| "1 dakikalık işlem listesi" | `1m` dilimi eklendi (`15m`'nin yanına, "1dk" düğmesi). |
| "Tepede long / dipte short açmasın, ilk pozisyon kararlı olsun" | **Optimum nokta filtresi** (long için zirveye, short için dibe ATR cinsinden yakınken girilmez) + **GÜÇLÜ AL/SAT varsa filtre atlanır** (güçlü sinyalde hemen girilir). Ölçümde 1g'de sonucu düşürdüğü için **varsayılan kapalı**, arayüzden açılabilir. |

### Trend modu (Supertrend) — düzeltmelerden sonraki ölçüm

1 gün dilimi, risk %5, app'in kendi backtest motoru:

| Kâr kilitleme | Seçim (10 coin) | Holdout (15 coin) | 500 bar (seçim/holdout) | İşlem |
|---|---|---|---|---|
| **%0 (kapalı)** | **+%24,5** (%90 poz.) | **+%31,7** (%87) | +%11,1 / +%7,2 | 350 |
| %3 (kullanıcı isteği) | −%10,4 (%0) | +%3,9 | +%3,6 / +%2,2 | 2.287 |

**Dürüst not:** kâr kilitleme kuralı **uygulandı** (fiyat %3 → pozisyon
durdurulur, kâr cüzdana yazılır, 1-2 dk beklenir, pozisyon yeniden
değerlendirilir — her iki yönde de). Ama trend modunda **sonucu düşürüyor**:
Supertrend günler boyunca pozisyon taşır, %3'te kârı kesip yeniden girmek
"kazananı sat, kaybedeni tut" olur; işlem sayısı 6,5 katına çıkıp komisyon
kârı götürür. Bu yüzden arayüzdeki **"Kâr kilitleme (%)"** alanı trend
modunda **0 yapılabilir** (ölçülen en iyi). MURO modunda kâr kilitleme
zaten var ve ölçülmüş durumda (%1 → seçim +%47,6 · holdout +%118,6).

### "Sadece LONG" modu — kullanıcı isteği

Sorun: aralık modunda açılan LONG hedefe (86.976) ulaşamayınca açık kalıyor ve
zarar ediyordu. Bu modda **SAT sinyali gelir gelmez LONG kapanır**, sonra
**AL sinyali gelene kadar nakitte beklenir**. Hiçbir zaman SHORT açılmaz.

Dört modun 4h / 500 mum karşılaştırması:

| Mod | LONG | SHORT | Komisyon | Net | Açık pozisyon |
|---|---|---|---|---|---|
| aralık (varsayılan) | 3 | 0 | 46,75 | **+1.212,92** | LONG @83.706,60 (acık −173) |
| **sadece LONG** | 18 | 0 | 175,15 | +677,61 | **yok** |
| aralık + sinyal çıkış | 12 | 0 | 92,87 | −252,18 | yok |
| sinyal | 19 | 11 | 250,69 | −46,13 | SHORT |

**Dürüst okuma:** "sadece LONG" asılı zarardaki pozisyonu **ortadan
kaldırıyor** (+%121'in içindeki −173 gidiyor) ama toplam düşüyor: 3 işlem
yerine 18 işlem, komisyon 46 → 175. Yani **sorununuz çözülüyor, net sonuç
küçülüyor.**

"İstediğiniz davranış açılır listeden **Sadece LONG** seçilerek kullanılabilir;
varsayılan onaylı sürümde kalındı."

### Arayüz tuzağı: periyodik güncelleme seçimi eziyordu

Cüzdan durumu saniyede bir geliyor. Bu mesaj, kullanıcı açılır listeden
mod seçerken **seçimi geri alıyordu** (testte görüldü: `signal_long`
seçildi, 3 saniye sonra `signal` olmuş). Çözüm: kullanıcı bir ayara
dokunduysa (`userTouched`) sunucudan gelen değerler o alanı artık
**ezmiyor**.

Sinyal modunda aynı sinyal tekrarlanırsa yeni işlem açılmaz; yalnızca
**sinyal değiştiğinde** aksiyon alınır.

**Ölçüm (500 mum, 1.000 USDT, x10, %80, %0,05):**

| Dilim | Mod | LONG | SHORT | İşlem | Komisyon | Net |
|---|---|---|---|---|---|---|
| 15m | aralık | 0 | 0 | 0 | 4,00 | −217 |
| 15m | **sinyal** | 17 | 18 | 35 | 295,77 | −54 |
| 1h | aralık | 0 | 0 | 0 | 4,00 | −100 |
| 1h | **sinyal** | 18 | 19 | 37 | 184,70 | −641 |
| 4h | **aralık (varsayılan)** | 3 | 0 | 3 | 46,75 | **+1.216,26 (+%121,6)** |
| 4h | aralık + pullback | 2 | 0 | 2 | 28,98 | +638 (+%64) |
| 4h | **sinyal** | 18 | 13 | 31 | 225,81 | −180 |

Sinyal modu **istendiği gibi çalışıyor** (LONG kapanıp SHORT açılıyor), ama
bu örneklemde komisyonu yiyor: 30-37 işlem × çift taraflı komisyon.
"Minimum bekleme (bar)" ayarı eklendi; 4h'de 20 bar beklemeyle +%928'e
çıktı — **ama bu tek örneklemde seçilmiş bir sayıdır (aşırı uyum) ve
15m/1h'de hiçbir değerde kârlı sonuç vermedi.** Varsayılan yapılmadı.

### Geriye dönük testte sinyal nasıl elde ediliyor?

`analyze()` **tek çağrıyla** tüm geçmişin bar başına sinyalini üretiyor
(`TimeframeAnalysis.signals`). Bu dizi **nedenseldir**: `signals[i]` yalnızca
*i*'ye kadar olan mumlara bakar. 150/150 kesme testiyle doğrulandı (ileriye
bakma yok).

### "En taban noktası" nasıl ölçülüyor?

Doğrudan eşitlik **çalışmaz**: mum kapandığında kapanış fiyatı en düşük
noktadan zaten ayrılmış olur. Bu yüzden fiyatın **penceredeki konumu**
kullanılır:

```
konum = (fiyat − pencerenin en düşüğü) / (zirve − dib)
```

`konum ≤ %12` → "en taban" (LONG), `konum ≥ %88` → "zirve / düşüş başlangıcı"
(SHORT). Bu ölçek bağımsızdır; dolar, jcoin fark etmez.

**Dönüş teyidi varsayılan KAPALI.** Ölçüm (BTC, 500 bar):

| Koşul | LONG tetiklenme sıklığı |
|---|---|
| Konum tek başına | bar başına **%9–19** (15m'de ~2 saatte bir) |
| + "yeşil mum" teyidi | bar başına **%1,5–4,7** (4h'de ~70 saatte bir) |

İkincisi canlı izlenemeyecek kadar seyrek; üstelik "dibi yapan mum" zaten
düşüş yönünde kapanmıştır. Onay kutusuyla açılabilir.

### Pozisyon kapanışı

Kapanış **girişte dondurulan** pencere ucuna göre yapılır:

- LONG → giriş anındaki pencerenin **zirvesi** (hedef)
- SHORT → giriş anındaki pencerenin **dibi** (hedef)

> Neden donduruluyor? Yuvaralanan pencere kullanılırsa girişten bir sonraki
> barda "dibden zirveye" zıplayabiliyor ve her pozisyon **tek barda**
> kapanıyordu. Ölçüldü: 500 barda 15m için 6 işlem, hepsi 1 barda.

Ayrıca **likidasyon** vardır: kaldıraç 10x ise fiyat %10 ters yönde gidince
teminat biter. Likidasyon fiyatı `giriş × (1 ∓ 1/kaldıraç)`.

### SHORT'un zor kuralı

Kuralınız gereği SHORT yalnızca **en son LONG fiyatının altında** verilir.
Pratik sonucu: fiyat bir LONG'dan sonra zirve yapıyorsa ve zirve LONG'un
üstündeyse SHORT **verilmez** — zarar etmemek için. Böylece:

- Aralıkta aşağı doğru tepe yapan (lower-high) oluşumlarda SHORT çalışır.
- Daha yüksek zirve yapan oluşumlarda yeni SHORT açılmaz.
- İlk LONG'dan önce hiç SHORT açılmaz (referans yok).

### Tarihsel tekrar ölçümü

`python test_paper.py` içindeki 3 backtest testi: özet doğruluğu, canlı
devamlılık (`mode=live`) ve deterministiklik. Gerçek veriyle ölçüm için
`PaperTrader.backtest(candles, tf)` doğrudan çağrılabilir.

### İş parçacığı güvenliği

Simülatör iki yerden beslenir:

- **analiz döngüsü** (servis thread'i) → `on_price()`
- **başlatma isteği** (web thread'i) → `backtest()`

İkisi **aynı nesne** üzerinde yazdığı için `PaperTrader` içinde bir
`RLock` var. Kilit olmadan geriye dönük test canlı hesabın ortasında
koşunca pozisyon kaybolur / bakiye yanlış artar.

### Dilim sıralaması tuzağı

Dilim değişimi **WebSocket**, simülatör başlatma **REST** ile gelir. İkisi
araya girerse sunucu **yanlış dilimin geçmişini** test eder (tarayıcıda
"bir adım geriden gitti" ölçüldü). Çözüm: istemci dilimi istek gövdesinde
`timeframe` alanıyla açıkça gönderir, sunucu `active_timeframe`'e
güvenmez.

---

## Grafik etkileşimi

| Hareket | Sonuç |
|---|---|
| **Fare tekerleği** | imlecin altındaki bar sabit kalacak şekilde yakınlaştırma |
| **Sol tuşla sürükleme** | grafiği kaydırma (geçmişe doğru) |
| **Alt kısımdaki kaydırıcı** | görünür aralığı sürükleme / boyutlandırma |
| **Sığdır** düğmesi | son 150 barı göster |
| **Fare grafiğin üzerinde** | çapraz çizgi + o mumun tarih/fiyat/hacim bilgisi |
| **Ort. çizgileri** anahtarı | EMA/SMA/Hull/VWMA çizgilerini gizler |
| **Sinyal yıldızları** anahtarı | yıldız işaretlerini gizler |

Eksen etiketi yakınlaştırmaya uyar: 90 bardan fazlası görünüyorken
`15.09.26`, azaldığında `15.09 23:00` biçiminde gün **ve saat** gösterilir.

---

## Anlık veri hattı

### Kline yerine işlem (trade) akışı

Bu, ölçümle gerekçelendirilmiş bir tasarım kararıdır. İlk sürümde canlı
mumlar `@kline_4h` WebSocket akışından geliyordu. Bu makinede ölçüldü:

| Akış | 20–30 saniyede gelen mesaj |
|---|---|
| `@kline_4h` | **0** |
| `@kline_1m` | **0** |
| `@aggTrade` | **0** |
| `@miniTicker` | **0** |
| `@trade` | **91** (4,5 msg/sn) |

WebSocket el sıkışması başarılı oluyor (`101 Switching Protocols`), sonra
**hiç kare gelmiyor**. Kline akışı bu ortamda tamamen sessiz. Bu,
"realtime göstermiyor" şikâyetinin gerçek sebebiydi — veri hattı değil, akış
seçimi.

Çözüm: **oluşan mum trade akışından kendimiz kuruluyor.** Her işlem için
fiyat / yüksek / düşük / hacim güncellenerek son barın değerleri yeniden
üretiliyor (`core/service.py` → `_ws_loop`). Bu yol her ağda çalışır.

### "Saat 23.00 görünüyor" meselesi

X eksenindeki saat **barın açılış saatidir**, güncel saat değildir. Saat
23:30'da sağ uçta görünen 23:00 barı 23:00–03:00 aralığını kapsayan oluşan
bardır; etiketi doğrudur, veri sapması yoktur. Kullanıcının istediği şey
o barın **içeriğinin anlık değişmesi**ydi ve bu artık çalışıyor.

Doğrulama (canlı, 20 saniyelik ölçüm):

```
t= 0  tik 198  son mum kapanış 82.526,20   başlık 82.526,20
t= 5  tik 230  son mum kapanış 82.535,90   başlık 82.540,80
t= 6  tik 605  son mum kapanış 82.540,70   başlık 82.540,70
t= 7  tik 649  son mum kapanış 82.538,90   başlık 82.538,90
     mum sayısı sabit: 400
```

---

## Sinyal mantığı

TradingView'in "İşlem detayı" sütunu **tek tip bir kural değildir.** Verdiğiniz
örnek bunu gösteriyor:

| Gösterge | Değer | TradingView | Eğer sabit seviye kuralı olsaydı |
|---|---|---|---|
| RSI (14) | 68,92 | Nötr | Nötr ✔ (70'e uğramadı) |
| Stokastik %K | 99,09 | **Nötr** | Sat olurdu ✘ |
| CCI (20) | 211,69 | Sat | Sat ✔ (≥100) |
| ADX (14) | 34,86 | **Nötr** | — |
| Müthiş Osilatör | 71,74 | **Nötr** | Al olurdu ✘ |
| MACD Seviyesi | 50,64 | **Sat** | Al olurdu ✘ (MACD > 0) |
| Williams %R | 0,00 | **Nötr** | Sat olurdu ✘ |
| Momentum (10) | 86,40 | Al | Al ✔ |

Yani bir kısmı **seviye** kuralı (RSI, CCI, Momentum, UO), bir kısmı
**kesişim** kuralıdır (Stokastik, AO, Stoch RSI, Williams %R, ADX) ve MACD
satırı **sinyal çizgisine göre konum**dur.

Bu yüzden `core/analysis.py` her osilatör için tek bir kural satırı içerir:

| Osilatör | Kural |
|---|---|
| RSI(14) | seviye: ≥70 Sat, ≤30 Al |
| Stokastik %K(14,3,3) | %K'nın %D'yi kesmesi |
| CCI(20) | seviye: ≥100 Sat, ≤−100 Al |
| ADX(14) | 25 eşiğini aşması / altına inmesi |
| Müthiş Osilatör | sıfırın üstüne çıkması / altına inmesi |
| Momentum(10) | işaret (pozitif Al, negatif Sat) |
| MACD Seviyesi | MACD çizgisi sinyal çizgisinin üstünde/altında |
| Stokastik RSI Hızlı | %K'nın %D'yi kesmesi |
| Williams %R(14) | −80'in üstüne çıkış / −20'nin altına iniş |
| Boğa Ayı Gücü | boğa gücünün 0'ı aşması / ayı gücünün 0 altına inmesi |
| UO(7,14,28) | seviye: ≥70 Sat, ≤30 Al |

Hareketli ortalamalarda fiyat MA'nın üstündeyse **Al**, altındaysa **Sat**.
Fiyat tam çizginin üzerinde zıplamasın diye küçük bir ölü bölge var (%0,02).

**İchimoku Ana Hattı** için bu ölü bölge daha geniş (%0,25): TradingView bu
satırı bulut (senkou) mantığıyla yorumlar, doğrudan fiyat karşılaştırması
aynı sonucu vermez.

### Bileşik skor

```
osilatör_skoru = (al − sat) / osilatör sayısı       → −1..+1
ort_skoru      = (al − sat) / hareketli ort. sayısı → −1..+1
bileşik        = 0,50 × osilatör + 0,50 × hareketli ort.
```

| Bileşik skor | Sinyal |
|---|---|
| ≥ +0,65 | **GÜÇLÜ AL** |
| ≥ +0,40 | **AL** |
| ≤ −0,65 | **GÜÇLÜ SAT** |
| ≤ −0,40 | **SAT** |
| arası | **NÖTR** |

Eşikler arayüzden değiştirilebilir (`1 GÜÇLÜ eşiği` / `2 AL/SAT eşiği`
alanları + **Uygula**). Alt paneldeki bileşik skor çizgisinde eşik çizgileri
görünür; güçlü sinyaller **büyük yıldız**, zayıf sinyaller küçük yıldızdır.

---

## Yıldız işaretleri

**Yıldızlar sürdüğü her barda değil, sinyalin ilk ortaya çıktığı barda
işaretlenir.** Arada en az 3 bar boşluk bırakılır (`MARKER_MIN_GAP`).
Sonuç 400 barda dilim başına:

| Dilim | AL | SAT | toplam |
|---|---|---|---|
| 15m | 18 | 33 | 51 |
| 1h | 23 | 29 | 52 |
| 4h | 42 | 13 | 55 |

> **Bulunan tuzak:** ECharts'te hazır bir `star` sembolü **yoktur**.
> `symbol: "star"` yazılınca sessizce kutuya düşer ve ekranda hiçbir şey
> görünmez. Gerçek yıldız `image://data:image/svg+xml;base64,…` ile
> `web/static/app.js` içinde üretiliyor.

> **Kategori ekseni tuzağı:** yıldızlar `scatter` serisidir ve kategori
> ekseninde çalışırlar; x koordinatı **zaman değil, kategori indeksi**
> olmak zorundadır. Zaman damgası verilince yıldız sessizce hiç çizilmez.

---

## ECharts tuzakları (bu projede canlıdan ölçüldü)

`web/static/app.js` başlığında da not düşülü. Kısaca:

1. **Hazır `star` sembolü yok** → `image://` + base64 SVG.
2. **`setOption(opt, true)` (notMerge) tüm option'ı siler.** Sadece
   `xAxis`+`series` gönderildiğinde `grid`/`yAxis`/`dataZoom` kayboluyor ve
   ECharts `Cannot read properties of undefined (reading 'coordinateSystem')`
   veriyor. Her zaman **merge** kullanılır.
3. **Mum dizisi OCLH'dir**: `[açılış, kapanış, en düşük, en yüksek]`. Sunucu
   ise `[zaman, açılış, en yüksek, en düşük, kapanış, hacim]` gönderir. Bu
   yanlış çeviride hacim "en yüksek" sayılıyor ve Y ekseni 0–120.000 çıkıyor.
4. **`setOption({series:[{data:[…]}]})` serinin tamamını değiştirir.** Sadece
   son mumu tazelemek için tek eleman göndermek 400 mumu tek muma düşürüyor
   ve grafik boş kalıyor. Tick anında dizinin tamamı gönderilir.
5. **`markLine.data` ilk anda boş olmalı.** `{yAxis: null}` yazmak ECharts'i
   kırıyor.
6. **JS zincirleme karşılaştırma `0 < b < 1` şeklinde yazılamaz** —
   `(0 < b) < 1` olarak hesaplanır ve her değeri reddeder. `&&` ile ayrı
   yazılmalı.

---

## Veritabanı

SQLite: `data/signals.db`

- **`signal_events`** — her sinyal değişiminde bir satır: zaman damgası,
  sembol, dilim, sinyal, önceki sinyal, bileşik skor, fiyat, osilatör/MA
  skorları, Al/Sat/Nötr sayıları ve o anki **tüm gösterge değerlerinin
  JSON'u**.
- **`app_log`** — sistem ve sinyal logları.

**DB Sıfırla** düğmesi her iki tabloyu da boşaltır (onay ister, geri
alınamaz). Sağ üstteki sayaç güncel kayıt sayısını ve dosya boyutunu gösterir.

Sayfa her açıldığında son 40 log satırı veritabanından okunup panele
yazılır; log paneli uygulama yeniden başlatılana kadar boş kalmaz.

---

## Dosya yapısı

```
main.py                     giriş noktası (web) + port bulucu + loglama
main_desktop.py             eski masaüstü (Tkinter) arayüzü girişi
config.py                   ayarlar (sembol, dilim, eşikler, zamanlama)
core/
  binance_client.py         REST (klines, fiyat) + WebSocket işlem akışı
  indicators.py             tüm göstergeler, saf numpy
  analysis.py               TradingView yorum kuralları + bileşik skor
  service.py                arka plan servisi: veri → analiz → log/DB
  store.py                  SQLite kayıt + sıfırlama + son loglar
  paper.py                  kaldıraç simülatörü (sanal cüzdan, komisyon, PnL)
  trend.py                  Supertrend tabanlı trend modu (1g önerilir)
  muro.py                   MURO algoritması (kâr kilitleme + geri çekilme)
web/
  server.py                 Starlette uygulaması, WebSocket yayını, REST uçları
  static/
    index.html              sayfa iskeleti + görünür JS hata yakalayıcı
    app.js                  ECharts grafiği, tablolar, log, kontroller
    style.css               koyu tema (+ mobil düzen @media)
    sw.js                   PWA service worker (canlı veriyi cache'LEMEZ)
    manifest.webmanifest    PWA tanımı (ana ekran adı, ikon, tema)
    icon-192/512.png        PWA ikonları (tools/make_icons.py üretir)
    icon-maskable-512.png   Android 8+ maskeli ikon
    vendor/echarts.min.js   yerel kopya (internet gerekmez)
ui/                         masaüstü sürümünün Tkinter arayüzü (opsiyonel)
tools/
  make_icons.py            PWA ikonlarını Pillow ile üretir
  check_sh.py              Termux betiklerinin yapısal kontrolü
  research_algo.py         algoritma araştırması (indirme, fold, holdout)
  research_muro.py         MURO araştırması (araması, holdout, duyarlılık)
ALGORITMA_ARASTIRMASI.md    MURO ölçüm raporu (yöntem, sonuçlar, sınırlar)
GOSTERGE_ARASTIRMASI.md    gösterge seçimi araştırması (IC, yöntem)
setup-termux.sh            Android kurulum betiği (pkg/pip otomatik)
start.sh                   sunucuyu tmux'ta başlatır/durdurur
selftest.py                 grafiksiz çekirdek doğrulama (canlı veriyle)
smoke_test.py               masaüstü arayüz testleri
```

## Testler

```bash
python selftest.py       # 4h canlı veri, gösterge tabloları, DB yaz/sıfırla
python test_paper.py     # kaldıraç simülatörü + MURO (71 test, ağ bağımsız)
python tools/check_sh.py # Termux betikleri (shebang/CRLF/blok dengesi)
```

Simülatör testleri kuralın her dalını ölçer: taban/zirve tetikleme, %80
teminat, iki taraflı komisyon, SHORT'un LONG fiyatını geçmemesi, likidasyon
fiyatının kaldıraçla orantısı, coin değişiminde sıfırlama — ve dört
regresyon testi: **Binance'in `low=0` gönderdiği bozuk mum**, **akıştaki
bozuk işlem fiyatları (13,11)**, ve **"Trade Başla"nın geçmiş test kârını
canlı kâra karıştırmaması**.

---

## Bulunan iki gerçek hata: Binance `low=0` ve akıştaki bozuk işlemler

### 1. Kline mumunda `low=0`

Canlı akışta ölçüldü: yeni açılan oluşan mumda Binance arada

```
ac=82790.0   yis=82795.2   dus=0.0   kap=0.0
```

gönderiyor. Bu mum tüm zinciri bozuyordu: Y ekseni 0'a doğru uzar, RSI/CCI/MACD
bozulur, "fiyat pencerenin en tabanında" testi `konum = (fiyat−0)/(zirve−0) ≈ %100`
hesaplayıp **simülatör anında sahte LONG açıp kapatır**.

Mum kaynakta onarılır (`candle_from_payload`): geçersiz fiyat açılışa sabitlenir,
yüksek/düşük tutarlılığı yeniden kurulur, artık bozuk kalan mumlar düşürülür.

### 2. `@trade` akışı bozuk işlemler gönderiyor (logdaki "fiyat 13,11")

Kullanıcı ETHUSDT seçtiğinde logda **fiyatı 13,11** olan (ETH için imkânsız)
sinyal satırları gördü. Ölçüm:

```
150 sn ETHUSDT @trade izlemesi
  toplam islem : 1579 (10,5 msg/sn)
  bozuk islem  : 12        ← fiyat=0.0, qty=0.0
```

**Mesajların ~%8'i bozuk.** Daha önce sadece `price <= 0` eleniyordu; sizin
gördüğünüz **13,11** ise o filtrenin geçtiği daha ince bir bozulma.

Bunlar mumun kapanışına yazıldığında: Y ekseni ve tüm göstergeler bozulur,
"pencere tabanında" kuralı anlık tetiklenir, log'a imkânsız satırlar yazılır.

**Çözüm:** her işlem son geçerli fiyata karşı kontrol edilir
(`config.TRADE_PRICE_SANITY = %25`); sapması büyük olan reddedilir ve log'a
düşürülür. Sembol değişiminde referans fiyat sıfırlanır. İki regresyon testi
eklendi (bozuk fiyat elenir / geçerli fiyat elenmez).

Web arayüzü tarayıcıda elle doğrulanır: `python main.py` → tarayıcı açılır.
Sağ altta `anlık tik: N · son tik X sn önce` sayacı canlı akışın çalıştığını
gösterir.

---

## Uyarı

Bu bir **eğitim ve gözlem** aracıdır; emir göndermez, pozisyon açmaz.
Gösterge gecikmeleri ve veri kalitesi nedeniyle üretilen sinyaller
yatırım tavsiyesi değildir. Yüksek kaldıraçlı vadeli işlem ciddi para
kaybına yol açabilir.