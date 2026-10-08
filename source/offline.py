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
import re
import json
import time
import hashlib
import tempfile
import threading
import urllib.request

import smart

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
DOWNLOAD_TIMEOUT = 30           # ثواني — مهلة الاتصال/القراية لكل urlopen (نت متوقّف = نرفض بدل ما نعلّق للأبد)

# قفل واحد بيرتّب التنزيل/المسح/التفريغ — كلهم بيلمسوا نفس الملفات
_lock = threading.Lock()

# قفل تاني للتنزيل بس: بيمسك عمليّة التنزيل كلها (من أول تنظيف الـstaging لحد الـcommit)
# عشان تنزيلين ميشبّكوش فوق بعض — بس من غير ما يوقّف التفريغ والمسح (اللي واخدين _lock).
_dl_lock = threading.Lock()

# الاختبارات بتحط opener مزيّف هنا عشان التنزيل يمشي من غير شبكة
_opener = None

# ── فحص بصمة الحزمة مرة واحدة لكل عملية (Task 20) ─────────────────────────────
# الموديل 150–190 MB، فهاشه على كل تفريغ كان هيبطّأ الوضع المحلي — بنحسبه مرة
# واحدة ونخزّن النتيجة على هوية المانيڨست (mtime_ns, size)، وبنمسحها لما تنزيل
# أو مسح يحصل. _verify_locked() بتفترض إن _lock ماسك (transcribe بيناديها واللوك
# معاه)؛ verify() هي اللي بتاخد اللوك وبتخزّن النتيجة.
_verify_cache = {}


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
    return urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT)


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
    # مانيڨست JSON سليم بس شكله غلط ([] / موديل مش نص / حجم مش رقم) = تثبيت بايظ،
    # مش استثناء — غير كده bootstrap نفسه بيقع وزرار الإزالة مايظهرش
    if not isinstance(data, dict):
        return None
    # N4: الموديل لازم يبقى واحد من اللي بنعرفهم — غير كده مانيڨست بايظ/مزوّر
    model = data.get("model")
    if not isinstance(model, str) or model not in MODELS:
        return None
    files = data.get("files")
    if not isinstance(files, dict) or not files:
        return None
    # التشغيل محتاج الـexe والموديل نفسه على الأقل — مانيڨست فيه الموديل لوحده
    # كان بيعدّي ويفتح وضع «دايمًا» من غير مفتاح والتفريغ بيفشل
    if "bin/whisper-cli.exe" not in files or "models/" + model + ".bin" not in files:
        return None
    # كل ملف لازم يكون موجود وبالظبط بنفس الحجم المسجّل — غير كده = تثبيت بايظ
    root = os.path.dirname(manifest_path)
    root_real = os.path.realpath(root)
    for rel, size in files.items():
        p = os.path.join(root, rel)
        try:
            if not os.path.exists(p) or os.path.getsize(p) != int(size):
                return None
            # N4: المسار لازم يفضل جوّه جذر offline — مانع أي خروج بـ".."
            if not os.path.realpath(p).startswith(root_real + os.sep):
                return None
        except (OSError, TypeError, ValueError):
            return None
    return model


# ── فحص بصمة الملفات (Task 20) ────────────────────────────────────────────────
def _sha256_file(path):
    """sha256 لملف بيتقري على قطع 1 MB — عشان ممن نحمّل الـ150 MB في الذاكرة مرة واحدة."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _manifest_identity(manifest_path):
    """هوية المانيڨست الحالية (mtime_ns, size) — None لو مفيش ملف."""
    try:
        st = os.stat(manifest_path)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def cached_verification():
    """
    نتيجة الفحص المخزّنة للمانيڨست الحالي: True/False، أو None لو الفحص لسه
    ما اتعملش (أو مفيش مانيڨست). مبيحسبش بصمات هنا — offline_status لازم يفضل
    سريع ومش بيحبس الواجهة على هاش 150 MB.
    """
    _, _, _, manifest_path = _dirs()
    identity = _manifest_identity(manifest_path)
    if identity is None:
        return None
    return _verify_cache.get(identity)


def verify():
    """
    بيفحص بصمة كل ملف في المانيڨست مرة واحدة لكل عملية. النتيجة بتتخزّن على
    هوية المانيڨست (mtime_ns, size). المانيڨست القديم (من غير "sha256"):
    الموديل بيتقارن بـMODELS pin، والـbin بيعدّي على الحجم.
    """
    _, _, _, manifest_path = _dirs()
    identity = _manifest_identity(manifest_path)
    if identity is None:
        return False
    result = _verify_cache.get(identity)
    if result is not None:
        return result
    with _lock:
        return _verified_cached_locked()


def _verified_cached_locked():
    """
    نتيجة الفحص للمانيڨست الحالي من الكاش، أو بتحسبها مرة وتخزّنها — لازم
    _lock يكون ماسك. transcribe() بيناديها هي مش _verify_locked() على طول، غير
    كده كل تفريغ كان هيعيد هاش الـ150–190 MB.
    """
    _, _, _, manifest_path = _dirs()
    identity = _manifest_identity(manifest_path)
    if identity is None:
        return False
    result = _verify_cache.get(identity)
    if result is None:
        result = _verify_locked()
        _verify_cache[identity] = result
    return result


def _verify_locked():
    """
    الفحص الفعلي — لازم يتبندّى والـ_lock ماسك (عشان remove/download مش يلمسوا
    الملفات في نص الهاش). بيرجّع True/False. مبياخدش اللوك بنفسه: transcribe()
    بيناديه واللوك معاه.
    """
    bin_dir, model_dir, staging, manifest_path = _dirs()
    if not os.path.exists(manifest_path):
        return False
    try:
        with open(manifest_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return False
    if not isinstance(data, dict):
        return False
    model = data.get("model")
    if not isinstance(model, str) or model not in MODELS:
        return False
    files = data.get("files")
    if not isinstance(files, dict) or not files:
        return False
    hashes = data.get("sha256")
    hashes = hashes if isinstance(hashes, dict) else {}
    root = os.path.dirname(manifest_path)
    root_real = os.path.realpath(root)
    for rel, size in files.items():
        p = os.path.join(root, rel)
        try:
            if not os.path.exists(p) or not os.path.realpath(p).startswith(root_real + os.sep):
                return False
        except OSError:
            return False
        if rel in hashes:
            if _sha256_file(p) != hashes[rel]:
                return False
        elif rel == "models/" + model + ".bin":
            # مانيڨست قديم من غير خريطة بصمات: الموديل بيتقارن بالبصمة المثبّتة
            if _sha256_file(p) != MODELS[model][1]:
                return False
        else:
            # الـbin من غير خريطة = بيعدّي على الحجم المسجّل
            try:
                if os.path.getsize(p) != int(size):
                    return False
            except (OSError, TypeError, ValueError):
                return False
    return True


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
    dest_real = os.path.realpath(dest)
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
            # N3: بعد قصّ "Release/" لازم يفضل اسم ملف عادي — أي فاصل مسار
            # ("/" أو "\\") أو ":" أو اسم خاص "." / ".." = نرفض الأرشيف كله
            if base in (".", "..") or "/" in base or "\\" in base or ":" in base:
                raise RuntimeError("الأرشيف فيه مسار مش سليم — اتلغى التثبيت")
            keep = base == "whisper-cli.exe"
            if base.lower().endswith(".dll"):
                low = base.lower()
                keep = low != "sdl2.dll" and not low.startswith("parakeet")
            if not keep:
                continue
            # N3: تأكيد أخير إن المسار النهائي جوّه dest — دفاع ضد أي حيلة مسار
            final = os.path.realpath(os.path.join(dest, base))
            if not final.startswith(dest_real + os.sep):
                raise RuntimeError("الأرشيف فيه مسار مش سليم — اتلغى التثبيت")
            with zf.open(info) as src, open(final, "wb") as dst:
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

    with _dl_lock:
        bin_dir, model_dir, staging, manifest_path = _dirs()
        os.makedirs(staging, exist_ok=True)
        _clear_staging(staging)
        os.makedirs(staging, exist_ok=True)

        try:
            # الموديل الأول (الثقيل) وبعدين الـbin — عشان progress يمشي بالتتابع
            # التنزيل والفك والفحص بيشتغلوا من غير _lock: التفريغ (transcribe)
            # والمسح (remove) بياخدوا _lock، فمش لازم يستنّوا تنزيل 150–190 MB.
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

            # الـcommit بس (نقل الملفات + المانيڨست + مسح القديم) جوه _lock —
            # هنا بنلمس bin/ وmodels/ الحقيقية، فمينفعش يبقى تنزيل/مسح فوق بعض.
            with _lock:
                # ننقل للمكان الحقيقي: bin وmodels، من غير ما نلمس الملفات القديمة غير بعد النجاح
                os.makedirs(bin_dir, exist_ok=True)
                os.makedirs(model_dir, exist_ok=True)
                old_files = _manifest_files(manifest_path)
                # المانيڨست بيتكتب آخر حاجة، بمسارات نسبية من جذر offline وأحجام حقيقية —
                # للملفات اللي نقلناها بس، مش لأي حاجة قديمة قاعدة في bin
                files = {}
                hashes = {}
                for name in os.listdir(staging):
                    src = os.path.join(staging, name)
                    if not os.path.isfile(src):
                        continue
                    if name == model + ".bin":
                        rel = "models/" + name
                    elif name in ("whisper-cli.exe",) or name.lower().endswith(".dll"):
                        rel = "bin/" + name
                    else:
                        continue
                    dst = os.path.join(os.path.dirname(manifest_path), rel)
                    os.replace(src, dst)
                    files[rel] = os.path.getsize(dst)
                    # بصمة الموديل هي المثبّتة (من MODELS) — بصمات الـexe والـdll
                    # بتيجي من الملفات اللي فُكّت من أرشيف متأكد منه (بصمة الـzip)
                    if rel == "models/" + model + ".bin":
                        hashes[rel] = model_sha
                    else:
                        hashes[rel] = _sha256_file(dst)

                manifest = {"model": model, "version": WHISPER_CPP_VERSION,
                            "files": files, "sha256": hashes}
                tmp = manifest_path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(manifest, f, ensure_ascii=False, indent=1)
                os.replace(tmp, manifest_path)
                _verify_cache.clear()
                # بعد ما التثبيت الجديد اتثبّت: الموديل التاني (150–190 MB) وأي ملف من
                # التثبيت القديم مش في الجديد كانوا هيفضلوا يتامى — remove() مش بيشوفهم
                stale = set(old_files) - set(files)
                stale |= {"models/" + m + ".bin" for m in MODELS if m != model}
                _remove_inside(os.path.dirname(manifest_path), stale)
        except Exception:
            _clear_staging(staging)
            raise
        finally:
            _clear_staging(staging)


def _manifest_files(manifest_path):
    """المسارات النسبية المسجّلة في المانيڨست — قايمة فاضية لو مفيش أو بايظ."""
    try:
        with open(manifest_path, encoding="utf-8") as f:
            files = json.load(f).get("files")
    except Exception:
        return []
    return list(files) if isinstance(files, dict) else []


def _remove_inside(root, rels):
    """بيمسح المسارات النسبية دي — بس اللي فعلًا جوّه root (N4: مانيڨست متلعوب فيه ميمسحش برّه)."""
    root_real = os.path.realpath(root)
    for rel in rels:
        p = os.path.join(root, rel)
        if not os.path.realpath(p).startswith(root_real + os.sep):
            continue
        try:
            os.remove(p)
        except OSError:
            pass


def _known_leftovers(bin_dir):
    """
    ملفات الباك اللي بنعرفها من غير مانيڨست: whisper-cli.exe والـdll في bin/
    (الفولدر ده بتاعنا لوحدنا) وموديلات MODELS — عشان تثبيت بايظ يتشال برضه.
    """
    rels = ["models/" + m + ".bin" for m in MODELS] + ["bin/whisper-cli.exe"]
    try:
        rels += ["bin/" + n for n in os.listdir(bin_dir) if n.lower().endswith(".dll")]
    except OSError:
        pass
    return rels


def residual():
    """فيه ملفات باك على الجهاز (حتى لو التثبيت بايظ)؟ — عشان زرار الإزالة يفضل متاح."""
    bin_dir, model_dir, staging, manifest_path = _dirs()
    root = os.path.dirname(manifest_path)
    if os.path.exists(manifest_path):
        return True
    return any(os.path.exists(os.path.join(root, rel)) for rel in _known_leftovers(bin_dir))


def remove():
    """بيمسح الموديل والـbin والمانيڨست المثبّتين — تحت اللوك عشان ميتعاركش مع تنزيل."""
    with _lock:
        bin_dir, model_dir, staging, manifest_path = _dirs()
        # ملفات المانيڨست + الملفات اللي بنعرفها بالاسم — مانيڨست بايظ أو ناقص
        # ميسيبش 150–190 MB على الجهاز من غير طريقة تشيلهم من الواجهة
        root = os.path.dirname(manifest_path)
        _remove_inside(root, set(_manifest_files(manifest_path)) | set(_known_leftovers(bin_dir)))
        for p in (manifest_path,):
            try:
                os.remove(p)
            except OSError:
                pass
        _verify_cache.clear()
        # الـstaging بتاع تنزيل شغّال مينفعش يتلمس — بنمسحه بس لو قدرنا ناخد _dl_lock
        # من غير استنى (يعني مفيش تنزيل في النص). لو فشلنا فيه تنزيل شغّال: نسيب الـstaging.
        if _dl_lock.acquire(blocking=False):
            try:
                _clear_staging(staging)
            finally:
                _dl_lock.release()


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


# ── علامات السكوت في مخرج whisper.cpp (F1) ─────────────────────────────────────
# whisper.cpp بيرجّع توكنات زي "[BLANK_AUDIO]" أو "(music)" أو "*silence*" للسكوت
# والضجيج بدل ما يكتب كلام. لو سابناها النص بيتحفظ في السجل ويتنسخ في الحافظة كأنه
# تفريغ حقيقي. بنشيل التوكن الواقف لوحده بس (مش كلمة جوه جملة) لو محتواه واحد من
# القايمة دي — بعد تجاهل حالة الحروف والمسافات والـunderscores.
# علامات إنجليزي: عمرها ما تبقى كلام عربي حقيقي، فبتتشال في أي مكان في السطر
_NONSPEECH_EN = frozenset({
    "blankaudio", "silence", "music", "noise", "inaudible",
    "applause", "laughter", "nospeech", "sound", "backgroundnoise",
})
# whisper بـ-l ar ممكن يكتب العلامة بالعربي «(موسيقى)» / «[صمت]» — بس الكلمات دي
# ممكن تبقى كلام حقيقي («سمّي الزر (صوت)»)، فبتتشال بس لو السطر كله علامات
_NONSPEECH_AR = frozenset({
    "موسيقى", "موسيقي", "صمت", "سكوت", "ضحك", "تصفيق", "ضوضاء", "صوت", "ضجيج",
})

_MARKER_RE = re.compile(r"\[[^\[\]\n]*\]|\([^()\n]*\)|\*[^*\n]*\*")


def _marker_key(inner):
    """اسم العلامة من غير حالة الحروف والمسافات والـunderscores — للمطابقة بس."""
    return "".join(ch for ch in inner.lower() if ch.isalnum())


def _strip_line(line):
    """سطر واحد من مخرج whisper (كل مقطع في سطر) من غير علامات السكوت."""
    line = _MARKER_RE.sub(
        lambda m: " " if _marker_key(m.group(0)[1:-1]) in _NONSPEECH_EN else m.group(0), line)
    toks = _MARKER_RE.findall(line)
    if toks and not _MARKER_RE.sub("", line).strip() and all(
            _marker_key(t[1:-1]) in _NONSPEECH_AR for t in toks):
        return ""                      # السطر كله علامة عربي = مقطع سكوت
    line = re.sub(r"[ \t]+", " ", line).strip()
    # «[صمت].» / «[BLANK_AUDIO].»: لو مفضلش غير ترقيم بعد شيل العلامات = مفيش كلام
    if not any(ch.isalnum() for ch in _MARKER_RE.sub("", line)):
        toks = _MARKER_RE.findall(line)
        if all(_marker_key(t[1:-1]) in _NONSPEECH_AR | _NONSPEECH_EN for t in toks):
            return ""
    return line


def _strip_markers(text):
    """
    بيشيل علامات السكوت من نص whisper.cpp سطر بسطر ويحافظ على فواصل الأسطر:
    الإنجليزي ([BLANK_AUDIO]، (music)…) في أي مكان، والعربي بس لو السطر كله علامة.
    الكلمات الحقيقية جوه الأقواس بتفضل زي ما هي.
    """
    lines = (_strip_line(ln) for ln in (text or "").splitlines())
    return "\n".join(ln for ln in lines if ln)


def transcribe(wav, language):
    """
    بيفرّغ wav بالموديل المثبّت ويرجّع النص. language=None = تعرّف تلقائي على اللغة،
    ولو طلّع لغة غير عربي/إنجليزي بنعيد كعربي (زي Client.transcribe). لو الإعادة فشلت
    أو مطلعش منها كلام، التفريغ الأول أحسن من إن الكلام يضيع.
    """
    text = _transcribe_once(wav, language)
    if language is None and smart.foreign_script(text):
        try:
            return _transcribe_once(wav, "ar") or text
        except RuntimeError:
            return text
    return text


def _transcribe_once(wav, language):
    """
    الملف المؤقت في temp وبيمسح دايمًا (حتى لو فشل). الفشل بيرمي RuntimeError —
    مفيش حالة بنرجّع فيها نص فاضي وندّعي إنه تفريغ.
    """
    out_base = os.path.join(tempfile.gettempdir(),
                            "emlaa_offline_%d" % int(time.time() * 1000))
    out_txt = out_base + ".txt"
    start = time.time()

    with _lock:
        # N5: اختيار الموديل ومسار الملف جوه اللوك — remove() بياخد نفس اللوك،
        # فميقدرش يمسح الملفات بين اختيار الموديل وتنفيذ whisper-cli
        model = installed()
        if not model:
            raise RuntimeError("مفيش موديل offline مثبّت — نزّل موديل الأول")
        _, model_dir, _, _ = _dirs()
        model_path = os.path.join(model_dir, model + ".bin")
        # T20: فحص بصمة الملفات قبل تشغيل whisper — لو الموديل اتلف بعد التثبيت
        # (بايت اتقلب بنفس الحجم) نرفض برسالة واضحة بدل ما whisper-cli يهب أو
        # يطلع نص غلط. مرة واحدة في الجلسة (من الكاش) — واحنا ماسكين _lock فعلًا.
        if not _verified_cached_locked():
            raise RuntimeError("الموديل المحلي بايظ — شيله ونزّله تاني من الإعدادات")
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
    # F1: بنشيل علامات السكوت بعد التفريغ — لو الناتج فضى بعدها (whisper سمع
    # سكوت/ضجيج بس) بنرجع "" مش نرمي، وApp.process هيقول للمستخدم «مطلعش نص».
    return _strip_markers(text)
