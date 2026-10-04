# -*- coding: utf-8 -*-
"""
مزوّدو الخدمة — OpenAI · Groq · Google Gemini
---------------------------------------------
كل مزوّد بيقدّم حاجتين: تفريغ صوت (STT) وتنظيف نص (chat).

  • OpenAI و Groq: نفس شكل الـAPI بالظبط، فبنستخدم مكتبة openai للاتنين
    وبنغيّر الـbase_url بس.
  • Gemini: شكل مختلف تمامًا (generateContent + الصوت جوّه الطلب base64)،
    فليه مسار خاص بـ urllib — من غير أي مكتبة زيادة.

المفاتيح بتتخزّن على جهاز المستخدم بس، كل مزوّد ومفتاحه، في ملف .env جنب البرنامج.
"""
import os
import ssl
import json
import base64
import urllib.request
import urllib.error
import urllib.parse


# ── شهادات SSL (مهم للـexe) ──────────────────────────────────────────────────
# لما البرنامج يتبني .exe بـPyInstaller، مكتبة openai/httpx مبتلاقيش ملف
# الشهادات، فأي نداء HTTPS بيفشل ويظهر كأنه «مفيش نت». بنبني SSLContext من
# حزمة certifi ونمرّره صراحةً لكل نداء — كده مش بنعتمد على بيئة الـexe.
def _ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()

# ── تعريف المزوّدين ──────────────────────────────────────────────────────────
PROVIDERS = {
    "groq": {
        "name":      "Groq",
        "tag":       "الأسرع",
        "desc":      "تفريغ فوري تقريبًا · فيه باقة مجانية سخية",
        "key_url":   "https://console.groq.com/keys",
        "key_hint":  "المفتاح بيبدأ بحروف gsk",
        "key_start": "gsk_",
        "env":       "GROQ_API_KEY",
        "base_url":  "https://api.groq.com/openai/v1",
        "stt":       "whisper-large-v3-turbo",
        "stt_alt":   ["whisper-large-v3"],
        "chat":      "qwen/qwen3.8-27b",
        "chat_alt":  ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "allam-2-7b", "llama-3.3-70b-versatile"],
    },
    "openai": {
        "name":      "OpenAI",
        "tag":       "الأدق",
        "desc":      "أحسن فهم للعامية المصرية · مدفوع بالكامل",
        "key_url":   "https://platform.openai.com/api-keys",
        "key_hint":  "المفتاح بيبدأ بحروف sk",
        "key_start": "sk-",
        "env":       "OPENAI_API_KEY",
        "base_url":  None,
        "stt":       "whisper-1",
        "stt_alt":   None,
        "chat":      "gpt-4o-mini",
        "chat_alt":  None,
    },
    "gemini": {
        "name":      "Google Gemini",
        "tag":       "مجاني",
        "desc":      "باقة مجانية يومية كبيرة من جوجل",
        "key_url":   "https://aistudio.google.com/apikey",
        "key_hint":  "هاته من Google AI Studio",
        "key_start": None,     # جوجل بقى ليها أكتر من فورمات (AIza· و AQ.…) → نسيب الـAPI هو اللي يتحقق
        "env":       "GEMINI_API_KEY",
        "base_url":  None,
        "stt":       "gemini-3.8-flash",
        "stt_alt":   ["gemini-flash-latest", "gemini-3.5-flash", "gemini-2.5-flash"],
        "chat":      "gemini-3.8-flash",
        "chat_alt":  ["gemini-flash-latest", "gemini-3.5-flash", "gemini-2.5-flash"],
    },
    "deepgram": {
        "name":      "Deepgram",
        "tag":       "رصيد $200",
        "desc":      "رصيد مجاني $200 مبيخلصش بسرعة · بيفهم العامية المصرية",
        "key_url":   "https://console.deepgram.com/",
        "key_hint":  "هاته من Deepgram Console ← API Keys",
        "key_start": None,
        "env":       "DEEPGRAM_API_KEY",
        "base_url":  None,
        "stt":       "nova-3",
        "stt_alt":   ["whisper-large"],   # nova-2 مبيدعمش العربي
        "chat":      None,     # Deepgram بيفرّغ بس — التنظيف بيتعمل بمفتاح مزوّد تاني لو موجود
        "chat_alt":  None,
    },
}

ORDER = ["groq", "openai", "gemini", "deepgram"]
DEFAULT = "groq"

GEMINI_API = "https://generativelanguage.googleapis.com/v1beta"
DEEPGRAM_API = "https://api.deepgram.com/v1"

# ── موديلات التفريغ بس (مش موديلات الشات) + نسبة الترشيح ─────────────────────
# النسبة = قد إيه الموديل مناسب للإملاء بالعامية المصرية (دقة + سرعة + تكلفة).
# 100% = الموصى به. القايمة دي بتتفلتر بعدين على حسب اللي متاح فعلاً للمفتاح.
MODELS = {
    "groq": [
        {"id": "whisper-large-v3-turbo", "score": 100, "note": "الأسرع · دقة ممتازة · مجاني"},
        {"id": "whisper-large-v3",       "score": 90,  "note": "أدق شوية في العربي · أبطأ"},
    ],
    "openai": [
        {"id": "gpt-4o-transcribe",      "score": 100, "note": "أدق تفريغ للعامية"},
        {"id": "gpt-4o-mini-transcribe", "score": 90,  "note": "قريب منه · أرخص وأسرع"},
        {"id": "whisper-1",              "score": 70,  "note": "الموديل القديم"},
    ],
    "gemini": [
        {"id": "gemini-3.8-flash",       "score": 100, "note": "أحدث Flash · سريع ومجاني"},
        {"id": "gemini-flash-latest",    "score": 95,  "note": "بيمشي مع آخر Flash تلقائيًا"},
        {"id": "gemini-3.5-flash",       "score": 85,  "note": "نسخة أقدم"},
        {"id": "gemini-2.5-flash",       "score": 75,  "note": "نسخة قديمة"},
    ],
    "deepgram": [
        {"id": "nova-3",                 "score": 100, "note": "بيدعم العامية المصرية · سريع جدًا"},
        {"id": "whisper-large",          "score": 70,  "note": "Whisper على سيرفرات Deepgram · أبطأ"},
        {"id": "whisper-medium",         "score": 50,  "note": "أخف · أقل دقة في العربي"},
    ],
}

# ── دليل المفتاح لكل مزوّد (خطوات قصيرة + روابط) ─────────────────────────────
GUIDES = {
    "groq": {
        "steps": ["اعمل حساب مجاني على console.groq.com",
                  "من القايمة ادخل API Keys ← Create API Key",
                  "انسخ المفتاح (بيبدأ بـ gsk_) والصقه هنا"],
        "docs": "https://console.groq.com/docs/speech-to-text",
        "free": "مجاني · من غير فيزا",
    },
    "openai": {
        "steps": ["سجّل دخول على platform.openai.com",
                  "اشحن رصيد من Billing (مفيش باقة مجانية)",
                  "API keys ← Create new secret key وانسخه"],
        "docs": "https://platform.openai.com/docs/guides/speech-to-text",
        "free": "مدفوع",
    },
    "gemini": {
        "steps": ["ادخل aistudio.google.com بحساب جوجل",
                  "دوس Get API key ← Create API key",
                  "انسخ المفتاح والصقه هنا"],
        "docs": "https://ai.google.dev/gemini-api/docs/audio",
        "free": "مجاني · باقة يومية",
    },
    "deepgram": {
        "steps": ["اعمل حساب على console.deepgram.com (بياخد $200 هدية)",
                  "من المشروع ادخل API Keys ← Create a New API Key",
                  "انسخ المفتاح فورًا (مبيظهرش تاني) والصقه هنا"],
        "docs": "https://developers.deepgram.com/docs/pre-recorded-audio",
        "free": "$200 رصيد مجاني",
    },
}

# مين ينضّف/يترجم لو المزوّد بيفرّغ بس (Deepgram) — أول مزوّد ليه مفتاح
CHAT_HELPERS = ["groq", "gemini", "openai"]

STT_PROMPT = ("كلام بالعامية المصرية، وممكن يكون فيه مصطلحات تقنية بالإنجليزي "
              "زي AI و API و PWA.")

POLISH_SYSTEM = (
    "أنت مصحّح لنصوص مُملاة بالصوت. صحّح الأخطاء الواضحة وعلامات الترقيم فقط، "
    "مع الحفاظ التام على العامية المصرية وأسلوب المتكلم، وخلّي المصطلحات التقنية "
    "بالإنجليزي بحروف لاتينية (AI, API, PWA...). رجّع النص المصحّح فقط من غير أي تعليق."
)

# تحويل الكلام المُملى لبرومبت جاهز يتلزق في أي موديل (Claude / ChatGPT / …).
# المستخدم بيتكلم عادي — والمخرج لازم يبقى طلب مرتّب وواضح، من غير ما نخترع
# تفاصيل هو مقالهاش.
PROMPT_SYSTEM = (
    "أنت بتحوّل كلام مُملى بالصوت لبرومبت جاهز يتبعت لموديل ذكاء اصطناعي "
    "(زي Claude أو ChatGPT).\n"
    "قواعد ملزمة:\n"
    "١) اكتب البرومبت بنفس لغة المتكلم (لو عربي يبقى عربي فصيح واضح مش عامية).\n"
    "٢) ابدأ بالمطلوب على طول — من غير مقدمات ولا «من فضلك».\n"
    "٣) رتّب الطلب: المهمة، السياق اللي المتكلم قاله، المتطلبات، شكل المخرج "
    "المطلوب — واستخدم نقاط لو الطلب فيه أكتر من عنصر.\n"
    "٤) اشتغل على اللي اتقال بس: ممنوع تحذف أي متطلب قاله المتكلم، وممنوع "
    "تضيف عناصر أو تفاصيل أو أرقام أو أسماء من عندك — حتى لو شكلها منطقي "
    "أو مكمّلة للطلب.\n"
    "٥) سيب المصطلحات التقنية بالإنجليزي زي ما هي (AI, API, PWA...).\n"
    "٦) رجّع نص البرومبت بس — من غير عناوين زي «البرومبت:» ولا شرح ولا "
    "علامات اقتباس حواليه."
)

TRANSLATE_SYSTEM = (
    "أنت مترجم ذكي ثنائي الاتجاه بين العربية والإنجليزية.\n"
    "قواعد صارمة ومباشرة:\n"
    "١) إذا كان الكلام المدخل عربياً، ترجمه إلى إنجليزية طبيعية، دقيقة واحترافية (Natural Fluent English).\n"
    "٢) إذا كان الكلام المدخل إنجليزياً، ترجمه إلى عربية سليمة، واضحة ومفهومة (Modern Standard Arabic).\n"
    "٣) حافظ بدقة على أسماء الأعلام والمصطلحات التقنية والرموز البرمجية (مثل AI, API, Python, Cloud...).\n"
    "٤) أرجع النص المترجم فقط مباشرة بدون أي مقدمات، شروحات، تعليقات، أو علامات اقتباس."
)



def meta(pid):
    return PROVIDERS.get(pid) or PROVIDERS[DEFAULT]


def _model_list(primary, alt):
    """بيرجّع قايمة بكل الموديلات المرشّحة بالترتيب بدون تكرار."""
    out = [primary] if primary else []
    if alt:
        if isinstance(alt, (list, tuple)):
            for a in alt:
                if a and a not in out:
                    out.append(a)
        elif alt not in out:
            out.append(alt)
    return out


# ── نداء HTTP بسيط (لـ Gemini) ───────────────────────────────────────────────
def _post_json(url, payload, headers, timeout=120):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as r:
        return json.loads(r.read().decode("utf-8"))


def _gemini_text(resp):
    """يطلّع النص من رد generateContent."""
    try:
        parts = resp["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts).strip()
    except Exception:
        return ""


def _http_msg(e):
    """يحوّل خطأ HTTP لرسالة مفهومة."""
    if isinstance(e, urllib.error.HTTPError):
        try:
            body = json.loads(e.read().decode("utf-8", "replace"))
            err = body.get("error")
            msg = (err.get("message", "") if isinstance(err, dict) else err) \
                or body.get("err_msg") or body.get("message") or ""     # Deepgram: err_msg
            return f"HTTP {e.code}: {msg}" if msg else f"HTTP {e.code}"
        except Exception:
            return f"HTTP {e.code}"
    return str(e)


# ── عميل موحّد ───────────────────────────────────────────────────────────────
class Client:
    """
    واجهة واحدة لكل المزوّدين: transcribe() و polish() و verify().
    الكود اللي فوق مش لازم يعرف مين المزوّد.
    """

    def __init__(self, provider_id, key, model=None, helper=None):
        self.id = provider_id
        self.m = meta(provider_id)
        self.key = (key or "").strip()
        self.model = (model or "").strip() or None   # موديل التفريغ اللي المستخدم اختاره
        self.helper = helper      # عميل مزوّد تاني للتنظيف (لو المزوّد ده بيفرّغ بس)
        self._oa = None
        self.vocab = []           # كلمات القاموس — بيحطها core قبل كل تسجيل
        if not self.key:
            raise RuntimeError(f"مفيش مفتاح لـ {self.m['name']}")

    def _stt_models(self):
        """الموديل المختار الأول، وبعده البدائل لو مش متاح."""
        base = _model_list(self.m["stt"], self.m.get("stt_alt"))
        if self.model:
            return [self.model] + [x for x in base if x != self.model]
        return base

    # ── OpenAI / Groq (نفس المكتبة) ──
    def _openai(self):
        if self._oa is None:
            from openai import OpenAI
            import httpx
            kw = {"api_key": self.key,
                  "http_client": httpx.Client(verify=_ssl_context())}
            if self.m["base_url"]:
                kw["base_url"] = self.m["base_url"]
            self._oa = OpenAI(**kw)
        return self._oa

    # ── تفريغ الصوت ──
    def transcribe(self, wav_path, language="ar"):
        if self.id == "gemini":
            return self._gemini_transcribe(wav_path)
        if self.id == "deepgram":
            return self._deepgram_transcribe(wav_path, language)
        return self._oa_transcribe(wav_path, language)

    def _deepgram_transcribe(self, wav_path, language):
        audio = open(wav_path, "rb").read()
        hdr = {"Authorization": "Token " + self.key, "Content-Type": "audio/wav"}
        terms = [str(w).strip() for w in self.vocab[:50] if str(w).strip()]
        last_err = None
        candidates = self._stt_models()
        for i, model in enumerate(candidates):
            q = [("model", model), ("language", language or "ar"),
                 ("smart_format", "true"), ("punctuate", "true")]
            # كلمات القاموس: nova-3 بياخد keyterm، اللي قبله بياخد keywords
            tries = []
            if terms:
                key = "keyterm" if model.startswith("nova-3") else "keywords"
                tries.append(q + [(key, t) for t in terms])
            tries.append(q)
            for j, params in enumerate(tries):
                url = DEEPGRAM_API + "/listen?" + urllib.parse.urlencode(params)
                req = urllib.request.Request(url, data=audio, headers=hdr, method="POST")
                try:
                    with urllib.request.urlopen(req, timeout=120, context=_ssl_context()) as r:
                        data = json.loads(r.read().decode("utf-8"))
                    alts = data["results"]["channels"][0]["alternatives"]
                    return (alts[0].get("transcript") or "").strip() if alts else ""
                except urllib.error.HTTPError as e:
                    last_err = e
                    if e.code == 400 and j < len(tries) - 1:
                        continue        # يمكن الكلمات المخصوصة مش مدعومة للغة دي → من غيرها
                    if e.code in (400, 403, 404) and i < len(candidates) - 1:
                        break           # الموديل مش متاح للعربي/للمفتاح → البديل
                    raise RuntimeError(_http_msg(e))
                except Exception as e:
                    raise RuntimeError(_http_msg(e))
        if last_err:
            raise RuntimeError(_http_msg(last_err))
        return ""

    def _oa_transcribe(self, wav_path, language):
        candidates = self._stt_models()
        last_err = None
        for i, model in enumerate(candidates):
            try:
                with open(wav_path, "rb") as f:
                    tr = self._openai().audio.transcriptions.create(
                        model=model, file=f, language=language, prompt=self._stt_prompt())
                return (getattr(tr, "text", "") or "").strip()
            except Exception as e:
                last_err = e
                s = str(e).lower()
                if i < len(candidates) - 1 and (
                    "model_not_found" in s or "does not have access" in s
                    or "decommission" in s or "404" in s or "blocked at the project level" in s
                ):
                    continue
                raise
        if last_err:
            raise last_err
        return ""

    def _gemini_transcribe(self, wav_path):
        audio = base64.b64encode(open(wav_path, "rb").read()).decode("ascii")
        payload = {
            "contents": [{"parts": [
                {"text": "فرّغ الصوت ده نصًا حرفيًا بالعربي. " + self._stt_prompt() +
                         " رجّع النص بس من غير أي مقدمة أو تعليق."},
                {"inline_data": {"mime_type": "audio/wav", "data": audio}},
            ]}],
            "generationConfig": {"temperature": 0},
        }
        hdr = {"x-goog-api-key": self.key}
        candidates = self._stt_models()
        last_err = None
        for i, model in enumerate(candidates):
            try:
                r = _post_json(f"{GEMINI_API}/models/{model}:generateContent", payload, hdr)
                return _gemini_text(r)
            except urllib.error.HTTPError as e:
                last_err = e
                if e.code == 404 and i < len(candidates) - 1:
                    continue          # الموديل مش متاح للمفتاح ده → جرّب البديل
                raise RuntimeError(_http_msg(e))
            except Exception as e:
                raise RuntimeError(_http_msg(e))
        if last_err:
            raise RuntimeError(_http_msg(last_err))
        return ""

    # ── معالجة النص بالموديل (تنظيف / تحويل لبرومبت) ──
    def _chat(self, system, text, temperature=0.2):
        """
        نداء واحد على موديل الشات بتعليمات جاهزة.
        لو حصل أي خطأ بيرجّع النص الأصلي — المعالجة رفاهية، النص الخام أهم.
        """
        if not text:
            return text
        if not self.m.get("chat"):
            # مزوّد بيفرّغ بس (Deepgram) → التنظيف على مزوّد تاني ليه مفتاح، وإلا النص زي ما هو
            return self.helper._chat(system, text, temperature) if self.helper else text
        try:
            if self.id == "gemini":
                return self._gemini_chat(system, text, temperature)
            return self._oa_chat(system, text, temperature)
        except Exception as e:
            # التنظيف رفاهية — النص الخام أهم، فبنكمّل بيه.
            # بس بنسجّل الفشل: المستخدم بياخد نص مش متنضّف من غير أي إشارة،
            # وبيفتكر إن الأداة وحشة. من غير اللوج ده مفيش طريقة نعرف.
            try:
                import core
                core.log_error(e, "chat/polish (تم تجاهله — رجّعنا النص الخام)")
            except Exception:
                pass
            return text

    def _stt_prompt(self):
        """البرومبت + كلمات القاموس (Whisper بياخد لحد ~٢٢٤ توكن، فبنقصّ)."""
        if not self.vocab:
            return STT_PROMPT
        words = "، ".join(str(w).strip() for w in self.vocab[:60])[:500]
        return STT_PROMPT + " كلمات وأسماء ممكن تيجي: " + words + "."

    def _vocab_rule(self):
        if not self.vocab:
            return ""
        return (" اكتب الكلمات والأسماء دي بنفس الكتابة بالظبط لو اتقالت: "
                + "، ".join(str(w).strip() for w in self.vocab[:100]) + ".")

    def polish(self, text):
        return self._chat(POLISH_SYSTEM + self._vocab_rule(), text)

    def to_prompt(self, text):
        """يحوّل الكلام المُملى لبرومبت مرتّب جاهز للّزق في أي موديل."""
        return self._chat(PROMPT_SYSTEM + self._vocab_rule(), text, temperature=0.2)

    def translate(self, text):
        """يترجم الكلام تلقائياً: لو عربي يحوله لإنجليزي، ولو إنجليزي يحوله لعربي."""
        return self._chat(TRANSLATE_SYSTEM, text, temperature=0.2)


    def _oa_chat(self, system, text, temperature):
        candidates = _model_list(self.m["chat"], self.m.get("chat_alt"))
        for i, model in enumerate(candidates):
            try:
                r = self._openai().chat.completions.create(
                    model=model, temperature=temperature,
                    messages=[{"role": "system", "content": system},
                              {"role": "user", "content": text}])
                return (r.choices[0].message.content or "").strip()
            except Exception as e:
                s = str(e).lower()
                if i < len(candidates) - 1 and (
                    "model_not_found" in s or "does not have access" in s
                    or "decommission" in s or "404" in s or "blocked at the project level" in s
                ):
                    continue
                break
        return text

    def _gemini_chat(self, system, text, temperature):
        payload = {
            "contents": [{"parts": [{"text": text}]}],
            "systemInstruction": {"parts": [{"text": system}]},
            "generationConfig": {"temperature": temperature},
        }
        hdr = {"x-goog-api-key": self.key}
        candidates = _model_list(self.m["chat"], self.m.get("chat_alt"))
        last = None
        for i, model in enumerate(candidates):
            try:
                r = _post_json(f"{GEMINI_API}/models/{model}:generateContent", payload, hdr)
                return _gemini_text(r) or text
            except urllib.error.HTTPError as e:
                last = RuntimeError(_http_msg(e))
                if e.code == 404 and i < len(candidates) - 1:
                    continue
                raise last
            except Exception as e:
                raise RuntimeError(_http_msg(e))
        raise last or RuntimeError("مفيش موديل متاح")


# ── التأكد إن المفتاح شغّال (قبل ما نبدأ) ────────────────────────────────────
def verify(provider_id, key):
    """
    بيرجّع (شغّال؟, رسالة عربي).
    بيتنده من ثريد مستقل عشان الواجهة ما تتجمّدش.
    """
    key = (key or "").strip()
    m = meta(provider_id)
    if not key:
        return False, "الصق المفتاح الأول"
    if m["key_start"] and not key.startswith(m["key_start"]):
        return False, f"{m['key_hint']} — اتأكد إنك نسخته كامل"

    try:
        if provider_id == "gemini":
            test_payload = {
                "contents": [{"parts": [{"text": "hi"}]}],
                "generationConfig": {"maxOutputTokens": 1}
            }
            hdr = {"Content-Type": "application/json", "x-goog-api-key": key}
            candidates = _model_list(m["chat"], m.get("chat_alt"))
            last_err = None
            verified = False
            for test_model in candidates:
                try:
                    url = f"{GEMINI_API}/models/{test_model}:generateContent"
                    req = urllib.request.Request(
                        url,
                        data=json.dumps(test_payload).encode("utf-8"),
                        headers=hdr,
                        method="POST"
                    )
                    with urllib.request.urlopen(req, timeout=15, context=_ssl_context()) as r:
                        r.read()
                    verified = True
                    break
                except urllib.error.HTTPError as e:
                    last_err = e
                    if e.code == 404:
                        continue
                    raise
            if not verified and last_err:
                raise last_err
        elif provider_id == "deepgram":
            _get_json(DEEPGRAM_API + "/projects", {"Authorization": "Token " + key}, timeout=15)
        else:
            from openai import OpenAI
            import httpx
            kw = {"api_key": key,
                  "http_client": httpx.Client(verify=_ssl_context())}
            if m["base_url"]:
                kw["base_url"] = m["base_url"]
            oa = OpenAI(**kw)
            oa.models.list()
            # لو Groq، نتأكد كمان إن الشات وموديل الصوت (Whisper) متاحين ومش محظورين على مستوى المشروع
            if provider_id == "groq":
                oa.chat.completions.create(
                    model=m["chat"],
                    messages=[{"role": "user", "content": "hi"}],
                    max_tokens=1
                )
                import io, wave, struct
                stt_candidates = _model_list(m["stt"], m.get("stt_alt"))
                stt_ok = False
                stt_last_err = None
                for stt_model in stt_candidates:
                    buf = io.BytesIO()
                    with wave.open(buf, 'wb') as wav:
                        wav.setnchannels(1)
                        wav.setsampwidth(2)
                        wav.setframerate(16000)
                        wav.writeframes(struct.pack('<h', 0) * 1600)
                    buf.name = 'test.wav'
                    buf.seek(0)
                    try:
                        oa.audio.transcriptions.create(model=stt_model, file=buf)
                        stt_ok = True
                        break
                    except Exception as e:
                        stt_last_err = e
                        s = str(e).lower()
                        if "404" in s or "model_not_found" in s or "does not have access" in s or "decommission" in s:
                            continue
                        raise
                if not stt_ok and stt_last_err:
                    raise stt_last_err
        return True, ""
    except Exception as e:
        s = _http_msg(e).lower()
        if "project has been denied access" in s or "permission_denied" in s:
            return False, "مشروع Google مرفوض أو محظور (Project denied access) — أنشئ مشروع جديد ومفتاح جديد من Google AI Studio"
        if "blocked at the project level" in s:
            return False, "الموديل محظور في إعدادات مشروع Groq — راجع limits في console.groq.com أو أنشئ مفتاح جديد"
        if "401" in s or "invalid" in s or "api key" in s or "unauthor" in s:
            return False, "المفتاح مش مقبول — اتأكد إنك نسخته كامل"
        if "403" in s or "permission" in s or "denied" in s:
            return False, "المفتاح مرفوض أو الصلاحية محظورة — اتأكد من صلاحيات الحساب"
        if "quota" in s or "billing" in s or "429" in s or "exceeded" in s:
            return False, "المفتاح شغّال بس الرصيد/الحد خلص"
        if "ssl" in s or "certificate" in s or "cert_" in s or "self-signed" in s or "self signed" in s:
            return False, "مشكلة في شهادات الأمان (SSL) — البرنامج محتاج نسخة محدّثة"
        if "connect" in s or "timed out" in s or "timeout" in s or "urlopen" in s:
            return False, "مفيش اتصال بالنت — اتأكد وجرّب تاني"
        if "404" in s or "not found" in s or "no longer available" in s:
            return False, "الخدمة مش لاقية الموديل — الموديل اتغيّر عند المزوّد"
        detail = " ".join(_http_msg(e).split())[:60]
        return False, ("معرفناش نتأكد من المفتاح" + (" — " + detail if detail else ""))


# ── موديلات التفريغ المتاحة للمفتاح ─────────────────────────────────────────
def _get_json(url, headers, timeout=12):
    # Groq (Cloudflare) بيرفض الـUser-Agent الافتراضي بتاع بايثون بـ403
    req = urllib.request.Request(url, headers={"User-Agent": "Emlaa", **headers}, method="GET")
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as r:
        return json.loads(r.read().decode("utf-8"))


def _is_stt(pid, mid):
    """هل ده موديل تفريغ صوت؟ (بنستبعد موديلات الشات والصور والنطق)."""
    s = mid.lower()
    if pid in ("groq", "openai"):
        return ("whisper" in s or "transcribe" in s) and "tts" not in s and "diarize" not in s
    if pid == "gemini":
        bad = ("image", "tts", "live", "embed", "native-audio", "thinking", "robotics", "computer", "lite")
        return s.startswith("gemini-") and "flash" in s and not any(b in s for b in bad)
    if pid == "deepgram":
        return not any(x in s for x in ("whisper-tiny", "whisper-base", "whisper-small"))
    return True


def _live_ids(pid, key):
    """أسماء الموديلات اللي المفتاح شايفها فعلاً (أو None لو معرفناش نسأل)."""
    if pid == "gemini":
        d = _get_json(GEMINI_API + "/models?pageSize=200", {"x-goog-api-key": key})
        return [m["name"].split("/", 1)[-1] for m in d.get("models", [])
                if "generateContent" in (m.get("supportedGenerationMethods") or [])]
    if pid == "deepgram":
        d = _get_json(DEEPGRAM_API + "/models", {"Authorization": "Token " + key})
        out = []
        for m in d.get("stt", []):
            langs = [str(l).lower() for l in (m.get("languages") or [])]
            name = m.get("canonical_name") or m.get("name")
            if name and any(l == "ar" or l.startswith("ar-") or l == "multi" for l in langs):
                # nova-3-general → nova-3 (الاسم اللي بيتبعت في الطلب)
                out.append(name.replace("-general", "") if name.startswith("nova") else name)
        return out
    base = meta(pid)["base_url"] or "https://api.openai.com/v1"
    d = _get_json(base + "/models", {"Authorization": "Bearer " + key})
    return [m.get("id") for m in d.get("data", []) if m.get("id")]


def list_models(pid, key=None):
    """
    موديلات التفريغ بس للمزوّد ده، مرتّبة بنسبة الترشيح.
    لو فيه مفتاح: بنسأل المزوّد ونخفي اللي مش متاح ونضيف موديلات تفريغ جديدة (من غير نسبة).
    بيرجّع {"models": [...], "live": هل اتأكدنا من المزوّد}.
    """
    catalog = [dict(m) for m in MODELS.get(pid, [])]
    live = None
    if key:
        try:
            live = [x for x in _live_ids(pid, key.strip()) if _is_stt(pid, x)]
        except Exception as e:
            try:
                import core
                core.log_error(e, f"models/{pid} (رجّعنا القايمة الثابتة)")
            except Exception:
                pass
    if live is None:
        return {"models": catalog, "live": False}
    known = {m["id"] for m in catalog}
    out = [m for m in catalog if m["id"] in live]
    for x in sorted(set(live) - known):
        out.append({"id": x, "score": None, "note": ""})
    # «latest» aliases مش بتظهر في الليستة أحيانًا — نسيبها لو المزوّد Gemini
    if pid == "gemini":
        out += [m for m in catalog if m["id"].endswith("-latest") and m not in out]
    out.sort(key=lambda m: -(m["score"] if m["score"] is not None else -1))
    return {"models": out or catalog, "live": bool(out)}


# ── قراءة/كتابة المفاتيح في .env ─────────────────────────────────────────────
def read_keys(env_path):
    """بيرجّع {provider_id: key} من ملف .env."""
    out = {}
    if not os.path.exists(env_path):
        return out
    try:
        for line in open(env_path, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            for pid, m in PROVIDERS.items():
                if k.strip() == m["env"]:
                    out[pid] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return out


def write_key(env_path, provider_id, key):
    """بيحفظ مفتاح مزوّد واحد من غير ما يمسح مفاتيح الباقيين."""
    var = meta(provider_id)["env"]
    lines, found = [], False
    if os.path.exists(env_path):
        try:
            for line in open(env_path, encoding="utf-8"):
                if line.strip().startswith(var + "="):
                    lines.append(f"{var}={key}\n"); found = True
                else:
                    lines.append(line)
        except Exception:
            lines = []
    if not found:
        lines.append(f"{var}={key}\n")
    open(env_path, "w", encoding="utf-8").writelines(lines)
    os.environ[var] = key
