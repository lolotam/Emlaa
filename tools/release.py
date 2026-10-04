# -*- coding: utf-8 -*-
"""
إصدار نسخة جديدة من إملاء · Emlaa — بأمر واحد.

    python tools/release.py 1.9 "اللي اتغيّر في النسخة دي"
    python tools/release.py 1.9 --notes-file notes.md

بيعمل بالترتيب:
  1) يغيّر APP_VERSION في source/notq.py
  2) يبني Emlaa.exe بـ PyInstaller (Notq.spec)
  3) git commit + tag vX.Y + push
  4) ينشئ GitHub Release ويرفع Emlaa.exe عليه
بعدها أي نسخة شغّالة عند المستخدمين هتلاقي الإصدار الجديد خلال ساعات (أو فورًا
من «تحقق من التحديثات») وتعرض «نزّل وثبّت».
محتاج: git و gh (مسجّل دخول) و PyInstaller.
"""
import io
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOTQ = os.path.join(ROOT, "source", "notq.py")
REPO = "lolotam/Emlaa"


def run(*cmd, **kw):
    print("→", " ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True, **kw)


def out(*cmd):
    return subprocess.run(cmd, cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def main():
    args = sys.argv[1:]
    if not args or not re.fullmatch(r"\d+(\.\d+){1,2}", args[0]):
        sys.exit("الاستخدام: python tools/release.py 1.9 \"الملاحظات\"  (أو --notes-file ملف)")
    version, notes = args[0], ""
    if len(args) >= 3 and args[1] == "--notes-file":
        notes = io.open(args[2], encoding="utf-8").read().strip()
    elif len(args) >= 2:
        notes = args[1]
    tag = "v" + version

    if tag in out("git", "tag", "--list", tag).split():
        sys.exit(f"الإصدار {tag} موجود قبل كده — اختار رقم أكبر")

    # 1) رقم الإصدار
    src = io.open(NOTQ, encoding="utf-8").read()
    m = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', src, re.M)
    if not m:
        sys.exit("مش لاقي APP_VERSION في source/notq.py")
    io.open(NOTQ, "w", encoding="utf-8", newline="").write(
        src[:m.start(1)] + version + src[m.end(1):])
    print(f"APP_VERSION: {m.group(1)} → {version}")

    # 2) البناء
    run(sys.executable, "-m", "PyInstaller", "Notq.spec", "--noconfirm")
    exe = os.path.join(ROOT, "dist", "Emlaa.exe")
    if not os.path.exists(exe):
        sys.exit("البناء فشل — مفيش dist/Emlaa.exe")

    # 3) git
    run("git", "add", "-A")
    if out("git", "status", "--porcelain"):
        run("git", "commit", "-m", f"Release {tag}")
    run("git", "tag", "-a", tag, "-m", f"Emlaa {tag}")
    run("git", "push", "origin", "HEAD", "--follow-tags")

    # 4) GitHub Release + الـexe
    run("gh", "release", "create", tag, exe, "--repo", REPO,
        "--title", f"Emlaa {tag}", "--notes", notes or f"Emlaa {tag}")

    # النسخة المحلية تبقى هي الجديدة
    try:
        shutil.copy2(exe, os.path.join(ROOT, "Emlaa.exe"))
    except PermissionError:
        print("ملحوظة: Emlaa.exe شغّال — اقفله وانسخ dist/Emlaa.exe مكانه")
    print(f"\n✓ اتنشر {tag}: https://github.com/{REPO}/releases/tag/{tag}")


if __name__ == "__main__":
    main()
