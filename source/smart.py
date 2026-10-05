# -*- coding: utf-8 -*-
"""
الذكاء الخفيف — قرارات نقية من غير ويندوز ولا مفاتيح
-----------------------------------------------------
كل الحساب/القرار الصغير في خط التفريغ (تنظيف نص، عدّ كلمات،
اختيار الأسلوب وطريقة الحقن…) يعيش هنا في دوال نقية، عشان:

  • تختبَر في الوحدة من غير ميكروفون ولا شبكة ولا مفاتيح.
  • لو كل القرارات في core كانت هتبقى متشابكة مع ويندوز والـpipeline
    ومينفعش يجرّبها حد لوحده.

الاتجاه واحد بس: core (وغيره) بيستورد smart — وsmart ميستوردش
حاجة من core، عشان لو طلع فيه استيراد بالغلط يبقى مسار واحد مش دورة.
"""
import re
import unicodedata


# ── تطبيع النص (مشترك بين تخطّي الردود القصيرة F2 والاختصارات الصوتية F8) ──

# أي فراغات متتالية (مسافات، تابات، أسطر) بتبقى مسافة واحدة
_SPACES = re.compile(r"\s+")
_TATWEEL = "\u0640"   # ـ (تطويل) — بيتكتب في «للـ» و«الـ»


def normalize(text):
    """
    شكل موحّد للمطابقة بس، مش للعرض: التشكيل والتطويل وعلامات الترقيم
    (عربي ولاتيني) بتتشال، والألف والياء والتاء المربوطة بتتوحّد، واللاتيني
    بيتصغّر. كده «إيميلي الشخصي!» و«ايميلي الشخصي» بيبقوا نفس العبارة.
    تطبيقها مرتين بيدّي نفس الناتج.
    """
    if not text:
        return ""
    # نص جاي متفكّك (NFD) من برنامج تاني بيترجع للشكل المركّب الأول،
    # عشان القواعد اللي تحت تشتغل على شكل واحد دايمًا
    s = unicodedata.normalize("NFC", text).replace(_TATWEEL, "")
    # الهمزات والمقصورة والتاء المربوطة نطقها واحد، ولو فضلت مختلفة
    # المطابقة هتفشل على كلمات عادية بسبب اختلاف الكتابة
    s = (s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
          .replace("ى", "ي").replace("ة", "ه"))
    s = s.lower()
    # بنسيب الحروف والأرقام (فئات L و N) والفراغات بس — كده التشكيل (M)
    # والترقيم والرموز (P و S) بيتشالوا مرة واحدة من غير ما نعدّد نطاقات
    kept = []
    for ch in s:
        if ch.isspace():
            kept.append(" ")
        elif unicodedata.category(ch)[0] in ("L", "N"):
            kept.append(ch)
    return _SPACES.sub(" ", "".join(kept)).strip()


def word_count(text):
    """عدد الكلمات بعد التطبيع — «تمام، شكراً.» كلمتين."""
    return len(normalize(text).split())


# ── F2: تخطّي الردود القصيرة ─────────────────────────────────────────────────

# قايمة تسمح مش تمنع (R1 #15 + F7): الكلمة اللاتيني لازم تكون من الردود
# الإنجليزي الجاهزة، والأرقام وحدها بتعدّي — بس أي كلمة عربي مش من الردود
# العادية (اسم شخص، منتج، «دوكر») أو كلمة إنجليزي برّا القايمة («Git Hub»)
# بتمشي polish عادي — فالتخطّي شغال آمن حتى والقاموس فاضي.
# العناصر محفوظة بالشكل المطبّع عشان الكتابات المختلفة لنفس الكلمة
# (شكرًا/شكراً) يلاقي نفس العنصر.
SHORT_REPLIES = frozenset({
    # ردود إيجاب
    "اه", "ايوه", "ايو", "حاضر", "طيب", "تمام", "ماشي", "موافق", "طبعا",
    "اكيد", "صح", "نعم", "صحيح", "اتفقنا", "خلاص", "اوكي", "اوك", "حلو", "جميل",
    "ممتاز", "عظيم", "معاك", "معك",
    # ردود سلب
    "لا", "بلاش", "ليش", "مفيش", "ايه",
    # شكر وتبريك وحمد
    "شكرا", "متشكر", "متشكره", "تسلم", "عفوا", "مشكور", "مبروك",
    "الحمد", "لله", "الحمدلله", "ان", "شاء", "الله", "يا", "رب",
    "ربنا", "امين", "بارك", "فيك", "حبيبي",
    # تحية
    "صباح", "الخير", "مساء", "النور", "اهلا", "مرحبا",
    "السلام", "عليكم", "سلام", "السلامه", "ازيك", "بخير", "نورت",
    # اعتذار وطلب بلطف
    "فضلك", "من", "لو", "سمحت", "اسف", "اسفه",
    # أوامر يومية قصيرة
    "ابعت", "ابعتلي", "هات", "افتح", "اقفل", "اكتب", "امسح",
    "شغل", "وقف", "تابع", "كمل",
    # كلمات ربط يومية (بكره/شويه هما بكرة/شوية بعد التطبيع ة→ه)
    "كده", "برضه", "برضو", "كمان", "تاني", "دلوقتي", "بكره",
    "شويه", "يلا", "بس", "يمكن", "ممكن", "مظبوط", "كويس",
    # ضمائر وحروف جر
    "مع", "في", "عن", "ب", "انا", "انت", "انتي",
    "احنا", "هم", "هو", "هي",
    # إنجليزي
    "yes", "yep", "yeah", "no", "nope",
    "ok", "okay", "alright", "right", "sure",
    "will", "do", "done",
    "thanks", "thank", "you", "please",
    "sorry",
    "hello", "hi", "hey",
    "good", "morning", "night", "great", "nice", "cool", "fine", "glad",
    "bye", "welcome",
    "how", "what", "when", "why",
    "me", "my", "your", "we", "us", "they", "he", "she", "it",
    "is", "am", "are", "was", "be",
    "can", "would", "should",
    "a", "the", "and", "but", "not", "only", "just",
    "to", "in", "on", "with",
    "here", "now",
    "one", "two", "three", "four", "five",
    "today", "tomorrow",
    "get", "go", "come",
})


def _is_pure_digits(tok):
    """توكن كله أرقام (٣ أو 3) — الأرقام وحدها بتعدّي من غير قايمة."""
    return bool(tok) and all(c.isdecimal() for c in tok)


def should_bypass(text, mode, cfg):
    """
    هل الرد ده قصير وعادي لدرجة إننا نتخطى لفة الـLLM؟ (F2)

    القايمة تسمح مش تمنع: أي كلمة عربي مش في القايمة (اسم شخص، منتج،
    «دوكر»…) تعني polish عادي — لو الـLLM مش هتعرفها هي اللي هتصلّحها
    (زي «دوكر» ← Docker)، فأسلم اتجاه هو «نمشي اللفة الكاملة» مش «نخفّ».
    الكلمة اللاتيني كمان لازم تكون من القايمة (F7): «Git Hub» أو «Open AI»
    مش تخطّي — بس الأرقام وحدها (١٢٣ أو 123) بتعدّي من غير قايمة.
    """
    if mode != "normal" or not cfg.get("polish", True) or not cfg.get("bypass_short", True):
        return False
    tokens = normalize(text).split()
    if not tokens or len(tokens) > cfg.get("bypass_max_words", 3):
        return False
    return all(tok in SHORT_REPLIES or _is_pure_digits(tok) for tok in tokens)


def light_clean(text):
    """
    تنظيف خفيف للرد اللي اتخطّى الـLLM: قصّ وتجميع الفراغات، وشيل
    «.»/«。」 اللي آخر الجملة لو الكلام 3 كلمات أو أقل — Whisper بيزود
    نقطة ورا الكلمة الواحدة، ودي الوحيدة اللي بنشيلها (F2)
    """
    s = _SPACES.sub(" ", (text or "").strip())
    if word_count(s) <= 3 and s[-1:] in (".", "。"):
        s = s[:-1]
    return s


# ── F5: أساليب السياق (بروفايل لكل برنامج) ────────────────────────────────────

PROFILES = ("dev", "chat", "formal")

# أسماء البرامج (اسم الـexe من غير .exe، حروف صغيرة) → الأسلوب الافتراضي.
# المتصفحات مش هنا عن قصد: Gmail وغيره بيبقوا تاب جوّه كروم، وعنوان النافذة
# مبنقراهوش — فالمتصفح ملوش أسلوب إلا لو المستخدم حدّده بنفسه.
BUILTIN_PROFILES = {
    **dict.fromkeys(("code", "cursor", "windsurf", "devenv", "idea64", "pycharm64", "webstorm64",
                     "windowsterminal", "cmd", "powershell", "pwsh", "mintty", "wezterm-gui",
                     "alacritty"), "dev"),
    **dict.fromkeys(("whatsapp", "telegram", "slack", "discord", "teams", "ms-teams", "signal",
                     "messenger"), "chat"),
    **dict.fromkeys(("outlook", "olk", "winword", "thunderbird"), "formal"),
}


def _profile_for(exe, cfg):
    """البروفايل المسجّل للبرنامج: اختيار المستخدم (app_profiles) بيغلب الخريطة الجاهزة،
    وقيمة محفوظة غلط معناها «مفيش». من غير ما يبص على context_styles."""
    exe = (exe or "").strip().lower()
    if not exe:
        return None
    overrides = cfg.get("app_profiles")
    if isinstance(overrides, dict):
        for name, prof in overrides.items():
            if str(name).strip().lower() == exe:
                return prof if prof in PROFILES else None
    return BUILTIN_PROFILES.get(exe)


def app_profile(exe, cfg):
    """
    أي أسلوب (dev/chat/formal) يناسب البرنامج المفتوح؟ (F5) — بيرجّع المفتاح بس،
    فاسم البرنامج نفسه عمره ما بيوصل للموديل. context_styles مقفول = مفيش أسلوب.
    """
    if not cfg.get("context_styles", True):
        return None
    return _profile_for(exe, cfg)


def is_dev_app(exe, cfg):
    """
    هل الهدف برنامج تطوير؟ (F7) — مستقل عن context_styles: قفل قاعدة الأسلوب مايلغيش
    إن نص برامج البرمجة بيفضل بايت-بايت من غير fix_mixed.
    """
    return _profile_for(exe, cfg) == "dev"


# ── زرار التسجيل: منطق الدوس/التسيب (قرار نقي، بيتشغل من غير pynput) ─────

# أقصى مدة ل«دوسة نضيفة» في وضع toggle: أطول من كده معناه ماسك الزرار
# (أو التكرار التلقائي) مش دوسة.
TAP_MAX = 0.6


class HotkeyLogic:
    """
    قرارات زرار التسجيل: press/release بمفتاح ووقت (now) صريح، وبيتفضّي
    قائمة إجراءات قصيرة: "begin:<mode>", "end", "cancel", "mask" أو [].

    ليه كده: القرار كان مخبّي جوّه start_hotkey في core متشابك مع
    pynput والـApp — فككناه هنا عشان يختبر على مفاتيح عادية (كلمات زي
    "ctrl_r") من غير ويندوز، والوقت جاي حجة مش time.time() عشان الاختبار
    مالاقيش لينت خالص.

    toggle: دوسة نضيفة تبدأ والتانية توقف. كورد (مفتاح معاه مفتاح تاني)
    أو مسكة أطول من TAP_MAX مهمل.
    hold: الدوسة تبدأ وتسيب نفس الزرار يوقف، وأي زرار تاني اتداس
    والتسجيل شغال = cancel (الكلام اللي اتسجل بيرمي بهدوء).
    """

    def __init__(self, key_map, mode_type, tap_max=TAP_MAX, alt_keys=()):
        self._key_map = dict(key_map)
        self._hold = mode_type == "hold"
        self._tap_max = tap_max
        self._alt = set(alt_keys)   # المفاتيح اللي في نفس الوقت زراير Alt — "mask" ليهم
        self._held = {}             # toggle: مفتاح → وقت الدوسة
        self._spoiled = set()       # toggle: مفاتيح اتداست في كورد
        self._active = None         # hold: مفتاح التسجيل اللي ماسكه دلوقتي

    def press(self, key, now, recording, busy):
        if self._hold:
            return self._press_hold(key, now, recording, busy)
        return self._press_toggle(key, now)

    def release(self, key, now, recording, busy):
        if self._hold:
            return self._release_hold(key, now)
        return self._release_toggle(key, now, recording, busy)

    def _mask(self, key):
        # أول دوسة على زرار Alt (لو هو زرار تسجيل) بتطلّع "mask" قبل أي إجراء —
        # حتى لو اتحولت لكورد بعد كده، عشان سيبان Alt مايفتحش قايمة البرنامج.
        # التكرار التلقائي وهو ماسك ملوش mask (المتصل بيتأكد قبل ما ينادي).
        if key in self._key_map and key in self._alt:
            return ["mask"]
        return []

    # ── hold ──

    def _press_hold(self, key, now, recording, busy):
        if self._active is not None and key == self._active:
            return []                  # تكرار تلقائي — مفيش mask ولا إجراء
        acts = self._mask(key)
        if self._active is not None:
            if key == self._active:
                # التكرار التلقائي لزرار التسجيل نفسه وهو لسه ماسك:
                # مايتحسبش دوسة جديدة — وكده لو التسجيل اتلغى (cancel) قبل
                # ما يتسيب الزرار، التكرار مايشغلش تسجيل جديد.
                return acts
            if recording:
                acts.append("cancel")
            return acts
        if key in self._key_map and not recording and not busy:
            self._active = key
            acts.append("begin:" + self._key_map[key])
        return acts

    def _release_hold(self, key, now):
        if key == self._active:
            self._active = None
            # مش لازم يكون recording وقت التسيب: لو begin فشل (ميك مبيفتحش)
            # التسيب يطلع "end" وApp.end() مايقفلش حاجة — نفس تصرف كود
            # قبل الكسح، حرفي.
            return ["end"]
        return []

    # ── toggle ──

    def _press_toggle(self, key, now):
        if key in self._held:
            return []                  # تكرار تلقائي وهو ماسك — مفيش mask ولا إجراء
        acts = self._mask(key)
        for k in self._held:
            if k != key:
                self._spoiled.add(k)
        if key in self._key_map:
            if key in self._held:      # تكرار تلقائي وهو ماسك
                return acts
            self._held[key] = now
            if len(self._held) > 1:
                self._spoiled.add(key)
        else:
            self._spoiled.update(self._held)
        return acts

    def _release_toggle(self, key, now, recording, busy):
        t0 = self._held.pop(key, None)
        clean = key not in self._spoiled
        self._spoiled.discard(key)
        if key not in self._key_map or t0 is None or not clean or now - t0 > self._tap_max:
            return []
        if recording:
            return ["end"]
        elif not busy:
            return ["begin:" + self._key_map[key]]
        return []


# ── F3: الحقن الهجين — تصنيف الهدف واستراتيجية الحقن ───────────────────────────
# قرار «الهدف ده نوعه إيه، ونكتب فيه إزاي؟» هنا بس — winput (ويندوز) و core
# (الحافظة ودورة التسجيل) بينفّذوا النتيجة.

# برامج الجلسات البعيدة (RDP/VM): الحافظة المحلية كتير ماتوصلش جوّه الجلسة
# (مشاركة الحافظة بتبقى مقفولة)، فالسطر الواحد بيتكتب بالكيبورد والمتعدد بـCtrl+V.
REMOTE_EXES = frozenset({
    "mstsc", "wfica32", "cdviewer", "vmware-view", "vmconnect", "msrdc"})

# الترمنالات باسم الـexe، زيادة على كلاسات UIA في TERMINAL_CLASSES — الاتنين لازم:
# ترمنال شغّال بصلاحيات أعلى ممكن مانعرفش نقرا اسم الـexe بتاعه، لكن UIA بتقرا الكلاس.
TERMINAL_EXES = frozenset({
    "windowsterminal", "conhost", "mintty", "alacritty", "wezterm-gui", "conemu64"})

# كلاسات UIA للترمنالات اللي مش بيقولوا عن نفسهم إنهم خانة كتابة
# (Windows Terminal / cmd / ConEmu / mintty). winput.focused_info بياخد
# نفس القائمة لقرار «قابل للكتابة» — مصدر واحد للجانبين.
TERMINAL_CLASSES = ("TermControl", "ConsoleWindowClass", "PseudoConsoleWindow",
                    "VirtualConsoleClass", "mintty")

# عتبة «تلقائي» للحدود العادية: أطول من ده → Ctrl+V بدل الكتابة حرف حرف
# (اللزق أسرع وأأمّن للنص الطويل).
AUTO_PASTE_THRESHOLD = 40


def _gui_strategy(text, method):
    """
    استراتيجية الحد العادي (gui): «تلقائي» = الافتراضي الجديد — نص أطول من
    AUTO_PASTE_THRESHOLD أو متعدّد الأسطر → Ctrl+V، وإلا كتابة حرف حرف؛
    «paste» = دايمًا Ctrl+V؛ «type» والقيم القديمة = حرف حرف، غير إن
    المتعدد لازم يتلزق مرة واحدة (كتابة حرف حرف بتدوس Enter عند كل سطر).
    """
    m = str(method or "auto").strip().lower()
    if m == "paste":
        return "ctrl_v"
    multi = "\n" in text
    if m == "auto":
        return "ctrl_v" if (multi or len(text) > AUTO_PASTE_THRESHOLD) else "type"
    return "ctrl_v" if multi else "type"


def insert_target(info, text, method):
    """
    (نوع الهدف، استراتيجية الحقن، النص اللي يتحقن) من معلومات العنصر
    المركّز (F3):
      نوع    = secure | remote | terminal | gui
      استراتيجيا = type | ctrl_v | shift_insert | handoff
      النص    = بعد سياسة الأسطر لكل نوع (secure: أسطر → مسافات —
                 Enter جوّه خانة باسورد = إرسال)

    بيتنادى مرة لكل نتيجة، قبل السجل/الحافظة/الصوت (R1 #1): التصنيف
    بيرافق العملية، والهدف الآمن عمره مايتمسح ولا يتنسخ ولا يتعرض.
    فشل UIA (is_password / editable = None) بيتعامل «gui» مش «secure»
    (سلوك النهارده) — لو اعتبرنا كل فشل خانة باسورد، السجل كان هيختفي بصمت.
    """
    info = info or {}
    text = text or ""
    if info.get("is_password") is True:
        # خانة باسورد: كيبورد بس، والأسطر بتبقى مسافات (Enter فيها = إرسال)
        return ("secure", "type", re.sub(r"[\r\n]+", " ", text))
    exe = str(info.get("exe") or "").strip().lower()
    cls_name = str(info.get("class") or "")
    multi = "\n" in text
    if exe in REMOTE_EXES:
        # قبل فحص «قابل للكتابة»: UIA بيشوف نافذة برنامج الريموت نفسها مش الخانة اللي
        # جوّه الجلسة، فبيقول editable=False — لو اتفحص الأول عمرنا ما هنكتب في RDP.
        # سطر واحد: كتابة (الحافظة ممكن ماتوصلش للجلسة)؛ المتعدد: Ctrl+V
        return ("remote", "ctrl_v" if multi else "type", text)
    # UIA قال صراحة إن مفيش خانة كتابة: مفيش حقن — handoff = نسخ وعرض في الواجهة
    if info.get("editable") is False:
        return ("gui", "handoff", text)
    if cls_name in TERMINAL_CLASSES or exe in TERMINAL_EXES:
        # المتعدد في الترمنال ممكن «يتنفّذ» سطر سطر حسب وضع bracketed-paste في الـshell،
        # ومينفعش نعرفه (R1 #4) — فمش بنحقنه، بنسلّمه للمستخدم
        return ("terminal", "shift_insert" if not multi else "handoff", text)
    return ("gui", _gui_strategy(text, method), text)


# ── F7: تصحيح النص المختلط (عربي/لاتيني) ─────────────────────────────────────
# نموذج الكتابة المفروض هو «للـ branch»: حرف التطويل + مسافة واحدة ورا الحرف
# العاري قبل الكلمة اللاتيني. بس المخرج ممكن ييجي بأي شكل («للbranch»،
# «للـbranch»، «لل branch») حسب الموديل أو النص القديم — فبنوحّده عشان العرض
# والحقن. الترقيم كمان: ، ؟ ؛ عربي في جملة عربية-الغالب، من غير ما نلمس
# الأرقام (1,000) والرلينكات والإيميلات والكود (جوّه backticks) والجمل
# الإنجليزية-الغالب. مش بنحط أي حروف تحكم اتجاه (U+200E/U+200F/U+061C).
# ليه محلي مش للموديل: القاعدة حتمية ورخيصة، وبتصلّح حتى الردود اللي
# اتخطّت الموديل خالص (F2).

# حروف العربية (الكتلة الأساسية + الملحقات + أشكال العرض)
_ARABIC_CHARS = "\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF"
_AR_LETTER = re.compile("[" + _ARABIC_CHARS + "]")


def _arabic_letters():
    """حروف العربية بس (فئة الحروف L) من نطاقاتها — من غير علامات الترقيم والأرقام.

    النطاق 0600-06FF فيه ، ؛ ؟ وأرقام هندية جوّه الحروف — فلو استبعدناه كله في
    الـlookbehind كانت «راجع،الAPI» عمرها ما تتصلّح. بناخد الحروف بس، فالترقيم
    والأرقام قبل «ال/لل/بال» بيبقوا حد كلمة طبيعي.
    """
    out = []
    for lo, hi in ((0x0600, 0x06FF), (0x0750, 0x077F), (0x08A0, 0x08FF),
                   (0xFB50, 0xFDFF), (0xFE70, 0xFEFF)):
        for cp in range(lo, hi + 1):
            ch = chr(cp)
            if unicodedata.category(ch)[0] == "L":
                out.append(ch)
    return "".join(out)


_ARABIC_LETTERS = _arabic_letters()

# الحرف العاري قبل كلمة لاتيني: «لل/بال/ال» + تطويل اختياري + مسافات اختيارية.
# الـlookbehind عشان كلمة عربي بتخلص في «ال» (زي «السائل») متتقسمش نصّ.
_ARTICLE = re.compile(
    r"(?<![" + _ARABIC_LETTERS + r"])(لل|بال|ال)(\u0640*)[ \t]*([A-Za-z])")

_PUNCT_MAP = {",": "\u060c", "?": "\u061F", ";": "\u061B"}
_PUNCT = re.compile(r"[,?;]")
# إشارة الترقيم دي متخلّية جوه لينك (scheme:// أو www.) أو إيميل
_URL_BEFORE = re.compile(r"(?:[A-Za-z][A-Za-z0-9+.-]*://|www\.)[^\s]*\Z")
_EMAIL_BEFORE = re.compile(r"[\w.%+-]+@[^\s]*\Z")
# F4/F5: أي حاجة محمية بايت-بايت من القاعدتين (article والترقيم):
# جوه backticks (كود)، أو لينك كامل (scheme:// أو www.)، أو إيميل — مصدر
# واحد للتقسيم عشان القاعدتين ميتفرقوش.
_PROTECTED = re.compile(r"`+|(?:[A-Za-z][A-Za-z0-9+.-]*://|www\.)[^\s]*|[\w.%+-]+@[^\s]+")


def _fix_article(s):
    """«للbranch»/«للـbranch»/«لل branch» → «للـ branch» — ونفسها للـ«الـ» والـ«بالـ»."""
    return _ARTICLE.sub(lambda m: m.group(1) + _TATWEEL + " " + m.group(3), s)


def _arabize_punct(s):
    """
    , ? ; → ، ؟ ؛ بس لما الإشارة جنب عربي، أو وراه بالضبط كلمة لاتيني بتخلص
    جملة عربية (…الـ API, …). أي حاجة تانية (أرقام، لينكات، إيميلات)
    بتفضل زي ما هي.
    """
    def _one(m):
        i = m.start()
        left = s[i - 1] if i > 0 else ""
        right = s[i + 1] if i + 1 < len(s) else ""
        # فاصل رقمي (1,000): رقم على الاتنين = مش ترقيم جملة
        if left.isdigit() and right.isdigit():
            return m.group(0)
        head = s[:i]
        if _URL_BEFORE.search(head) or _EMAIL_BEFORE.search(head):
            return m.group(0)
        # العربية على أي جنب = كده كفاية
        if _AR_LETTER.fullmatch(left) or _AR_LETTER.fullmatch(right):
            return _PUNCT_MAP[m.group(0)]
        # كلمة لاتيني مغمورة في جملة عربية (عربي أو تطويل وراها بعد أي مسافة)
        # = الترقيم هنا عربي مش إنجليزي
        if left.isascii() and left.isalpha():
            j = i - 1
            while j >= 0 and s[j].isascii() and s[j].isalnum():
                j -= 1
            while j >= 0 and s[j] in " \t":
                j -= 1
            if j >= 0 and (_AR_LETTER.fullmatch(s[j]) or s[j] == _TATWEEL):
                return _PUNCT_MAP[m.group(0)]
        return m.group(0)
    return _PUNCT.sub(_one, s)


def _outside_protected(s, fn):
    """
    بيطبّق القاعدة (article أو ترقيم) على النص العادي بس. المحمي: جوه
    backticks (كود — F4)، الروابط (scheme:// أو www.)، والإيميلات (F5) —
    كل دول بيفضلوا بايت-بايت. فتحة backtick من غير قفلة: الباقي كله بيتعامل
    كود (تعليق كود ناقص) زي ما هو.
    """
    out = []
    i = 0
    inside = False
    while i < len(s):
        m = _PROTECTED.search(s, i)
        if m is None:
            out.append(s[i:] if inside else fn(s[i:]))
            break
        start = m.start()
        out.append(s[i:start] if inside else fn(s[i:start]))
        tok = m.group(0)
        out.append(tok)
        if tok.startswith("`"):
            inside = not inside
        i = m.end()
    return "".join(out)


def _arabic_dominant(s):
    """حروف عربية أكتر من لاتيني — السطر اللي بيفرق بين «خلّي» و«سيبها إنجليزي»."""
    ar = sum(1 for c in s if _AR_LETTER.fullmatch(c))
    la = sum(1 for c in s if c.isascii() and c.isalpha())
    return ar > la


def fix_mixed(text):
    """
    F7: يوحّد شكل النص المختلط في جملة واحدة:
      • الحرف العاري قبل كلمة لاتيني على شكله المثالي
        («للـ branch» / «الـ API» / «بالـ code» — تطويل + مسافة واحدة).
      • , ? ; بالجمل العربية-الغالب على ، ؟ ؛.
    مبيلمسش: أرقام بفواصل (1,000)، لينكات، إيميلات، جوه backticks،
    جمل إنجليزي-الغالب. مبيحطش حروف تحكم اتجاه. تطبيقه مرتين = نفس الناتج.
    """
    s = str(text or "")
    if not s:
        return s
    s = _outside_protected(s, _fix_article)
    if _arabic_dominant(s):
        s = _outside_protected(s, _arabize_punct)
    return s


# ── باقي الدوال: التوقيع متفق عليه هنا، والتنفيذ في المهام الجاية ─────────

def match_snippet(text, snippets):
    """هل الكلام كله هو جملة اختصار صوتي؟ يرجّع الاختصار أو None (F8)"""
    raise NotImplementedError


def is_network_error(err):
    """هل الخطأ ده من النت (مش مفتاح غلط ولا حد استخدام)؟ (F9)"""
    raise NotImplementedError
