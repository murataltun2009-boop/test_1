# GÖSTERGE ARAŞTIRMASI — ÖLÇÜM RAPORU

**Tarih:** 2026-10-18
**Araçlar:** `tools/research_indicators.py`, `tools/validate_combo.py`, `tools/validate_honest.py`
**Veri:** 18 coin × 3 zaman dilimi (15m/1h/4h) × 500 bar = **27.000 bar**

> ## ⚠️ ANA SONUÇ
>
> **Hiçbir gösterge grubu, uygulanabilir bir avantaj göstermedi.**
> Ham ölçümde kârlı görünen kombinasyonlar, bağımsız doğrulamada
> çöktü. Bu raporun tamamı **olumsuz sonucu** belgeliyor.

---

## 1. Yöntem ve ilk hata

İlk ölçüm **ham edge** (sinyal yönüne göre ileri getiri) ile yapıldı.
Sonuç: `RSI(14) +%1,04` ile birinci sırada çıktı.

**Bu yanlıştı.** Teşhis: test döneminde piyasa yükseliyordu
(8-bar ileri getiri +%0,42) ve RSI düşüşte "AL" diyerek yükselen
piyasada doğru çıkıyordu. Ölçtüğüm şey göstergenin gücü değil,
**piyasa yönü + göstergenin o yonda olması** idi.

### Düzeltme: Bilgi Katsayısı (IC)

```
IC = ortalama( sinyal_i × işaret(fiyat_i) )
```

IC, göstergenin piyasadan **bağımsız** bilgi taşıyıp taşımadığını
ölçer. −1..+1; 0 = bilgi yok.

---

## 2. Tek gösterge sonuçları (IC, 9 kırılım: 3 dilim × 3 ufuk)

En sağlam göstergeler **9 testin kaçında pozitif**:

| Gösterge | Pozitif | Ortalama IC | Değerlendirme |
|---|---|---|---|
| **Williams %R** | **8/9** | **+0,051** | En tutarlı |
| **ADX(14)** | **8/9** | **+0,049** | En tutarlı |
| Boğa Ayı Gücü | 6/9 | +0,033 | Zayıf |
| EMA(200) | 4/9 | +0,006 | Tutarsız |
| SMA(200) | 4/9 | +0,002 | Tutarsız |
| **Nihai Osilatör** | 4/9 | **−0,107** | **En kötü** |
| MACD(12,26) | — | −0,001 | Rastgele |

> **Nihai Osilatör** IC −0,107 ile en kötü. Mevcut sistemde 11
> osilatörden biri olarak kullanılıyor.

> **MA'ların çoğu negatif IC.** "Fiyat MA'nın üstündeyse AL" kuralı
> 8 bar sonra fiyatı ters yönde hareket ettiriyor (kısa vadeli
> momentum tersine dönüyor). Bu, mevcut `ma_only` modunun
> zararla bitmesini açıklıyor.

---

## 3. Korelasyon

| İkili | Uyum | Ortak bar |
|---|---|---|
| RSI(14) ↔ CCI(20) | %100 | 2.060 |
| RSI(14) ↔ EMA(20) | %100 | 2.060 |
| CCI(20) ↔ EMA(20) | %100 | 6.415 |
| CCI(20) ↔ Williams %R | **%1,4** | 1.021 |
| Williams %R ↔ MACD | **%10,8** | 3.357 |

**Yorum:** MA grubu (12 gösterge) neredeyse tek ses — birbirinin
yerine geçiyor, birlikte kullanmanın anlamı yok. Williams %R ise
MA grubuyla **neredeyse hiç örtüşmüyor** — bu yüzden tek başına
katkı sağlıyor.

---

## 4. Kombinasyon araması — AŞIRI UYUM TESPİT EDİLDİ

Greedy ileri seçim (in-sample %70, hedef maks |IC|):

| Adım | Küme | IC (IS) |
|---|---|---|
| 1 | EMA(10) | 0,0811 |
| 2 | + SMA(200) | 0,1159 |
| 3 | + RSI(14) | 0,1163 |
| 7 | + 4 gösterge daha | 0,1097 |

**Out-of-sample doğrulama (son %30):**

| Küme | IC (IS) | IC (OOS) |
|---|---|---|
| greedy ilk 3 | −0,1163 | **−0,0295** |
| greedy ilk 5 | −0,1145 | −0,0221 |
| tek: ADX(14) | +0,0560 | **+0,0486** |
| tek: Williams %R | +0,0478 | **+0,0401** |

> **Klasik aşırı uyum.** Greedy seçimi IS'te 3× iyileştiriyor,
> OOS'ta **yok oluyor**. Aynı şekilde **işaret değişiyor**
> (pozitiften negatife).

---

## 5. Gerçek trade doğrulaması (asıl test)

Williams %R + ADX, mevcut simülatörle 18 coin'de backtest edildi
(1.000 USDT, 10x, %80 teminat, %0,05 komisyon):

| Kural | İşlem | Kaz/Kay | Net |
|---|---|---|---|
| Williams %R **tek** | 636 | 385/251 | **−578,47** |
| Williams %R + ADX>20 | 401 | — | +10.022,93 |
| **Williams %R + ADX>25** | 272 | 171/101 | **+20.790,41** |
| Williams %R + ADX>30 | 166 | — | +8.984,77 |

Mevcut kurallarla aynı veride:

| Kural | İşlem | Net |
|---|---|---|
| range (varsayılan) | 139 | −3.418,84 |
| ma_only | 5.734 | −35.036,96 |
| osc_only | 3.904 | −38.946,71 |

> Görünürde `+20.790` — 18.000 USDT yatırıma karşı **%115**.

### AMA: Kırpma testi bunu çürüttü

| Ölçüt | Sonuç |
|---|---|
| Toplam net | +20.790,41 |
| **Medyan coin** | **−407,47** |
| Kazanan coin | **8 / 18** |
| En iyi 4 coinin payı | **+%40.000 (toplamdan fazla)** |

Coin bazında:

```
XMRUSDT    +15238,71   (14 islem)   ← tek basina toplamin %73'u
NEARUSDT    +9658,56   (17 islem)
ATOMUSDT    +6007,80   (18 islem)
APTUSDT     +2412,38   (18 islem)
BTCUSDT      +864,45   (12 islem)
...
SUIUSDT    -2259,59   (15 islem)
LINKUSDT   -1988,78   (13 islem)
XRPUSDT    -1885,70   (13 islem)
```

> **Medyan coin para kaybediyor.** Kâr, 4 şanslı coinden geliyor.
> 10 coin zararda. Bu bir strateji değil, varyanstır.

---

## 6. Zaman bölmesi

| Veri aralığı | İşlem | Net |
|---|---|---|
| İlk %50 | 106 | +11.391,76 |
| Son %50 | 141 | +1.771,71 |

Her iki yarı da pozitif ama **OOS %84 daha düşük**. Zamanla zayıflıyor.

## 7. Zaman dilimi

| Dilim | İşlem | Net |
|---|---|---|
| 15m | 79 | **−2.078,59** |
| 1h | 87 | +3.536,11 |
| 4h | 106 | +19.332,89 |

> Kâr **tamamen 4h'den** geliyor. 15m zarar.

---

## 8. Ölçüm sırasında bulunan hatalar

Araştırma kendi hatalarını da ortaya çıkardı — ikisi de ciddiydi:

1. **`adx_trend` eşiği yok sayıyordu.** Parametre geçiliyor ama
   fonksiyon içinde 25'e sabitlenmişti. "ADX filtresi YOK" varyantı
   bile 25 filtresi uyguluyordu → 4 varyantın tamamı aynı sonucu
   veriyordu (20.790).

2. **"İlk %50" aslında tüm veriydi.** Bölme `0.0` idi ve
   `mum[0:]` demekti. Zaman bölmesi testi geçersizdi.

> Bu iki hata olmadan sonuç "temiz" görünüyordu. **Doğrulama
> adımı atlanırsa araştırma kendini doğruluyor.**

---

## 9. Sonuç

| Soru | Cevap |
|---|---|
| En iyi tek gösterge hangisi? | **Williams %R** (IC +0,051, 8/9 pozitif) |
| İkinci? | **ADX(14)** (IC +0,049, 8/9 pozitif) |
| En kötü? | **Nihai Osilatör** (IC −0,107) |
| Hangi kombinasyon en çok kâr yapar? | **Hiçbiri, güvenilir biçimde** |
| Mevcut sistemde değiştirilmeli mi? | **Aşağıdaki notlara bak** |

### Uygulama için dürüst öneri

1. **`osc_only` ve `ma_only` modlarında kazanç beklentisi yok.**
   Ölçümde ikisi de net zararla bitti (−38.946 ve −35.036).
   Ana kural (`range`) daha iyi (−3.418).

2. **Williams %R ve ADX, mevcut sistemde zaten var.** Bileşik skora
   katılıyor. Ayrı bir kural olarak eklemek **doğrulanmış bir
   avantaj sağlamıyor** — ölçüm bunu göstermedi.

3. **Nihai Osilatör zararlı katkı yapıyor.** Bileşik skordan
   çıkarılması düşünülebilir, ama bunu da doğrulamak gerekir.

---

## 10. Uyarılar

- **Tek dönem, tek veri.** 500 bar × 18 coin, ~3 ay. Kripto bir
  yıl içinde tamamen karakter değiştirebilir.
- **18 coin küçük örneklem.** 36 coin'lik liste genişletildikten
  sonra yazıldı; daha geniş test gerekebilir.
- **Komisyon %0,05 varsayıldı.** Gerçek VIP oranları daha düşük.
- **10x kaldıraç.** Likidasyon riski kâr hesabına girmiyor.
- **Bu bir finans tavsiyesi değildir.** Ölçüm, kâr garantisi değildir.

---

## 11. Yeniden çalıştırma

```bash
python tools/research_indicators.py --collect   # veriyi indir
python tools/research_indicators.py --report    # IC + korelasyon
python tools/validate_combo.py                  # trade kuralı testi
python tools/validate_honest.py                 # bağımsız doğrulama
```

Araçlar kalıcıdır; coin listesi değişirse `research_indicators.py`
içindeki `COINLER` listesini güncelleyin.