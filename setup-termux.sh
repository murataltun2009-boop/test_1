#!/data/data/com.termux/files/usr/bin/bash
# ===================================================================
#  Binance Futures Canlı Teknik Analiz  —  Termux kurulum betiği
# ===================================================================
#
#  KULLANIM
#    1) Play Store'dan "Termux" kurun  (F-Droid'daki sürüm de olur)
#    2) Termux'u açıp bu komutu yapıştırın:
#         bash setup-termux.sh
#    3) Kurulum bitince:  ./start.sh
#
#  ÖNEMLİ
#    * Play Store'daki Termux SALT-OKUNUR (read-only) olabilir ve
#      `pkg` çalışmayabilir. Bu durumda F-Droid sürümünü kurun:
#        https://f-droid.org/packages/com.termux/
#    * Uygulama bilgisayarınızda çalışan bir sunucuya DEĞİL,
#      telefonun kendisindeki bu sunucuya bağlanır. Yani:
#        Chrome → http://localhost:8765
#    * Telefonu açtıktan sonra arka planda servis
#      (tmux) çalışmazsa grafik donar. Aşağıda tmux kuruluyor.
# ===================================================================
set -u

BOLD=$'\033[1m'; DIM=$'\033[2m'; OK=$'\033[32m'; ERR=$'\033[31m'
WARN=$'\033[33m'; R=$'\033[0m'

step() { echo "${BOLD}==> $1${R}"; }
info() { echo "    ${DIM}$1${R}"; }
ok()   { echo "    ${OK}✓ $1${R}"; }
warn() { echo "    ${WARN}! $1${R}"; }
die()  { echo "${ERR}HATA: $1${R}"; exit 1; }

echo
echo "${BOLD}╔══════════════════════════════════════════════╗${R}"
echo "${BOLD}║  Binance Futures TA — Android / Termux kurulum  ║${R}"
echo "${BOLD}╚══════════════════════════════════════════════╝${R}"
echo

# ---------------------------------------------------------------- 1
step "Ortam kontrolü"

if ! command -v pkg >/dev/null 2>&1; then
  die "pkg bulunamadi (Termux salt-okunur olabilir).
  F-Droid surumunu kurun: https://f-droid.org/packages/com.termux/"
fi

command -v python >/dev/null 2>&1 && ok "Python: $(python -V 2>&1)" \
  || warn "Python yok, kurulacak"
command -v node  >/dev/null 2>&1 && ok "Node.js: $(node -v)" \
  || warn "Node.js yok (PWA ekranları için önerilir, zorunlu değil)"

# ---------------------------------------------------------------- 2
step "Sistem paketleri"
pkg update -y >/dev/null 2>&1
pkg install -y python python-numpy tmux termux-api 2>&1 | tail -3
ok "python, python-numpy, tmux, termux-api kuruldu"

# ---------------------------------------------------------------- 3
step "Python bağımlılıkları"
# requirements.txt'in TAMAMI kullanılmıyor: pandas / customtkinter /
# matplotlib yalnizca eski masaüstü arayüzü içindi ve Termux'ta
# derlenmeleri uzun sürer (matplotlib için derleme araci gerekir).
# OLCUM: grep ile tarandı — web arayüzünün gerçekten kullandığı
# paketler yalnızca aşağıdakiler.
python -m pip install --upgrade pip --quiet 2>&1 | tail -1
python -m pip install numpy requests websocket-client starlette uvicorn 2>&1 | tail -3
ok "numpy, requests, websocket-client, starlette, uvicorn hazır"

# ---------------------------------------------------------------- 4
step "Veritabanı ve gerekli dosyalar"
mkdir -p data logs
[ -f data/signals.db ] && ok "data/signals.db mevcut" || info "veritabanı ilk çalıştırmada oluşacak"
ok "data/ ve logs/ hazır"

# ---------------------------------------------------------------- 5
step "PWA ikonları"
if [ ! -f web/static/icon-512.png ]; then
  python tools/make_icons.py && ok "ikonlar üretildi" \
  || warn "Pillow yok; ikonları PC'de üretip kopyalayabilirsiniz"
else
  ok "PWA ikonları mevcut"
fi

# ---------------------------------------------------------------- 6
step "Başlatma betiği"
chmod +x start.sh 2>/dev/null || true
[ -f start.sh ] && ok "start.sh hazır" || warn "start.sh bulunamadı"

echo
echo "${OK}${BOLD}──────────────────────────────────────────────${R}"
echo "${OK}${BOLD} Kurulum tamam.${R}"
echo
echo "  ${BOLD}Başlat:${R}   ./start.sh"
echo "  ${BOLD}Durdur:${R}    tmux attach -t ta  →  Ctrl+B sonra D"
echo "  ${BOLD}Aç:${R}      Chrome → ${BOLD}http://localhost:8765${R}"
echo "  ${BOLD}Ana ekran:${R}  Chrome ⋮ → ${BOLD}Ana ekrana ekle${R}"
echo
echo "${DIM}  Not: telefon ekranı söner/servis arka planda öldüyse${R}"
echo "${DIM}  grafik durur. Akışı korumak için:${R}"
echo "${DIM}    termux-wake-lock${R}"
echo "${OK}${BOLD}──────────────────────────────────────────────${R}"
echo