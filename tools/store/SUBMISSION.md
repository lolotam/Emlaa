# نشر إملاء على Microsoft Store — خطوة بخطوة

## 1) حساب المطوّر (مرة واحدة)
1. ادخل https://storedeveloper.microsoft.com واعمل حساب **Individual** (للأفراد مجاني).
2. التحقق من الهوية بياخد من يوم لكام يوم.

## 2) حجز الاسم
Partner Center → **Apps and games → New product → MSIX or PWA app** → اكتب الاسم: **Emlaa**
(ولو عايز اسم عربي كمان، احجز **إملاء** وضيفه كاسم للغة العربية في الـListing).

## 3) حط هوية المنتج في المشروع
Partner Center → المنتج → **Product management → Product identity** وانسخ:

| من Partner Center | في `tools/store/store.json` |
|---|---|
| Package/Identity/Name | `identity_name` |
| Package/Identity/Publisher | `publisher` (بيبدأ بـ `CN=`) |
| Package/Properties/PublisherDisplayName | `publisher_display_name` |
| الاسم اللي حجزته | `display_name` |

## 4) ابني الحزمة
```bash
python tools/store_package.py
```
الناتج: `dist/store/Emlaa_<version>_x64.msix`. الـStore هو اللي بيوقّعها، فمش محتاج شهادة.

تجربة على جهازك قبل الرفع: فعّل **Settings → System → For developers → Developer Mode** وبعدين:
```bash
python tools/store_package.py --no-build --register
```

## 5) الـSubmission
| القسم | اللي تحطه |
|---|---|
| **Pricing and availability** | Free · كل الأسواق |
| **Properties** | Category: **Productivity** · Subcategory: — · Privacy policy URL: `https://github.com/lolotam/Emlaa/blob/main/PRIVACY.md` · Website: `https://walidmohamed.com` · Support: `https://github.com/lolotam/Emlaa/issues` |
| **Age ratings** | الاستبيان: مفيش محتوى عنيف/جنسي/مقامرة · المستخدم بيبعت صوت لخدمة خارجية باختياره → في الغالب **3+ / Everyone** |
| **Packages** | ارفع ملف الـ`.msix` |
| **Store listings** | انسخ النصوص تحت (عربي + English) والصور من `tools/store/screenshots/` |
| **Submission options → Restricted capabilities** | اشرح `runFullTrust` (النص تحت) |
| **Notes for certification** | النص تحت + **مفتاح Groq مجاني للتجربة** |

### تبرير runFullTrust
> Emlaa is a desktop dictation utility (Win32, packaged with the Desktop Bridge). It needs full trust to (1) register global keyboard hotkeys so the user can start and stop dictation from any app, (2) type the transcribed text at the cursor in the focused app via SendInput and UI Automation, (3) show a system-tray icon, and (4) record from the microphone. It does not install drivers or services and does not modify system settings.

### Notes for certification
> The app transcribes speech using the user's own API key for a cloud provider. To test: on first launch choose **Groq**, paste the test key below, and click Confirm. Then put the cursor in any text field (e.g. Notepad), tap **Right Ctrl**, speak (Arabic or English), and tap **Right Ctrl** again; the text is typed at the cursor. The microphone is used only while recording.
> Test key (Groq): `<حط هنا مفتاح Groq مخصوص للمراجعين — واحذفه بعد ما الموافقة تيجي>`

> ⚠ اعمل مفتاح Groq **جديد** للمراجعين بس، والصقه في الخانة دي (مش بيظهر للناس)، وامسحه من console.groq.com بعد الموافقة.

---

## نصوص الـListing

### العربية (ar-EG)
**الاسم:** إملاء
**وصف قصير:** اتكلم عربي في أي برنامج… والكلام يتكتب مكانك.

**الوصف:**
```
إملاء بيحوّل صوتك لنص في أي برنامج على ويندوز. دوس زرار، اتكلم عربي (أو إنجليزي)، ودوس تاني — والكلام يتكتب مكان المؤشر على طول: في المتصفح، Word، واتساب، ChatGPT، Claude، أو أي خانة كتابة.

• بيفهم العامية المصرية، وبيسيب المصطلحات التقنية بالإنجليزي زي ما هي (AI · API).
• 4 ميزات، لكل ميزة زرار تختاره بنفسك: تسجيل عادي (بيصلّح الترقيم والأخطاء) · تحويل لبرومبت مرتّب للذكاء الاصطناعي · ترجمة عربي ⇄ إنجليزي · تعديل النص المحدد بالصوت.
• اختار المزوّد اللي يناسبك: Groq (مجاني وسريع جدًا) · Google Gemini (باقة مجانية) · Deepgram (رصيد مجاني) · OpenAI — ورتّب بدائل لكل ميزة: لو موديل فشل بيجرّب اللي بعده.
• لو مفيش خانة كتابة: النص بيظهر على الشاشة ويتنسخ ويتحفظ في السجل.
• سجل لكل اللي اتكتب، ومدير للحافظة، وقاموس لأسماءك ومصطلحاتك.
• موجة عائمة وقت التسجيل · وضع فاتح وغامق · واجهة عربي وEnglish.

خصوصيتك: مفيش حسابات ولا تتبّع. المفاتيح والسجل على جهازك بس، والصوت رايح مباشرة للمزوّد اللي اخترته بمفتاحك انت.

البرنامج مجاني بالكامل. محتاج مفتاح API من المزوّد (Groq وGemini عندهم باقات مجانية).
```
**المميزات (Product features):**
- اكتب بصوتك في أي برنامج
- بيفهم العامية المصرية
- تحويل الكلام لبرومبت مرتّب
- ترجمة عربي ⇄ إنجليزي
- 4 مزوّدين واختيار الموديل
- سجل وحافظة وقاموس على جهازك

**كلمات البحث:** إملاء · تفريغ صوتي · صوت إلى نص · كتابة بالصوت · عامية مصرية · Arabic dictation · speech to text

### English (en-US)
**Name:** Emlaa
**Short description:** Speak Arabic in any app — and it types for you.

**Description:**
```
Emlaa turns your voice into text in any Windows app. Tap a hotkey, speak Arabic (or English), tap again — and your words are typed right at the cursor: in your browser, Word, WhatsApp, ChatGPT, Claude, or any text field.

• Understands Egyptian Arabic and keeps technical terms in English (AI, API).
• 4 features, each on a hotkey you record yourself: Dictation (fixes punctuation and typos) · Prompt (turns speech into a clear, structured AI prompt) · Translate (Arabic ⇄ English) · Edit selected text by voice.
• Choose your provider: Groq (free and very fast) · Google Gemini (free tier) · Deepgram (free credit) · OpenAI — and order fallbacks per feature: if one model fails, the next one is tried.
• No text field? The text pops up on screen, is copied to the clipboard and saved to history.
• History of everything you dictated, a clipboard manager, and a dictionary for your names and terms.
• Floating wave while recording · light and dark themes · Arabic and English interface.

Privacy: no accounts, no tracking. Keys and history stay on your PC; audio goes straight to the provider you chose, using your own key.

Emlaa is completely free. It needs an API key from your chosen provider (Groq and Gemini have free tiers).
```
**Product features:**
- Dictate into any app
- Understands Egyptian Arabic
- Turn speech into a structured AI prompt
- Arabic ⇄ English translation
- 4 providers with model choice
- Local history, clipboard and dictionary

**Search terms:** Arabic dictation · speech to text · voice typing · Egyptian Arabic · transcription · Whisper · إملاء

### الصور
ارفع الصور من `tools/store/screenshots/` (1366×768):
1. `01-home-ar.png` — الرئيسية
2. `02-models-ar.png` — اختيار الموديل بنسب الترشيح
3. `03-history-ar.png` — السجل
4. `04-home-en.png` — الواجهة بالإنجليزي
5. `05-clipboard-en.png` — مدير الحافظة
6. `06-settings-light-en.png` — الوضع الفاتح

---

## التحديثات بعد النشر
لكل إصدار جديد:
1. `python tools/release.py 1.9 "الملاحظات"` ← بيحدّث نسخة GitHub (المستخدمين المباشرين بيتحدّثوا لوحدهم).
2. `python tools/store_package.py --no-build` ← حزمة الـStore من نفس الـexe.
3. Partner Center ← المنتج ← **Update submission** ← ارفع الـ`.msix` الجديد ← Submit.

مستخدمين الـStore بياخدوا التحديث من الـStore نفسه — نسخة الـStore مبتسألش GitHub خالص.
