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

# قايمة تسمح مش تمنع (R1 #15): التوكن اللي كله لاتيني أو أرقام بيتقبل زي ما
# هو، بس أي كلمة عربي مش من الردود العادية (اسم شخص، منتج، «دوكر») بتمشي polish
# عادي — فالتخطّي شغال آمن حتى والقاموس فاضي.
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


def _is_latin_or_digit(tok):
    """توكن كله حروف لاتيني وأرقام — مفيش لهجي عربي يتصلّح."""
    return all((c.isascii() and c.isalpha()) or c.isdecimal() for c in tok)


def should_bypass(text, mode, cfg):
    """
    هل الرد ده قصير وعادي لدرجة إننا نتخطى لفة الـLLM؟ (F2)

    القايمة تسمح مش تمنع: أي كلمة عربي مش في القايمة (اسم شخص، منتج،
    «دوكر»…) تعني polish عادي — لو الـLLM مش هتعرفها هي اللي هتصلّحها
    (زي «دوكر» ← Docker)، فأسلم اتجاه هو «نمشي اللفة الكاملة» مش «نخفّ».
    """
    if mode != "normal" or not cfg.get("polish", True) or not cfg.get("bypass_short", True):
        return False
    tokens = normalize(text).split()
    if not tokens or len(tokens) > cfg.get("bypass_max_words", 3):
        return False
    return all(tok in SHORT_REPLIES or _is_latin_or_digit(tok) for tok in tokens)


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


def app_profile(exe, cfg):
    """
    أي أسلوب (dev/chat/formal) يناسب البرنامج المفتوح؟ (F5) — بيرجّع المفتاح بس،
    فاسم البرنامج نفسه عمره ما بيوصل للموديل. اختيار المستخدم (app_profiles)
    بيغلب الخريطة الجاهزة، وقيمة محفوظة غلط معناها «من غير أسلوب».
    """
    if not cfg.get("context_styles", True):
        return None
    exe = (exe or "").strip().lower()
    if not exe:
        return None
    overrides = cfg.get("app_profiles")
    if isinstance(overrides, dict):
        for name, prof in overrides.items():
            if str(name).strip().lower() == exe:
                return prof if prof in PROFILES else None
    return BUILTIN_PROFILES.get(exe)


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


# ── باقي الدوال: التوقيع متفق عليه هنا، والتنفيذ في المهام الجاية ─────────

def fix_mixed(text):
    """يرتّب الترقيم والفراغات بين عربي وإنجليزي في جملة واحدة (F7)"""
    raise NotImplementedError


def insert_target(info, text, method):
    """(نوع الهدف، استراتيجية الحقن) من معلومات UIA والاختيار (F3)"""
    raise NotImplementedError


def match_snippet(text, snippets):
    """هل الكلام كله هو جملة اختصار صوتي؟ يرجّع الاختصار أو None (F8)"""
    raise NotImplementedError


def is_network_error(err):
    """هل الخطأ ده من النت (مش مفتاح غلط ولا حد استخدام)؟ (F9)"""
    raise NotImplementedError
