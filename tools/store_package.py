# -*- coding: utf-8 -*-
"""
بناء نسخة Microsoft Store من إملاء · Emlaa (حزمة MSIX).

    python tools/store_package.py              # يبني Emlaa.exe + الحزمة
    python tools/store_package.py --no-build   # يستخدم dist/Emlaa.exe أو Emlaa.exe الموجود
    python tools/store_package.py --register   # يثبّت الحزمة على جهازك للتجربة (محتاج Developer Mode)

الناتج: dist/store/Emlaa_<version>_x64.msix — ده اللي بيترفع على Partner Center.
الـStore هو اللي بيوقّع الحزمة، فمش محتاج شهادة.

قبل الرفع: حط قيم Partner Center في tools/store/store.json
(Product management → Product identity: Package/Identity/Name و Publisher و PublisherDisplayName).
أداة makeappx بتتنزّل لوحدها أول مرة (حزمة Microsoft.Windows.SDK.BuildTools من NuGet).
"""
import glob
import io
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE_DIR = os.path.join(ROOT, "tools", "store")
LAYOUT = os.path.join(ROOT, "build", "store", "layout")
OUT_DIR = os.path.join(ROOT, "dist", "store")
CACHE = os.path.join(os.environ.get("LOCALAPPDATA", ROOT), "Emlaa-build", "sdk-buildtools")
NUGET = "https://www.nuget.org/api/v2/package/Microsoft.Windows.SDK.BuildTools"


def app_version():
    src = io.open(os.path.join(ROOT, "source", "emlaa.py"), encoding="utf-8").read()
    v = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', src, re.M).group(1)
    parts = [int(p) for p in v.split(".")][:3]
    parts += [0] * (3 - len(parts))
    return ".".join(map(str, parts)) + ".0"          # الـStore عايز آخر رقم 0


def makeappx():
    found = glob.glob(os.path.join(CACHE, "bin", "*", "x64", "makeappx.exe"))
    if not found:
        print("→ بنزّل أدوات التغليف من NuGet (مرة واحدة)…")
        os.makedirs(CACHE, exist_ok=True)
        pkg = os.path.join(CACHE, "buildtools.zip")
        urllib.request.urlretrieve(NUGET, pkg)
        with zipfile.ZipFile(pkg) as z:
            z.extractall(CACHE)
        os.remove(pkg)
        found = glob.glob(os.path.join(CACHE, "bin", "*", "x64", "makeappx.exe"))
    if not found:
        sys.exit("مش لاقي makeappx.exe")
    return sorted(found)[-1]


def make_assets(dst):
    """أيقونات الحزمة من source/emlaa.png بكل المقاسات المطلوبة."""
    from PIL import Image
    src = Image.open(os.path.join(ROOT, "source", "emlaa.png")).convert("RGBA")
    os.makedirs(dst, exist_ok=True)

    def canvas(w, h, scale, name):
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        side = int(min(w, h) * scale)
        icon = src.resize((side, side), Image.LANCZOS)
        img.paste(icon, ((w - side) // 2, (h - side) // 2), icon)
        img.save(os.path.join(dst, name))

    canvas(50, 50, 1.0, "StoreLogo.png")
    canvas(44, 44, 1.0, "Square44x44Logo.png")
    for t in (16, 24, 32, 44, 48, 256):            # أيقونة شريط المهام من غير خلفية
        canvas(t, t, 1.0, f"Square44x44Logo.targetsize-{t}_altform-unplated.png")
    canvas(71, 71, 0.7, "SmallTile.png")
    canvas(150, 150, 0.6, "Square150x150Logo.png")
    canvas(310, 150, 0.6, "Wide310x150Logo.png")
    canvas(310, 310, 0.6, "LargeTile.png")


def main():
    args = sys.argv[1:]
    cfg = json.load(io.open(os.path.join(STORE_DIR, "store.json"), encoding="utf-8"))
    version = app_version()

    exe = os.path.join(ROOT, "dist", "Emlaa.exe")
    if "--no-build" not in args:
        subprocess.run([sys.executable, "-m", "PyInstaller", "Emlaa.spec", "--noconfirm"], cwd=ROOT, check=True)
    if not os.path.exists(exe):
        exe = os.path.join(ROOT, "Emlaa.exe")
    if not os.path.exists(exe):
        sys.exit("مفيش Emlaa.exe — شغّله من غير --no-build")

    # تجهيز فولدر الحزمة
    if os.path.exists(LAYOUT):
        shutil.rmtree(LAYOUT)
    os.makedirs(LAYOUT)
    shutil.copy2(exe, os.path.join(LAYOUT, "Emlaa.exe"))
    make_assets(os.path.join(LAYOUT, "Assets"))
    tpl = io.open(os.path.join(STORE_DIR, "AppxManifest.template.xml"), encoding="utf-8").read()
    from xml.sax.saxutils import escape
    values = {k: escape(str(v)) for k, v in cfg.items() if not k.startswith("_")}
    values["version"] = version
    manifest = re.sub(r"\{(\w+)\}", lambda m: values.get(m.group(1), m.group(0)), tpl)
    io.open(os.path.join(LAYOUT, "AppxManifest.xml"), "w", encoding="utf-8").write(manifest)

    if "--register" in args:
        # تجربة على الجهاز من غير توقيع (محتاج: Settings → For developers → Developer Mode)
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        f"Add-AppxPackage -Register '{os.path.join(LAYOUT, 'AppxManifest.xml')}' -ForceApplicationShutdown"],
                       check=True)
        print("✓ اتثبّتت للتجربة — دوّر على Emlaa في قايمة Start")
        return

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, f"Emlaa_{version}_x64.msix")
    subprocess.run([makeappx(), "pack", "/o", "/d", LAYOUT, "/p", out], check=True)
    print(f"\n✓ الحزمة جاهزة: {out}")
    print("  ارفعها على Partner Center ← Packages")


if __name__ == "__main__":
    main()
