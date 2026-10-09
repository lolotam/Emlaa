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
import socket
import difflib
import http.client
import unicodedata
import urllib.error
from collections import namedtuple


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

# ── الزراير بأرقام ويندوز (vk) ─────────────────────────────────────────────
# الزرار بيتعرف برقمه مش باسمه في pynput: Alt اليمين في كيبورد عليه عربي ويندوز
# بيبعته AltGr، وpynput بيفرّق alt_r (extended) عن alt_gr مع إن الاتنين VK_RMENU —
# فالمقارنة بالاسم كانت بتفشل. والزرار اللي بيتسجّل من الكيبورد بيتحفظ برقمه زي ما هو.
VK_ESCAPE = 0x1B
MODIFIER_VKS = frozenset({0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C})
# الـhook دايمًا بيبعت الكود اليمين/الشمال — العام (0x10–0x12) عمره ما بييجي له تسيب، فلو
# اتحسب ماسك وقت بداية المستمع كان هيفضل ماسك للأبد ويبوّظ كل الزراير
SIDE_MODIFIER_VKS = MODIFIER_VKS - {0x10, 0x11, 0x12}

# أسماء الإعدادات القديمة (قايمة الزراير الثابتة) ← رقمها — للترحيل بس
LEGACY_HOTKEY_VKS = {
    "ctrl_r": 0xA3, "alt_r": 0xA5, "shift_r": 0xA1, "caps_lock": 0x14, "scroll_lock": 0x91,
    "f6": 0x75, "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
}

Hotkey = namedtuple("Hotkey", "mods trigger")


def hotkey_shape_ok(vks):
    """[] أو [أي زرار] أو [موديفاير، زرار مش موديفاير] — وEsc ممنوع (هو الإلغاء)."""
    vks = list(vks or [])
    if VK_ESCAPE in vks or len(vks) > 2:
        return False
    if len(vks) == 2:
        return vks[0] in MODIFIER_VKS and vks[1] not in MODIFIER_VKS
    return True


def hotkey_from_vks(vks):
    """[] = مفيش زرار (None)؛ [t] = زرار لوحده؛ [m, t] = موديفاير + الزرار اللي بيشغّل."""
    vks = list(vks or [])
    if not vks:
        return None
    return Hotkey(frozenset(vks[:-1]), vks[-1])


class HotkeyMatcher:
    """
    المطابقة الوحيدة: المنع (HotkeyFilter) والتشغيل (HotkeyLogic) بيسألوها هي، عشان
    مفيش زرار يتمنع ومايشتغلش. F7 وCtrl+F7 ممكن يبقوا وضعين مختلفين: التطابق على
    الموديفايرز الماسكة بالظبط — زيادة موديفاير (Shift+F7) مش بتطابق حاجة.
    """

    def __init__(self, hotkeys):
        self._by_trigger = {}
        for mode, hk in hotkeys.items():
            if hk is not None:
                self._by_trigger.setdefault(hk.trigger, []).append((hk.mods, mode))

    def match(self, trigger, held):
        held_mods = (frozenset(held) & MODIFIER_VKS) - {trigger}
        for mods, mode in self._by_trigger.get(trigger, ()):
            if mods == held_mods:
                return mode
        return None

    def triggers(self):
        return set(self._by_trigger)


_VK_NAMES = {
    0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x13: "Pause", 0x14: "Caps Lock",
    0x20: "Space", 0x21: "Page Up", 0x22: "Page Down", 0x23: "End", 0x24: "Home",
    0x25: "Left", 0x26: "Up", 0x27: "Right", 0x28: "Down", 0x2C: "Print Screen",
    0x2D: "Insert", 0x2E: "Delete", 0x90: "Num Lock", 0x91: "Scroll Lock",
    0xA6: "Browser Back", 0xA7: "Browser Forward", 0xA8: "Browser Refresh", 0xA9: "Browser Stop",
    0xAA: "Browser Search", 0xAB: "Browser Favorites", 0xAC: "Browser Home",
    0xAD: "Mute", 0xAE: "Volume Down", 0xAF: "Volume Up", 0xB0: "Media Next",
    0xB1: "Media Prev", 0xB2: "Media Stop", 0xB3: "Media Play/Pause", 0xB4: "Mail",
    0xB5: "Media Select",
}
# الموديفايرز بس اللي ليها اسم عربي (يمين/شمال) — الباقي نفس الكتابة في اللغتين
_MOD_NAMES = {
    0x10: ("Shift", "Shift"), 0x11: ("Ctrl", "Ctrl"), 0x12: ("Alt", "Alt"),
    0xA0: ("Shift الشمال", "Left Shift"), 0xA1: ("Shift اليمين", "Right Shift"),
    0xA2: ("Ctrl الشمال", "Left Ctrl"), 0xA3: ("Ctrl اليمين", "Right Ctrl"),
    0xA4: ("Alt الشمال", "Left Alt"), 0xA5: ("Alt اليمين", "Right Alt"),
    0x5B: ("Win الشمال", "Left Win"), 0x5C: ("Win اليمين", "Right Win"),
}


def vk_label(vk, lang="ar"):
    if vk in _MOD_NAMES:
        ar, en = _MOD_NAMES[vk]
        return en if lang == "en" else ar
    if 0x70 <= vk <= 0x87:
        return "F%d" % (vk - 0x6F)
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        return chr(vk)
    return _VK_NAMES.get(vk, "Key 0x%02X" % vk)


def hotkey_label(vks, lang="ar"):
    return " + ".join(vk_label(v, lang) for v in (vks or []))


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

    «هل الدوسة دي زرار تسجيل؟» بيتقرر من HotkeyMatcher بالموديفايرز الماسكة (held):
    نفس المطابقة اللي بتقرر المنع، فمفيش زرار يتمنع ومايشتغلش. قاموس {زرار: وضع}
    القديم لسه مقبول (زراير لوحدها من غير موديفايرز).
    """

    def __init__(self, matcher, mode_type, tap_max=TAP_MAX, alt_keys=(), cancel_keys=()):
        if not isinstance(matcher, HotkeyMatcher):
            matcher = HotkeyMatcher({mode: Hotkey(frozenset(), key) for key, mode in dict(matcher).items()})
        self._matcher = matcher
        self._triggers = matcher.triggers()
        self._hold = mode_type == "hold"
        self._tap_max = tap_max
        self._alt = set(alt_keys)   # المفاتيح اللي في نفس الوقت زراير Alt — "mask" ليهم
        self._cancel = set(cancel_keys)   # مفاتيح الإلغاء (Esc) — بس لو مش زراير تسجيل
        self._held = {}             # toggle: مفتاح → (وقت الدوسة، الوضع اللي طابقه)
        self._spoiled = set()       # toggle: مفاتيح اتداست في كورد
        self._active = None         # hold: مفتاح التسجيل اللي ماسكه دلوقتي

    def press(self, key, now, recording, busy, held=frozenset()):
        # مفتاح إلغاء (مش زرار تسجيل): بيطلّع "cancel" وقت التسجيل في الوضعين،
        # وno-op وقت الخمول من غير ما يلمس الحالة (منيفسدش hotkey متعقدة).
        if key in self._cancel and key not in self._triggers:
            if recording:
                # F6: لو زرار تسجيل متعقد اتساس دلوقتي والتسجيل هيتلغى، بنففسد كل
                # المتعقدين — عشان تسيب الزرار بعد الإلغاء ميشغّلش تسجيل جديد.
                self._spoiled.update(self._held)
                return ["cancel"]
            return []
        mode = self._matcher.match(key, held)
        if self._hold:
            return self._press_hold(key, mode, recording, busy)
        return self._press_toggle(key, now, mode)

    def release(self, key, now, recording, busy):
        if self._hold:
            return self._release_hold(key, now)
        return self._release_toggle(key, now, recording, busy)

    def _mask(self, key):
        # أول دوسة على زرار Alt (لو هو زرار تسجيل) بتطلّع "mask" قبل أي إجراء —
        # حتى لو اتحولت لكورد بعد كده، عشان سيبان Alt مايفتحش قايمة البرنامج.
        # التكرار التلقائي وهو ماسك ملوش mask (المتصل بيتأكد قبل ما ينادي).
        if key in self._triggers and key in self._alt:
            return ["mask"]
        return []

    # ── hold ──

    def _press_hold(self, key, mode, recording, busy):
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
        if mode is not None and not recording and not busy:
            self._active = key
            acts.append("begin:" + mode)
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

    def _press_toggle(self, key, now, mode):
        if key in self._held:
            return []                  # تكرار تلقائي وهو ماسك — مفيش mask ولا إجراء
        acts = self._mask(key)
        for k in self._held:
            if k != key:
                self._spoiled.add(k)
        if mode is not None:
            # الوضع بيتثبّت وقت الدوسة: Ctrl لو اتساب قبل الزرار مايغيّرش الوضع
            self._held[key] = (now, mode)
            if len(self._held) > 1:
                self._spoiled.add(key)
        else:
            self._spoiled.update(self._held)
        return acts

    def _release_toggle(self, key, now, recording, busy):
        entry = self._held.pop(key, None)
        clean = key not in self._spoiled
        self._spoiled.discard(key)
        if entry is None or not clean or now - entry[0] > self._tap_max:
            return []
        if recording:
            return ["end"]
        elif not busy:
            return ["begin:" + entry[1]]
        return []


class HotkeyFilter:
    """
    قرار «نمنع الحدث ده عن البرامج التانية؟» — بيتحسب جوّه الـhook نفسه (لازم يبقى سريع).
    المنع بنفس HotkeyMatcher اللي بيشغّل التسجيل. القرار بيتثبّت لكل دوسة حقيقية لحد
    التسيب: التكرار التلقائي والتسيب بياخدوا قرار أول دوسة، حتى لو Ctrl اتداس أو اتساب
    في النص (غير كده البرنامج كان ممكن يستلم تسيب من غير دوسة أو العكس).
    الموديفاير لوحده (Ctrl/Alt/Shift/Win) عمره ما بيتمنع — Ctrl+C وأخواتها تفضل شغّالة.
    initially_down: الزراير الماسكة وقت ما المستمع بدأ (من ويندوز) — عشان Ctrl الماسك
    من قبل يتحسب. is_down(vk): حالة الزرار الفعلية — قبل أي زرار عادي بنشيل الموديفاير اللي
    مبقاش ماسك (تسيبه ضاع، زي Ctrl+Alt+Del أو Win+L) عشان مايفضلش يبوّظ المطابقة.
    """

    def __init__(self, matcher, initially_down=frozenset(), is_down=None):
        self._matcher = matcher
        self._down = set(initially_down)
        self._latched = {}
        self._is_down = is_down

    def event(self, vk, is_press, injected, fake_altgr_ctrl):
        """بيرجّع (dispatch, suppress): نبعته لمنطق الزراير؟ ونمنعه عن البرامج التانية؟"""
        if injected or fake_altgr_ctrl:
            return False, False
        if is_press:
            if vk not in self._down:
                if self._is_down is not None and vk not in MODIFIER_VKS:
                    self._down = {k for k in self._down if k not in MODIFIER_VKS or self._is_down(k)}
                matched = self._matcher.match(vk, frozenset(self._down)) is not None
                self._latched[vk] = matched and vk not in MODIFIER_VKS
                self._down.add(vk)
            return True, self._latched.get(vk, False)
        suppress = self._latched.pop(vk, False)
        self._down.discard(vk)
        return True, suppress

    def held(self):
        return frozenset(self._down)


CAPTURE_PAIR_ERR = "لازم زرار منهم يبقى Ctrl أو Alt أو Shift أو Win"


class CaptureSession:
    """
    تسجيل زرار التسجيل من الكيبورد (count = ١ أو ٢). بيسجّل الزراير اللي اتداست جوّه
    الجلسة بس: الزراير الماسكة من قبلها (initially_down) — حتى تكرارها التلقائي — مش
    بتاعتنا لحد ما تتساب، فتعدّي للبرنامج زي ما هي ومايفضلش فيه زرار «متعلّق».
    decided = النتيجة (أو الغلط أو الإلغاء) اتعرفت؛ finished = decided وكل زرار
    سجّلناه اتساب — المستمع لازم يفضل يمنع لحد finished، غير كده البرنامج التاني
    يستلم تسيب زرار ما استلمش دوسته.
    """

    def __init__(self, count, initially_down=frozenset()):
        self._count = count
        self._foreign = set(initially_down)
        self._down = []             # زرايرنا الماسكة دلوقتي بترتيب الدوس
        self._pair = None           # count=2: أول زرارين اتمسكوا مع بعض
        self.decided = False
        self.cancelled = False
        self.error = None
        self.result = None

    @property
    def finished(self):
        return self.decided and not self._down

    def captured_down(self):
        """زرايرنا اللي لسه ماسكة — المستمع مايتقفلش وفيه واحد منهم (تسيبه هيتمنع)."""
        return frozenset(self._down)

    def event(self, vk, is_press, fake_altgr_ctrl):
        """True = الحدث ده بتاعنا (لازم يتمنع عن البرامج التانية)."""
        if fake_altgr_ctrl:
            return False
        if vk in self._foreign:
            if not is_press:
                self._foreign.discard(vk)
            return False
        if is_press:
            if vk in self._down:
                return True                         # تكرار تلقائي لزرار بتاعنا
            if self.decided:
                return False                        # زرار جديد بعد ما خلصنا — مش بتاعنا
            self._down.append(vk)
            if vk == VK_ESCAPE and len(self._down) == 1:
                self.cancelled = self.decided = True
            elif self._count == 2 and self._pair is None and len(self._down) >= 2:
                self._pair = self._down[:2]
            return True
        if vk not in self._down:
            return False
        self._down.remove(vk)
        if not self.decided:
            if self._count == 1:
                self._decide([vk])
            elif self._pair is not None:
                mods = [k for k in self._pair if k in MODIFIER_VKS]
                keys = [k for k in self._pair if k not in MODIFIER_VKS]
                if len(mods) == 1 and len(keys) == 1:
                    self._decide([mods[0], keys[0]])
                else:
                    self.error, self.decided = CAPTURE_PAIR_ERR, True
        return True

    def _decide(self, vks):
        self.decided = True
        if hotkey_shape_ok(vks):
            self.result = vks
        else:
            self.error = "الزرار ده مينفعش يبقى زرار تسجيل"


# ── إعدادات الميزات الأربعة: كل ميزة ليها زرارها وقايمة تفريغ وقايمة معالجة ──────
FEATURES = ("normal", "prompt", "translate", "edit")
LOCAL = "local"                       # الموديل المحلي (Whisper من غير إنترنت) — عنصر تفريغ بس
STT_ONLY = ("deepgram", LOCAL)        # بيفرّغوا بس — ممنوعين في قايمة المعالجة
KNOWN_PROVIDERS = ("groq", "openai", "gemini", "deepgram")
_CHAT_FALLBACK_ORDER = ("groq", "gemini", "openai")


def default_features(cfg, pools, local_model, stt_orders, chat_orders):
    """
    ترحيل الإعدادات القديمة (مزوّد واحد لكل حاجة) لقوايم الميزات من غير تغيير في التصرف:
    البدائل اللي كانت مخبّية جوّه المزوّد (stt_alt / chat_alt) بتبقى عناصر ظاهرة بنفس
    الترتيب. cfg = الملف القديم؛ stt_orders/chat_orders = ترتيب النهارده لكل مزوّد.
    """
    names = {"normal": cfg.get("hotkey_normal") or cfg.get("hotkey"),
             "prompt": cfg.get("hotkey_prompt"), "translate": cfg.get("hotkey_translate"),
             "edit": cfg.get("hotkey_edit")}
    pid = cfg.get("provider") if cfg.get("provider") in KNOWN_PROVIDERS else "groq"
    local = {"provider": LOCAL, "model": ""}

    # «من غير إنترنت دايمًا» كان اختيار خصوصية: النص عمره ما راح لموديل — فالعادي بيفضل
    # خام. البرومبت/الترجمة/التعديل مايشتغلوش من غير معالجة أصلًا، فبياخدوا القايمة
    local_only = cfg.get("offline_mode") == "always"
    if local_only:
        stt = [local]
    else:
        stt = [{"provider": pid, "model": m} for m in stt_orders.get(pid) or []]
        if local_model and cfg.get("offline_mode", "fallback") == "fallback":
            stt.append(local)
        stt = stt or [local]

    candidates = [pid] + [p for p in _CHAT_FALLBACK_ORDER if p != pid]
    chat_capable = [p for p in candidates if chat_orders.get(p)]
    keyed = [p for p in chat_capable if pools.get(p)]
    ai_pid = keyed[0] if keyed else (chat_capable[0] if chat_capable else None)
    ai = [{"provider": ai_pid, "model": m} for m in chat_orders.get(ai_pid) or []]

    out = {}
    for mode in FEATURES:
        vk = LEGACY_HOTKEY_VKS.get(str(names[mode] or "").strip().lower())
        out[mode] = {
            "hotkey": [vk] if vk else [],
            "stt": [dict(i) for i in stt],
            # من غير ولا مفتاح شات: العادي بيفضل خام زي النهارده؛ الباقي محتاج معالجة
            # فبياخد أول مزوّد شات — التشغيل هيقول إن المفتاح ناقص بدل ما الحفظ يترفض
            "ai": [dict(i) for i in ai] if ((keyed and not local_only) or mode != "normal") else [],
        }
    return out


def validate_features(features, known=KNOWN_PROVIDERS):
    """قبل الحفظ بس: رسالة الغلط بالعربي، أو None لو الإعدادات سليمة."""
    if not isinstance(features, dict) or any(not isinstance(features.get(m), dict) for m in FEATURES):
        return "إعدادات الميزات ناقصة"
    seen = {}
    for mode in FEATURES:
        f = features[mode]
        stt, ai, hk = f.get("stt"), f.get("ai"), f.get("hotkey")
        if not isinstance(stt, list) or not stt:
            return "لازم يبقى فيه مزوّد تفريغ واحد على الأقل في كل ميزة"
        if not isinstance(ai, list) or (not ai and mode != "normal"):
            return "لازم يبقى فيه موديل معالجة واحد على الأقل (غير التسجيل العادي)"
        for item in stt:
            if not isinstance(item, dict) or item.get("provider") not in tuple(known) + (LOCAL,):
                return "مزوّد تفريغ مش معروف"
        for item in ai:
            if not isinstance(item, dict) or item.get("provider") not in known \
                    or item.get("provider") in STT_ONLY or not item.get("model"):
                return "المعالجة محتاجة مزوّد بيعرف يكتب (مش Deepgram ولا الموديل المحلي)"
        if not isinstance(hk, list) or not all(isinstance(v, int) for v in hk) or not hotkey_shape_ok(hk):
            return "زرار التسجيل مش مظبوط — زرار واحد، أو Ctrl/Alt/Shift/Win مع زرار"
        if hk:
            if tuple(hk) in seen:
                return "كل ميزة لازم يبقى ليها زرار مختلف"
            seen[tuple(hk)] = mode
    # Ctrl اليمين لوحده زرار ميزة، وCtrl اليمين + F8 زرار ميزة تانية: دوسة Ctrl هتبدأ
    # الأولى وF8 هيلغيها — فبنرفض التركيبة دي من الأول
    singles = {k[0] for k in seen if len(k) == 1}
    if any(len(k) == 2 and k[0] in singles for k in seen):
        return "زرار لوحده مينفعش يبقى أول زرار في تركيبة ميزة تانية"
    return None


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


# ── F2: قرار مبدئي للغة البرومبت (القرار النهائي في providers._prompt_lang) ────
# قرار نقي رخيص: الطلب التقني الأكيد = "en"، والمش واضح = None (بيتساب للموديل).
# الكلمات العربي التقنية القوية بتمسك على شكلها المطبّع (normalize) عشان الهمزة
# والتاء المربوطة والألف مايفرقوش في الكتابات المصرية (ابليكيشن/الويب سايت…).

# كلمات تقنية عربي قوية (والمصري منها) — أي واحدة في الطلب = الطلب تقني أكيد.
# القايمة دي مش كل الكلمات التقنية: الكلمات الملتبسة اتشالت عشان معناها بيختلف
# حسب السياق — «برنامج» ممكن «برنامج غذائي» (مش تقني) و«تطبيق» ممكن «تطبيق
# القانون» و«موقع» ممكن «موقع البيت». دي مبيتقررش في الكود؛ بتتساب للموديل
# (providers._prompt_lang بيسأل TECH/OTHER). «كود» و«سكريبت» برضه ملتبسين: «كود خصم»
# و«سكريبت إعلان» طلبات تسويق مش برمجة.
TECH_ARABIC_KEYWORDS = frozenset({
    "ابليكيشن", "الابليكيشن", "أبليكيشن", "الأبليكيشن",
    "برمجة", "مبرمج",
    "سيرفر", "سرفر",
    "داتابيز", "داتا بيز",
    "قاعدة بيانات", "قاعده بيانات",
    "باك اند", "الباك اند",
    "فرونت اند", "الفرونت اند",
    "ويب سايت", "الويب سايت",
    "سوفتوير", "سوفت وير",
    "ديفلوبر", "مطور برمجيات",
    "لوجين", "داشبورد",
})

# مصطلحات تقنية لاتيني — بتتطابق على حدود الكلمة (عشان "app" ماتمسكش في "happy").
# بس المصطلحات اللي ملهاش معنى تاني: «discount code» و«script إعلان» و«app» و«cloud»
# و«server» (جرسون) و«library» و«java» (قهوة)… كلمات عادية كمان، فبتروح للتصنيف
# (providers._prompt_lang) زي «كود» و«سكريبت». الطلب الإنجليزي كله بيتمسك من غلبة اللاتيني.
TECH_LATIN_TERMS = (
    "api", "python", "nodejs", "javascript", "typescript",
    "html", "css", "docker", "github", "sql", "mysql", "postgres",
    "database", "backend", "frontend", "fullstack", "website",
    "coding", "programming", "developer", "software",
    "deployment", "devops", "aws", "azure", "android", "ios",
    "flutter", "kotlin", "php", "django",
    "kubernetes", "graphql", "json", "linux", "algorithm", "blockchain",
)

# عبارات لاتيني من أكتر من كلمة — بتمسك كـsubstring بعد تصغير الحروف.
TECH_LATIN_PHRASES = (
    "back end", "back-end", "front end", "front-end", "machine learning",
    "deep learning", "artificial intelligence", "smart contract",
)

# الكلمة لازم تقف لوحدها (بعد التطبيع): مسموح سابقة (و/ف/ب/ل/ك + ال/لل) ولاحقة قصيرة
# (جمع/ضمير) بس. المطابقة كـsubstring كانت بتمسك «ويب» جوّه «ويبقى» و«موقع» جوّه
# «موقعة» — فطلبات عربي عادية كانت بتطلع برومبت إنجليزي (نفس الغلطة اللي بنصلّحها).
# «تطوير» اتشالت: «تطوير الذات» مش طلب تقني.
_TECH_ARABIC_RE = re.compile(
    r"(?:^| )(?:[وفبلك])?(?:ال|لل)?(?:"
    + "|".join(sorted((re.escape(normalize(k)) for k in TECH_ARABIC_KEYWORDS), key=len, reverse=True))
    + r")(?:ات|ين|ان|ه|ها|ي|ك|كم|نا|هم)?(?= |$)")

_LATIN_TECH_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(t) for t in TECH_LATIN_TERMS) + r")\b", re.I)


# معرّفات مش كلام: إيميل، لينك، دومين بـwww، @حساب
_IDENTIFIER_RE = re.compile(r"\S+@\S+|https?://\S+|www\.\S+|@\w+")


def _is_ar_letter(c):
    """حرف عربي فعلًا (فئة L) — مش رقم هندي ولا ، ؛ ؟ من نفس النطاق."""
    return bool(_AR_LETTER.fullmatch(c)) and unicodedata.category(c).startswith("L")


def latin_dominant(text):
    """حروف لاتينية أكتر من عربي — بيستخدم في فحص لغة مخرج البرومبت (F2)."""
    s = str(text or "")
    ar = sum(1 for c in s if _is_ar_letter(c))
    la = sum(1 for c in s if c.isascii() and c.isalpha())
    return la > ar


def prompt_language(text):
    """
    القرار المحلي للغة برومبت الطلب: "en" | "ar" | None (F2).
      • "en" لو الطلب نفسه إنجليزي — مفيش فيه حرف عربي وأغلبه لاتيني (بعد شيل
        الإيميلات واللينكات).
      • "ar" للنص الفاضي بس.
      • None لأي طلب عربي أو مخلوط: القرار هنا بيتاخد من الموديل (providers._prompt_lang
        بيسأل TECH/OTHER حسب اللي المستخدم عايز يطلّعه). الكلمات التقنية مبتقررش
        لوحدها: «اكتب إعلان لدورة Python» و«اكتب رسالة فيها كود خصم» طلبات كتابة
        مش برمجة — فبتستخدم بس كتخمين لو التصنيف نفسه فشل (tech_guess).
    """
    s = str(text or "")
    if not s.strip():
        return "ar"
    # الطريق المختصر للإنجليزي بس لو مفيش ولا حرف عربي: «اكتب إعلان لدورة JavaScript
    # و TypeScript» حروفها اللاتيني أكتر بس هي طلب عربي (كتابة) — لازم توصل للتصنيف.
    # وبنشيل الإيميل/اللينك/@الحساب الأول عشان مايعدّوش كلام.
    bare = _IDENTIFIER_RE.sub(" ", s)
    if not has_arabic(bare) and latin_dominant(bare):
        return "en"
    return None


def is_english(text):
    """كلام إنجليزي خالص (مفيش ولا حرف عربي) — بيتنضّف بقواعد إنجليزي. المخلوط عربي."""
    return prompt_language(text) == "en"


def has_arabic(text):
    """فيه حرف عربي فعلًا — مش رقم هندي ولا ، ؛ ؟ من نفس النطاق."""
    return any(_is_ar_letter(c) for c in str(text or ""))


# حروف لغات غير العربي والإنجليزي (سيريلي، عبري، هندي، صيني/ياباني، كوري، تاي، يوناني،
# وحروف الفارسي/الأوردو اللي مش في العربي) — علامة إن التعرّف التلقائي على اللغة غلط
_FOREIGN_SCRIPT = re.compile(
    "[Ͱ-ϿЀ-ӿ֐-׿ऀ-෿฀-๿"
    "぀-ヿ㐀-鿿가-힯"
    "پچژکگیےٹڈڑںھہ]")


def foreign_script(text):
    """التعرّف التلقائي طلّع لغة غير عربي/إنجليزي (غالبًا عامية اتفهمت فارسي) → نعيد كعربي."""
    return bool(_FOREIGN_SCRIPT.search(text or ""))


def tech_guess(text):
    """
    تخمين احتياطي "en"/"ar" لما تصنيف الموديل يفشل: كلمة تقنية قوية (عربي أو لاتيني)
    = "en"، غير كده "ar". مش قرار نهائي — الموديل بيشوف القصد، والكلمات مبتشوفوش.
    """
    s = str(text or "")
    if _TECH_ARABIC_RE.search(normalize(s)):
        return "en"
    lower = _IDENTIFIER_RE.sub(" ", s).lower()
    if _LATIN_TECH_RE.search(lower) or any(p in lower for p in TECH_LATIN_PHRASES):
        return "en"
    return "ar"


# ── F8: الاختصارات الصوتية ──────────────────────────────────────────────────
# أدنى تشابه بين الكلام المنطوق ومفتاح الاختصار عشان نعتبره «هو هو». التطبيع
# (normalize) بيوحّد اختلافات الكتابة الكبيرة (همزة، تاء مربوطة، ى/ي…)، والباقي
# (كلمة اتسمعت غلط بشوية) بيتمسك بـSequenceMatcher. الحد عالي عن قصد: نص الاختصار
# ممكن يكون IBAN أو عنوان أو إيميل، والكتابة الغلط لبيانات مخزّنة أوحش بكتير من
# اختصار متماشش.
SNIPPET_RATIO = 0.9


def match_snippet(text, snippets):
    """هل الكلام كله هو جملة اختصار صوتي؟ يرجّع الاختصار أو None (F8)"""
    target = normalize(text)
    if not target:
        return None
    best, best_ratio = None, 0.0
    for sn in snippets or []:
        # الاختصار dict فيه trigger (المفتاح المنطوق) وtext (النص اللي يتوسّع ليه)
        if not isinstance(sn, dict):
            continue
        trigger = str(sn.get("trigger") or "").strip()
        key = normalize(trigger)
        if not key:
            continue
        if key == target:
            return sn                # تطابق تام بعد التطبيع — مفيش لزوم ندور تاني
        ratio = difflib.SequenceMatcher(None, target, key).ratio()
        if ratio > best_ratio:
            best_ratio, best = ratio, sn
    return best if best is not None and best_ratio >= SNIPPET_RATIO else None


def is_network_error(err):
    """
    هل الخطأ ده من النت — DNS/اتصال/مهلة — مش مفتاح غلط ولا حد استخدام؟ (F9)

    بيرجّع True لـ:
      • providers.NetworkError (بنعرّفه بسمة is_network، من غير استيراد providers
        عشان smart يفضل نقي ومفيش دورة استيراد).
      • ConnectionError / TimeoutError / socket.timeout (رفض اتصال أو مهلة) —
        ومنهم http.client.RemoteDisconnected (فئة فرعية من ConnectionResetError).
      • http.client.IncompleteRead (السيرفر قفل قبل Content-Length المعلن).
      • urllib.error.URLError من غير حالة HTTP — ده DNS/رفض، مش رد جه بـstatus.
    HTTP status (401/429…) وأي خطأ تاني بيرجّع False — دي مشكلة مفتاح أو حد
    مش نت، وليها رسالة تانية.
    """
    if err is None:
        return False
    if getattr(err, "is_network", False):
        return True
    if isinstance(err, (ConnectionError, TimeoutError, socket.timeout)):
        # RemoteDisconnected جوّه ConnectionError أصلًا (فئة فرعية من ConnectionResetError)
        return True
    # IncompleteRead: السيرفر قال Content-Length وقفل قبل ما يبعت الكل — النص ناقص،
    # وده قطع اتصال مش رد سليم.
    if isinstance(err, http.client.IncompleteRead):
        return True
    # URLError بيحتوي HTTPError كمان — اللي ليه .code/.status معناه رد وصل، مش شبكة
    if isinstance(err, urllib.error.URLError) and not isinstance(err, urllib.error.HTTPError):
        return True
    return False
