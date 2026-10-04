/* إملاء · Emlaa — الترجمة (عربي ⇄ English)
   النص العربي هو الأصل في الصفحة والكود. لما اللغة تبقى English، أي نص (أو title / placeholder)
   بيتبدّل بترجمته من القاموس ده — حتى النصوص اللي الكود بيكتبها بعدين (MutationObserver).
   كلام المستخدم نفسه (السجل، الحافظة، القاموس، آخر نتيجة) مش بيتترجم أبدًا. */
"use strict";

const EN = {
  // ── الهيكل والقائمة ──
  "إملاء": "Emlaa", "صوتك بيتكتب في أي مكان": "Your voice, typed anywhere",
  "عام": "General", "الرئيسية": "Home", "المحتوى": "Content", "السجل": "History",
  "الحافظة": "Clipboard", "القاموس": "Dictionary", "النظام": "System", "الإعدادات": "Settings",
  "تظل بياناتك خاصة": "Your data stays private",
  "السجل والحافظة محفوظين على جهازك بس. الصوت بيتبعت لمزوّد التفريغ اللي اخترته وقت التسجيل وبس.":
    "History and clipboard are stored only on this device. Audio goes only to the transcription provider you chose, only while recording.",
  "الإصدار": "Version", "تحقق من التحديثات": "Check for updates",
  "فاتح / غامق": "Light / dark", "تصغير": "Minimize", "إغلاق (يفضل شغّال جنب الساعة)": "Close (keeps running in the tray)",
  "English / عربي": "English / عربي",
  // ── الحالة ──
  "جاهز": "Ready", "بيسجّل…": "Recording…", "بيفرّغ الكلام…": "Transcribing…", "بيجهّز البرومبت…": "Building prompt…",
  "بيترجم…": "Translating…", "اتكتب ✓": "Typed ✓", "في مشكلة": "Something went wrong", "محتاج مفتاح": "Needs an API key",
  // ── الرئيسية ──
  "اتكلم، وإملاء يكتب مكانك": "Speak, and Emlaa types for you",
  "دوسة على زرار من التلاتة تبدأ التسجيل، ودوسة تانية توقفه — والكلام يتكتب مكان المؤشر.":
    "Tap any of your three hotkeys to start recording and tap again to stop — your words are typed at the cursor.",
  "إجمالي الكلمات": "Total words", "الوقت اللي وفّرته": "Time saved", "دقيقة": "min", "ساعة": "hr",
  "مقارنة بالكتابة على الكيبورد": "Compared with typing on a keyboard",
  "متوسط سرعة الإملاء": "Average dictation speed", "كلمة في الدقيقة": "words per minute",
  "بتتحسب من التسجيلات الجديدة": "Calculated from new recordings",
  "الكلمات آخر ٧ أيام": "Words in the last 7 days", "عدد الكلمات في كل يوم": "Words per day",
  "تسجيل": "Record", "عادي": "Normal", "برومبت": "Prompt", "ترجمة": "Translate",
  "ابدأ التسجيل": "Start recording", "إيقاف التسجيل": "Stop recording",
  "آخر نتيجة": "Last result", "نسخ": "Copy", "اتنسخ": "Copied",
  "لسه مفيش تسجيلات — جرّب دلوقتي.": "No recordings yet — try one now.",
  "آخر التسجيلات": "Recent recordings", "عرض السجل كله": "View all history", "التسجيلات هتظهر هنا.": "Recordings will appear here.",
  "دوسة على أي زرار من التلاتة تبدأ، ودوسة تانية توقف.": "Tap any of the three keys to start, tap again to stop.",
  "امسك الزرار واتكلم، وسيبه لما تخلص.": "Hold the key and speak, release when you're done.",
  "النهارده": "Today", "امبارح": "Yesterday",
  "الأحد": "Sun", "الاتنين": "Mon", "التلات": "Tue", "الأربع": "Wed", "الخميس": "Thu", "الجمعة": "Fri", "السبت": "Sat",
  // ── السجل ──
  "كل اللي اتكتب بصوتك — بيتحفظ دايمًا، حتى لو مكانش فيه خانة كتابة.": "Everything you dictated — always saved, even when there was no text field.",
  "دوّر في السجل…": "Search history…", "الكل": "All", "الكلام زي ما اتقال": "As spoken",
  "مفيش نتايج للبحث ده.": "No results for this search.", "السجل فاضي — أول تسجيل هيظهر هنا.": "History is empty — your first recording will appear here.",
  "مسح": "Delete", "إلغاء": "Cancel", "اتمسح": "Deleted",
  // ── الحافظة ──
  "كل نص بتنسخه في أي برنامج بيتحفظ هنا. الباسوردات من برامج الباسوردات مش بتتحفظ.":
    "Every text you copy in any app is saved here. Passwords from password managers are never saved.",
  "حفظ النسخ": "Save copies", "دوّر في النسخ…": "Search copies…", "كل البرامج": "All apps", "كل الأوقات": "All time",
  "آخر ٧ أيام": "Last 7 days", "آخر ٣٠ يوم": "Last 30 days", "النص": "Text", "البرنامج": "App", "الوقت": "Time",
  "مفيش نسخ لسه — انسخ أي نص في أي برنامج وهيظهر هنا.": "No copies yet — copy any text in any app and it appears here.",
  "مفيش نسخ بالفلتر ده.": "No copies match this filter.", "عرض أكتر": "Show more",
  "دوسة تفتح النص كله": "Click to expand", "نسخ تاني": "Copy again",
  "حفظ النسخ اشتغل": "Saving copies is on", "حفظ النسخ اتقفل": "Saving copies is off",
  // ── القاموس ──
  "أسماء ومصطلحات عايز إملاء يكتبها صح دايمًا — اسمك، اسم شركتك، مصطلحات شغلك.":
    "Names and terms you want Emlaa to always spell right — your name, your company, your work terms.",
  "اكتب كلمة أو اسم… (مثلاً: اسم شركتك، د. وليد)": "Type a word or name… (e.g. your company, Dr. Walid)",
  "إضافة": "Add", "بتتبعت مع كل تسجيل عشان الموديل يكتبها بنفس الطريقة": "Sent with every recording so the model spells them the same way",
  "القاموس فاضي. ضيف الأسماء والمصطلحات اللي الموديل بيغلط فيها.": "The dictionary is empty. Add names and terms the model gets wrong.",
  "الكلمة موجودة بالفعل": "That word is already there",
  // ── الإعدادات ──
  "التغييرات بتشتغل علطول بعد الحفظ — من غير ما تقفل البرنامج.": "Changes apply as soon as you save — no restart needed.",
  "مزوّد التفريغ": "Transcription provider", "المزوّد": "Provider", "اللي بيفرّغ الصوت وينضّف النص": "Transcribes your voice and cleans up the text",
  "المفتاح (API key)": "API key", "سيبها فاضية لو مش عايز تغيّر المفتاح المحفوظ": "Leave empty to keep the saved key",
  "هات مفتاح ↗": "Get a key ↗", "الاختصارات": "Shortcuts", "تسجيل عادي": "Normal dictation",
  "بيكتب كلامك زي ما هو بعد التنظيف": "Types what you said, cleaned up", "تحويل لبرومبت": "Turn into a prompt",
  "بيرتّب كلامك كطلب واضح للـAI": "Rewrites your words as a clear AI prompt", "عربي ← إنجليزي والعكس": "Arabic ⇄ English",
  "طريقة التسجيل": "Recording mode",
  "في وضع الدوسة الزرار لازم يتداس لوحده — Shift+حرف مش بيبدأ تسجيل": "In tap mode the key must be pressed alone — Shift+letter won't start a recording",
  "دوسة تبدأ · دوسة توقف": "Tap to start · tap to stop", "امسك واتكلم · سيبه يوقف": "Hold to talk · release to stop",
  "فتح إملاء من أي مكان": "Open Emlaa from anywhere", "اختصار يجيب النافذة قدّامك": "A shortcut that brings the window to the front",
  "مفيش": "None",
  "الكتابة": "Typing", "تنظيف النص وتصحيحه": "Clean up and correct text", "بيصلّح الترقيم والأخطاء ويحافظ على العامية": "Fixes punctuation and mistakes, keeps your dialect",
  "كتابة النص تلقائيًا مكان المؤشر": "Type text at the cursor automatically",
  "لو مفيش خانة كتابة، النص بيظهر على الشاشة ويتنسخ": "If there's no text field, the text pops up on screen and is copied",
  "طريقة الكتابة": "Typing method", "الحرف بالحرف بيشتغل في كل الخانات": "Letter by letter works in every field",
  "حرف حرف": "Letter by letter", "لزق Ctrl+V (أسرع)": "Paste with Ctrl+V (faster)",
  "المظهر": "Appearance", "«تلقائي» بيمشي مع إعداد الويندوز": "“Auto” follows your Windows setting",
  "تلقائي": "Auto", "فاتح": "Light", "غامق": "Dark",
  "اللغة": "Language", "لغة الواجهة": "Interface language",
  "البرنامج": "App",
  "يفضل شغّال جنب الساعة": "Keep running in the tray", "قفل النافذة بيخبّيها مش بيقفل البرنامج": "Closing the window hides it instead of quitting",
  "زرار عائم ظاهر طول الوقت": "Always-visible floating button", "لو مقفول: الموجة بتظهر بس وقت التسجيل": "When off, the wave shows only while recording",
  "حفظ كل حاجة بتتنسخ": "Save everything you copy", "قسم الحافظة": "Clipboard section",
  "صوت تنبيه مع البداية والنهاية": "Beep on start and stop", "بيب قصير": "A short beep",
  "طمّني لو نزلت نسخة جديدة": "Tell me about new versions", "بيسأل عن رقم آخر إصدار بس — مفيش أي بيانات عنك": "Only asks for the latest version number — nothing about you is sent",
  "احتفظ بآخر 10 تسجيلات بس": "Keep only the last 10 recordings",
  "الأقدم بيتمسح من جهازك أول ما يتسجّل جديد": "Older ones are deleted from this device when a new one is saved",
  "حفظ الإعدادات": "Save settings", "بحفظ…": "Saving…", "بتأكد من المفتاح…": "Checking the key…",
  "اتحفظ ✓ — التغييرات شغّالة دلوقتي": "Saved ✓ — changes are live", "كل وضع لازم يبقى ليه زرار مختلف": "Each mode needs a different key",
  "✓ المفتاح محفوظ": "✓ Key saved", "مفيش مفتاح": "No key",
  // ── أول مرة ──
  "أهلاً بيك في إملاء": "Welcome to Emlaa", "اختار مزوّد التفريغ وحط مفتاحه — خطوة واحدة وتبدأ تتكلم.": "Pick a transcription provider and paste its key — one step and you're talking.",
  "الصق المفتاح هنا": "Paste the key here", "تأكيد وابدأ": "Confirm and start", "الصق المفتاح الأول": "Paste the key first",
  "تمام — دوس على زرار التسجيل واتكلم": "All set — press record and speak",
  // ── تنبيهات ──
  "اتنسخ ✓": "Copied ✓", "مقدرتش أنسخ": "Couldn't copy", "المحرّك لسه بيجهز…": "The engine is still starting…",
  "بدوّر…": "Checking…", "عندك آخر إصدار ✓": "You're on the latest version ✓",
  // ── رسايل المحرّك (Python) ──
  "الميكروفون مش متاح — وصّله وجرّب، أو غيّره من الإعدادات": "Microphone unavailable — plug it in or pick another in Settings",
  "مشكلة في قراية الصوت — جرّب تاني": "Couldn't read the audio — try again",
  "التسجيل كان قصير أوي — اتكلم شوية وبعدين وقّف": "Recording was too short — speak a little, then stop",
  "مطلعش نص — قرّب من الميك وجرّب تاني": "No text came out — move closer to the mic and try again",
  "مفيش ميكروفون متوصّل": "No microphone connected", "الميكروفون مش شغّال": "The microphone isn't working",
  "محطّتش مفتاح للمزوّد ده — افتح الإعدادات وحطّه": "No key for this provider — add one in Settings",
  "الحد المجاني خلص — استنى شوية أو غيّر المزوّد من الإعدادات": "Free quota used up — wait a bit or switch provider in Settings",
  "المفتاح مش مقبول — انسخه من الأول وحطّه في الإعدادات": "Key not accepted — copy it again and paste it in Settings",
  "المفتاح مرفوض — يمكن الخدمة مش مفعّلة على حسابك أو بلدك مش مدعومة": "Key rejected — the service may not be enabled for your account or country",
  "الموديل مش متاح على حسابك — تم تحديث البرنامج لدعم أحدث الموديلات": "Model not available on your account",
  "مشكلة في شهادات الأمان — لو على نت شركة أو مدرسة جرّب نت تاني": "Security certificate problem — on a work or school network, try another connection",
  "التسجيل طويل أوي — سجّل مقطع أقصر": "Recording too long — record a shorter clip",
  "سيرفر المزوّد مضغوط دلوقتي — جرّب بعد شوية": "The provider is overloaded — try again shortly",
  "مفيش اتصال بالنت — اتأكد من الاتصال وجرّب تاني": "No internet connection — check it and try again",
};

/* نصوص فيها أرقام بتتكتب من الكود */
const pl = (n, one, many) => (n === "1" ? one : many);
const EN_PATTERNS = [
  [/^([\d,.]+) تسجيل$/, (m, n) => `${n} ${pl(n, "recording", "recordings")}`],
  [/^([\d,.]+) كلمة$/, (m, n) => `${n} ${pl(n, "word", "words")}`],
  [/^([\d,.]+) نسخة$/, (m, n) => `${n} ${pl(n, "copy", "copies")}`],
  [/^([\d,.]+) من ([\d,.]+) نسخة$/, "$1 of $2 copies"],
  [/^([\d,.]+) (تسجيل|نسخة) متحدد$/, (m, n, u) => `${n} ${u === "تسجيل" ? pl(n, "recording", "recordings") : pl(n, "copy", "copies")} selected`],
  [/^تأكيد مسح ([\d,.]+)$/, "Confirm delete $1"],
  [/^اتمسح ([\d,.]+) (تسجيل|نسخة)$/, (m, n, u) => `Deleted ${n} ${u === "تسجيل" ? pl(n, "recording", "recordings") : pl(n, "copy", "copies")}`],
  [/^الإصدار v(.+)$/, "Version v$1"],
  [/^نزّل v(.+) ↗$/, "Download v$1 ↗"],
  [/^فيه نسخة جديدة: v(.+)$/, "New version available: v$1"],
  [/^(.*) · فيه مفتاح محفوظ — سيب الخانة فاضية عشان تفضل عليه$/, (m, h) => `${tr(h)} · A key is saved — leave empty to keep it`],
  [/^(.*) · لازم مفتاح قبل الحفظ$/, (m, h) => `${tr(h)} · A key is required before saving`],
  [/^المفتاح بيبدأ بحروف (.+)$/, "The key starts with $1"],
  [/^حدّث لـ v(.+)$/, "Update to v$1"],
  [/^بينزّل… (\d+)%$/, "Downloading… $1%"],
  [/^التحديث فشل — (.+)$/, (m, e) => `Update failed — ${tr(e)}`],
  [/^هاته من (.+)$/, "Get it from $1"],
  [/^(.+) بيفرّغ بس — التنظيف والبرومبت والترجمة هيشتغلوا بمفتاح (.+)$/, "$1 only transcribes — cleanup, prompt and translate will use your $2 key"],
  [/^(.+) بيفرّغ بس — ضيف مفتاح Groq أو Gemini كمان عشان التنظيف والبرومبت والترجمة يشتغلوا$/, "$1 only transcribes — add a Groq or Gemini key too so cleanup, prompt and translate work"],
];

/* أسماء وأوصاف المزوّدين (جاية من Python) */
Object.assign(EN, {
  "الأسرع": "Fastest", "الأدق": "Most accurate", "مجاني": "Free",
  "تفريغ فوري تقريبًا · فيه باقة مجانية سخية": "Near-instant transcription · generous free tier",
  "أحسن فهم للعامية المصرية · مدفوع بالكامل": "Best with Egyptian dialect · paid only",
  "باقة مجانية يومية كبيرة من جوجل": "Large free daily quota from Google",
  "رصيد $200": "$200 credit", "هاته من Deepgram Console ← API Keys": "Get it from Deepgram Console → API Keys",
  "رصيد مجاني $200 مبيخلصش بسرعة · بيفهم العامية المصرية": "$200 free credit that lasts · understands Egyptian Arabic",
  // ── موديل التفريغ ──
  "موديل التفريغ": "Transcription model", "موصى به": "Recommended", "بدون تقييم": "Not rated",
  "قايمة مقترحة — هتتحدّث لما تحط المفتاح": "Suggested list — updates once you add a key",
  "بجيب الموديلات المتاحة على مفتاحك…": "Fetching the models available to your key…",
  "دي موديلات التفريغ المتاحة على مفتاحك": "Transcription models available to your key",
  "قايمة مقترحة — معرفناش نسأل المزوّد دلوقتي": "Suggested list — couldn't reach the provider right now",
  "الأسرع · دقة ممتازة · مجاني": "Fastest · excellent accuracy · free",
  "أدق شوية في العربي · أبطأ": "Slightly more accurate in Arabic · slower",
  "أدق تفريغ للعامية": "Most accurate for dialect", "قريب منه · أرخص وأسرع": "Close to it · cheaper and faster",
  "الموديل القديم": "Legacy model", "أحدث Flash · سريع ومجاني": "Latest Flash · fast and free",
  "بيمشي مع آخر Flash تلقائيًا": "Always tracks the latest Flash", "نسخة أقدم": "Older version", "نسخة قديمة": "Old version",
  "بيدعم العامية المصرية · سريع جدًا": "Supports Egyptian Arabic · very fast", "أخف · أقل دقة في العربي": "Lighter · less accurate in Arabic",
  "Whisper على سيرفرات Deepgram · أبطأ": "Whisper on Deepgram servers · slower",
  // ── دليل المفتاح ──
  "إزاي أجيب مفتاح": "How to get a key for", "صفحة المفاتيح ↗": "API keys page ↗", "التوثيق ↗": "Docs ↗",
  "مجاني · من غير فيزا": "Free · no card", "مدفوع": "Paid", "مجاني · باقة يومية": "Free · daily quota", "$200 رصيد مجاني": "$200 free credit",
  "اعمل حساب مجاني على console.groq.com": "Create a free account at console.groq.com",
  "من القايمة ادخل API Keys ← Create API Key": "Open API Keys → Create API Key",
  "انسخ المفتاح (بيبدأ بـ gsk_) والصقه هنا": "Copy the key (starts with gsk_) and paste it here",
  "سجّل دخول على platform.openai.com": "Sign in at platform.openai.com",
  "اشحن رصيد من Billing (مفيش باقة مجانية)": "Add credit under Billing (no free tier)",
  "API keys ← Create new secret key وانسخه": "API keys → Create new secret key, then copy it",
  "ادخل aistudio.google.com بحساب جوجل": "Go to aistudio.google.com with your Google account",
  "دوس Get API key ← Create API key": "Click Get API key → Create API key",
  "انسخ المفتاح والصقه هنا": "Copy the key and paste it here",
  "اعمل حساب على console.deepgram.com (بياخد $200 هدية)": "Sign up at console.deepgram.com ($200 free credit)",
  "من المشروع ادخل API Keys ← Create a New API Key": "In your project open API Keys → Create a New API Key",
  "انسخ المفتاح فورًا (مبيظهرش تاني) والصقه هنا": "Copy the key right away (it's shown once) and paste it here",
  // ── التحديث ──
  "نزّل وثبّت التحديثات تلقائيًا": "Download and install updates automatically",
  "من GitHub · بيستنى لحد ما التسجيل يخلص وبعدين يعيد التشغيل لوحده": "From GitHub · waits until recording finishes, then restarts by itself",
  "فيه نسخة جديدة من إملاء — تحب تنزّلها وتثبّتها؟": "A new version of Emlaa is available — download and install it?",
  "صفحة الإصدار ↗": "Release page ↗", "بعدين": "Later", "نزّل وثبّت": "Download & install",
  "نزّل من GitHub ↗": "Download from GitHub ↗", "جرّب تاني": "Try again",
  "بيثبّت ويعيد التشغيل…": "Installing and restarting…", "معرفناش نبدأ التحديث": "Couldn't start the update",
  "التثبيت التلقائي مش متاح هنا — نزّله من صفحة الإصدار": "Automatic install isn't available here — download it from the release page",
  "بصمة الملف مش مطابقة — اتلغى التحديث": "File checksum doesn't match — update cancelled",
  "الملف اللي نزل مش برنامج ويندوز": "The downloaded file isn't a Windows program",
  "عندك آخر إصدار ✓": "You're on the latest version ✓", "بدوّر…": "Checking…",
  "Ctrl اليمين": "Right Ctrl", "Alt اليمين": "Right Alt", "Shift اليمين": "Right Shift", "العربية": "العربية",
});

let LANG = "ar";
const AR_RE = /[؀-ۿ]/;
const SKIP = ".row-text, .row-raw, .last-text, .r-text, .clip-text, .word, .app-tag, .user-text";
const NODES = new WeakMap();      // text node → { orig, shown }

function tr(ar, force) {
  if ((LANG !== "en" && !force) || !ar || !AR_RE.test(ar)) return ar;
  const key = ar.trim();
  if (EN[key] !== undefined) return ar.replace(key, EN[key]);
  for (const [re, rep] of EN_PATTERNS) {
    if (re.test(key)) return ar.replace(key, key.replace(re, rep));
  }
  // «Groq · الأسرع ✓» وأمثالها: نترجم كل جزء لوحده
  if (key.includes(" · ")) return ar.replace(key, key.split(" · ").map(p => {
    const t = p.replace(/ ✓$/, ""); const v = EN[t] !== undefined ? EN[t] : t;
    return p.endsWith(" ✓") ? v + " ✓" : v;
  }).join(" · "));
  return ar;
}

function skipped(el) { return !el || (el.closest && el.closest(SKIP)); }

function trText(node) {
  if (skipped(node.parentElement)) return;
  let rec = NODES.get(node);
  if (!rec || node.nodeValue !== rec.shown) rec = { orig: node.nodeValue };     // الكود كتب نص جديد
  if (!AR_RE.test(rec.orig)) return;
  rec.shown = LANG === "en" ? tr(rec.orig) : rec.orig;
  NODES.set(node, rec);
  if (node.nodeValue !== rec.shown) node.nodeValue = rec.shown;
}

function trAttrs(el) {
  if (skipped(el)) return;
  for (const a of ["title", "placeholder", "aria-label"]) {
    const store = "i18n" + a.replace("-", "");
    const cur = el.getAttribute(a);
    if (cur === null) continue;
    // الأصل العربي بيتغيّر بس لو الكود كتب قيمة جديدة (مش الأصل ولا ترجمته الإنجليزي)
    if (el.dataset[store] === undefined || (cur !== el.dataset[store] && cur !== tr(el.dataset[store], true))) {
      if (!AR_RE.test(cur)) continue;
      el.dataset[store] = cur;
    }
    const want = LANG === "en" ? tr(el.dataset[store]) : el.dataset[store];
    if (cur !== want) el.setAttribute(a, want);
  }
}

function translateTree(root) {
  if (root.nodeType === 3) return trText(root);
  if (root.nodeType !== 1) return;
  trAttrs(root);
  const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
  for (let n = w.nextNode(); n; n = w.nextNode()) n.nodeType === 3 ? trText(n) : trAttrs(n);
}

let busy = false;
const observer = new MutationObserver(muts => {
  if (busy) return;
  busy = true;
  try {
    for (const m of muts) {
      if (m.type === "characterData") trText(m.target);
      else if (m.type === "attributes") trAttrs(m.target);
      else m.addedNodes.forEach(translateTree);
    }
  } finally { busy = false; }
});

function setLang(lang) {
  LANG = lang === "en" ? "en" : "ar";
  const h = document.documentElement;
  h.lang = LANG;
  h.dir = LANG === "en" ? "ltr" : "rtl";
  try { localStorage.setItem("emlaa-lang", LANG); } catch (e) {}
  busy = true;
  try { translateTree(document.body); } finally { busy = false; }
  document.title = LANG === "en" ? "Emlaa" : "إملاء";
}

document.addEventListener("DOMContentLoaded", () => {
  let saved = "ar";
  try { saved = localStorage.getItem("emlaa-lang") || "ar"; } catch (e) {}
  setLang(saved);
  observer.observe(document.body, { subtree: true, childList: true, characterData: true,
                                    attributes: true, attributeFilter: ["title", "placeholder", "aria-label"] });
});
