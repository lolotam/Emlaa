# -*- coding: utf-8 -*-
"""
أدوات مشتركة لتثبيت باقات التفريغ المحلية (Whisper · Nemotron)
----------------------------------------------------------------
القواعد اللي محرّكين بيستخدموها: تنزيل متحقّق من بصمته وحجمه، فك آمن للأرشيف،
كتابة ذرّية للمانيڨست، تشغيل عملية من غير نافذة console، ومسح ملفات متأكدين إنها
جوّه جذر معروف.

كل محرّك (offline = whisper.cpp · nemotron = NeMo-Speech.cpp) بياخد القواعد من هنا
عشان ما تتكتبش مرتين وتتغيّر في مكان وتنسى التاني.
"""
import hashlib
import json
import os
import shutil
import subprocess
import urllib.request

CREATE_NO_WINDOW = 0x08000000   # عشان مفيش نافذة console تخطف لمّا الـCLI يشتغل
DOWNLOAD_TIMEOUT = 30           # ثواني — مهلة الاتصال/القراية لكل urlopen
CHUNK = 256 * 1024              # حجم القراءة الواحدة من الشبكة
HASH_CHUNK = 1024 * 1024        # حجم قراءة البصمة (من غير تحميل الملف كله في الذاكرة)


class Cancelled(RuntimeError):
    """المستخدم لغى التنزيل — مفيش تثبيت نص نص."""


def _urlopen(url):
    """الفتح الافتراضي — مهلة الاتصال/القراية من غير ما نعلّق للأبد."""
    return urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT)


def sha256_file(path):
    """sha256 لملف بيتقري على قطع HASH_CHUNK — عشان ممن نحمّل الـ742 MB في الذاكرة مرة واحدة."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(HASH_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def stream_download(url, dest, sha256, size, progress=None, done=0, total=0,
                    opener=None, cancel=None):
    """
    بينزّل url لـdest عبر .part، ويتأكد من البصمة والحجم. progress بيتندّى
    بكسر من الإجمالي الكلي للعملية (كل ملفاتها) — مش للملف ده لوحده.
    الإلغاء بيتفحص كل قراءة: الملف بيفضل .part ناقص وما بينشرش.
    """
    h = hashlib.sha256()
    got = 0
    part = dest + ".part"
    fetch = opener if opener is not None else _urlopen
    with fetch(url) as r, open(part, "wb") as f:
        while True:
            if cancel is not None and cancel.is_set():
                raise Cancelled("اتلغى التنزيل")
            chunk = r.read(CHUNK)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
            got += len(chunk)
            if progress and total:
                progress(min(1.0, (done + got) / total))
    if size and got != size:
        raise RuntimeError("الملف نزل ناقص (%d من %d)" % (got, size))
    if sha256 and h.hexdigest() != sha256:
        raise RuntimeError("بصمة الملف مش مطابقة")
    os.replace(part, dest)
    return got


def run(cmd, **kw):
    """process من غير نافذة console — وبناخد stdout/stderr في الذاكرة."""
    return subprocess.run(cmd, capture_output=True, creationflags=CREATE_NO_WINDOW, **kw)


def clear_dir(path):
    """بيمسح فولدر كله — بيستخدم في الفشل وفي أول كل تنزيل."""
    try:
        shutil.rmtree(path)
    except OSError:
        pass


def remove_inside(root, rels):
    """بيمسح المسارات النسبية دي — بس اللي فعلًا جوّه root (مانيفست متلعوب فيه ميمسحش برّه)."""
    root_real = os.path.realpath(root)
    for rel in rels:
        p = os.path.join(root, rel)
        if not os.path.realpath(p).startswith(root_real + os.sep):
            continue
        try:
            os.remove(p)
        except OSError:
            pass


def read_json(path):
    """ملف JSON → (البيانات، سليم؟). ملف مش موجود أو تالف = (None, False)."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), True
    except (OSError, ValueError):
        return None, False


def write_json_atomic(path, data):
    """كتابة ذرّية: ملف مؤقت وبعدين os.replace — الملف عمره ما يبقى نص مكتوب."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def safe_relative_path(name):
    """
    المسار النسبي السليم جوّه الأرشيف، أو None لو المسار ده مش آمن:
    ".." · مسار مطلق · drive letter · backslash · جزء فاضي.
    المسار الآمن بيتقري بـ"/" بس (زي كل أرشيفات zip).
    """
    if not name or name.startswith("/") or name.startswith("\\"):
        return None
    if "\\" in name or ":" in name:
        return None
    parts = name.split("/")
    if any(p in ("", ".", "..") for p in parts):
        return None
    return "/".join(parts)


def is_within(root, path):
    """الملف جوّه الجذر ولا برّه؟ — آخر خط دفاع قبل أي كتابة."""
    return os.path.realpath(path).startswith(os.path.realpath(root) + os.sep)
