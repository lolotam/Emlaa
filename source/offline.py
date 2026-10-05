# -*- coding: utf-8 -*-
"""
إملاء — التفريغ بدون إنترنت (whisper.cpp)
----------------------------------------
مسار تفريغ بديل بيشتغل كلّه على جهاز المستخدم: بينزّل موديل whisper.cpp
وبياناته، وبيفرّغ الـwav بـwhisper-cli.exe من غير ما أي صوت يعدّي على سيرفر.

ليه اللوك والدول الفاصل:
  • التنزيل/المسح/التفريغ كلهم بيتشاركوا نفس الملفات — لو اتنين اشتغلوا فوق
    بعض (تنزيل ومسح مثلًا) الملفات هتبقى نصّ مكتوبة وهتفشل.
  • بنكتب المانيڨست آخر خطوة، فـinstalled() مبيرجعش اسم موديل إلا لما كل
    الملفات فعلًا على القرص — أي قطع في النص معناه «مفيش موديل» مش «موديل بايظ».

استيراد core جوّه الدوال بس: core هيستورد offline في مهمة لاحقة، فلو استوردناه
من فوق هيتبني دورة استيراد.
"""
import os
import json
import time
import hashlib
import tempfile
import threading
import urllib.request

# ── القيم المثبّتة (متفق عليها مسبقًا — مينفعش تتغيّر) ───────────────────────
WHISPER_CPP_VERSION = "v1.9.2"
WHISPER_CPP_URL     = "https://github.com/ggml-org/whisper.cpp/releases/download/v1.9.2/whisper-bin-x64.zip"
WHISPER_CPP_SHA256  = "49dcc16de826f20bd53d44f947a1ae49dfa81f86cad67a64d80820cb192d674a"
WHISPER_CPP_SIZE    = 8194445

# آخر commit لريبو موديلات whisper.cpp على HuggingFace — عشان نثبّت نسخة الموديل
HF_REVISION = "5359861c739e955e79d9a303bcbc70fb988958b1"

# اسم الموديل → (رابط التنزيل، بصمة sha256، الحجم بالبايت)
MODELS = {
    "base":       ("https://huggingface.co/ggerganov/whisper.cpp/resolve/5359861c739e955e79d9a303bcbc70fb988958b1/ggml-base.bin",
                   "60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe", 147951465),
    "small-q5_1": ("https://huggingface.co/ggerganov/whisper.cpp/resolve/5359861c739e955e79d9a303bcbc70fb988958b1/ggml-small-q5_1.bin",
                   "ae85e4a935d7a567bd102fe55afc16bb595bdb618e11b2fc7591bc08120411bb", 190085487),
}

# whisper-cli بيشتغل من غيرهم — بنستبعدهم من الفك عشان حجم أقل وتشغيل أنضف
_SKIP_DLL = ("sdl2.dll",)

CREATE_NO_WINDOW = 0x08000000   # عشان مفيش نافذة console تخطف لمّا الـCLI يشتغل
TRANSCRIBE_TIMEOUT = 120        # ثواني — أقصى وقت لتفريغ مقطع واحد

# قفل واحد بيرتّب التنزيل/المسح/التفريغ — كلهم بيلمسوا نفس الملفات
_lock = threading.Lock()

# الاختبارات بتحط opener مزيّف هنا عشان التنزيل يمشي من غير شبكة
_opener = None


def _dirs():
    """
    بيرجّع (bin, models, staging, manifest) من core.BASE. استيراد core هنا
    عشان core بيستورد offline في مهمة لاحقة — مينفعش يبقى فوق الملف.
    """
    import core
    base = core.BASE
    return (os.path.join(base, "offline", "bin"),
            os.path.join(base, "offline", "models"),
            os.path.join(base, "offline", ".staging"),
            os.path.join(base, "offline", "manifest.json"))


def _threads():
    """عدد ثريدات التفريغ: بنسيب ٢ للميكروبات، بس مش أقل من ٤ ولا أكتر من ٨."""
    return min(8, max(4, (os.cpu_count() or 4) - 2))


def _open(url):
    """بيرجّع file-like بيتقري chunks — الاختبارات بتحط _opener من غير شبكة."""
    if _opener is not None:
        return _opener(url)
    # core (اللي استوردناه في _dirs قبل التنزيل) بيحط SSL_CERT_FILE=certifi،
    # فالـurlopen العادي بيلاقي الشهادات جوّه الـexe
    return urllib.request.urlopen(url)


# ── المثبّت دلوقتي ────────────────────────────────────────────────────────────
def installed():
    """اسم الموديل المثبّت، أو None لو مفيش تثبيت سليم (ملفات ناقصة أو حجم مختلف)."""
    bin_dir, model_dir, staging, manifest_path = _dirs()
    if not os.path.exists(manifest_path):
        return None
    try:
        with open(manifest_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    files = data.get("files")
    if not isinstance(files, dict) or not files:
        return None
    # كل ملف لازم يكون موجود وبالظبط بنفس الحجم المسجّل — غير كده = تثبيت بايظ
    root = os.path.dirname(manifest_path)
    for rel, size in files.items():
        p = os.path.join(root, rel)
        try:
            if not os.path.exists(p) or os.path.getsize(p) != int(size):
                return None
        except OSError:
            return None
    return data.get("model")


# ── التنزيل والتثبيت ──────────────────────────────────────────────────────────
def _stream_download(url, dest, sha256, size, progress, done, total):
    """
    بينزّل url لـdest عبر .part، ويتأكد من البصمة والحجم. progress بيتندّى
    بكسر من الإجمالي الكلي للعملية (bin + model) — مش للملف ده لوحده.
    """
    h = hashlib.sha256()
    got = 0
    part = dest + ".part"
    with _open(url) as r, open(part, "wb") as f:
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
            got += len(chunk)
            if progress and total:
                progress(min(1.0, (done + got) / total))
    if size and got != size:
        raise RuntimeError(f"الملف نزل ناقص ({got} من {size})")
    if sha256 and h.hexdigest() != sha256:
        raise RuntimeError("بصمة الملف مش مطابقة")
    os.replace(part, dest)
    return got


def _extract_bin(zip_path, dest):
    """
    يفكك أرشيف whisper.cpp وياخد بس whisper-cli.exe والـdll المطلوبة، مفلطحة
    في dest من غير "Release/". SDL2.dll وأي حاجة بتتبدأ بـparakeet بيتسابوا —
    whisper-cli بيشتغل من غيرهم. أي مسار فيه ".." أو مطلق = نرفض الأرشيف كله.
    """
    import zipfile
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = info.filename
            if ".." in name or os.path.isabs(name):
                raise RuntimeError("الأرشيف فيه مسار مش سليم — اتلغى التثبيت")
            if not name.startswith("Release/"):
                continue
            base = name[len("Release/"):]
            if not base:
                continue
            keep = base == "whisper-cli.exe"
            if base.lower().endswith(".dll"):
                low = base.lower()
                keep = low != "sdl2.dll" and not low.startswith("parakeet")
            if not keep:
                continue
            with zf.open(info) as src, open(os.path.join(dest, base), "wb") as dst:
                dst.write(src.read())


def _run(cmd, **kw):
    """بنفصل subprocess.run عشان الاختبار يقدر يزوّد نسخة مزيّفة من غير عملية حقيقية."""
    import subprocess
    return subprocess.run(cmd, capture_output=True, creationflags=CREATE_NO_WINDOW, **kw)


def _clear_staging(staging):
    """بيمسح فولدر الـstaging كله — بيستخدم في الفشل وفي أول كل تنزيل."""
    import shutil
    try:
        shutil.rmtree(staging)
    except OSError:
        pass


def download(model, progress=None):
    """
    بينزّل ويجهّز موديل offline + بيانات whisper.cpp. بيدور كله في .staging،
    وبيبني الملفات الحقيقية مكانها وبيقفل بالمانيڨست آخر خطوة — فلو حصل أي
    فشل في النص مفيش حاجة بتتسجّل كـ«مثبّت»، وبيترمى الـstaging.
    """
    if model not in MODELS:
        raise ValueError(f"موديل offline مش معروف: {model}")
    model_url, model_sha, model_size = MODELS[model]
    total = WHISPER_CPP_SIZE + model_size

    with _lock:
        bin_dir, model_dir, staging, manifest_path = _dirs()
        os.makedirs(staging, exist_ok=True)
        _clear_staging(staging)
        os.makedirs(staging, exist_ok=True)

        try:
            # الموديل الأول (الثقيل) وبعدين الـbin — عشان progress يمشي بالتتابع
            model_file = os.path.join(staging, model + ".bin")
            _stream_download(model_url, model_file, model_sha, model_size,
                             progress, 0, total)

            zip_file = os.path.join(staging, "whisper.zip")
            _stream_download(WHISPER_CPP_URL, zip_file, WHISPER_CPP_SHA256,
                             WHISPER_CPP_SIZE, progress, model_size, total)

            _extract_bin(zip_file, staging)

            # فحص دخان: لازم الـexe يشغّل ويطبع help من غير مشاكل
            exe = os.path.join(staging, "whisper-cli.exe")
            if _run([exe, "--help"]).returncode != 0:
                raise RuntimeError("whisper-cli مش بيشتغل — اتلغى التثبيت")

            if progress:
                progress(1.0)

            # ننقل للمكان الحقيقي: bin وmodels، من غير ما نلمس الملفات القديمة غير بعد النجاح
            os.makedirs(bin_dir, exist_ok=True)
            os.makedirs(model_dir, exist_ok=True)
            for name in os.listdir(staging):
                src = os.path.join(staging, name)
                if not os.path.isfile(src):
                    continue
                if name == model + ".bin":
                    dst = os.path.join(model_dir, name)
                elif name in ("whisper-cli.exe",) or name.lower().endswith(".dll"):
                    dst = os.path.join(bin_dir, name)
                else:
                    continue
                os.replace(src, dst)

            # المانيڨست بيتكتب آخر حاجة، بمسارات نسبية من جذر offline وأحجام حقيقية
            files = {}
            for name in os.listdir(bin_dir):
                p = os.path.join(bin_dir, name)
                files["bin/" + name] = os.path.getsize(p)
            files["models/" + model + ".bin"] = os.path.getsize(
                os.path.join(model_dir, model + ".bin"))

            manifest = {"model": model, "version": WHISPER_CPP_VERSION, "files": files}
            tmp = manifest_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=1)
            os.replace(tmp, manifest_path)
        except Exception:
            _clear_staging(staging)
            raise
        finally:
            _clear_staging(staging)


def remove():
    """بيمسح الموديل والـbin والمانيڨست المثبّتين — تحت اللوك عشان ميتعاركش مع تنزيل."""
    with _lock:
        bin_dir, model_dir, staging, manifest_path = _dirs()
        # بنعرف الملفات من المانيڨست عشان مانمسحش حاجة مش بتاعتنا
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, encoding="utf-8") as f:
                    data = json.load(f)
                root = os.path.dirname(manifest_path)
                for rel in (data.get("files") or {}):
                    try:
                        os.remove(os.path.join(root, rel))
                    except OSError:
                        pass
            except Exception:
                pass
        for p in (manifest_path,):
            try:
                os.remove(p)
            except OSError:
                pass
        _clear_staging(staging)


# ── التفريغ ───────────────────────────────────────────────────────────────────
def build_cmd(wav, model_path, language, out_base):
    """
    بيبني أمر whisper-cli. language=None (وضع الترجمة) = "auto" عشان الـCLI
    يتعرّف على اللغة لوحده. -nt بتشيل الطوابع الزمنية، و-otxt بيطلع .txt.
    """
    bin_dir, _, _, _ = _dirs()
    exe = os.path.join(bin_dir, "whisper-cli.exe")
    lang = language or "auto"
    return [exe, "-m", model_path, "-f", wav, "-l", lang, "-nt",
            "-t", str(_threads()), "-otxt", "-of", out_base]


# ساعة mtime في NTFS أخشن من time.time() (لحد ~16ms)، فملف اتكتب بعد start
# ممكن يطلع mtime بتاعه قبله بشوية — السماحية دي بتمنع رفض نتيجة سليمة.
MTIME_SLACK = 2.0


def _read_result(out_txt, start):
    """النص من .txt لو اتكتب بعد ما بدأنا ومش فاضي بعد القصّ — غير كده None."""
    try:
        if os.path.getmtime(out_txt) < start - MTIME_SLACK:
            return None
        with open(out_txt, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    return text.strip() or None


def transcribe(wav, language):
    """
    بيفرّغ wav بالموديل المثبّت ويرجّع النص. الملف المؤقت في temp وبيمسح دايمًا
    (حتى لو فشل). الفشل بيرمي RuntimeError — مفيش حالة بنرجّع فيها نص فاضي
    وندّعي إنه تفريغ.
    """
    model = installed()
    if not model:
        raise RuntimeError("مفيش موديل offline مثبّت — نزّل موديل الأول")
    _, model_dir, _, _ = _dirs()
    model_path = os.path.join(model_dir, model + ".bin")

    out_base = os.path.join(tempfile.gettempdir(),
                            "emlaa_offline_%d" % int(time.time() * 1000))
    out_txt = out_base + ".txt"
    start = time.time()

    with _lock:
        try:
            # ملف قديم بنفس الاسم ميتقريش كأنه نتيجة التشغيل ده
            try:
                os.remove(out_txt)
            except OSError:
                pass
            cmd = build_cmd(wav, model_path, language, out_base)
            try:
                r = _run(cmd, timeout=TRANSCRIBE_TIMEOUT)
            except Exception:
                # timeout أو أي فشل في التشغيل — ننضّف ونطلع بـRuntimeError موحّد
                try:
                    os.remove(out_txt)
                except OSError:
                    pass
                raise RuntimeError("التفريغ offline فشل")
            try:
                text = None
                if r.returncode == 0:
                    text = _read_result(out_txt, start)
            finally:
                try:
                    os.remove(out_txt)
                except OSError:
                    pass
        except Exception:
            try:
                os.remove(out_txt)
            except OSError:
                pass
            raise

    if text is None:
        raise RuntimeError("التفريغ offline رجّع نص فاضي")
    return text
