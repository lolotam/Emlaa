# -*- coding: utf-8 -*-
"""
إملاء — المحرّك
--------------
تسجيل صوت بالميك → تفريغ عند المزوّد اللي المستخدم اختاره → كتابة النص
مكان المؤشر في أي برنامج.

الملفات اللي جنب البرنامج:
  config.json  الإعدادات (المزوّد، زرار التسجيل، التنظيف…)
  .env         مفاتيح المزوّدين — على جهاز المستخدم بس

الصوت رايح للمزوّد بحساب المستخدم مباشرة — مش بيعدّي علينا.
الاتصال الوحيد بسيرفرنا هو سؤال «آخر إصدار كام؟» (check_update تحت)،
من غير أي بيانات عن المستخدم، وبيتقفل من الإعدادات.
"""
import os
import sys
import time
import json
import wave
import tempfile
import threading
import collections
import urllib.request
from dataclasses import dataclass, field

# ── شهادات SSL جوّه الـexe ───────────────────────────────────────────────────
# نثبّت مسار حزمة certifi كمتغيّر بيئة كمان — عشان أي نداء HTTPS بمكتبة
# بايثون الأصلية (urllib) يلاقي الشهادات جوّه الـexe المبنيّ بـPyInstaller.
try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
except Exception:
    pass

import providers
import smart     # القرارات النقية (تخطّي الردود القصيرة F2…) — core بيستورد smart، مش العكس
import offline   # F9: تفريغ من غير إنترنت — مسار بديل من غير مفتاح ولا شبكة (بيتستورد core جوّه دواله بس)

# ── مسار البيانات ────────────────────────────────────────────────────────────
# لما يبقى .exe مبنيّ بـPyInstaller، __file__ بيبقى فولدر مؤقت — فبنستخدم
# مكان الـexe نفسه عشان الإعدادات والمفاتيح تفضل جنبه.
def _is_packaged():
    """هل البرنامج متثبّت كحزمة MSIX (نسخة Microsoft Store)؟"""
    try:
        import ctypes
        n = ctypes.c_uint32(0)
        # APPMODEL_ERROR_NO_PACKAGE (15700) = برنامج عادي مش حزمة
        return ctypes.windll.kernel32.GetCurrentPackageFullName(ctypes.byref(n), None) != 15700
    except Exception:
        return False


# نسخة الـStore: فولدر البرنامج للقراية بس، والتحديثات بتيجي من الـStore نفسه.
# EMLAA_STORE_TEST=1 بيجرّب سلوك نسخة الـStore من غير ما نبني حزمة.
PACKAGED = getattr(sys, "frozen", False) and _is_packaged()
STORE = PACKAGED or os.environ.get("EMLAA_STORE_TEST") == "1"

if PACKAGED:
    BASE = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Emlaa")
    os.makedirs(BASE, exist_ok=True)
elif getattr(sys, "frozen", False):
    BASE = os.path.dirname(sys.executable)
else:
    _here = os.path.dirname(os.path.abspath(__file__))
    _parent = os.path.dirname(_here)
    if os.path.exists(os.path.join(_parent, "config.json")) or os.path.exists(os.path.join(_parent, ".env")):
        BASE = _parent
    else:
        BASE = _here

CFG_PATH  = os.path.join(BASE, "config.json")
ENV_PATH  = os.path.join(BASE, ".env")
SHOW_PATH = os.path.join(BASE, ".show-request")


# ── نسخة واحدة بس ────────────────────────────────────────────────────────────
_MUTEX = None


def single_instance():
    """
    بيمنع تشغيل نسخة تانية. ده مش تحسين شكلي:

    قفل النافذة بيصغّر البرنامج جنب الساعة مش بيقفله — فالمستخدم بيدوس على
    الـexe تاني فاكر إنه قافله، وتبقى نسختين شغّالين. الاتنين بيسجّلوا **نفس
    زرار التسجيل**، فالنسخة القديمة ممكن ترد على الزرار بالمزوّد القديم رغم
    إنك غيّرته، والاتنين بيكتبوا في نفس config.json فالإعدادات بتتلغبط.

    بيرجّع True لو إحنا النسخة الأولى.
    """
    global _MUTEX
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        _MUTEX = k32.CreateMutexW(None, False, "EmlaaSingleInstance")
        return k32.GetLastError() != 183          # ERROR_ALREADY_EXISTS
    except Exception:
        return True                               # لو الفحص نفسه فشل، ما نمنعش حد


def request_show():
    """النسخة التانية بتسيب علامة، والنسخة الشغّالة بتفتح نافذتها وتمسحها."""
    try:
        open(SHOW_PATH, "w").close()
    except Exception:
        pass


DEFAULTS = {
    "provider":          providers.DEFAULT,
    "models":            {},        # موديل التفريغ المختار لكل مزوّد {provider: model}
    "hotkey":            "ctrl_r",
    "hotkey_normal":     "ctrl_r",
    "hotkey_prompt":     "alt_r",
    "hotkey_translate":  "shift_r",
    "hotkey_edit":       "",        # F6: زرار التعديل في المكان — "" = مقفول
    "overlay_x":         None,
    "overlay_y":         None,
    "mode":              "toggle",  # ضغطة تبدأ وضغطة توقف (hold = امسك واتكلم)
    "mic":               "",
    "language":          "ar",
    "offline_mode":      "fallback",  # F9: "fallback" = لما النت يقطع بس · "always" = دايمًا من غير شبكة
    "offline_model":     "",          # آخر موديل offline اختاره المستخدم في الإعدادات
    "polish":            True,
    "bypass_short":      True,    # ردود قصيرة من القايمة → من غير لفة LLM خالص (F2)
    "bypass_max_words":  3,       # حد عدد الكلمات اللي بيتسمح التخطّي فيه
    "context_styles":    True,    # أساليب السياق: شكل الكتابة بيتغيّر حسب البرنامج (F5)
    "app_profiles":      {},      # overrides: {اسم البرنامج: dev/chat/formal}
    "prompt_mode":       False,
    "auto_paste":        True,
    "insert_method":     "auto",   # F3: auto = Ctrl+V للنص الطويل/المتعدد، وإلا حرف حرف
    "beep":              True,
    "minimize_to_tray":  True,
    "check_updates":     True,
    "auto_update":       True,      # نزّل وثبّت الإصدار الجديد لوحده (بعد ما التسجيل يخلص)
    "floating_button":   False,     # الموجة بتظهر وقت التسجيل بس؛ True = زرار صغير ظاهر طول الوقت
    "dictionary":        [],        # كلمات وأسماء خاصة — بتتبعت للموديل عشان يكتبها صح
    "snippets":          [],        # اختصارات صوتية: {trigger, text} — الكلام المطابق بيتوسّع لنص جاهز (F8)
    "clipboard_history": True,      # يحفظ كل حاجة بتتنسخ في قسم الحافظة
    "open_hotkey":       "<ctrl>+<alt>+n",
    "theme":             "dark",    # dark / light / system
    "lang":              "ar",      # لغة الواجهة: ar / en
    "history_keep_last10": True,    # السجل بيحتفظ بآخر 10 تسجيلات بس والأقدم بيتمسح
}

SR = 16000          # 16kHz mono — الأنسب لموديلات التفريغ
HISTORY_PATH = os.path.join(BASE, "history.json")


_store_lock = threading.RLock()


def _read_list(path):
    """
    بيقرا ملف JSON فيه list. بيرجّع (البيانات, سليم؟).
    ملف مش موجود = ([], True). ملف بايظ = ([], False) — واللي بيكتب لازم
    مايكتبش فوقه (كان بيحصل: قراية فاشلة = سجل فاضي = الكتابة تمسح كل القديم).
    """
    if not os.path.exists(path):
        return [], True
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return (data, True) if isinstance(data, list) else ([], False)
    except Exception:
        return [], False


def _write_list(path, items):
    """
    كتابة آمنة: ملف مؤقت وبعدين os.replace — الملف عمره ما يبقى نص مكتوب
    حتى لو البرنامج اتقفل غصب في النص.
    """
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _load_for_write(path, where):
    """
    زي _read_list بس للي هيكتب: لو الملف بايظ، بنحتفظ بيه باسم تاني
    (history.corrupt-<الوقت>.json) بدل ما يضيع، ونسجّل في اللوج.
    """
    items, ok = _read_list(path)
    if not ok:
        bak = "%s.corrupt-%d.json" % (os.path.splitext(path)[0], int(time.time()))
        try:
            os.replace(path, bak)
        except Exception:
            pass
        log_error(RuntimeError("الملف مكانش بيتقري — اتحفظ نسخة منه في " + bak), where)
    return items


def history_get(limit=100):
    """بيرجّع سجل التسجيلات من الأحدث للأقدم."""
    return _read_list(HISTORY_PATH)[0][:limit]


def history_add(mode, raw_text, result_text, dur=None, engine=None, bypass=False, app=""):
    """
    بيحفظ عملية تسجيل جديدة في ملف history.json (dur = طول التسجيل بالثواني،
    engine = مين فرّغ ومين نضّف، bypass = الـLLM اتتخطّت للرد القصير F2،
    app = اسم البرنامج اللي اتكتب قدامه F5). بيرجّع الـid عشان الصوت يتحفظ بيه.
    """
    if not result_text or not result_text.strip():
        return None
    import datetime
    now = datetime.datetime.now()
    entry = {
        "id": int(now.timestamp() * 1000),
        "time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "time_display": now.strftime("%I:%M %p").lstrip("0"),
        "date_display": now.strftime("%Y/%m/%d"),
        "mode": mode or "normal",
        "raw": (raw_text or "").strip(),
        "result": result_text.strip(),
        "words": len((raw_text or "").split()),
    }
    if dur:
        entry["dur"] = round(float(dur), 2)
    if engine:
        entry["engine"] = engine
    if bypass:
        # بيتكتب بس لو الـLLM اتتخطّت فعلًا — السجلات العادية والقديمة من غيره،
        # والواجهة بتقراه بـ .get
        entry["bypass"] = True
    if app:
        # F5: بيتكتب بس لو اسم البرنامج اتعرف فعلًا — السجلات القديمة والأقدم
        # من غير المفتاح، والواجهة بتقراه بـ .get
        entry["app"] = app
    with _store_lock:
        items = _load_for_write(HISTORY_PATH, "history/read")
        items.insert(0, entry)
        try:
            _write_list(HISTORY_PATH, items[:history_cap()])
        except Exception as e:
            log_error(e, "history/write")
    return entry["id"]


# ── صوت آخر ١٠ تسجيلات (يتسمع ويتنزّل mp3 من السجل) ─────────────────────────
RECORDINGS_DIR = os.path.join(BASE, "recordings")
AUDIO_KEEP = 10


def recording_path(rid):
    return os.path.join(RECORDINGS_DIR, f"{int(rid)}.mp3")


def recording_ids():
    """الـid بتاع كل تسجيل صوته محفوظ."""
    try:
        names = os.listdir(RECORDINGS_DIR)
    except FileNotFoundError:
        return set()
    return {int(n[:-4]) for n in names if n.endswith(".mp3") and n[:-4].isdigit()}


def recording_save(rid, wav):
    """يحوّل الـwav لـmp3 (‏64kbps ≈ ٨ كيلو للثانية) ويحفظه باسم الـid، وبعدين يشيل الزيادة."""
    try:
        import lameenc
        with wave.open(wav, "rb") as w:
            pcm, rate, ch = w.readframes(w.getnframes()), w.getframerate(), w.getnchannels()
        enc = lameenc.Encoder()
        enc.set_bit_rate(64)
        enc.set_in_sample_rate(rate)
        enc.set_channels(ch)
        enc.set_quality(2)
        data = enc.encode(pcm) + enc.flush()
        os.makedirs(RECORDINGS_DIR, exist_ok=True)
        tmp = recording_path(rid) + ".tmp"
        try:
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, recording_path(rid))
        except Exception:
            # الملف المؤقت فيه صوت المستخدم — لو فشلنا نكتبه أو نبدّله لازم يتمسح
            # مش يفضل معلق (الـprune كان بيتجاهله خالص)
            try:
                os.remove(tmp)
            except Exception:
                pass
            raise
    except Exception as e:
        log_error(e, "recordings/save")
    recordings_prune()


def _remove_stray_tmp():
    """بيمسح ملفات .mp3.tmp اللي فضلت من كتابة فاشلة (بيبقى فيها صوت مسجّل)."""
    try:
        for n in os.listdir(RECORDINGS_DIR):
            if n.endswith(".mp3.tmp"):
                try:
                    os.remove(os.path.join(RECORDINGS_DIR, n))
                except Exception as e:
                    log_error(e, "recordings/prune")
    except FileNotFoundError:
        pass
    except Exception as e:
        log_error(e, "recordings/prune")


def recordings_prune():
    """
    الصوت بيفضل لآخر AUDIO_KEEP تسجيلات موجودة في السجل بس: أي ملف أقدم،
    أو تسجيله اتمسح من السجل، بيتمسح (الـid = وقت التسجيل، فالأكبر = الأحدث).
    """
    with _store_lock:
        _remove_stray_tmp()
        items, ok = _read_list(HISTORY_PATH)
        if not ok:                     # السجل بايظ = مانعرفش مين عايش — مانمسحش صوت حد
            return
        live = {i.get("id") for i in items}
        ids = sorted(recording_ids(), reverse=True)
        keep = set([i for i in ids if i in live][:AUDIO_KEEP])
        for i in ids:
            if i not in keep:
                try:
                    os.remove(recording_path(i))
                except Exception as e:
                    log_error(e, "recordings/prune")


def history_cap():
    """عدد التسجيلات اللي بتتحفظ: 10 لو «احتفظ بآخر 10» شغّال، وإلا 1000."""
    return 10 if CFG.get("history_keep_last10", True) else 1000


def history_prune():
    """بيطبّق الحد على السجل الموجود (لما الإعداد يتفعّل)."""
    with _store_lock:
        items, ok = _read_list(HISTORY_PATH)
        if ok and len(items) > history_cap():
            try:
                _write_list(HISTORY_PATH, items[:history_cap()])
            except Exception as e:
                log_error(e, "history/prune")
    recordings_prune()


def history_clear():
    """يمسح السجل بالكامل."""
    try:
        if os.path.exists(HISTORY_PATH):
            os.remove(HISTORY_PATH)
    except Exception:
        pass
    recordings_prune()


def history_delete(ids):
    """يمسح تسجيلات معيّنة بالـid."""
    ids = set(ids or [])
    with _store_lock:
        items = [i for i in _load_for_write(HISTORY_PATH, "history/read") if i.get("id") not in ids]
        try:
            _write_list(HISTORY_PATH, items)
        except Exception as e:
            log_error(e, "history/write")
    recordings_prune()


def history_stats():
    """
    أرقام الصفحة الرئيسية من السجل الحقيقي:
    عدد الكلمات، الوقت اللي اتوفّر مقارنة بالكتابة (٤٠ كلمة/دقيقة)، ومتوسط سرعة الإملاء.
    السرعة بتتحسب بس من التسجيلات اللي اتحفظ طولها (الجديدة).
    """
    items = history_get(limit=1000)
    words = sum(i.get("words") or len((i.get("raw") or "").split()) for i in items)
    timed = [i for i in items if i.get("dur")]
    t_words = sum(i.get("words") or len((i.get("raw") or "").split()) for i in timed)
    t_secs = sum(i["dur"] for i in timed)
    wpm = round(t_words / (t_secs / 60)) if t_secs >= 1 else None
    spoken_min = (t_secs / 60) if timed else words / 130.0     # تقدير لو مفيش أطوال
    saved_min = max(0.0, words / 40.0 - spoken_min)
    return {"words": words, "count": len(items), "wpm": wpm,
            "saved_min": round(saved_min, 1)}


# ── سجل الحافظة (كل حاجة بتتنسخ في الويندوز) ─────────────────────────────────
CLIP_PATH = os.path.join(BASE, "clipboard.json")
_clip_lock = threading.Lock()

def clip_get():
    return _read_list(CLIP_PATH)[0]


def _clip_save(items):
    try:
        _write_list(CLIP_PATH, items)
    except Exception as e:
        log_error(e, "clipboard/write")


def clip_add(text, source=""):
    import datetime
    text = (text or "")
    if not text.strip():
        return None
    text = text[:20000]
    with _clip_lock:
        items = _load_for_write(CLIP_PATH, "clipboard/read")
        # نفس النص اتنسخ تاني → نطلّعه فوق بدل ما يتكرر
        items = [i for i in items if i.get("text") != text]
        now = datetime.datetime.now()
        entry = {"id": int(now.timestamp() * 1000), "time": now.strftime("%Y-%m-%d %H:%M:%S"),
                 "text": text, "source": source or ""}
        items.insert(0, entry)
        _clip_save(items[:1000])
    return entry


def clip_delete(ids):
    ids = set(ids or [])
    with _clip_lock:
        _clip_save([i for i in _load_for_write(CLIP_PATH, "clipboard/read") if i.get("id") not in ids])


def clip_clear():
    with _clip_lock:
        _clip_save([])


# ── أرقام تسلسل الحافظة «بتاعتنا» ────────────────────────────────────────────
# لما أسر التحديد (winput.capture_target) بيكتب ويرجّع نصوص في الحافظة، رقم
# التسلسل بيتغيّر كذا مرة — والـClipboardWatcher كان هيسجّل النصوص دي كأنها نسخ
# حقيقية من المستخدم. بنحتفظ بآخر 64 رقم تسلسل وسمناهم، والـwatcher بيتخطاهم.
_owned_clip_lock = threading.Lock()
_owned_clip_seqs = collections.deque(maxlen=64)


def mark_clip_owned(seq):
    """يوسّم رقم تسلسل حافظة كـ«بتاعنا» — الـClipboardWatcher يتخطاه."""
    try:
        seq = int(seq)
    except (TypeError, ValueError):
        return
    with _owned_clip_lock:
        _owned_clip_seqs.append(seq)


def _clip_is_owned(seq):
    """True لو رقم التسلسل ده من عمليات الحافظة بتاعتنا."""
    with _owned_clip_lock:
        return seq in _owned_clip_seqs


# ── كبس مراقب الحافظة مؤقتًا (M4) ─────────────────────────────────────────────
# قبل ما ننشر حاجة إحنا بنفسنا للحافظة (أسر Ctrl+C أو نسخ نص اختصار) بنكب المراقب
# لفترة قصيرة: التغيير بيحصل بسرعة ورقم التسلسل بيتوسم «بتاعتنا» بعده — بس الفجوة
# بين النشر والوسم كانت بتخلّي المراقب (اللي بيقرا كل نص ثانية) يسجّل النص بتاعنا
# كنسخة حقيقية. الكبس بيمنع ده من غير ما يقدّم `last`، فبعد انتهاء الكبس المراقب
# بيعيد تقييم الرقم الحالي (بتاعنا → يتخطى، نسخة مستخدم → تتسجل).
_clip_suppress_lock = threading.Lock()
_clip_suppress_until = 0.0


def suppress_clip_watch(seconds):
    """بيمنع مراقب الحافظة من التسجيل لحد `seconds` ثانية من دلوقتي."""
    global _clip_suppress_until
    with _clip_suppress_lock:
        _clip_suppress_until = time.monotonic() + seconds


def _clip_watch_suppressed():
    """True لو المراقب مكبوت دلوقتي."""
    with _clip_suppress_lock:
        return time.monotonic() < _clip_suppress_until


def _clip_read_text(u32, k32, cf_unicodetext):
    """
    نص الحافظة الحالي عبر Win32 — None لو مقدرناش نقراه. مستقل عن _watch_once
    عشان الاختبار يزوّد قراية مزيّفة من غير GlobalLock ولا wstring_at حقيقي.
    """
    import ctypes
    text = None
    for _ in range(5):                       # برنامج تاني ممكن يكون فاتحها
        if u32.OpenClipboard(None):
            try:
                h = u32.GetClipboardData(cf_unicodetext)
                if h:
                    p = k32.GlobalLock(h)
                    if p:
                        try:
                            text = ctypes.wstring_at(p)
                        finally:
                            k32.GlobalUnlock(h)
            finally:
                u32.CloseClipboard()
            break
        time.sleep(0.05)
    return text


class ClipboardWatcher:
    """
    بيراقب الحافظة (بيقرا رقم التغيير من الويندوز كل نص ثانية) وبيحفظ أي نص جديد.
    بيحترم علامة «ExcludeClipboardContentFromMonitorProcessing» اللي برامج
    الباسوردات بتحطها — فالباسوردات المنسوخة منها مش بتتحفظ. وبيتخطى أي رقم
    تسلسل اتوسم «بتاعنا» (mark_clip_owned) — التغييرات اللي إحنا عملناها بنفسنا.
    """

    def __init__(self, on_new=None):
        self.on_new = on_new
        self._stop = threading.Event()
        self._t = None

    def start(self):
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        import ctypes
        from ctypes import wintypes
        u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
        u32.GetClipboardData.restype = wintypes.HANDLE
        k32.GlobalLock.restype = ctypes.c_void_p
        k32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        k32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        excl = u32.RegisterClipboardFormatW("ExcludeClipboardContentFromMonitorProcessing")
        CF_UNICODETEXT = 13
        last = u32.GetClipboardSequenceNumber()
        while not self._stop.wait(0.5):
            try:
                last = self._watch_once(u32, k32, excl, CF_UNICODETEXT, last)
            except Exception as e:
                log_error(e, "clipboard/watch")
                time.sleep(2)

    def _watch_once(self, u32, k32, excl, cf_unicodetext, last):
        """
        تكرار واحد من المراقبة: بيرجّع قيمة last الجديدة. مستقل عن _run عشان
        الاختبار يقدر يشغّل دورة واحدة بـuser32 مزيّف من غير ثريد ولا نوم حقيقي.
        """
        seq = u32.GetClipboardSequenceNumber()
        if seq == last or not CFG.get("clipboard_history", True):
            return seq
        # M4: مكبوت = ممن نسجّل التغيير وممن نقدّم last — لما الكبس ينتهي
        # بنعيد تقييم الرقم الحالي من أول وجديد.
        if _clip_watch_suppressed():
            return last
        if _clip_is_owned(seq):
            return seq
        if u32.IsClipboardFormatAvailable(excl) or not u32.IsClipboardFormatAvailable(cf_unicodetext):
            return seq
        text = _clip_read_text(u32, k32, cf_unicodetext)
        # N3: بعد القراية نعيد قراية رقم التسلسل — لو اتغيّر في النص (نسخة تانية
        # وصلت جوّه قرايتنا) فالقراية بتاعت نص قديم/حد تاني → نتجاهلها ومبنقدّمش
        # last، عشان التكرار الجاي يعيد تقييم الرقم الحالي من أول.
        if u32.GetClipboardSequenceNumber() != seq:
            return last
        if text and text.strip():
            e = clip_add(text, _foreground_app())
            if e and self.on_new:
                self.on_new(e)
        return seq


def _foreground_app():
    """اسم البرنامج اللي في المقدمة (chrome، code، …) — بيتعرض جنب كل نسخة."""
    try:
        import ctypes
        from ctypes import wintypes
        u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
        pid = wintypes.DWORD()
        u32.GetWindowThreadProcessId(u32.GetForegroundWindow(), ctypes.byref(pid))
        h = k32.OpenProcess(0x1000, False, pid.value)       # QUERY_LIMITED_INFORMATION
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(520)
            n = wintypes.DWORD(520)
            if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                return os.path.splitext(os.path.basename(buf.value))[0]
        finally:
            k32.CloseHandle(h)
    except Exception:
        pass
    return ""


def asset(name):
    """مسار ملف مرفق (أيقونة) — بيشتغل في وضع التطوير و وضع الـexe."""
    root = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    p = os.path.join(root, name)
    return p if os.path.exists(p) else os.path.join(BASE, name)


# ── الإعدادات ────────────────────────────────────────────────────────────────
def load_config():
    cfg = dict(DEFAULTS)
    if os.path.exists(CFG_PATH):
        try:
            cfg.update(json.load(open(CFG_PATH, encoding="utf-8")))
        except Exception:
            pass
    if not cfg.get("hotkey_normal") and cfg.get("hotkey"):
        cfg["hotkey_normal"] = cfg["hotkey"]
    return cfg



def save_config(cfg):
    try:
        json.dump(cfg, open(CFG_PATH, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
    except Exception:
        pass


# ── التحديث (GitHub Releases) ────────────────────────────────────────────────
# النداء الوحيد اللي البرنامج بيعمله لـGitHub: بيسأل «آخر إصدار كام؟» من صفحة
# الإصدارات العامة. مبيبعتش أي حاجة عنك — لا مفتاح ولا كلام ولا معرّف جهاز.
# لو فيه إصدار أحدث: بينزّل Emlaa.exe الجديد جنب القديم، يتأكد من حجمه وبصمته
# (sha256)، يبدّلهم، ويشغّل النسخة الجديدة. إعداداتك ومفاتيحك وسجلّك في ملفات
# منفصلة جنب البرنامج، فمش بتتلمس.
GITHUB_REPO = "lolotam/Emlaa"
RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases/latest"
ASSET_NAME = "Emlaa.exe"


def _gh_request(url, current_version, accept="application/vnd.github+json"):
    return urllib.request.Request(url, headers={
        "User-Agent": f"Emlaa/{current_version}", "Accept": accept})


def check_update(current_version, timeout=8):
    """
    بيرجّع dict فيه {version, url, notes, asset_url, size, sha256} لو فيه إصدار أحدث، أو None.
    أي فشل = None (البرنامج مالوش دعوة بفشل ده).
    نسخة الـStore مبتسألش GitHub خالص — الـStore هو اللي بيحدّثها.
    """
    if STORE:
        return None
    try:
        with urllib.request.urlopen(_gh_request(RELEASES_API, current_version),
                                    timeout=timeout, context=providers._ssl_context()) as r:
            data = json.loads(r.read().decode("utf-8"))
        if data.get("draft") or data.get("prerelease"):
            return None
        latest = str(data.get("tag_name", "")).strip().lstrip("vV")
        if not (latest and _newer(latest, current_version)):
            return None
        asset = next((a for a in data.get("assets", []) if a.get("name") == ASSET_NAME), None) \
            or next((a for a in data.get("assets", []) if str(a.get("name", "")).lower().endswith(".exe")), None)
        digest = str((asset or {}).get("digest") or "")
        return {"version": latest,
                "url": data.get("html_url") or RELEASES_PAGE,
                "notes": (data.get("body") or "").strip()[:1500],
                "asset_url": (asset or {}).get("browser_download_url"),
                "size": (asset or {}).get("size"),
                "sha256": digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else None,
                "can_install": bool(asset) and can_self_update()}
    except Exception:
        return None


def can_self_update():
    """التحديث التلقائي شغّال بس من الـexe، ولو الفولدر بتاعه نقدر نكتب فيه."""
    if STORE or not getattr(sys, "frozen", False):
        return False
    return os.access(os.path.dirname(sys.executable), os.W_OK)


def download_update(info, progress=None, current_version="0"):
    """بينزّل الـexe الجديد جنب القديم باسم مؤقت ويتأكد منه. بيرجّع المسار."""
    import hashlib
    exe = sys.executable
    tmp = exe + ".download"
    h = hashlib.sha256()
    got = 0
    total = int(info.get("size") or 0)
    req = _gh_request(info["asset_url"], current_version, accept="application/octet-stream")
    with urllib.request.urlopen(req, timeout=30, context=providers._ssl_context()) as r, open(tmp, "wb") as f:
        total = total or int(r.headers.get("Content-Length") or 0)
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk); h.update(chunk); got += len(chunk)
            if progress and total:
                progress(min(99, int(got * 100 / total)))
    try:
        if total and got != total:
            raise RuntimeError(f"الملف نزل ناقص ({got} من {total})")
        if info.get("sha256") and h.hexdigest() != info["sha256"]:
            raise RuntimeError("بصمة الملف مش مطابقة — اتلغى التحديث")
        with open(tmp, "rb") as f:
            if f.read(2) != b"MZ":
                raise RuntimeError("الملف اللي نزل مش برنامج ويندوز")
    except Exception:
        try:
            os.remove(tmp)
        except Exception:
            pass
        raise
    return tmp


def install_update(tmp):
    """
    بيبدّل الـexe ويجهّز تشغيل النسخة الجديدة بعد ما البرنامج ده يقفل.
    ويندوز بيسمح نغيّر اسم برنامج شغّال، فبنسمّي القديم .old ونحط الجديد مكانه.
    """
    import subprocess
    exe = sys.executable
    old = exe + ".old"
    try:
        if os.path.exists(old):
            os.remove(old)
    except Exception:
        pass
    os.replace(exe, old)
    try:
        os.replace(tmp, exe)
    except Exception:
        os.replace(old, exe)          # رجّع القديم زي ما كان
        raise
    # بعد ما العملية دي تخلص (والـmutex يتفك) شغّل النسخة الجديدة
    ps = (f"Wait-Process -Id {os.getpid()} -ErrorAction SilentlyContinue; "
          f"Start-Sleep -Milliseconds 700; Start-Process -FilePath '{exe.replace(chr(39), chr(39) * 2)}'")
    subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
                     creationflags=0x08000000 | 0x00000200,      # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
                     close_fds=True)


def cleanup_update_leftovers():
    """بيمسح النسخة القديمة (.old) وأي تنزيل ناقص — بيتنده أول ما البرنامج يفتح."""
    if not getattr(sys, "frozen", False):
        return
    for suffix in (".old", ".download"):
        try:
            p = sys.executable + suffix
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            pass


def _newer(a, b):
    """a أحدث من b؟ مقارنة رقمية عشان 1.10 تبقى أحدث من 1.9 مش العكس."""
    def parts(v):
        out = []
        for chunk in str(v).split("."):
            digits = "".join(c for c in chunk if c.isdigit())
            out.append(int(digits) if digits else 0)
        return out
    pa, pb = parts(a), parts(b)
    n = max(len(pa), len(pb))
    pa += [0] * (n - len(pa))
    pb += [0] * (n - len(pb))
    return pa > pb


CFG = load_config()


def beep(freq, dur):
    if not CFG.get("beep"):
        return
    try:
        import winsound
        winsound.Beep(freq, dur)
    except Exception:
        pass


# ── التسجيل ──────────────────────────────────────────────────────────────────
class Recorder:
    """
    الميك بيفضل مفتوح من أول ما البرنامج يشتغل (hot mic)، وبنجمّع الصوت وقت
    التسجيل بس. كده أول لحظة من الكلام بتتسجّل من غير تأخير ولا قصّ.
    """

    def __init__(self):
        import sounddevice as sd, numpy as np
        self.sd, self.np = sd, np
        self._frames = []
        self._active = False
        self._lock = threading.Lock()
        self._level = 0.0
        self.stream = None
        self._open()

    def _open(self):
        """
        بيفتح الميك. لو الجهاز المحفوظ في الإعدادات مش موجود (هيدفون اتفصل،
        أو ميك USB اتشال) بنرجع للجهاز الافتراضي بدل ما البرنامج يقع.

        قبل كده كان أي تغيير في أجهزة الصوت بيمنع البرنامج إنه يشتغل أصلًا،
        والمستخدم ميعرفش السبب ولا يعرف يغيّر الإعداد لأن الواجهة مش بتفتح.
        """
        saved = (CFG.get("mic") or "").strip() or None
        last = None
        for device in ([saved, None] if saved else [None]):
            try:
                st = self.sd.InputStream(samplerate=SR, channels=1, dtype="int16",
                                         device=device, blocksize=0, callback=self._cb)
                st.start()
                self.stream = st
                if saved and device is None:
                    # الجهاز المحفوظ مش موجود — نمسحه عشان ما يفشلش تاني
                    CFG["mic"] = ""
                    save_config(CFG)
                    log_error(last or RuntimeError("mic fallback"), "recorder/fallback-to-default")
                return
            except Exception as e:
                last = e
        raise last or RuntimeError("مفيش ميكروفون")

    def _alive(self):
        try:
            return bool(self.stream) and self.stream.active
        except Exception:
            return False

    def ensure_open(self):
        """
        بينده قبل كل تسجيل. لو الستريم مات في النص (الجهاز اتفصل والبرنامج
        شغّال) بنحاول نفتحه تاني بدل ما التسجيل يطلع فاضي من غير ما حد يفهم.
        """
        if self._alive():
            return True
        try:
            if self.stream:
                try:
                    self.stream.close()
                except Exception:
                    pass
            self._open()
            return True
        except Exception as e:
            log_error(e, "recorder/reopen")
            return False

    def _cb(self, indata, frames, tinfo, status):
        # المستوى بيتحسب دايمًا (الميك مفتوح من البداية) عشان مؤشّر الموجة
        # يقرا صوت المستخدم علطول — مش وقت التسجيل بس. الفريمات بس هي اللي
        # بتتجمّع وقت التسجيل.
        try:
            self._level = float(self.np.abs(indata).mean()) / 3000.0
        except Exception:
            pass
        if self._active:
            with self._lock:
                self._frames.append(indata.copy())

    @property
    def level(self):
        """0..1 — بيتستخدم في مؤشّر الصوت المتحرّك في الواجهة."""
        return min(1.0, self._level)

    def start(self):
        with self._lock:
            self._frames = []
        self._level = 0.0
        self._active = True

    def stop(self):
        self._active = False
        time.sleep(0.05)                      # نلحق آخر بلوك صوت
        with self._lock:
            frames, self._frames = self._frames, []
        self._level = 0.0
        if not frames:
            return None
        audio = self.np.concatenate(frames, axis=0)
        if len(audio) < int(SR * 0.3):        # أقل من ٣ من عشرة = دوسة غلط
            return None
        wav = os.path.join(tempfile.gettempdir(), f"emlaa_{int(time.time() * 1000)}.wav")
        with wave.open(wav, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
            w.writeframes(audio.tobytes())
        return wav

    def discard(self):
        """يوقف التجميع ويرمي الصوت من غير ما يكتب ملف (زرار الإلغاء)."""
        self._active = False
        with self._lock:
            self._frames = []
        self._level = 0.0

    def close(self):
        try:
            self.stream.stop(); self.stream.close()
        except Exception:
            pass


# ── كتابة النص مكان المؤشر ───────────────────────────────────────────────────
def has_text_focus():
    """
    True لو المؤشر واقف في خانة كتابة (Edit / Document قابل للكتابة)،
    False لو مفيش (سطح المكتب، صورة، زرار…)، None لو مقدرناش نعرف.
    بيستخدم UI Automation — بيشتغل مع كروم وVS Code والبرامج العادية.
    (F3: الشغل اتنقّل لـwinput.focused_info — الكفاية هنا ترفيلة بنفس العقد القديم.)
    """
    import winput
    return winput.focused_info()["editable"]


def _copy_to_clipboard(text):
    """بيرجّع True/False هل نشري النص للحافظة نجح — مش بيقطع الشغل لو فشل."""
    try:
        import pyperclip
        pyperclip.copy(text)
        return True
    except Exception as e:
        log_error(e, "clipboard/copy")
        return False


def _mark_owned_if_snippet(from_snippet):
    """لو النص اللي اننسخ جاي من اختصار صوتي، نعلّم رقم تغييره إنه بتاعنا."""
    if from_snippet:
        import winput
        mark_clip_owned(winput._clipboard_sequence())


def _pre_copy_suppress(from_snippet):
    """كبس المراقب قبل نشر نص اختصار (M4) — عشان مايتسجلش كنسخة حقيقية."""
    if from_snippet:
        suppress_clip_watch(1.0)


def paste_text(text, target=None, from_snippet=False, guard=None):
    """
    بيحقن النتيجة مكان المؤشر حسب تصنيف الهدف (smart.insert_target — F3):
      "placed"      = الأحداث اتحقنت كويس
      "failed"      = الحقن فشل بس النص على الحافظة (المستخدم يقدر يلزقه)
      "clip_failed" = مفيش حقن ولا نسخة على الحافظة (نشر الحافظة فشل، أو
                      الكتابة فشلت والنسخة الاحتياطية فشلت كمان)
      "handoff"     = ممن متحقن (مفيش خانة كتابة / auto_paste مقفول / متعدد في
                      ترمنال…) — النص بيتنسخ (غير الخانات الآمنة) والواجهة بتعرضه
    target = نتيجة insert_target اللي جات من process() (تصنيف مرة واحدة
    لكل نتيجة)؛ لو ماسكة، بيتحسب هنا عشان العقد القديم بيرحم.
    from_snippet = النص جاي من اختصار صوتي — أي نسخة للحافظة بتتعلم إنها بتاعتنا
    عشان مراقب الحافظة مايسجلهاش (نص الاختصار اتسجّل بالفعل كإملاء).
    guard = دالة فحص قبل الحقن مباشرة (M6): بتتندّى بعد sleep الفوكس، ولو رجّعت
    False منحقنش ونسلّم النص زي مسار الـhandoff (نسخ غير الخانات الآمنة).
    """
    import winput
    if target is None:
        info = winput.focused_info()
        info["exe"] = _foreground_app()
        target = smart.insert_target(info, text, CFG.get("insert_method"))
    cls, strategy, inj = target
    if strategy == "handoff" or not CFG.get("auto_paste", True):
        # مفيش حقن: ننسخ للمستخدم والواجهة تعرضه — غير الخانة الآمنة:
        # دي عمرها ماتوصل للحافظة
        if cls != "secure":
            # L3: لو نشر الحافظة فشل مفيش حاجة وصلت للمستخدم — منرجعش "handoff"
            # (كانت بتتسجّل "done" فوقها)؛ نرجّع "clip_failed" والـcaller ينشر خطأ.
            _pre_copy_suppress(from_snippet)
            if not _copy_to_clipboard(inj):
                return "clip_failed"
            _mark_owned_if_snippet(from_snippet)
        return "handoff"
    time.sleep(0.12)                            # نفوز الفوكس يثبت قبل ما نحقن
    # الفحص الأخير لازم يبقى قبل الحقن على طول (بعد تجهيز الحافظة اللي ممكن تاخد وقت):
    # فحص قبلها بكتير كان بيسيب فرصة إن الفوكس يتنقل والنتيجة تتكتب في مكان تاني
    still_target = (lambda: True) if guard is None else guard
    if cls == "secure":
        # خانة آمنة: كتابة بس — الحافظة مش طريقها
        if not still_target():
            return "handoff"
        return "placed" if winput.type_text(inj) else "failed"
    if strategy == "type":
        # نسخة احتياطية على الحافظة: لو الكتابة فشلت والنص وصل الحافظة = "failed"
        # (المستخدم يقدر يلزقه بنفسه)، ولو الاتنين فشلوا = "clip_failed" (ولا حاجة)
        _pre_copy_suppress(from_snippet)
        backup = _copy_to_clipboard(inj)
        if backup:
            _mark_owned_if_snippet(from_snippet)
        if not still_target():
            return "handoff" if backup else "clip_failed"
        if winput.type_text(inj):
            return "placed"
        return "failed" if backup else "clip_failed"
    if strategy in ("ctrl_v", "shift_insert"):
        # اللزق هو النص نفسه: فشل نشر الحافظة = مفيش حاجة اتحقنت ولا اتنسخت
        _pre_copy_suppress(from_snippet)
        if not _copy_to_clipboard(inj):
            return "clip_failed"
        _mark_owned_if_snippet(from_snippet)
        if not still_target():
            return "handoff"                    # النص على الحافظة بالفعل — المستخدم يلزقه
        fn = winput.paste_ctrl_v if strategy == "ctrl_v" else winput.paste_shift_insert
        return "placed" if fn() else "failed"
    return "handoff"


def _probe_password(probe, key):
    """
    L1 (خصوصية): قراية «الخانة باسورد؟» على ثريد دايمون منفصل — UI Automation
    بيقدر يسدّ ثواني، فممن نحبس بيه ثريد الـlistener (pynput لازم يفضل سريع)
    ولا ثريد الواجهة. النتيجة بتتحفظ في probe[key] من لحظة النداء، والثريد نفسه
    بيتسجّل في probe["threads"] عشان process يستناه ويرجع لحالة الخانة الحقيقية.
    """
    def run():
        try:
            import winput
            info = winput.focused_info()
            probe[key] = info.get("is_password") is True
        except Exception:
            probe[key] = False

    t = threading.Thread(target=run, daemon=True)
    probe.setdefault("threads", []).append(t)
    t.start()


def _probe_password_seen(op, timeout=1.0):
    """
    L1 (خصوصية): بيستنى ثريدَيّ البروب اللي قرؤوا «باسورد؟» من لحظة begin/end
    (أقصى timeout ثانية في الإجمالي) وبيرجّع True لو أي واحد فيهم شاف خانة
    باسورد. مشتركة بين process و_process_edit عشان نفس السلوك في كل الأوضاع.
    """
    probe = getattr(op, "probe", {})
    deadline = time.time() + timeout
    for t in probe.get("threads") or ():
        left = deadline - time.time()
        if left > 0:
            t.join(left)
    return probe.get("begin") is True or probe.get("end") is True


# ── التطبيق (تسجيل + hotkey) ─────────────────────────────────────────────────
@dataclass(frozen=True)
class Operation:
    """
    بيانات دورة إملاء واحدة (تسجيل → تفريغ → كتابة).
    ثابت (frozen) وبيتولد مرة واحدة في begin() — قبل كده كان «الوضع» بيتقرأ
    من متغيّر بيتنازع عليه ثريدين: الدوسة اللي فتحت التسجيل وقفلته من
    ثريد تاني كانت ممكن تقرأ الوضع الغلط أو توصل بيانات فوق عملية لسه شغّالة.
    (target_app بيتعبأ في begin() — F5، وباقي حقول الهدف hwnd / selection…
    بتتملّأ في مهام تالية).
    """
    mode: str
    target_app: str = ""
    target_class: str = ""
    hwnd: int = 0
    runtime_id: tuple = ()
    selection: str = ""
    selection_hash: str = ""
    # L1 (خصوصية): حامل متغيّر للـprobe — الـdict نفسه mutable رغم إن العملية
    # frozen. فيه probe["begin"/"end"] (نتيجة قراية «باسورد؟» على ثريد دايمون)
    # وprobe["threads"] (الثريدين اللي قرؤوا عشان process يستناهم).
    probe: dict = field(default_factory=dict, compare=False)


class App:
    """
    الواجهة بترث منه وبتعمل override لـ on_state / on_text عشان تعرض الحالة.
    """

    # قفل واحد بيحرس (recording, busy, _op): أي انتقال بينهم لازم يبقى خطوة
    # واحدة — عشان دوسة الزرار والضغط من الواجهة في نفس اللحظة ما يشغلوش
    # عملية اتنين فوق بعض (كان بيحصل: end() قفل recording والـworker لسه
    # لسه ماحجزش busy، فتسجيل جديد كان بيبدأ فوق الأول).
    _state_lock = threading.Lock()

    def __init__(self):
        self.rec = Recorder()
        self.recording = False
        self.busy = False
        self._op = None
        self._client = None
        self._client_sig = None
        self._listener = None

    # ── العميل بيتبني حسب المزوّد المختار، وبيتعاد بناؤه لو اتغيّر ──
    def client(self):
        pid = CFG.get("provider", providers.DEFAULT)
        keys = providers.read_keys(ENV_PATH)
        key = keys.get(pid, "")
        model = (CFG.get("models") or {}).get(pid)
        # المزوّد اللي بيفرّغ بس (Deepgram) بيستعين بأول مزوّد تاني ليه مفتاح للتنظيف والترجمة
        hid = None
        if not providers.meta(pid).get("chat"):
            hid = next((h for h in providers.CHAT_HELPERS if keys.get(h)), None)
        sig = (pid, key, model, hid, keys.get(hid) if hid else None)
        if self._client is None or self._client_sig != sig:
            helper = providers.Client(hid, keys[hid]) if hid else None
            self._client = providers.Client(pid, key, model=model, helper=helper)
            self._client_sig = sig
        return self._client

    def reset_client(self):
        self._client = None
        self._client_sig = None

    # ── هوكس للواجهة ──
    def on_state(self, state, msg=None):
        pass

    def on_text(self, text):
        pass

    def on_update(self, info):
        pass

    def on_unplaced(self, text):
        """النتيجة اتنسخت بس مكانش فيه خانة كتابة — الواجهة تعرضها للمستخدم."""
        pass

    # ── دورة التسجيل ──
    def _set_busy(self, on):
        # busy بيتحوّل من جوّه القفل زي recording: لو اتستنى عليه ثريد
        # تاني (begin)، الفحص والتحويل لازم يقعّا في نفس اللحظة.
        with self._state_lock:
            self.busy = on

    def begin(self, mode="normal"):
        # F5: اسم البرنامج بيتقعد على العملية قبل القفل — هو اللي هيحدد أسلوب
        # السياق (dev/chat/formal) وقت التنظيف، ومبيغادرش يتغيّر في نص الدورة.
        target_app = (_foreground_app() or "").strip().lower()
        with self._state_lock:
            # فحص وحجز في خطوة واحدة: لو التسجيل شغّال أو التفريغ شغّال،
            # الدوسة الجديدة تترفض — بدل ما كل ثريد يفحص وبعدين يكمّل لوحده.
            if self.recording or self.busy:
                return
            self.recording = True
            self.active_mode = mode
            op = Operation(mode=mode, target_app=target_app)
            if mode == "edit":
                # حدث الإلغاء بيتعمل قبل ما العملية تتنشر: cancel() اللي ييجي قبل ما العامل
                # يبدأ لازم يلاقيه، وإلا الأسر كان بيبدأ ويحقن Ctrl+C في اللي بعده
                op.probe["cancel"] = threading.Event()
            self._op = op
        if mode == "edit":
            # F6: أسر التحديد (UIA/الحافظة) بيقدر يسدّ ثواني، فمينفعش يحصل على ثريد
            # الـlistener (pynput لازم يفضل سريع). بنسلّم الباقي لعامل ونرجع فورًا.
            threading.Thread(target=self._begin_edit, args=(op,), daemon=True).start()
            return
        # L1 (خصوصية): نقرا «باسورد؟» على ثريد دايمون من لحظة الحجز — عشان
        # process يرجع لحالة الخانة وقت التسجيل نفسه، مش وقت بداية التفريغ
        # (الفوكس ممكن يكون اتنقل في النص، وكلمة السر عمرها ما تضيع حمايتها).
        _probe_password(op.probe, "begin")
        # فتح الميك جوه القفل كان بيقعد فيه: لو الجهاز اتفصل والستريم بيأخد
        # وقت يتفتح، كان end() يقعد منتظر القفل والمستخدم مش قادر يوقف.
        if not self.rec.ensure_open():
            with self._state_lock:
                # الدورة ممكن تكون اتلغت/اتبدلت ولسه شغّالة؟ لو _op بقى عملية تانية،
                # الدولة ملكها — ممن نمسحها ولا ننشر خطأ ميك فوقها
                if self._op is not op:
                    return
                self.recording = False
                self._op = None
            self.on_state("err", "الميكروفون مش متاح — وصّله وجرّب، أو غيّره من الإعدادات")
            return
        # F1: فتح الميك ممكن ياخد وقت (ريكونكت)، وجوّه الوقت ده end()/cancel()
        # بيقدروا يقفلوا recording ويشيلوا _op. بنفحص تاني جوّه القفل إن الدورة
        # لسه ملكنا (نفس الـOperation) — غير كده منبدأش تسجيل يتيم.
        with self._state_lock:
            if not self.recording or self._op is not op:
                return
        self._begin_tail(op, mode)

    def _begin_tail(self, op, mode):
        """
        نهاية begin المشتركة بين كل الأوضاع: الصفارة برّه القفل وقبل الالتقاط،
        فحص تاني، الالتقاط جوّه القفل، إعلان "rec"، وفحص stale — في مكان واحد
        عشان سباقات cancel/begin تفضل ثابتة ومفيش نسختين من نفس الإصلاح.
        """
        # الصفارة برّه القفل وقبل الالتقاط: لو سبقت الالتقاط كانت بتتسجّل جوّه
        # الصوت، ولو جوّه القفل كانت بتقعد فيه ~90ms بتمنع cancel يوصّل.
        beep(880, 90)
        # فحص تاني بعد الصفارة: cancel ممكن يكون وصل في النص — ومنبدأش التقاط
        # يتيم من غير عملية تملكه
        with self._state_lock:
            if not self.recording or self._op is not op:
                return
            self.rec.start()
        self.on_state("rec", mode)
        # لو cancel وصل بين الالتقاط وإعلان "rec"، رسالة "rec" بتسبق رسالة
        # الإلغاء وتسيّب الواجهة على "rec" — فننادي "ready" برّه القفل عشان
        # الواجهة متفضلش واقفة على "rec"
        with self._state_lock:
            stale = self._op is not op
        if stale:
            self.on_state("ready")

    def _edit_refuse(self, op, msg):
        """
        رفض بداية وضع التعديل: بنمسح الحجز والعملية بس لو لسه ملكنا (نفس الـop
        اللي حجزناه) وننشر الخطأ. لو المستخدم وقّف/لغى في النص، بنسكت خالص.
        """
        with self._state_lock:
            if self._op is not op:
                return
            self.recording = False
            self._op = None
        self.on_state("err", msg)

    def _begin_edit(self, op):
        """
        F6: العامل اللي بينفّذ بداية التعديل في المكان. أسر التحديد بيحصل على
        ثريد دايمون داخلي بميزانية قصوى (١.٥ ثانية) — UIA بيقدر يسدّ ثواني على
        التحديدات الضخمة أو برامج مش متعاونة، ومنستناش عليه للابد. أي رفض بيحصل
        و الـop لسه حيّ؛ لو المستخدم وقّف في النص، العامل بيسكت وبيخلص.
        """
        import winput
        import dataclasses
        # N5: حدث الإلغاء بيتحفظ على العملية نفسها (op.probe["cancel"]) مش متغير
        # محلي — عشان end()/cancel() يقدروا يقفلوه فورًا ويبطلوا أسر معلق في UIA،
        # مش بس بعد الـjoin بتاع الـ1.5 ثانية. برضه M2: بيوصل لجوّه الأسر — لو
        # فاضت الميزانية أو العملية بقت قديمة، ثريد الأسر بيبطل قبل ما يلمس الحافظة.
        cancel = op.probe.setdefault("cancel", threading.Event())
        with self._state_lock:
            current = self.recording and self._op is op
        if cancel.is_set() or not current:
            return                                 # اتلغى قبل ما الأسر يبدأ — منلمسش حاجة
        captured = {}

        def _capture():
            try:
                captured["result"] = winput.capture_target(cancel=cancel)
            except Exception:
                captured["result"] = None

        t = threading.Thread(target=_capture, daemon=True)
        t.start()
        t.join(1.5)                                # الميزانية القصوى للأسر (كله جوّه ثريد واحد)
        exceeded = t.is_alive()                    # لسه شغّال = فاضت الميزانية
        with self._state_lock:
            current = self.recording and self._op is op
        if exceeded or not current:
            cancel.set()                           # الثريد المتأخر يبطل حالًا
        result = captured.get("result") or {}
        # M1: خانة باسورد (أو مقدرناش نقرا) — الرفض من capture نفسه ورسالته واحدة
        if result.get("password"):
            self._edit_refuse(op, "مينفعش تعديل خانة باسورد")
            return
        sel = (result.get("selection") or "")
        # فاضت الميزانية أو الأسر فشل أو مفيش تحديد → رفض. (الثريد اللي لسه
        # شغّال daemon وبيبص في UIA — بنسيبه يخلص لوحده، النتيجة مش هتوصل.)
        if exceeded or not sel:
            self._edit_refuse(op, "حدّد النص اللي عايز تعدّله الأول")
            return
        if len(sel) > 6000:
            self._edit_refuse(op, "النص المحدد طويل أوي — حدّد جزء أصغر")
            return
        new_op = dataclasses.replace(
            op, hwnd=int(result.get("hwnd") or 0),
            runtime_id=tuple(result.get("runtime_id") or ()),
            selection=sel,
            selection_hash=result.get("selection_hash") or "")
        with self._state_lock:
            if not self.recording or self._op is not op:
                return
            self._op = new_op
        # نفس نهاية begin العادية — من هنا ومع بعدين مفيش فرق بين الأوضاع
        self._begin_tail(new_op, "edit")

    def end(self):
        with self._state_lock:
            # نقفل التسجيل ونحجز التفريغ (busy) في نفس اللحظة: قبل كده كانت
            # الفجوة بين الاتنين بتسمح بتسجيل جديد يبدأ فوق الأول — الـworker
            # لسه مشغّل والوضع الجديد بينتقل مع القديم.
            if not self.recording:
                return
            self.recording = False
            self.busy = True
            op = self._op
            self._op = None
        # L1 (خصوصية): نقرا «باسورد؟» كمان لحظة الإيقاف — قبل الصفارة ما توقف
        # الريكوردر — عشان لو المستخدم كان واقف في خانة باسورد وقت ما وقّف.
        if op is not None:
            _probe_password(op.probe, "end")
            # N5: لو في أسر edit لسه شغّال (معلق في UIA)، بنلغيه حالًا — مش
            # نستنى الـ1.5 ثانية بتاع join في _begin_edit.
            ev = op.probe.get("cancel")
            if ev is not None:
                ev.set()
        beep(500, 90)
        try:
            wav = self.rec.stop()
        except Exception as e:
            log_error(e, "recorder/stop")
            self._set_busy(False)             # مفيش worker بدأ — الحجز اتأخد على الفاضي فبيترجّع
            self.on_state("err", "مشكلة في قراية الصوت — جرّب تاني")
            return
        if not wav:
            self._set_busy(False)             # نفس السبب: مفيش عملية هتبدأ فالحجز بيتترجّع
            self.on_state("ready", "التسجيل كان قصير أوي — اتكلم شوية وبعدين وقّف")
            return
        threading.Thread(target=self.process, args=(wav, op), daemon=True).start()

    def cancel(self):
        """إلغاء التسجيل: الصوت بيترمي ومفيش تفريغ."""
        with self._state_lock:
            if not self.recording:
                return
            self.recording = False
            op = self._op
            self._op = None                   # العملية اتلغت — مفيش ما يستلمها في end()
            self._active_key = None           # وضع hold: سيبان الزرار بعد كده مايعملش حاجة
            # N5: بنقفل حدث أسر edit لو لسه شغّال — جوّه القفل مباشرة بعد ما
            # شيلنا العملية، عشان الأسر المعلق في UIA يبطل فورًا مش بعد الـjoin.
            if op is not None:
                ev = op.probe.get("cancel")
                if ev is not None:
                    ev.set()
            # الديسكارد جوّه القفل نفسه: بيقلّب flags ويمسح frames بس، فآمن هنا.
            # لو فضل برّه، begin() على ثريد تاني كان ممكن يبدأ تسجيل جديد في الفجوة،
            # والديسكارد المتأخر كان هيمسح التسجيل الجديد.
            try:
                self.rec.discard()
            except Exception as e:
                log_error(e, "recorder/cancel")
        self.on_state("ready", "اتلغى التسجيل")

    def process(self, wav, op):
        # busy اتحجز بالفعل في end() (قبل ما الثريد ده يبدأ) — هنا بنفكّه
        # في finally بعد كل الحالات: نجاح، فشل، أو أي return بدري.
        cur_mode = op.mode
        try:
            if cur_mode == "edit":
                # F6: وضع التعديل مسار مستقل — مفيش فحص باسورد مبكّر ولا
                # bypass/snippets/polish/fix_mixed/prompt/translate، التعليمات بس.
                self._process_edit(wav, op)
                return
            # F2 (خصوصية): معلومات الفوكس بتتقرا مرة واحدة في أول العملية — قبل
            # أي نداء للموديل وحتى قبل إشعار الواجهة — عشان نمسك حالة الخانة
            # والوقت اللي التسجيل لسه واقف عليها. لو باسورد، نصها عمره ما يوصل
            # للموديل ولا يتعدّل (بيتكتب زي ما اتفرّغ).
            # L1: نستنى ثريدَيّ البروب اللي قرؤوا «باسورد؟» من لحظة begin/end
            # (أقصى ثانية واحدة في الإجمالي) — القراية هنا وحدها مش كفاية لأن
            # الفوكس ممكن يكون اتنقل بين وقت التسجيل وبداية التفريغ.
            import winput
            info = winput.focused_info()
            info["exe"] = _foreground_app()
            # أي واحد (begin أو end أو القراية الحالية) شاف باسورد = العملية
            # محمية طول عمرها — مش بنخفّضها أبدًا.
            early_secure = (_probe_password_seen(op)
                            or info.get("is_password") is True)
            self.on_state("work", cur_mode)    # جوّه الـtry: لو الواجهة رمت خطأ، busy لازم يتفك برضه
            try:
                with wave.open(wav, "rb") as w:
                    dur = w.getnframes() / float(w.getframerate())
            except Exception:
                dur = None
            # الترجمة في الاتجاهين: المتكلم ممكن يتكلم إنجليزي، فمانجبرش التفريغ على العربي
            # (كان بيكتب الإنجليزي بحروف عربي، والترجمة تطلع عربي ← إنجليزي بس)
            lang = None if cur_mode == "translate" else CFG.get("language", "ar")
            # F9: مسار offline — "always" بيفرّغ من غير ما نبني Client خالص (من غير مفتاح)،
            # و"fallback" بيرجع للموديل المحلي بس لو النت وقع والموديل مثبّت.
            # N1: "always" = وضع خصوصية — الصوت عمره ما يروح لأي مزوّد. لو الموديل
            # مش متثبّت منبنيش Client ولا ننادي مزوّد، نرفض على طول (من غير سجل/حافظة).
            offline_used = False
            offline_model = None
            if CFG.get("offline_mode") == "always":
                if not offline.installed():
                    self.on_state("err", "التفريغ من غير إنترنت مش متثبّت — نزّله من الإعدادات")
                    return
                offline_used = True
                offline_model = offline.installed()
                text = offline.transcribe(wav, lang)
            else:
                cl = self.client()
                cl.vocab = [w for w in (CFG.get("dictionary") or []) if str(w).strip()]
                # F8: مفاتيح الاختصارات الصوتية بتتبعت للموديل زي كلمات القاموس —
                # عشان Whisper يسمعها صح ويطلعها زي ما المستخدم نطقها.
                cl.vocab_extra = [str(s.get("trigger") or "").strip()
                                  for s in (CFG.get("snippets") or [])
                                  if isinstance(s, dict) and str(s.get("trigger") or "").strip()]
                try:
                    text = cl.transcribe(wav, lang)
                except Exception as e:
                    if smart.is_network_error(e) and offline.installed():
                        offline_used = True
                        offline_model = offline.installed()
                        text = offline.transcribe(wav, lang)
                    else:
                        raise
            if not text:
                self.on_state("ready", "مطلعش نص — قرّب من الميك وجرّب تاني")
                return
            # بعد تفريغ offline الموديل (LLM) عمره ما بيتنادي. البرومبت والترجمة محتاجين نت
            # فبيتسلّموا للمستخدم؛ العادي بيكمّل في نفس مسار الكتابة تحت بالنص الخام —
            # عشان قواعد الباسورد والحقن والسجل تفضل في مكان واحد
            if offline_used and cur_mode != "normal":
                self._offline_handoff(wav, op, text, dur, offline_model, early_secure)
                return

            bypass = False
            snippet = None
            if early_secure or offline_used:
                # خانة باسورد: مفيش أي لفة موديل في أي وضع (عادي/برومبت/ترجمة)
                # ولا تنضيف محلي — النص بيتكتب زي ما اتفرّغ. حتى لو المستخدم
                # اختار برومبت أو ترجمة، كلمة السر عمرها ماتوصل للموديل.
                # وبرضه مفيش توسيع اختصار: نص الاختصار (IBAN/عنوان/إيميل) ممن
                # يندسّ في خانة باسورد.
                out = text
            elif cur_mode == "prompt":
                self.on_state("prompt", "بجهّز البرومبت…")
                out = cl.to_prompt(text)
            elif cur_mode == "translate":
                self.on_state("translate", "بترجم الكلام…")
                out = cl.translate(text)
            else:
                # F8 (الوضع العادي): لو الكلام كله اختصار صوتي محفوظ، النص بيتوسّع
                # لنص الاختصار حرفيًا — من غير أي لفة موديل ولا تنضيف، لأن النص
                # المخزّن (IBAN/عنوان/إيميل) ممن يتغيّر ولو بحرف. بيعتمد على
                # التطبيع مش على التطابق الحرفي.
                snippet = smart.match_snippet(text, CFG.get("snippets"))
                if snippet is not None:
                    out = snippet.get("text", "")
                elif CFG.get("polish", True):
                    if smart.should_bypass(text, cur_mode, CFG):
                        # رد يومي قصير (F2): مفيش قيمة للفة LLM كاملة —
                        # التنظيف المحلي أسرع ومابيغيّرش الكلمة اللي اتقالت
                        out = smart.light_clean(text)
                        bypass = True
                    else:
                        # F5: لو البرنامج اللي قدامه عنده override، تنظيف النص ياخد أسلوبه
                        out = cl.polish(text, profile=smart.app_profile(op.target_app, CFG))
                else:
                    out = text

            # الموديل ممكن ياخد ثواني والفوكس يتحرّك في النص — فبنعيد قراية الفوكس
            # قبل تصنيف الهدف. الاستعلام الأخير ده هو اللي بيحدد مكان الكتابة.
            info2 = winput.focused_info()
            info2["exe"] = _foreground_app()
            late_secure = info2.get("is_password") is True
            if early_secure and not late_secure:
                # الفوكس كان على خانة باسورد وقت التسجيل وبعدين اتنقل — ممن نكتب
                # كلمة السر في أي مكان تاني (غالبًا خانة عادية المستخدم بيقلّب فيها).
                # بنرفض من غير سجل/حافظة/صوت/عرض/تسليم.
                self.on_state("err", "الفوكس اتنقل من خانة الباسورد — مكتبتش حاجة")
                return
            secure = late_secure
            # F3 (R1 #1): تصنيف الهدف قبل السجل/الحافظة/الصوت — الهدف الآمن:
            # مفيش حاجة من التسجيل ده بتطلع من هنا (لسجل، صوت، نسخ، ولا عرض النص).
            target = smart.insert_target(info2, out, CFG.get("insert_method"))
            # F7: بعد مخرج الوضع العادي (polish أو تخطّي الرد القصير) بنصلّح
            # النص المختلط: الحرف العاري قبل الكلمة اللاتيني على شكله المثالي
            # («للـ branch») والترقيم العربي — بس من غير تطبيقات dev (الكود لازم
            # يفضل شكله التقني) ومن غير الترمنال: النص ممكن يكون أمر، وتغيير
            # بايتاته خطر. التصنيف ماشي عليه زي ما هو: مبنصنّفش تاني، بنغيّر
            # النص المتحقن بس ونسّيبه على سياسة الأسطر الأصلية.
            # ومن غير خانات الباسورد: أي تعديل في الترقيم هناك بيغيّر الباسورد نفسه
            if (cur_mode == "normal" and CFG.get("polish", True)
                    and snippet is None and not offline_used
                    and not smart.is_dev_app(op.target_app, CFG)
                    and target[0] not in ("terminal", "secure")):
                out = smart.fix_mixed(out)
                target = (target[0], target[1], out)
            rid = None
            if not secure:
                # F8: في السجل النتيجة بتظهر «[اختصار] <المفتاح>» — مش نص الاختصار
                # الكامل — عشان المستخدم يعرف إن اللي اتكتب ده كان اختصار مش إملاء.
                history_result = ("[اختصار] " + str(snippet.get("trigger") or "")) if snippet is not None else out
                # engine بعد نداء الموديل — غير كده السجل مايعرفش موديل التنضيف
                engine = ({"stt": "offline", "stt_model": "whisper.cpp " + (offline_model or "")}
                          if offline_used else cl.engine())
                rid = history_add(cur_mode, text, history_result, dur, engine=engine,
                                  bypass=bypass, app=op.target_app)
                self.on_text(out)
            res = None
            if not secure or CFG.get("auto_paste", True):
                if snippet is not None:
                    res = paste_text(out, target, from_snippet=True)
                else:
                    res = paste_text(out, target)
                if not secure and res == "clip_failed":
                    self.on_state("err", "مقدرتش أكتب النص ولا أنسخه — جرّب تاني")
                elif not secure and res in ("failed", "handoff"):
                    self.on_unplaced(out)
            else:
                # L2: خانة آمنة واللزق التلقائي مقفول — مفيش كتابة ولا نسخ (الحافظة
                # ممن توصلها الباسورد)، فالمستخدم لازم يكتبها بنفسه. من غير الرسالة
                # دي الواجهة كانت بتفضل واقفة على "work".
                self.on_state("err", "الكتابة التلقائية مقفولة — خانة الباسورد مينفعش أنسخ لها")
            if rid:
                recording_save(rid, wav)          # بعد الكتابة عشان مايأخّرهاش (قبل ما الـwav يتمسح)
            # "done" بس لما النتيجة انكتبت أو اتسلّمت للمستخدم. «clip_failed» ناشر
            # "err" فوق فمينفعش يتغطى بـ"done". الخانة الآمنة لو الكتابة فشلت: "err"
            # من غير "done" — مفيش حافظة تلزق منها، المستخدم لازم يكتبها بنفسه.
            if res == "placed" or res == "handoff" or (not secure and res == "failed"):
                self.on_state("done", "اتفرّغ من غير إنترنت (من غير تحسين)" if offline_used else cur_mode)
            elif secure and res == "failed":
                self.on_state("err", "مقدرتش أكتب في خانة الباسورد — اكتبها بنفسك")
        except Exception as e:
            log_error(e, "process/transcribe")
            self.on_state("err", friendly_error(e))
        finally:
            self._set_busy(False)
            try:
                os.remove(wav)
            except Exception:
                pass

    def _offline_handoff(self, wav, op, text, dur, offline_model, early_secure):
        """
        F9: برومبت/ترجمة بعد تفريغ offline — التحويل نفسه محتاج نت، فالنص الخام بيتنسخ
        وبيتعرض بدل ما يتكتب. من غير خانات الباسورد: نصها عمره ما يروح للحافظة ولا السجل.
        """
        if early_secure:
            self.on_state("err", "مينفعش أنسخ نص خانة باسورد — التحويل محتاج إنترنت")
            return
        # N2: فحص أخير للفوكس قبل أي نسخ/عرض/سجل — نفس قراية process المتأخرة.
        # الفوكس ممكن يكون اتنقل لخانة باسورد بعد التفريغ، فنرفض من غير ما نلمس حاجة.
        import winput
        if winput.focused_info().get("is_password") is True:
            self.on_state("err", "مينفعش أنسخ نص خانة باسورد — التحويل محتاج إنترنت")
            return
        engine = {"stt": "offline", "stt_model": "whisper.cpp " + (offline_model or "")}
        cur_mode = op.mode
        if _copy_to_clipboard(text):
            self.on_unplaced(text)
        else:
            self.on_state("err", "مقدرتش أنسخ النص — جرّب تاني")
            return
        history_add(cur_mode, text, text, dur, engine=engine, app=op.target_app)
        self.on_state("done", "اتفرّغ بس — التحويل محتاج إنترنت")

    def _process_edit(self, wav, op):
        """
        F6: تنفيذ التعديل في المكان. التعليمات المنطوقة بتتفّرغ وتروح للموديل
        مع النص المحدد، والنتيجة بتتحقن مكان التحديد (أو بتتنسخ لو الهدف اتغيّر).
        النص المحدد نفسه عمره ما يتسجّل في السجل — التعليمات والنتيجة بس.
        """
        import winput
        self.on_state("work", "edit")
        # N2: نفس فحص بروب التسجيل بتاع process — لو begin/end شافوا خانة باسورد
        # (أثناء التسجيل نفسه)، التعليمات ممن توصل للموديل إطلاقًا، لأن التحديد
        # ممكن يكون باسورد متسرب من خانة المستخدم اتنقل عنها.
        if _probe_password_seen(op):
            self.on_state("err", "مينفعش تعديل خانة باسورد")
            return
        # F9/N1: التعديل في المكان بيحتاج الموديل (LLM) — وضع offline دايمًا مينفعش
        # معاه سواء الموديل متثبّت ولا لأ: مينفعش نبني Client ولا ننادي أي مزوّد.
        if CFG.get("offline_mode") == "always":
            self.on_state("err", "التعديل محتاج إنترنت")
            return
        cl = self.client()
        cl.vocab = [w for w in (CFG.get("dictionary") or []) if str(w).strip()]
        cl.vocab_extra = [str(s.get("trigger") or "").strip()
                          for s in (CFG.get("snippets") or [])
                          if isinstance(s, dict) and str(s.get("trigger") or "").strip()]
        try:
            with wave.open(wav, "rb") as w:
                dur = w.getnframes() / float(w.getframerate())
        except Exception:
            dur = None
        try:
            instruction = cl.transcribe(wav, CFG.get("language", "ar"))
        except Exception as e:
            # F9: النت وقع والموديل المحلي موجود — التفريغ ممكن يتعمل، بس التعديل
            # نفسه محتاج الموديل، فنرفض من غير ما نلمس التحديد ولا نحقن حاجة.
            if smart.is_network_error(e) and offline.installed():
                self.on_state("err", "التعديل محتاج إنترنت")
                return
            raise
        if not instruction:
            self.on_state("ready", "مطلعش نص — قرّب من الميك وجرّب تاني")
            return
        result = cl.edit(op.selection, instruction)
        if result is None:
            # فشل النداء = مفيش تعديل — التحديد زي ما هو، ومنكتبش حاجة
            self.on_state("err", "معرفتش أعدّل النص — جرّب تاني")
            return
        info = winput.focused_info()
        info["exe"] = _foreground_app()
        target = smart.insert_target(info, result, CFG.get("insert_method"))
        # M6: الهدف اتحوّل لخانة باسورد بعد الأسر — ممن نحقن ولا ننسخ (الباسورد
        # عمره مايوصل للحافظة)؛ بنوقف برسالة واضحة من غير "done".
        if target[0] == "secure":
            self.on_state("err", "مكتبتش التعديل — الهدف بقى خانة باسورد")
            return
        # M6: الحقن بيعيد فحص الهدف بعد انتظار الفوكس (guard) — لو اتغيّر،
        # paste_text بيتسلّم (نسخ) بدل ما يكتب فوق حاجة تانية.
        res = paste_text(result, target, guard=lambda: winput.same_target(op))
        # M7: الهدف اتغيّر والنسخة فشلت كمان → خطأ بدل on_unplaced + "done"
        if res == "clip_failed":
            self.on_state("err", "مقدرتش أكتب النص ولا أنسخه — جرّب تاني")
            return
        if res in ("failed", "handoff"):
            self.on_unplaced(result)
        rid = history_add("edit", instruction, result, dur, engine=cl.engine())
        if rid:
            recording_save(rid, wav)
        if res in ("placed", "handoff", "failed"):
            self.on_state("done", "edit")

    # ── أزرار التسجيل العامة (3 أوضاع مستقلة) ──
    def start_hotkey(self):
        from pynput import keyboard
        import winput   # آثار جانبية Win32 (mask/مفاتيح القفل) — جوّه الدالة عشان
                       # ماتستورداش في مستوى موديول core (وsmart مالمسهاش خالص)

        def _parse_key(val):
            if not val:
                return None
            s = str(val).lower().strip()
            try:
                return keyboard.Key[s]
            except KeyError:
                try:
                    return keyboard.KeyCode.from_char(s)
                except Exception:
                    return None

        hk_normal = CFG.get("hotkey_normal") or CFG.get("hotkey") or "ctrl_r"
        hk_prompt = CFG.get("hotkey_prompt") or "alt_r"
        hk_trans  = CFG.get("hotkey_translate") or "shift_r"
        hk_edit   = CFG.get("hotkey_edit") or ""        # F6: "" = مقفول
        mode_type = CFG.get("mode", "hold")

        key_map = {}
        k_norm = _parse_key(hk_normal)
        k_prmt = _parse_key(hk_prompt)
        k_trns = _parse_key(hk_trans)
        k_edit = _parse_key(hk_edit)

        if k_norm: key_map[k_norm] = "normal"
        if k_prmt: key_map[k_prmt] = "prompt"
        if k_trns: key_map[k_trns] = "translate"
        if k_edit: key_map[k_edit] = "edit"

        self._active_key = None

        # أي زرار من الأربعة هو Alt (بيشتغل عليه "mask") أو مفتاح قفل
        # (بنرجّع حالته لو الدوسة قلبته) — بنسأل من اسم الإعداد مش من
        # داخلية pynput، عشان الاسم هو اللي المستخدم فعلاً كتب.
        ALT_NAMES = ("alt_r", "alt_l", "alt", "alt_gr")
        LOCK_VKS = {"caps_lock": winput.VK_CAPS_LOCK,
                    "scroll_lock": winput.VK_SCROLL_LOCK}
        alt_keys, lock_vks = set(), {}
        for k, raw in ((k_norm, hk_normal), (k_prmt, hk_prompt), (k_trns, hk_trans), (k_edit, hk_edit)):
            if not k:
                continue
            s = str(raw).lower().strip()
            if s in ALT_NAMES:
                alt_keys.add(k)
            if s in LOCK_VKS:
                lock_vks[k] = LOCK_VKS[s]

        # القرار نفسه (toggle: دوسة نضيفة / hold: دوسة-تسيب + أي زرار تاني
        # وقت التسجيل = cancel) بقى جوّه smart.HotkeyLogic — مبسوط هنا
        # عشان الاختبار من غير pynput ولا ويندوز.
        logic = smart.HotkeyLogic(key_map, mode_type, alt_keys=alt_keys)
        # مفاتيح قفل اتداست ولسه ماتسابتش. كل دوسة حقيقية على Caps/Scroll Lock بتقلب
        # الحالة مرة واحدة بالظبط (التكرار التلقائي مابيقلبهاش)، فعند التسيب بنرجّعها
        # بدوسة واحدة. مش بنقارن GetKeyState قبل وبعد: من ثريد الـhook الحالة بتبان
        # متقلبة من وقت الدوسة نفسها، فالمقارنة كانت دايمًا «متغيرتش» (اتجرّب فعليًا).
        locks_down = set()

        def guard(fn):
            def wrapped(key):
                try:
                    fn(key)
                except Exception as e:
                    log_error(e, "hotkey")
                    try:
                        self.recording = False
                        self._active_key = None
                        self.on_state("err", friendly_error(e))
                    except Exception:
                        pass
            return wrapped

        @guard
        def on_press(key):
            now = time.time()
            if key in lock_vks:
                locks_down.add(key)
            for act in logic.press(key, now, self.recording, self.busy):
                if act == "mask":
                    winput.send_vk(winput.VK_MASK)
                elif act == "end":
                    self.end()
                elif act == "cancel":
                    self.cancel()
                elif act.startswith("begin:"):
                    self.begin(mode=act[len("begin:"):])

        @guard
        def on_release(key):
            for act in logic.release(key, time.time(), self.recording, self.busy):
                if act == "end":
                    self.end()
                elif act == "cancel":
                    self.cancel()
                elif act.startswith("begin:"):
                    self.begin(mode=act[len("begin:"):])
            if key in locks_down:
                locks_down.discard(key)
                winput.send_vk(lock_vks[key])

        def win32_event_filter(msg, data):
            # أحداثنا التركيبية (معلّمة EMLAA_TAG) مابنسمعهاش:
            # غير كده منطق زرار التسجيل كان هيسمع دوساته هو. بنفلتر
            # أحداثنا إحنا بس — مفاتيح المستخدم الحقيقية مالهاش دعوة بالفلتر.
            return data.dwExtraInfo != winput.EMLAA_TAG

        self._listener = keyboard.Listener(on_press=on_press, on_release=on_release,
                                           win32_event_filter=win32_event_filter)
        self._listener.daemon = True
        self._listener.start()


    def restart_hotkey(self):
        """
        بيعيد تسجيل زرار التسجيل بالقيمة الجديدة من غير ما البرنامج يتقفل.
        (قبل كده كان لازم إعادة تشغيل — والرسالة دي كانت بتخلّي المستخدم
         يقفل ويفتح ويشك إن الإعدادات ما اتحفظتش أصلًا.)
        """
        try:
            if self._listener:
                self._listener.stop()
        except Exception:
            pass
        self._listener = None
        self.start_hotkey()

    def shutdown(self):
        try:
            if self._listener:
                self._listener.stop()
        except Exception:
            pass
        self.rec.close()


ERR_LOG = os.path.join(BASE, "emlaa-error.log")
try:                                    # الاسم القديم من النسخ اللي قبل كده
    _old_log = os.path.join(BASE, "notq-error.log")
    if os.path.exists(_old_log) and not os.path.exists(ERR_LOG):
        os.replace(_old_log, ERR_LOG)
except Exception:
    pass


def log_error(e, where=""):
    """
    بيكتب الخطأ الحقيقي في ملف جنب البرنامج.

    ليه ده مهم: الرسالة اللي المستخدم بيشوفها مختصرة عن قصد، ومن غير الملف ده
    الخطأ الفعلي بيضيع خالص — لا المستخدم يعرفه ولا إحنا. أول بلاغ وصلنا
    (١١ أغسطس) كان «حصل خطأ — جرّب تاني» على مزوّدين مختلفين، ومكانش فيه أي
    طريقة نعرف بيها السبب.
    """
    try:
        import traceback, datetime
        with open(ERR_LOG, "a", encoding="utf-8") as f:
            f.write(chr(10) + "=" * 60 + chr(10))
            f.write(str(datetime.datetime.now()) + "  |  " + str(where) + chr(10))
            f.write("المزوّد: " + str(CFG.get("provider")) +
                    "  |  اللغة: " + str(CFG.get("language")) +
                    chr(10))
            f.write("".join(traceback.format_exception(type(e), e, e.__traceback__)))
    except Exception:
        pass


def friendly_error(e):
    """
    رسالة عربي واضحة تقول للمستخدم **يعمل إيه** — مش بس إن فيه مشكلة.
    وأي حالة مش متوقّعة بتوديه على ملف اللوج بدل ما تسيبه في حيرة.
    """
    s = str(e).lower()

    if "مفيش مفتاح" in str(e):
        return "محطّتش مفتاح للمزوّد ده — افتح الإعدادات وحطّه"
    if "project has been denied access" in s or "permission_denied" in s:
        return "مشروع Google محظور أو مرفوض (Project denied access) — أنشئ مشروع جديد ومفتاح جديد من Google AI Studio"
    if "blocked at the project level" in s:
        return "الموديل محظور في إعدادات مشروع Groq — فعّله من console.groq.com/settings/project/limits أو أنشئ مفتاح جديد"
    if "quota" in s or "billing" in s or "429" in s or "exceeded" in s or "rate limit" in s:
        return "الحد المجاني خلص — استنى شوية أو غيّر المزوّد من الإعدادات"
    if "401" in s or "unauthor" in s or "api key" in s or "api_key" in s or "invalid" in s:
        return "المفتاح مش مقبول — انسخه من الأول وحطّه في الإعدادات"
    if "403" in s or "permission" in s or "denied" in s or "not enabled" in s:
        return "المفتاح مرفوض — يمكن الخدمة مش مفعّلة على حسابك أو بلدك مش مدعومة"
    if "not found" in s or "404" in s or "does not exist" in s or "decommission" in s or "no longer available" in s:
        return "الموديل مش متاح على حسابك — تم تحديث البرنامج لدعم أحدث الموديلات"
    if "ssl" in s or "certificate" in s or "cert_" in s or "self-signed" in s or "self signed" in s:
        return "مشكلة في شهادات الأمان — لو على نت شركة أو مدرسة جرّب نت تاني"
    if "413" in s or "payload" in s or "too large" in s or "request entity" in s:
        return "التسجيل طويل أوي — سجّل مقطع أقصر"
    if "500" in s or "502" in s or "503" in s or "overload" in s or "unavailable" in s:
        return "سيرفر المزوّد مضغوط دلوقتي — جرّب بعد شوية"
    # F9: خطأ شبكة حقيقي (DNS/اتصال/مهلة) — لو الموديل المحلي مش مثبّت بنقترح عليه تنزيله
    if smart.is_network_error(e):
        msg = "مفيش اتصال بالنت — اتأكد من الاتصال وجرّب تاني"
        if not offline.installed():
            msg += chr(10) + "تقدر تنزّل التفريغ من غير إنترنت من الإعدادات"
        return msg
    if "connect" in s or "timeout" in s or "timed out" in s or "urlopen" in s or "network" in s:
        return "مفيش اتصال بالنت — اتأكد من الاتصال وجرّب تاني"

    # حالة مش متوقّعة: نطلّع أول سطر من الخطأ الأصلي + نوديه على اللوج.
    # من غير ده الرسالة بتبقى بلا معنى والدعم مش هيعرف يساعده.
    detail = " ".join(str(e).split())[:70]
    return ("مشكلة مش متوقّعة — ابعت ملف emlaa-error.log للدعم" +
            (chr(10) + detail if detail else ""))
