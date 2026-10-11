"""Bash betiklerinin temel yapısal kontrolü (Termux uyumu).

Bu tam bir bash ayrıştırıcısı DEĞİLDİR; WSL yokken `bash -n`
calistirilamadiği için en çok kaza yapan noktalari denetler:
shebang, satir sonu (CRLF), blok acma/kapama dengesi, tirnak dengesi.

Kullanim:  python tools/check_sh.py
"""
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OPENERS = re.compile(r"(?:^|[;&|]\s*)(?:if|for|while|case)\b", re.M)
CLOSERS = re.compile(r"(?:^|[;&|]\s*)(?:fi|done|esac)\b", re.M)


def check(path):
    src = open(path, encoding="utf-8").read()
    lines = src.split("\n")
    problems = []

    # 1) Shebang — Termux'ta bash'in tam yolu gerekir
    if not src.startswith("#!/data/data/com.termux/files/usr/bin/bash"):
        problems.append(f"shebang beklenenden farkli: {lines[0]!r}")

    # 2) CRLF — Windows'te yazilmis dosya Termux'ta calismaz
    if "\r" in src:
        problems.append("CR (CRLF satir sonu) var — Termux'ta bozar")

    # 3) Blok acma/kapama dengesi
    opens = len(OPENERS.findall(src))
    closes = len(CLOSERS.findall(src))
    if opens != closes:
        problems.append(f"blok acan({opens}) != kapatan({closes})")

    # 4) Tirnak dengesi — yorum satirlari haric, mantiksal satir basina.
    #    Satir \ ile bitiyorsa veya tirkacla bitmiyorsa cok satirlı
    #    dizge devam ediyor demektir; onu saymiyoruz.
    in_string = False
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if in_string:
            if '"' in line:
                in_string = False
            continue
        if stripped.startswith("#") or not stripped:
            continue
        if line.endswith("\\"):
            continue
        # Tirnak sayimi tek ve satir tirkacla BITMIYORSA cok satirlı dizge
        if line.count('"') % 2:
            if not stripped.endswith('"'):
                in_string = True
                continue
            problems.append(f"satir {i}: cift tirnak dengesi bozuk")
        if line.count("'") % 2:
            if not stripped.endswith("'"):
                continue
            problems.append(f"satir {i}: tek tirnak dengesi bozuk")

    # 5) Yorum isaretli satir disinda kalan tirnak artigi
    print(f"{path}: {len(lines)} satir, {len(src)} bayt")
    print(f"  shebang        : {lines[0]}")
    print(f"  satir sonu     : {'LF (Linux/Termux uyumlu)' if chr(13) not in src else 'CRLF (BOZUK)'}")
    print(f"  blok acan/kap  : {opens}/{closes}"
          + ("  dengeli" if opens == closes else "  DENGESIZ"))
    for p in problems:
        print("  ! " + p)
    print("  -> " + ("gecerli" if not problems else " SORUN VAR"))
    print()
    return not problems


if __name__ == "__main__":
    good = check("setup-termux.sh") and check("start.sh")
    print("SONUC:", "her sey yolunda" if good else " SORUN VAR")
    sys.exit(0 if good else 1)