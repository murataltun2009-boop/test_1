#!/data/data/com.termux/files/usr/bin/bash
# ===================================================================
#  Analiz sunucusunu başlatır (Termux / Android).
# ===================================================================
#
#  Kullanım:
#     ./start.sh              → tmux oturumunda arka planda çalıştır
#     ./start.sh onermesi     → tmux olmadan bu ekranda çalıştır
#     ./start.sh log          → tmux günlüğünü ekrana bas
#     ./start.sh durdur       → oturumu kapat
#
#  NEDEN tmux: Android ekranı kapandığında Termux arka plan
#  sürecini öldürür ve grafik donar. tmux oturumu bunu önler;
#  telefonu yeniden açtığınızda "tmux attach -t ta" ile geri
#  bağlanırsınız.
# ===================================================================
set -u

OTURUM="ta"
DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="${PORT:-8765}"

cd "$DIR" || { echo "HATA: dizin bulunamadı"; exit 1; }

# Ekran sönerken işlemci uykuya girsin diye.
command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock 2>/dev/null

case "${1:-}" in
  durdur)
    tmux kill-session -t "$OTURUM" 2>/dev/null \
      && echo "Durduruldu." || echo "Çalışan oturum yok."
    exit 0
    ;;
  log)
    tmux capture-pane -pt "$OTURUM" 2>/dev/null \
      || echo "Oturum yok. Önce ./start.sh çalıştırın."
    exit 0
    ;;
  onermesi)
    # --nomodule yerine PYTHONPATH'e proje kökünü koyuyoruz.
    PYTHONPATH="$DIR" exec python -u main.py --no-browser --port "$PORT"
    ;;
esac

command -v tmux >/dev/null 2>&1 || { echo "HATA: tmux yok — pkg install tmux"; exit 1; }

if tmux has-session -t "$OTURUM" 2>/dev/null; then
  echo "Zaten çalışıyor. Günlük:  ./start.sh log"
  exit 0
fi

echo "Başlatılıyor → http://localhost:$PORT"
tmux new-session -d -s "$OTURUM" -c "$DIR" \
  "PYTHONPATH='$DIR' python -u main.py --no-browser --port $PORT; echo; echo '[sunucu durdu]'; sleep 3600"

sleep 3
if tmux has-session -t "$OTURUM" 2>/dev/null; then
  echo
  echo "  ✔ Çalışıyor:  http://localhost:$PORT"
  echo "  Günlük:       ./start.sh log"
  echo "  Durdur:       ./start.sh durdur"
  echo "  Geri bağlan:  tmux attach -t $OTURUM"
  echo
else
  echo "HATA: sunucu başlamadı. Şu komutu deneyin:  ./start.sh log"
  exit 1
fi