# -*- coding: utf-8 -*-
"""
إملاء — محرّك Nemotron المحلي (NeMo-Speech.cpp)
-----------------------------------------------
محرّك تفريغ محلي تاني: موديل Nemotron 3.5 ASR Streaming 0.6B من NVIDIA بيشتغل على
NeMo-Speech.cpp (محرّك C++ أصلي). الصوت مايفيشش برّه الجهاز — زي Whisper بالظبط.

كل حاجة متثبّتة (من مصادر NVIDIA الرسمية):
  • المحرّك: nemo-speech 0.3.0 لويندوز x64 (نسخة المعالج) — الرابط والحجم والبصمة تحت.
  • الموديل: nemotron-3.5-asr-streaming-0.6b.q8_0.gguf من HuggingFace — نفس الكلام.

اللغة: الموديل نفسه بيحدّد اللغة (language-ID) وبيفهم العربي والإنجليزي.
بس "ar" → "ar-AR" · "en" → "en-US" · أي حاجة تانية (منها None) → "auto".

الفولدرات بتاعتنا جوّه مجلد بيانات إملاء (core.BASE) — مفيش أي ملف برّه، ولا بنلمس
أي ملف بتاع مشروع تاني.
"""
import os
import re
import time
import tempfile
import threading
import urllib.request

import asr_pack

# ── المحرّك (NeMo-Speech.cpp) ─────────────────────────────────────────────────
NEMO_SPEECH_VERSION = "0.3.0"
NEMO_SPEECH_ARCHIVE = "nemo-speech-0.3.0-windows-x86_64-cpu.zip"
NEMO_SPEECH_URL = ("https://github.com/NVIDIA/NeMo-Speech.cpp/releases/download/v0.3.0/"
                   + NEMO_SPEECH_ARCHIVE)
NEMO_SPEECH_SHA256 = "4ed9740e361e4653f56c3dce7d1e81883a1c8b831c1bd7d01567fff1130b5b05"
NEMO_SPEECH_SIZE = 8694509

# ── الموديل ──────────────────────────────────────────────────────────────────
MODEL_ID = "nemotron-3.5"                        # اسم الحزمة في الواجهة
MODEL_LABEL = "nemotron-3.5-asr-streaming-0.6b"  # اسم الموديل الحقيقي (بيظهر في السجل)
MODEL_FILE = "nemotron-3.5-asr-streaming-0.6b.q8_0.gguf"
MODEL_REVISION = "ea30d66debe3740a08b573244286791d423d6b3e"
MODEL_URL = ("https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b/resolve/"
             + MODEL_REVISION + "/" + MODEL_FILE)
MODEL_SHA256 = "3fc991d3badad7277c11030a7519832cddaf2057aafed6d4b25147e953a070b1"
MODEL_SIZE = 742090464

# الحزم المحلية اللي ينفع تتختار:Pack id → الحجم الكلي للتحميل (الموديل + المحرّك)
PACKS = {MODEL_ID: MODEL_SIZE + NEMO_SPEECH_SIZE}

# لغات الموديل (codes من قاموس الـGGUF نفسه: en/en-US · ar/ar-AR · auto)
LANGUAGE_CODES = {"ar": "ar-AR", "en": "en-US"}
AUTO_LANGUAGE = "auto"

# وسم اللغة اللي الموديل بيرفقه بالoutput (‎<ar-AR>‎) — بنشيله عشان النص يطلع نضيف
LANG_TAG_RE = re.compile(r"\s*<[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,4})?>\s*$")

EXE_NAME = "nemo-speech.exe"
TRANSCRIBE_TIMEOUT = 300       # ثواني — الموديل كبير (742 MB) وأول تحميل بياخد وقت
SMOKE_TIMEOUT = 60             # ثواني — فحص دخان للـexe بعد الفك

# قفل واحد بيرتّب التنزيل/المسح/التفريغ — كلهم بيلمسوا نفس الملفات
_lock = threading.Lock()

# قفل تاني للتنزيل بس: بيمسك عمليّة التنزيل كلها (من أول تنظيف الـstaging لحد الـcommit)
_dl_lock = threading.Lock()

# الاختبارات بتحط opener مزيّف هنا عشان التنزيل يمشي من غير شبكة
_opener = None

# كاش فحص البصمة: هوية المانيڨست (mtime_ns, size) → نتيجة الفحص
_verify_cache = {}


# ── الفولدرات ────────────────────────────────────────────────────────────────
def _dirs():
    """
    بيرجّع (runtime, models, staging, manifest) من core.BASE. استيراد core هنا
    عشان core بيستورد offline في مهمة لاحقة — مينفعش يبقى فوق الملف.
    """
    import core
    root = os.path.join(core.BASE, "offline", "nemo")
    return (os.path.join(root, "runtime"),
            os.path.join(root, "models"),
            os.path.join(root, ".staging"),
            os.path.join(root, "manifest.json"))


def _root():
    """جذر حزمة Nemotron — أي ملف لازم يبقى جوّه."""
    return os.path.dirname(_dirs()[3])


def _open(url):
    """بيرجّع file-like بيتقري chunks — الاختبارات بتحط _opener من غير شبكة."""
    if _opener is not None:
        return _opener(url)
    # core (اللي استوردناه في _dirs قبل التنزيل) بيحط SSL_CERT_FILE=certifi،
    # فالـurlopen العادي بيلاقي الشهادات جوّه الـexe
    return urllib.request.urlopen(url, timeout=asr_pack.DOWNLOAD_TIMEOUT)


def _run(cmd, **kw):
    """بنفصل subprocess.run عشان الاختبار يقدر يزوّد نسخة مزيّفة من غير عملية حقيقية."""
    return asr_pack.run(cmd, **kw)


# ── الحالة والتثبيت ──────────────────────────────────────────────────────────
def _manifest_data():
    """بيانات المانيڨست كـdict، أو None لو مفيش أو تالف."""
    data, ok = asr_pack.read_json(_dirs()[3])
    return data if ok and isinstance(data, dict) else None


def _manifest_identity():
    """هوية المانيڨست الحالية (mtime_ns, size) — None لو مفيش ملف."""
    try:
        st = os.stat(_dirs()[3])
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _files_ok(files):
    """كل ملف في المانيڨست موجود بنفس الحجم وجوّه الجذر — True/False."""
    root = _root()
    for rel, size in files.items():
        p = os.path.join(root, rel.replace("/", os.sep))
        try:
            if not os.path.exists(p) or os.path.getsize(p) != int(size):
                return False
            if not asr_pack.is_within(root, p):
                return False
        except (OSError, TypeError, ValueError):
            return False
    return True


def installed():
    """اسم الحزمة المثبّتة، أو None لو التثبيت ناقص أو الملف ناقص."""
    data = _manifest_data()
    if not data:
        return None
    if data.get("model") != MODEL_ID:
        return None
    files = data.get("files")
    if not isinstance(files, dict) or not files:
        return None
    # التشغيل محتاج الـexe والموديل نفسه — من غيرهم مفيش تفريغ
    exe = data.get("exe")
    if not isinstance(exe, str) or exe not in files:
        return None
    if "models/" + MODEL_FILE not in files:
        return None
    return MODEL_ID if _files_ok(files) else None


def verify():
    """
    بيفحص بصمة كل ملف في المانيڨست مرة واحدة لكل عملية. النتيجة بتتخزّن على
    هوية المانيڨست (mtime_ns, size) — الموديل 742 MB، فالهاش على كل تفريغ
    كان هيبطّأ الوضع المحلي.
    """
    identity = _manifest_identity()
    if identity is None:
        return False
    result = _verify_cache.get(identity)
    if result is not None:
        return result
    with _lock:
        return _verified_cached_locked()


def _verified_cached_locked():
    """نتيجة الفحص للمانيڨست الحالي من الكاش، أو بتحسبها مرة وتخزّنها — _lock ماسك."""
    identity = _manifest_identity()
    if identity is None:
        return False
    result = _verify_cache.get(identity)
    if result is None:
        result = _verify_locked()
        _verify_cache[identity] = result
    return result


def _verify_locked():
    """الفحص الفعلي — لازم _lock يكون ماسك (عشان remove/download مش يلمسوا الملفات)."""
    data = _manifest_data()
    if not data or data.get("model") != MODEL_ID:
        return False
    files = data.get("files")
    if not isinstance(files, dict) or not files:
        return False
    hashes = data.get("sha256")
    hashes = hashes if isinstance(hashes, dict) else {}
    root = _root()
    for rel, size in files.items():
        p = os.path.join(root, rel.replace("/", os.sep))
        try:
            if not os.path.exists(p) or not asr_pack.is_within(root, p):
                return False
            if rel in hashes:
                if asr_pack.sha256_file(p) != hashes[rel]:
                    return False
            elif os.path.getsize(p) != int(size):
                return False
        except (OSError, TypeError, ValueError):
            return False
    return True


def cached_verification():
    """
    نتيجة الفحص المخزّنة للمانيڨست الحالي: True/False، أو None لو الفحص لسه
    ما اتعملش (أو مفيش مانيڨست). مبيحسبش بصمات هنا.
    """
    identity = _manifest_identity()
    if identity is None:
        return None
    return _verify_cache.get(identity)


# ── التنزيل والتثبيت ─────────────────────────────────────────────────────────
def _extract_runtime(zip_path, dest):
    """
    يفكك أرشيف NeMo-Speech.cpp جوّه dest — كل الملفات. أي member فيه ".." أو
    مسار مطلق أو drive letter أو backslash = الأرشيف كله يترفض (N3).
    """
    import zipfile
    dest_real = os.path.realpath(dest)
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = info.orig_filename
            if name.endswith("/"):          # مجلد — مافيش ملف فيه
                continue
            rel = asr_pack.safe_relative_path(name)
            if rel is None:
                raise RuntimeError("الأرشيف فيه مسار مش سليم — اتلغى التثبيت")
            final = os.path.realpath(os.path.join(dest, rel.replace("/", os.sep)))
            if not final.startswith(dest_real + os.sep):
                raise RuntimeError("الأرشيف فيه مسار مش سليم — اتلغى التثبيت")
            os.makedirs(os.path.dirname(final), exist_ok=True)
            with zf.open(info) as src, open(final, "wb") as dst:
                dst.write(src.read())


def _find_exe(payload_root):
    """مسار nemo-speech.exe جوّه الشجرة المستخرجة (بالـos.sep) — None لو مفيش."""
    for dirpath, _dirs, names in os.walk(payload_root):
        for name in names:
            if name.lower() == EXE_NAME:
                return os.path.join(dirpath, name)
    return None


def _publish(payload_root, root):
    """
    ينقل ملفات الـpayload لمكانها النهائي جوّه root — بيرجّع {مسار نسبي: حجم}.
    كل ملف بينتقل بـos.replace (نفس الـvolume) — والمانيڨست بيتكتب بعدها.
    """
    files = {}
    for dirpath, _dirs, names in os.walk(payload_root):
        for name in names:
            src = os.path.join(dirpath, name)
            rel = os.path.relpath(src, payload_root).replace(os.sep, "/")
            dst = os.path.join(root, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.replace(src, dst)
            files[rel] = os.path.getsize(dst)
    return files


def download(progress=None, cancel=None):
    """
    بينزّل ويجهّز محرّك NeMo-Speech.cpp وموديل Nemotron 3.5. كله في الـstaging،
    والـcommit (نقل الملفات + المانيڨست) آخر خطوة — فلو فشل أي تنزيل مفيش حاجة
    بتتسجّل كـ«مثبّت».
    """
    total = NEMO_SPEECH_SIZE + MODEL_SIZE

    with _dl_lock:
        _runtime_dir, _models_dir, staging, manifest_path = _dirs()
        payload = os.path.join(staging, "payload")
        downloads = os.path.join(staging, "dl")
        asr_pack.clear_dir(staging)
        os.makedirs(os.path.join(payload, "models"), exist_ok=True)
        os.makedirs(downloads, exist_ok=True)

        try:
            # الموديل الأول (الثقيل) وبعدين المحرّك — عشان progress يمشي بالتتابع
            model_file = os.path.join(payload, "models", MODEL_FILE)
            asr_pack.stream_download(MODEL_URL, model_file, MODEL_SHA256, MODEL_SIZE,
                                     progress, 0, total, opener=_open, cancel=cancel)

            zip_file = os.path.join(downloads, NEMO_SPEECH_ARCHIVE)
            asr_pack.stream_download(NEMO_SPEECH_URL, zip_file, NEMO_SPEECH_SHA256,
                                     NEMO_SPEECH_SIZE, progress, MODEL_SIZE, total,
                                     opener=_open, cancel=cancel)

            runtime_payload = os.path.join(payload, "runtime")
            os.makedirs(runtime_payload, exist_ok=True)
            _extract_runtime(zip_file, runtime_payload)

            # فحص دخان: لازم الـexe يشغّل ويطبع نسخة الـruntime من غير مشاكل
            exe = _find_exe(runtime_payload)
            if not exe:
                raise RuntimeError("أرشيف NeMo-Speech.cpp مفيهوش nemo-speech.exe — اتلغى التثبيت")
            if _run([exe, "--version"], timeout=SMOKE_TIMEOUT).returncode != 0:
                raise RuntimeError("nemo-speech مش بيشتغل — اتلغى التثبيت")

            if progress:
                progress(1.0)

            # الـcommit بس (نقل الملفات + المانيڨست) جوه _lock — هنا بنلمس
            # الملفات الحقيقية، فمينفعش يبقى تنزيل/مسح فوق بعض.
            with _lock:
                if cancel is not None and cancel.is_set():
                    raise asr_pack.Cancelled("اتلغى التنزيل")
                root = _root()
                os.makedirs(root, exist_ok=True)
                old_files = _manifest_files(manifest_path)
                files = _publish(payload, root)
                exe_rel = os.path.relpath(exe, payload).replace(os.sep, "/")
                # بصمة الموديل هي المثبّتة (اتأكدنا منها وقت التنزيل) — وبصمات
                # ملفات المحرّك بتتحسب من الملفات اللي فُكّت من أرشيف متأكد منه
                hashes = {}
                for rel in files:
                    if rel == "models/" + MODEL_FILE:
                        hashes[rel] = MODEL_SHA256
                    else:
                        hashes[rel] = asr_pack.sha256_file(
                            os.path.join(root, rel.replace("/", os.sep)))
                manifest = {"model": MODEL_ID, "version": NEMO_SPEECH_VERSION,
                            "exe": exe_rel, "files": files, "sha256": hashes}
                asr_pack.write_json_atomic(manifest_path, manifest)
                _verify_cache.clear()
                # ملفات التثبيت القديم اللي مش في الجديد بتتمسح — غير كده كانت
                # هتفضل تتامى ومحدش يقدر يشيلها من الواجهة
                asr_pack.remove_inside(root, set(old_files) - set(files))
        finally:
            asr_pack.clear_dir(staging)


def _manifest_files(manifest_path):
    """المسارات النسبية المسجّلة في المانيڨست — قايمة فاضية لو مفيش أو بايظ."""
    data, ok = asr_pack.read_json(manifest_path)
    if not ok or not isinstance(data, dict):
        return []
    files = data.get("files")
    return list(files) if isinstance(files, dict) else []


# ── الإزالة ──────────────────────────────────────────────────────────────────
def _known_leftovers():
    """ملفات الباك اللي بنعرفها بالاسم — عشان تثبيت بايظ يتشال برضه."""
    runtime_dir, models_dir, _staging, _manifest = _dirs()
    rels = ["models/" + MODEL_FILE]
    for dirpath, _subdirs, names in os.walk(runtime_dir):
        for name in names:
            rel = os.path.relpath(os.path.join(dirpath, name), _root())
            rels.append(rel.replace(os.sep, "/"))
    return rels


def residual():
    """فيه ملفات باك على الجهاز (حتى لو التثبيت بايظ)؟ — عشان زرار الإزالة يفضل متاح."""
    if os.path.exists(_dirs()[3]):
        return True
    root = _root()
    return any(os.path.exists(os.path.join(root, rel.replace("/", os.sep)))
               for rel in _known_leftovers())


def remove():
    """بيمسح الموديل والمحرّك المثبّتين — تحت اللوك عشان ميتعاركش مع تنزيل."""
    with _lock:
        root = _root()
        asr_pack.remove_inside(root, set(_manifest_files(_dirs()[3])) | set(_known_leftovers()))
        try:
            os.remove(_dirs()[3])
        except OSError:
            pass
        _verify_cache.clear()
        # الـstaging بتاع تنزيل شغّال مينفعش يتلمس — بنمسحه بس لو قدرنا ناخد _dl_lock
        # من غير استنى (يعني مفيش تنزيل في النص).
        if _dl_lock.acquire(blocking=False):
            try:
                asr_pack.clear_dir(_dirs()[2])
            finally:
                _dl_lock.release()


# ── التفريغ ──────────────────────────────────────────────────────────────────
def language_code(language):
    """'ar' → 'ar-AR' · 'en' → 'en-US' · أي حاجة تانية (منها None) → 'auto'."""
    return LANGUAGE_CODES.get(str(language or "").strip().lower(), AUTO_LANGUAGE)


def build_cmd(wav, model_path, language, out_path):
    """
    بيبني أمر nemo-speech: تفريغ wav بالموديل واللغة، والنص في ملف.
    --force عشان الـCLI بيرفض يكتب فوق ملف موجود من غيرها.
    """
    data = _manifest_data() or {}
    exe_rel = data.get("exe") or ("runtime/bin/" + EXE_NAME)
    exe = os.path.join(_root(), exe_rel.replace("/", os.sep))
    return [exe, "transcribe", wav, "--model", model_path,
            "--language", language_code(language), "--format", "text",
            "--output", out_path, "--force"]


def _read_output(path):
    """نص الملف الناتج — من غير وسم اللغة اللي الموديل بيرفقه."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return ""
    return LANG_TAG_RE.sub("", text).strip()


def _error_detail(stderr):
    """آخر جزء من stderr — بيساعد في تشخيص الفشل من ملف اللوج."""
    try:
        text = (stderr or b"").decode("utf-8", "replace")
    except Exception:
        return ""
    return " ".join(text.split())[-200:]


def transcribe(wav, language):
    """
    بيفرّغ wav بـnemo-speech ويرجّع النص. language=None = الموديل يحدّد اللغة
    لوحده، و"ar"/"en" = لغة محدّدة. الفشل بيرمي RuntimeError — مفيش حالة بنرجّع
    فيها نص فاضي وندّعي إنه تفريغ.
    """
    out_path = os.path.join(tempfile.gettempdir(),
                             "emlaa_nemo_%d.txt" % int(time.time() * 1000))

    with _lock:
        if not installed():
            raise RuntimeError("مفيش موديل offline مثبّت — نزّل موديل الأول")
        if not _verified_cached_locked():
            raise RuntimeError("الموديل المحلي بايظ — شيله ونزّله تاني من الإعدادات")
        model_path = os.path.join(_dirs()[1], MODEL_FILE)
        # ملف قديم بنفس الاسم ميتقريش كأنه نتيجة التشغيل ده
        try:
            os.remove(out_path)
        except OSError:
            pass
        text = ""
        try:
            cmd = build_cmd(wav, model_path, language, out_path)
            try:
                r = _run(cmd, timeout=TRANSCRIBE_TIMEOUT)
            except Exception:
                raise RuntimeError("التفريغ offline فشل")
            if r.returncode != 0:
                detail = _error_detail(r.stderr)
                raise RuntimeError("التفريغ offline فشل" + (": " + detail if detail else ""))
            text = _read_output(out_path)
        finally:
            try:
                os.remove(out_path)
            except OSError:
                pass

    if not text:
        raise RuntimeError("التفريغ offline رجّع نص فاضي")
    return text
