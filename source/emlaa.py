# -*- coding: utf-8 -*-
"""
إملاء — صوت إلى نص عربي · Walid Mohamed
واجهة رسومية · بتشتغل في الخلفية جنب الساعة

تشغيل: Emlaa.exe   (أو python emlaa.py وقت التطوير)
"""
import os
import sys
import threading
import webbrowser

# في وضع الـexe الويندوز مبيديش stdout — أي print هيرمي استثناء من غير ده
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

import tkinter as tk
from tkinter import ttk

import core
import providers

APP_VERSION = "1.9"
BRAND_NAME  = "Walid Mohamed"
BRAND_URL   = "https://walidmohamed.com"


def R(t):
    """
    يثبّت اتجاه السطر يمين←شمال.

    Tkinter مبيحددش اتجاه الفقرة، فأي كلمة إنجليزي أو علامة ترقيم في آخر جملة
    عربي بتتنطّ لأول السطر. RLE (U+202B) + PDF (U+202C) بيجبروا السطر على RTL.
    الـ\\n فاصل فقرات في bidi — فكل سطر بيتحوّط لوحده.
    """
    return "\n".join("‫" + ln + "‬" for ln in str(t).split("\n"))


# ── الثيم ────────────────────────────────────────────────────────────────────
BG      = "#0b0d13"
CARD    = "#141722"
CARD_HI = "#1a1e2c"
FIELD   = "#1b1f2c"
BORDER  = "#262b3b"
LINE    = "#1e2230"
FG      = "#edeff6"
MUTED   = "#818799"
DIM     = "#565c6e"
VIO     = "#8b5cf6"
VIO_DK  = "#5b46b0"
VIO_GLOW = "#a78bfa"
GREEN   = "#22c55e"
RED     = "#ef4444"
AMBER   = "#f59e0b"

FONT   = "Segoe UI"
MONO   = "Consolas"

STATE = {
    "ready":     (VIO,       "جاهز — امسك الزرار واتكلم"),
    "rec":       (RED,       "بسجّل… اتكلم"),
    "work":      (AMBER,     "بفرّغ الكلام…"),
    "prompt":    (AMBER,     "بحوّله لبرومبت…"),
    "translate": ("#06b6d4", "بترجم الكلام…"),
    "done":      (GREEN,     "اتكتب ✓"),
    "err":       (RED,       "في مشكلة"),
}

HOTKEYS = [
    ("ctrl_r",      "Ctrl اليمين"),
    ("alt_r",       "Alt اليمين"),
    ("shift_r",     "Shift اليمين"),
    ("caps_lock",   "Caps Lock"),
    ("scroll_lock", "Scroll Lock"),
    ("f6",          "F6"),
    ("f7",          "F7"),
    ("f8",          "F8"),
    ("f9",          "F9"),
    ("f10",         "F10"),
    ("f11",         "F11"),
    ("f12",         "F12"),
]
HK_LABEL = dict(HOTKEYS)
HK_KEY   = {v: k for k, v in HOTKEYS}


def open_link(url):
    try:
        webbrowser.open_new_tab(url)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════
class WaveOverlay(tk.Toplevel):
    """
    زرار عائم صغير فوق كل البرامج:
    - وهو فاضي: كبسولة صغيرة (54x20) فيها نقط موجة هادية — بتنوّر لما الماوس يعدّي عليها
    - ضغطة عليه وهو فاضي: يبدأ التسجيل · كليك يمين: يفتح نافذة إملاء
    - وقت التسجيل بيكبر لكبسولة سودا (150x38): ✕ إلغاء على الشمال، موجة الصوت في النص، ✓ إنهاء على اليمين
    - قابل للتحريك بالسحب من أي مكان غير الزرارين، مع حفظ مكانه الأخير تلقائياً
    - الموجة بيضا في الوضع العادي، وبلون الوضع في البرومبت (برتقالي) والترجمة (تركواز)
    - لو اتقفل من الإعدادات بيرجع يظهر وقت التسجيل بس
    """
    W, H   = 150, 38                  # حجم الكبسولة وقت التسجيل
    IW, IH = 54, 20                   # حجم الزرار وهو فاضي
    BTN_R  = 13                       # نص قطر زرار ✕ / ✓
    BTN_PAD = 6                       # المسافة بين الزرار وحرف الكبسولة
    N    = 11                         # عدد أعمدة الموجة
    KEY  = "#010203"                  # لون خلفية شفاف
    DRAG = 4                          # أقل حركة (px) تتحسب سحب مش ضغطة

    BODY      = "#0e0e12"
    EDGE      = "#24252d"
    CANCEL_BG = ("#2c2d35", "#3d3e48")   # عادي / هوفر
    STOP_BG   = ("#ffffff", "#dcdce2")

    MODE_COLORS = {
        "normal":    ("#8b5cf6", "#a78bfa"),   # بنفسجي
        "prompt":    ("#f59e0b", "#fbbf24"),   # كهرماني / برتقالي
        "translate": ("#06b6d4", "#22d3ee"),   # تركواز / أزرق سماوي
    }

    def __init__(self, master, level_getter=None, on_click=None, on_menu=None, on_cancel=None):
        super().__init__(master)
        self._get   = level_getter or (lambda: getattr(getattr(master, "engine", None), "rec", None) and getattr(master.engine.rec, "level", 0.0) or 0.0)
        self._on_click  = on_click
        self._on_menu   = on_menu
        self._on_cancel = on_cancel
        self._lvl   = 0.0
        self._job   = None
        self._rec   = False
        self._state = "ready"
        self._mode  = "normal"
        self._phase = 0.0
        self._hover = False
        self._hot   = None                # الزرار اللي الماوس عليه: "cancel" / "stop" / None
        self._btn   = None                # الزرار اللي اتداس عليه في الضغطة الحالية

        # إحداثيات السحب بالفأرة
        self._drag_x = 0
        self._drag_y = 0
        self._press  = (0, 0)
        self._moved  = False

        self.overrideredirect(True)
        self.configure(bg=self.KEY)
        try:
            self.attributes("-topmost", True)
            self.attributes("-transparentcolor", self.KEY)
            self.attributes("-alpha", 0.98)
            self.attributes("-toolwindow", True)
        except Exception:
            pass

        self.cv = tk.Canvas(self, width=self.W, height=self.H,
                            bg=self.KEY, highlightthickness=0, cursor="hand2")
        self.cv.pack()

        # ✕ = إلغاء · ✓ = إنهاء · سحب من النص = تحريك · كليك يمين = فتح البرنامج
        self.cv.bind("<Button-1>", self._start_drag)
        self.cv.bind("<B1-Motion>", self._on_drag)
        self.cv.bind("<ButtonRelease-1>", self._end_drag)
        self.cv.bind("<Button-3>", lambda e: self._on_menu and self._on_menu())
        self.cv.bind("<Motion>", self._on_motion)
        self.cv.bind("<Enter>", lambda e: self._set_hover(True))
        self.cv.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<Destroy>", self._on_destroy)

        self.withdraw()

    def _on_destroy(self, e):
        # لو الشباك اتمسح وإحنا مش بنقفل البرنامج، نسجّل مين مسحه عشان نعرف السبب
        if e.widget is self and not getattr(self.master, "_quitting", False):
            import traceback
            core.log_error(RuntimeError("الموجة العائمة اتمسحت:" + chr(10) +
                                        "".join(traceback.format_stack(limit=12))), "overlay/destroy")

    @staticmethod
    def enabled():
        return bool(core.CFG.get("floating_button", False))

    def _size(self):
        return (self.IW, self.IH) if self._state == "idle" else (self.W, self.H)

    # ── الزرارين (شغّالين وقت التسجيل بس) ──
    def _btn_centers(self):
        off = self.BTN_PAD + self.BTN_R
        return {"cancel": (off, self.H / 2), "stop": (self.W - off, self.H / 2)}

    def _hit(self, x, y):
        if self._state != "rec":
            return None
        r2 = (self.BTN_R + 2) ** 2
        for name, (bx, by) in self._btn_centers().items():
            if (x - bx) ** 2 + (y - by) ** 2 <= r2:
                return name
        return None

    def _cursor_for(self, hot):
        if hot or self._state == "idle":
            return "hand2"
        return "fleur"

    def _on_motion(self, e):
        if self._btn or self._moved:
            return
        hot = self._hit(e.x, e.y)
        if hot != self._hot:
            self._hot = hot
            self.cv.config(cursor=self._cursor_for(hot))

    def _set_hover(self, on):
        self._hover = on
        if not on and self._btn is None:
            self._hot = None
        if self._state == "idle":
            self._draw_idle()

    def _start_drag(self, e):
        self._drag_x = e.x_root - self.winfo_x()
        self._drag_y = e.y_root - self.winfo_y()
        self._press  = (e.x_root, e.y_root)
        self._moved  = False
        self._btn    = self._hit(e.x, e.y)

    def _on_drag(self, e):
        if self._btn:                      # الضغطة بدأت على زرار — مفيش سحب
            return
        if not self._moved:
            dx, dy = e.x_root - self._press[0], e.y_root - self._press[1]
            if abs(dx) < self.DRAG and abs(dy) < self.DRAG:
                return
            self._moved = True
            self.cv.config(cursor="fleur")
        w, h = self._size()
        self.geometry(f"{w}x{h}+{e.x_root - self._drag_x}+{e.y_root - self._drag_y}")

    def _end_drag(self, e):
        btn, self._btn = self._btn, None
        if btn:
            # زي أي زرار عادي: الأكشن بيحصل لو السيبان كان على نفس الزرار
            if self._hit(e.x, e.y) == btn:
                cb = self._on_cancel if btn == "cancel" else self._on_click
                if cb:
                    cb()
            return
        moved, self._moved = self._moved, False
        self._hot = self._hit(e.x, e.y)
        self.cv.config(cursor=self._cursor_for(self._hot))
        if not moved:
            # وقت التسجيل الضغط في النص مالوش أكشن — الإلغاء والإنهاء من الزرارين
            if self._state == "idle" and self._on_click:
                self._on_click()
            return
        # المكان بيتحفظ كمركز الزرار (محسوب على مقاس الكبسولة الكبيرة)
        # عشان الزرار الصغير والكبسولة يفضلوا متمركزين في نفس النقطة
        w, h = self._size()
        cx = e.x_root - self._drag_x + w // 2
        cy = e.y_root - self._drag_y + h // 2
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        core.CFG["overlay_x"] = max(0, min(sw - self.W, cx - self.W // 2))
        core.CFG["overlay_y"] = max(0, min(sh - self.H, cy - self.H // 2))
        core.save_config(core.CFG)
        self._place()

    def _center(self):
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        try:
            x = max(0, min(sw - self.W, int(core.CFG.get("overlay_x"))))
            y = max(0, min(sh - self.H, int(core.CFG.get("overlay_y"))))
        except (TypeError, ValueError):
            x = (sw - self.W) // 2
            y = sh - self.H - 95
        return x + self.W // 2, y + self.H // 2

    def _place(self):
        w, h = self._size()
        cx, cy = self._center()
        self.cv.config(width=w, height=h)
        self.geometry(f"{w}x{h}+{cx - w // 2}+{cy - h // 2}")

    def show(self, mode="normal"):
        self._mode = mode or "normal"
        self._state = "rec"
        self._rec = True
        self._lvl = 0.0
        self._place()
        self.deiconify()
        try:
            self.attributes("-topmost", True)
        except Exception:
            pass
        if self._job is None:
            self._tick()

    def set_state(self, st, mode=None):
        if mode:
            self._mode = mode
        self._state = st
        self._rec = (st == "rec")
        if st != "rec":
            self._hot = self._btn = None
            self.cv.config(cursor=self._cursor_for(None))
        if st == "rec":
            self.show(mode=self._mode)
        elif st in ("work", "prompt", "translate"):
            self._draw(0.2)
        elif st == "done":
            self._draw(0.0)
            self.after(1200, self._settle)
        elif st == "err":
            self._draw(0.0)
            self.after(1800, self._settle)
        elif st == "ready":
            self.hide()

    def _settle(self):
        # لو بدأ تسجيل جديد في الثانية دي، مانخبّيش الموجة من تحته
        if self._state in ("done", "err"):
            self.hide()

    def set_recording(self, on):
        self._rec = bool(on)

    def hide(self):
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
            self._job = None
        self._rec = False
        self._hot = self._btn = None
        if self.enabled():
            self._state = "idle"
            self.cv.config(cursor="hand2")
            self._place()
            self._draw_idle()
            self.deiconify()
            try:
                self.attributes("-topmost", True)
            except Exception:
                pass
        else:
            self._state = "ready"
            self.withdraw()

    def _tick(self):
        try:
            lvl = float(self._get() or 0.0)
        except Exception:
            lvl = 0.0
        disp = min(1.0, lvl * 2.4)
        # طلوع سريع ونزول هادي عشان الموجة متترعشش
        self._lvl = disp if disp > self._lvl else self._lvl * 0.82 + disp * 0.18
        self._phase += 0.25
        self._draw(self._lvl)
        self._job = self.after(40, self._tick)

    def _pill(self, w=None, h=None, border_col=None):
        c = self.cv
        W, H = w or self.W, h or self.H
        r = H / 2
        bg_col = self.BODY
        border_col = border_col or self.EDGE
        # الحشوة الأول من غير حدود، وبعدين الإطار كخط واحد متصل حوالين الكبسولة
        c.create_oval(0, 0, H, H, fill=bg_col, outline="")
        c.create_oval(W - H, 0, W, H, fill=bg_col, outline="")
        c.create_rectangle(r, 0, W - r, H, fill=bg_col, outline="")
        c.create_arc(0, 0, H - 1, H - 1, start=90, extent=180, style="arc", outline=border_col)
        c.create_arc(W - H, 0, W - 1, H - 1, start=-90, extent=180, style="arc", outline=border_col)
        c.create_line(r, 0, W - r, 0, fill=border_col)
        c.create_line(r, H - 1, W - r, H - 1, fill=border_col)

    def _draw_idle(self):
        """الزرار وهو فاضي: نقط موجة هادية، بتنوّر وتعلى شوية مع الهوفر."""
        c = self.cv
        c.delete("all")
        W, H = self.IW, self.IH
        self._pill(W, H, border_col="#5a5b66" if self._hover else self.EDGE)
        cy = H / 2
        heights = (1.5, 3.0, 4.5, 3.0, 1.5) if self._hover else (1.2,) * 5
        col = "#ffffff" if self._hover else "#6b6d7a"
        gap = 6
        x0 = W / 2 - gap * (len(heights) - 1) / 2
        for i, hh in enumerate(heights):
            xc = x0 + i * gap
            c.create_line(xc, cy - hh, xc, cy + hh, fill=col, width=2.4, capstyle="round")

    def _draw_buttons(self):
        c = self.cv
        r = self.BTN_R
        pos = self._btn_centers()
        lx, ly = pos["cancel"]
        rx, ry = pos["stop"]

        # ✕ إلغاء — دايرة رمادي غامق
        c.create_oval(lx - r, ly - r, lx + r, ly + r, outline="",
                      fill=self.CANCEL_BG[self._hot == "cancel"])
        s = 4
        c.create_line(lx - s, ly - s, lx + s, ly + s, fill="#ffffff", width=2, capstyle="round")
        c.create_line(lx - s, ly + s, lx + s, ly - s, fill="#ffffff", width=2, capstyle="round")

        # ✓ إنهاء — دايرة بيضا وعلامة صح غامقة
        c.create_oval(rx - r, ry - r, rx + r, ry + r, outline="",
                      fill=self.STOP_BG[self._hot == "stop"])
        c.create_line(rx - 5, ry + 0.5, rx - 1.5, ry + 4, rx + 5, ry - 3.5,
                      fill=self.BODY, width=2.2, capstyle="round", joinstyle="round")

    def _draw(self, cur):
        import math
        c = self.cv
        c.delete("all")
        self._pill()
        cy = self.H / 2

        if self._state == "done":
            c.create_text(self.W / 2, cy, text="✓ تم", fill="#22c55e",
                          font=(FONT, 10, "bold"))
            return

        if self._state == "err":
            c.create_text(self.W / 2, cy, text="! خطأ", fill="#ef4444",
                          font=(FONT, 10, "bold"))
            return

        _, glow_col = self.MODE_COLORS.get(self._mode, self.MODE_COLORS["normal"])
        busy = self._state in ("work", "prompt", "translate")

        if busy:
            # بنفرّغ: مفيش زراير، والموجة بتتموّج لوحدها على عرض الكبسولة
            x0, x1 = 22, self.W - 22
            col = glow_col
        else:
            self._draw_buttons()
            edge = self.BTN_PAD + self.BTN_R * 2 + 7
            x0, x1 = edge, self.W - edge
            col = "#ffffff" if self._mode == "normal" else glow_col

        n = self.N
        mid = (n - 1) / 2
        slot = (x1 - x0) / n
        max_h = self.H / 2 - 8                      # أطول نص عمود
        for i in range(n):
            d = abs(i - mid) / mid                  # 0 في النص → 1 على الأطراف
            if busy:
                h = 2.0 + (math.sin(self._phase - i * 0.55) + 1.0) * 3.2
            else:
                env = 1.0 - 0.7 * d ** 1.4          # أطول في النص وبتقل على الجناب
                wob = 0.78 + 0.22 * math.sin(self._phase * 1.6 + d * 4.0)
                h = 1.6 + (max_h - 1.6) * max(cur, 0.03) * env * wob
            xc = x0 + i * slot + slot / 2
            c.create_line(xc, cy - h, xc, cy + h, fill=col, width=2.6, capstyle="round")


class ResultToast(tk.Toplevel):
    """
    لما التفريغ يخلص ومفيش خانة كتابة متعلّم عليها، النص بيظهر هنا فوق الموجة:
    اتنسخ للحافظة بالفعل، فالمستخدم يقدر يلزقه بـ Ctrl+V في أي مكان.
    بيختفي لوحده بعد ١٥ ثانية (إلا لو الماوس عليه)، ودوسة على النص بتنسخه تاني.
    """
    BG, BORDER = "#17171c", "#2b2b32"
    _current = None

    @classmethod
    def show_for(cls, master, text):
        if cls._current is not None:
            try:
                cls._current.destroy()
            except Exception:
                pass
        cls._current = cls(master, text)

    def __init__(self, master, text):
        super().__init__(master)
        self.text = text
        self._hover = False
        self.overrideredirect(True)
        try:
            self.attributes("-topmost", True)
            self.attributes("-toolwindow", True)
        except Exception:
            pass
        self.configure(bg=self.BORDER)
        box = tk.Frame(self, bg=self.BG, padx=14, pady=10)
        box.pack(padx=1, pady=1)

        head = tk.Frame(box, bg=self.BG); head.pack(fill="x")
        x = tk.Label(head, text="✕", bg=self.BG, fg=MUTED, font=(FONT, 10), cursor="hand2")
        x.pack(side="left"); x.bind("<Button-1>", lambda e: self.destroy())
        # عربي وإنجليزي في نفس الـLabel بيتلخبط ترتيبهم في Tk — فكل واحد في Label لوحده
        self.note = tk.Label(head, text=self._t("✓ اتنسخ للحافظة", "✓ Copied to clipboard"), bg=self.BG, fg=GREEN,
                             font=(FONT, 9, "bold"))
        self.note.pack(side="right")
        tk.Label(head, text="Ctrl+V", bg="#232329", fg=FG, font=(MONO, 8, "bold"),
                 padx=6).pack(side="right", padx=(0, 8))

        shown = text if len(text) <= 600 else text[:600] + "…"
        body = tk.Label(box, text=R(shown), bg=self.BG, fg=FG, font=(FONT, 11),
                        wraplength=360, justify="right", anchor="e", cursor="hand2")
        body.pack(fill="x", pady=(8, 2))
        body.bind("<Button-1>", lambda e: self._copy())
        tk.Label(box, text=self._t("مكانش فيه خانة كتابة — اتحفظ في السجل كمان", "No text field was focused — also saved to History"), bg=self.BG,
                 fg=DIM, font=(FONT, 8)).pack(anchor="e")

        for w in (self, box, body):
            w.bind("<Enter>", lambda e: setattr(self, "_hover", True))
            w.bind("<Leave>", lambda e: setattr(self, "_hover", False))
        self._place()
        self.after(15000, self._expire)

    @staticmethod
    def _t(ar, en):
        return en if core.CFG.get("lang") == "en" else R(ar)

    def _place(self):
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        try:
            cx = int(core.CFG.get("overlay_x")) + WaveOverlay.W // 2
            top = int(core.CFG.get("overlay_y"))
        except (TypeError, ValueError):
            cx, top = sw // 2, sh - WaveOverlay.H - 95
        x = max(8, min(sw - w - 8, cx - w // 2))
        y = top - h - 10 if top - h - 10 > 8 else top + WaveOverlay.H + 10
        self.geometry(f"+{x}+{min(y, sh - h - 8)}")

    def _copy(self):
        try:
            self.clipboard_clear(); self.clipboard_append(self.text); self.update_idletasks()
            self.note.config(text=self._t("✓ اتنسخ تاني", "✓ Copied again"))

        except Exception:
            pass

    def _expire(self):
        if not self.winfo_exists():
            return
        if self._hover:
            self.after(3000, self._expire)
        else:
            self.destroy()


class EmlaaClassic(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()                       # مانوريهاش غير لما تجهز
        self.title("إملاء")
        self.configure(bg=BG)
        self.resizable(False, False)
        try:
            self.iconbitmap(core.asset("emlaa.ico"))
        except Exception:
            pass

        self.cfg     = core.CFG
        self.engine  = None
        self.tray    = None
        self.last_text = ""
        self._pulse_on = False
        self.wave = None
        self._ui_state = None
        self._ready = False
        self._sel_provider = self.cfg.get("provider", providers.DEFAULT)

        self._style()
        # في الـexe مفيش console — أي خطأ جوّه callback بتاع Tk كان بيضيع في صمت
        self.report_callback_exception = lambda et, ev, tb: core.log_error(ev, "ui/callback")
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        # الشريط العائم يتبع النافذة: يختفي مع التصغير/القفل للتراي، ويرجع مع الفتح
        self.bind("<Map>", self._on_map)
        self.bind("<Unmap>", self._on_unmap)

        keys = providers.read_keys(core.ENV_PATH)
        if keys.get(self._sel_provider):
            self._screen_main()
            self._start_engine()
        else:
            self._screen_welcome()

        self._center()
        self.deiconify()
        threading.Thread(target=self._start_tray, daemon=True).start()
        self._watch_show_request()
        self._check_update()

    # ── مظهر ttk ──
    def _style(self):
        s = ttk.Style(self)
        try:
            s.theme_use("clam")
        except Exception:
            pass
        s.configure("D.TCombobox", fieldbackground=FIELD, background=FIELD,
                    foreground=FG, arrowcolor=MUTED, bordercolor=BORDER,
                    lightcolor=FIELD, darkcolor=FIELD, insertcolor=FG,
                    relief="flat", padding=8)
        s.map("D.TCombobox",
              fieldbackground=[("readonly", FIELD)], background=[("readonly", FIELD)],
              foreground=[("readonly", FG)], arrowcolor=[("active", VIO)],
              bordercolor=[("focus", VIO), ("active", VIO)])
        for k, v in [("background", FIELD), ("foreground", FG),
                     ("selectBackground", VIO), ("selectForeground", "white"),
                     ("borderWidth", 0), ("relief", "flat")]:
            self.option_add(f"*TCombobox*Listbox.{k}", v)
        self.option_add("*TCombobox*Listbox.font", "{%s} 10" % FONT)

    def _center(self):
        # العرض بييجي من _fit مش من reqwidth — الكروت بتطلب أقل من اللازم
        self.update_idletasks()
        w = getattr(self, "_win_w", 0) or self.winfo_reqwidth()
        h = self.winfo_reqheight()
        x = (self.winfo_screenwidth() - w) // 2
        y = max(20, (self.winfo_screenheight() - h) // 2 - 40)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _fit(self, w=452):
        self._win_w = w   # مش _w — ده اسم محجوز لتكينتر
        self.update_idletasks()
        self.geometry(f"{w}x{self.winfo_reqheight()}")

    def _clear(self):
        for w in self.winfo_children():
            w.destroy()

    # ── عناصر مشتركة ──
    def _card(self, parent, bg=CARD, **kw):
        return tk.Frame(parent, bg=bg, highlightthickness=1,
                        highlightbackground=BORDER, highlightcolor=BORDER, **kw)

    def _mic(self, parent, size=28, col=FG, bg=BG):
        cv = tk.Canvas(parent, width=size, height=size, bg=bg, highlightthickness=0)
        s, bw = size, size * 0.30
        x0, x1 = s / 2 - bw / 2, s / 2 + bw / 2
        top, bot, r = s * 0.12, s * 0.56, bw / 2
        w = max(2, int(s * 0.07))
        cv.create_oval(x0, top, x1, top + 2 * r, fill=col, outline="")
        cv.create_oval(x0, bot - 2 * r, x1, bot, fill=col, outline="")
        cv.create_rectangle(x0, top + r, x1, bot - r, fill=col, outline="")
        cv.create_arc(s * .26, s * .30, s * .74, s * .72, start=200, extent=140,
                      style="arc", outline=col, width=w)
        cv.create_line(s / 2, s * .72, s / 2, s * .86, fill=col, width=w)
        cv.create_line(s * .36, s * .88, s * .64, s * .88, fill=col, width=w)
        return cv

    def _switch(self, parent, var, text="", sub=None, bg=CARD, on_change=None):
        row = tk.Frame(parent, bg=bg)
        txt = tk.Frame(row, bg=bg); txt.pack(side="right", fill="x", expand=True)
        l1 = tk.Label(txt, text=R(text), bg=bg, fg=FG, font=(FONT, 10), anchor="e")
        l1.pack(fill="x")
        l2 = None
        if sub:
            l2 = tk.Label(txt, text=R(sub), bg=bg, fg=DIM, font=(FONT, 8), anchor="e")
            l2.pack(fill="x")
        row._l1, row._l2 = l1, l2         # عشان نقدر نطفّي السطر لو بقى مش مؤثّر
        cv = tk.Canvas(row, width=44, height=24, bg=bg, highlightthickness=0)
        cv.pack(side="left", padx=(0, 12))

        def draw():
            cv.delete("all")
            on = bool(var.get())
            c = VIO if on else BORDER
            cv.create_oval(1, 2, 21, 22, fill=c, outline="")
            cv.create_oval(23, 2, 43, 22, fill=c, outline="")
            cv.create_rectangle(11, 2, 33, 22, fill=c, outline="")
            kx = 32 if on else 12
            cv.create_oval(kx - 8, 4, kx + 8, 20, fill="white", outline="")

        def flip(_=None):
            var.set(not var.get()); draw()
            if on_change:
                on_change(bool(var.get()))

        for w in [cv, l1, txt] + ([l2] if l2 else []):
            w.bind("<Button-1>", flip); w.config(cursor="hand2")
        draw()
        return row

    def _footer(self, parent):
        f = tk.Frame(parent, bg=BG)
        tk.Frame(f, bg=LINE, height=1).pack(fill="x", padx=22, pady=(4, 12))
        row = tk.Frame(f, bg=BG); row.pack()
        link = tk.Label(row, text=BRAND_NAME, bg=BG, fg=VIO,
                        font=(FONT, 9, "bold"), cursor="hand2")
        link.pack(side="left")
        tk.Label(row, text=R("صُنع بـ") + " ", bg=BG, fg=DIM, font=(FONT, 9)).pack(side="left")
        tk.Label(row, text="❤", bg=BG, fg="#e0446d", font=(FONT, 10)).pack(side="left")
        tk.Label(row, text=" " + R("في") + " ", bg=BG, fg=DIM, font=(FONT, 9)).pack(side="left")
        link.bind("<Button-1>", lambda e: open_link(BRAND_URL))
        link.bind("<Enter>", lambda e: link.config(fg=FG))
        link.bind("<Leave>", lambda e: link.config(fg=VIO))
        tk.Label(f, text=R(f"إملاء {APP_VERSION} · أداة مجانية"), bg=BG, fg="#3a3f4f",
                 font=(FONT, 8)).pack(pady=(3, 13))
        return f

    # ═══════════════ شاشة البداية: المزوّد + المفتاح ═══════════════
    def _screen_welcome(self):
        self._clear()
        self.title("إملاء · الإعداد")

        top = tk.Frame(self, bg=BG); top.pack(fill="x", pady=(26, 0))
        self._mic(top, 42, VIO).pack()
        tk.Label(top, text=R("أهلاً بيك في إملاء"), bg=BG, fg=FG,
                 font=(FONT, 19, "bold")).pack(pady=(10, 3))
        tk.Label(top, text=R("اتكلم عربي في أي برنامج… والكلام يتكتب لوحده"),
                 bg=BG, fg=MUTED, font=(FONT, 10)).pack()

        tk.Label(self, text=R("اختار اللي هيفرّغ لك الكلام"), bg=BG, fg=MUTED,
                 font=(FONT, 9), anchor="e").pack(fill="x", padx=24, pady=(22, 7))

        self._pcards = {}
        holder = tk.Frame(self, bg=BG); holder.pack(fill="x", padx=24)
        for pid in providers.ORDER:
            self._pcards[pid] = self._provider_card(holder, pid)
            self._pcards[pid]["frame"].pack(fill="x", pady=3)

        # ── المفتاح ──
        self.key_wrap = tk.Frame(self, bg=BG)
        self.key_wrap.pack(fill="x", padx=24, pady=(16, 0))

        hdr = tk.Frame(self.key_wrap, bg=BG); hdr.pack(fill="x")
        self.key_lbl = tk.Label(hdr, text="", bg=BG, fg=MUTED, font=(FONT, 9), anchor="e")
        self.key_lbl.pack(side="right", fill="x", expand=True)
        self.key_link = tk.Label(hdr, text=R("↗ اعمل مفتاح"), bg=BG, fg=VIO,
                                 font=(FONT, 9, "bold"), cursor="hand2")
        self.key_link.pack(side="left", padx=(0, 10))
        self.key_link.bind("<Button-1>",
                           lambda e: open_link(providers.meta(self._sel_provider)["key_url"]))

        kf = tk.Frame(self.key_wrap, bg=FIELD, highlightthickness=1,
                      highlightbackground=BORDER, highlightcolor=VIO)
        kf.pack(fill="x", pady=(7, 0))
        self.key_var = tk.StringVar()
        self.key_in = tk.Entry(kf, textvariable=self.key_var, bg=FIELD, fg=FG, bd=0,
                               insertbackground=FG, justify="left", font=(MONO, 10))
        self.key_in.pack(fill="x", ipady=9, padx=11)
        self.key_in.bind("<Return>", lambda _: self._confirm())

        self.msg = tk.Label(self, text="", bg=BG, fg=MUTED, font=(FONT, 9),
                            wraplength=390, justify="right")
        self.msg.pack(pady=(9, 0))

        self.go = tk.Button(self, text=R("تأكيد وابدأ"), bg=VIO, fg="white", bd=0,
                            font=(FONT, 12, "bold"), activebackground=VIO_DK,
                            activeforeground="white", cursor="hand2", command=self._confirm)
        self.go.pack(fill="x", padx=24, ipady=11, pady=(11, 4))

        self._footer(self).pack(fill="x", side="bottom", pady=(12, 0))
        self._pick(self._sel_provider)
        self._fit(478)

    def _provider_card(self, parent, pid):
        m = providers.meta(pid)
        fr = tk.Frame(parent, bg=CARD, highlightthickness=1,
                      highlightbackground=BORDER, cursor="hand2")
        inner = tk.Frame(fr, bg=CARD); inner.pack(fill="x", padx=13, pady=10)

        dot = tk.Canvas(inner, width=18, height=18, bg=CARD, highlightthickness=0)
        dot.pack(side="left")

        txt = tk.Frame(inner, bg=CARD); txt.pack(side="right", fill="x", expand=True)
        line = tk.Frame(txt, bg=CARD); line.pack(fill="x")
        tk.Label(line, text=m["name"], bg=CARD, fg=FG,
                 font=(FONT, 11, "bold")).pack(side="right")
        tag = tk.Label(line, text=R(m["tag"]), bg=VIO_DK, fg="white",
                       font=(FONT, 8, "bold"), padx=7)
        tag.pack(side="right", padx=(8, 0))
        sub = tk.Label(txt, text=R(m["desc"]), bg=CARD, fg=MUTED,
                       font=(FONT, 8.5 if False else 9), anchor="e")
        sub.pack(fill="x", pady=(2, 0))

        widgets = [fr, inner, dot, txt, line, sub, tag]
        for w in widgets:
            w.bind("<Button-1>", lambda e, p=pid: self._pick(p))
            try: w.config(cursor="hand2")
            except Exception: pass
        return {"frame": fr, "dot": dot, "bgs": [fr, inner, txt, line, sub, dot],
                "labels": [sub]}

    def _pick(self, pid):
        """اختيار المزوّد — بيغيّر شكل الكارت والمفتاح المعروض."""
        self._sel_provider = pid
        keys = providers.read_keys(core.ENV_PATH)
        for p, c in self._pcards.items():
            on = (p == pid)
            bg = CARD_HI if on else CARD
            c["frame"].config(highlightbackground=VIO if on else BORDER)
            for w in c["bgs"]:
                try: w.config(bg=bg)
                except Exception: pass
            for w in c["frame"].winfo_children():
                self._recolor(w, bg)
            d = c["dot"]; d.delete("all"); d.config(bg=bg)
            d.create_oval(2, 2, 16, 16, outline=VIO if on else BORDER, width=2)
            if on:
                d.create_oval(6, 6, 12, 12, fill=VIO, outline="")

        m = providers.meta(pid)
        self.key_lbl.config(text=R(f"مفتاح {m['name']} — {m['key_hint']}"))
        self.key_var.set(keys.get(pid, ""))
        self.msg.config(text="")
        self.key_in.focus_set()

    def _recolor(self, w, bg):
        """يلوّن الأبناء اللي خلفيتهم كانت لون الكارت (مش الشارة الملوّنة)."""
        try:
            if w.cget("bg") in (CARD, CARD_HI):
                w.config(bg=bg)
        except Exception:
            pass
        for c in w.winfo_children():
            self._recolor(c, bg)

    def _confirm(self):
        pid = self._sel_provider
        key = self.key_var.get().strip().strip('"').strip("'")
        self.go.config(text=R("بتأكد من المفتاح…"), state="disabled")
        self.msg.config(text="")

        def work():
            ok, err = providers.verify(pid, key)
            self.after(0, lambda: done(ok, err))

        def done(ok, err):
            if ok:
                providers.write_key(core.ENV_PATH, pid, key)
                self.cfg["provider"] = pid
                core.save_config(self.cfg)
                self._screen_main()
                self._center()
                self._start_engine()
                return
            self.go.config(text=R("تأكيد وابدأ"), state="normal")
            self.msg.config(text=R(err), fg=AMBER if "الصق" in err else RED)

        threading.Thread(target=work, daemon=True).start()

    # ═══════════════ الشاشة الرئيسية ═══════════════
    def _screen_main(self):
        self._clear()
        self.title("إملاء")
        PADX = 22

        head = tk.Frame(self, bg=BG); head.pack(fill="x", padx=PADX, pady=(15, 0))
        # شارة بتبان بس لما وضع البرومبت يبقى شغّال — عشان يبان من غير ما
        # المستخدم يفتح الإعدادات ويتساءل ليه الكلام اتغيّر
        self.mode_lbl = tk.Label(head, text=R("برومبت"), bg=VIO_DK, fg="white",
                                 font=(FONT, 8, "bold"), padx=9, pady=6)
        brand = tk.Frame(head, bg=BG); brand.pack(side="right")
        self._mic(brand, 27).pack(side="right")
        ttl = tk.Frame(brand, bg=BG); ttl.pack(side="right", padx=(0, 9))
        tk.Label(ttl, text=R("إملاء"), bg=BG, fg=FG, font=(FONT, 17, "bold")).pack(anchor="e")
        self.prov_lbl = tk.Label(ttl, text="", bg=BG, fg=MUTED, font=(FONT, 8))
        self.prov_lbl.pack(anchor="e")
        self._render_provider(); self._render_mode()

        self.canvas = tk.Canvas(self, width=204, height=204, bg=BG, highlightthickness=0)
        self.canvas.pack(pady=(16, 6))
        self.canvas.bind("<Button-1>", lambda e: self._toggle_record())
        self.canvas.config(cursor="hand2")
        self._circle(VIO)

        self.status = tk.Label(self, text=R("بجهّز الميكروفون…"), bg=BG, fg=FG,
                               font=(FONT, 12, "bold"))
        self.status.pack()
        self.hint = tk.Label(self, text="", bg=BG, fg=MUTED, font=(FONT, 9))
        self.hint.pack(pady=(3, 0))

        hrow = tk.Frame(self, bg=BG); hrow.pack(fill="x", padx=PADX, pady=(15, 5))
        tk.Label(hrow, text=R("آخر نص"), bg=BG, fg=MUTED, font=(FONT, 9),
                 anchor="e").pack(side="right")
        self.copy_btn = tk.Button(hrow, text=R("نسخ"), bg=CARD, fg=MUTED, bd=0,
                                  activebackground=BORDER, activeforeground=FG,
                                  cursor="hand2", font=(FONT, 8, "bold"), padx=13, pady=3,
                                  command=self._copy)
        self.copy_btn.pack(side="left")
        tc = self._card(self); tc.pack(fill="x", padx=PADX)
        self.text = tk.Text(tc, bg=CARD, fg=FG, bd=0, height=3, width=1, wrap="word",
                            font=(FONT, 12), padx=13, pady=11, insertbackground=FG)
        self.text.tag_configure("rtl", justify="right")
        self.text.pack(fill="both")
        self._set_text("…")

        srow = tk.Frame(self, bg=BG); srow.pack(fill="x", padx=PADX, pady=(17, 0))
        self.hbtn = tk.Button(srow, text=R("📜  سجل التسجيلات"), bg=CARD, fg=FG, bd=0,
                              font=(FONT, 9, "bold"), activebackground=CARD_HI,
                              activeforeground=FG, cursor="hand2",
                              command=self._open_history)
        self.hbtn.pack(side="right", fill="x", expand=True, ipady=9, padx=(4, 0))
        self.sbtn = tk.Button(srow, text=R("⚙  الإعدادات"), bg=CARD, fg=MUTED, bd=0,
                              font=(FONT, 9, "bold"), activebackground=CARD_HI,
                              activeforeground=FG, cursor="hand2",
                              command=self._open_settings)
        self.sbtn.pack(side="left", fill="x", expand=True, ipady=9, padx=(0, 4))

        self.foot = self._footer(self)
        self.foot.pack(fill="x", side="bottom", pady=(15, 0))
        self._fit(452)

    def _open_history(self):
        """نافذة تصفح سجل التسجيلات السابقة مع إمكانية النسخ ومسح السجل."""
        if getattr(self, "_hist_dlg", None) and self._hist_dlg.winfo_exists():
            self._hist_dlg.lift()
            self._hist_dlg.focus_force()
            return

        d = tk.Toplevel(self, bg=BG)
        self._hist_dlg = d
        d.title("إملاء · سجل التسجيلات")
        d.configure(bg=BG)
        try:
            d.iconbitmap(core.asset("emlaa.ico"))
        except Exception:
            pass
        d.transient(self)

        w, h = 460, 520

        head = tk.Frame(d, bg=BG)
        head.pack(fill="x", padx=20, pady=(16, 8))

        def do_clear():
            core.history_clear()
            render_items()

        clr_btn = tk.Button(head, text=R("مسح السجل"), bg=CARD, fg=MUTED, bd=0,
                            font=(FONT, 8, "bold"), activebackground=BORDER,
                            activeforeground=RED, cursor="hand2", padx=9, pady=3,
                            command=do_clear)
        clr_btn.pack(side="left")

        tk.Label(head, text=R("سجل التسجيلات"), bg=BG, fg=FG,
                 font=(FONT, 13, "bold"), anchor="e").pack(side="right")

        container = tk.Frame(d, bg=BG)
        container.pack(fill="both", expand=True, padx=20, pady=(4, 8))

        cv = tk.Canvas(container, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(container, orient="vertical", command=cv.yview)
        scroll_frame = tk.Frame(cv, bg=BG)

        scroll_frame.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cw = cv.create_window((0, 0), window=scroll_frame, anchor="nw")
        cv.configure(xscrollcommand=None, yscrollcommand=sb.set)

        cv.bind("<Configure>", lambda e: cv.itemconfig(cw, width=e.width))

        def _on_mousewheel(e):
            cv.yview_scroll(int(-1 * (e.delta / 120)), "units")
        cv.bind_all("<MouseWheel>", _on_mousewheel)

        cv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        MODE_BADGES = {
            "normal":    ("عادي",    "#2e1b4d", "#c084fc"),
            "prompt":    ("برومبت",  "#3d2800", "#fbbf24"),
            "translate": ("ترجمة",   "#0e3a47", "#22d3ee"),
        }

        def render_items():
            for child in scroll_frame.winfo_children():
                child.destroy()
            items = core.history_get()
            if not items:
                empty = tk.Frame(scroll_frame, bg=BG)
                empty.pack(fill="both", expand=True, pady=80)
                tk.Label(empty, text="📜", bg=BG, fg=DIM, font=(FONT, 28)).pack(pady=(0, 6))
                tk.Label(empty, text=R("مفيش أي تسجيلات سابقة لسه"), bg=BG, fg=MUTED,
                         font=(FONT, 10)).pack()
                return

            for item in items:
                m_type = item.get("mode", "normal")
                lbl_text, b_bg, b_fg = MODE_BADGES.get(m_type, ("عادي", "#2e1b4d", "#c084fc"))

                card = tk.Frame(scroll_frame, bg=CARD, highlightthickness=1,
                                highlightbackground=BORDER)
                card.pack(fill="x", pady=5, padx=2)

                top = tk.Frame(card, bg=CARD)
                top.pack(fill="x", padx=12, pady=(10, 4))

                res_text = item.get("result", "")

                b_copy = tk.Button(top, text=R("نسخ"), bg=FIELD, fg=MUTED, bd=0,
                                   font=(FONT, 8, "bold"), padx=9, pady=2, cursor="hand2",
                                   activebackground=BORDER, activeforeground=FG)
                def copy_cmd(t=res_text, btn=b_copy):
                    try:
                        d.clipboard_clear()
                        d.clipboard_append(t)
                        d.update_idletasks()
                        btn.config(text=R("اتنسخ ✓"), fg=GREEN)
                        d.after(1200, lambda: btn.winfo_exists() and btn.config(text=R("نسخ"), fg=MUTED))
                    except Exception:
                        pass
                b_copy.config(command=copy_cmd)
                b_copy.pack(side="left")

                time_str = item.get("time_display", "")
                date_str = item.get("date_display", "")
                tk.Label(top, text=f"{date_str}  {time_str}", bg=CARD, fg=DIM,
                         font=(FONT, 8)).pack(side="left", padx=(10, 0))

                tk.Label(top, text=R(lbl_text), bg=b_bg, fg=b_fg,
                         font=(FONT, 7, "bold"), padx=6, pady=1).pack(side="right")

                t_lbl = tk.Label(card, text=R(res_text), bg=CARD, fg=FG,
                                 font=(FONT, 10), justify="right", anchor="e",
                                 wraplength=380)
                t_lbl.pack(fill="x", padx=12, pady=(2, 10))

        render_items()

        bot = tk.Frame(d, bg=BG)
        bot.pack(fill="x", side="bottom", pady=(2, 12))
        tk.Button(bot, text=R("إغلاق"), bg=CARD, fg=MUTED, bd=0, font=(FONT, 9),
                  activebackground=BG, activeforeground=FG, cursor="hand2",
                  padx=24, pady=5, command=d.destroy).pack()

        d.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - w) // 2
        y = max(10, self.winfo_rooty() + 20)
        d.geometry(f"{w}x{h}+{x}+{y}")

    def _open_settings(self):
        """
        نافذة إعدادات مستقلة.
        (كانت بتتفتح جوّه النافذة الرئيسية — الطول كان بيعدّي حدود الشاشة
         وآخر الإعدادات كان بيتقص، فبقت نافذة لوحدها زي أي برنامج عادي.)
        """
        if getattr(self, "_dlg", None) and self._dlg.winfo_exists():
            self._dlg.lift(); self._dlg.focus_force(); return

        d = tk.Toplevel(self, bg=BG)
        self._dlg = d
        d.title("إملاء · الإعدادات")
        d.configure(bg=BG)
        d.resizable(False, False)
        try:
            d.iconbitmap(core.asset("emlaa.ico"))
        except Exception:
            pass
        d.transient(self)

        # مسوّدة المفاتيح: اللي اتحفظ فعلًا + أي حاجة المستخدم يكتبها دلوقتي.
        self._key_drafts = dict(providers.read_keys(core.ENV_PATH))
        self._last_pid = None

        head = tk.Frame(d, bg=BG); head.pack(fill="x", padx=22, pady=(18, 0))
        tk.Label(head, text=R("الإعدادات"), bg=BG, fg=FG,
                 font=(FONT, 14, "bold"), anchor="e").pack(fill="x")

        inner = tk.Frame(d, bg=BG); inner.pack(fill="x", padx=22, pady=(14, 0))
        CARD_BG = BG

        tk.Label(inner, text=R("اللي بيفرّغ الكلام"), bg=BG, fg=MUTED,
                 font=(FONT, 8), anchor="e").pack(fill="x")
        self.prov_var = tk.StringVar(
            value=providers.meta(self.cfg.get("provider")) ["name"])
        pc = ttk.Combobox(inner, textvariable=self.prov_var, state="readonly",
                          justify="right", style="D.TCombobox",
                          values=[providers.meta(p)["name"] for p in providers.ORDER])
        pc.pack(fill="x", pady=(6, 0), ipady=2)
        pc.bind("<<ComboboxSelected>>", lambda e: self._provider_changed())

        self.skey_lbl = tk.Label(inner, text="", bg=BG, fg=MUTED,
                                 font=(FONT, 8), anchor="e")
        self.skey_lbl.pack(fill="x", pady=(13, 0))
        kf = tk.Frame(inner, bg=FIELD, highlightthickness=1,
                      highlightbackground=BORDER, highlightcolor=VIO)
        kf.pack(fill="x", pady=(6, 0))
        self.skey_var = tk.StringVar()
        tk.Button(kf, text="👁", bg=FIELD, fg=MUTED, bd=0, activebackground=FIELD,
                  activeforeground=FG, cursor="hand2",
                  command=lambda: self.skey_in.config(
                      show="" if self.skey_in.cget("show") else "•")
                  ).pack(side="left", padx=(6, 2))
        self.skey_in = tk.Entry(kf, textvariable=self.skey_var, show="•", bg=FIELD,
                                fg=FG, bd=0, insertbackground=FG, justify="left",
                                font=(MONO, 10))
        self.skey_in.pack(side="right", fill="x", expand=True, ipady=7, padx=(4, 11))
        self.skey_link = tk.Label(inner, text=R("↗ اعمل مفتاح جديد"), bg=BG, fg=VIO,
                                  font=(FONT, 8, "bold"), cursor="hand2", anchor="e")
        self.skey_link.pack(fill="x", pady=(5, 0))
        self.skey_link.bind("<Button-1>", lambda e: open_link(
            providers.meta(self._settings_pid())["key_url"]))

        tk.Frame(inner, bg=LINE, height=1).pack(fill="x", pady=16)

        # ── أزرار الاختصارات الثلاثة ──
        tk.Label(inner, text=R("زرار التسجيل العادي (تفريغ وتنظيف)"), bg=BG, fg=MUTED,
                 font=(FONT, 8), anchor="e").pack(fill="x")
        cur_norm = self.cfg.get("hotkey_normal") or self.cfg.get("hotkey") or "ctrl_r"
        self.hk_norm_var = tk.StringVar(value=HK_LABEL.get(cur_norm, cur_norm))
        ttk.Combobox(inner, textvariable=self.hk_norm_var, state="readonly", justify="right",
                     style="D.TCombobox", values=[v for _, v in HOTKEYS]
                     ).pack(fill="x", pady=(4, 9), ipady=2)

        tk.Label(inner, text=R("زرار تسجيل البرومبت (تحويل لطلب للـAI)"), bg=BG, fg=MUTED,
                 font=(FONT, 8), anchor="e").pack(fill="x")
        cur_prmt = self.cfg.get("hotkey_prompt") or "alt_r"
        self.hk_prmt_var = tk.StringVar(value=HK_LABEL.get(cur_prmt, cur_prmt))
        ttk.Combobox(inner, textvariable=self.hk_prmt_var, state="readonly", justify="right",
                     style="D.TCombobox", values=[v for _, v in HOTKEYS]
                     ).pack(fill="x", pady=(4, 9), ipady=2)

        tk.Label(inner, text=R("زرار الترجمة الفورية (عربي ⟷ إنجليزي)"), bg=BG, fg=MUTED,
                 font=(FONT, 8), anchor="e").pack(fill="x")
        cur_trns = self.cfg.get("hotkey_translate") or "shift_r"
        self.hk_trns_var = tk.StringVar(value=HK_LABEL.get(cur_trns, cur_trns))
        ttk.Combobox(inner, textvariable=self.hk_trns_var, state="readonly", justify="right",
                     style="D.TCombobox", values=[v for _, v in HOTKEYS]
                     ).pack(fill="x", pady=(4, 9), ipady=2)


        self.polish_var = tk.BooleanVar(value=self.cfg.get("polish", True))
        self.polish_row = self._switch(inner, self.polish_var, "تنظيف النص وتصحيحه",
                                       "بيصلّح الترقيم والأخطاء ويحافظ على العامية", bg=BG)
        self.polish_row.pack(fill="x", pady=(15, 2))

        self.prompt_var = tk.BooleanVar(value=self.cfg.get("prompt_mode", False))
        self._switch(inner, self.prompt_var, "حوّل كلامي لبرومبت جاهز",
                     "بدل ما يكتب كلامك زي ما هو، يرتّبه كطلب واضح للـAI",
                     bg=BG, on_change=self._prompt_toggled).pack(fill="x", pady=(13, 2))

        self.paste_var = tk.BooleanVar(value=self.cfg.get("auto_paste", True))
        self._switch(inner, self.paste_var, "كتابة النص تلقائيًا",
                     "لو قفلته، النص هيتنسخ للحافظة بس", bg=BG).pack(fill="x", pady=(13, 2))

        self.tray_var = tk.BooleanVar(value=self.cfg.get("minimize_to_tray", True))
        self._switch(inner, self.tray_var, "يفضل شغّال جنب الساعة",
                     "قفل النافذة بيصغّره مش بيقفله", bg=BG).pack(fill="x", pady=(13, 2))

        self.float_var = tk.BooleanVar(value=self.cfg.get("floating_button", False))
        self._switch(inner, self.float_var, "زرار عائم ظاهر طول الوقت",
                     "لو مقفول: الموجة بتظهر بس وقت التسجيل · اسحبها لأي مكان", bg=BG).pack(fill="x", pady=(13, 2))

        self.upd_var = tk.BooleanVar(value=self.cfg.get("check_updates", True))
        self._switch(inner, self.upd_var, "طمّني لو نزلت نسخة جديدة",
                     "بيسأل سيرفرنا عن رقم آخر إصدار بس — مفيش أي بيانات عنك",
                     bg=BG).pack(fill="x", pady=(13, 2))

        self.smsg = tk.Label(d, text="", bg=BG, fg=MUTED, font=(FONT, 9),
                             wraplength=380, justify="right")
        self.smsg.pack(fill="x", padx=22, pady=(16, 0))

        self.save_btn = tk.Button(d, text=R("حفظ"), bg=VIO, fg="white", bd=0,
                                  font=(FONT, 11, "bold"), activebackground=VIO_DK,
                                  activeforeground="white", cursor="hand2",
                                  command=self._save)
        self.save_btn.pack(fill="x", padx=22, ipady=10, pady=(8, 6))
        tk.Button(d, text=R("إغلاق"), bg=BG, fg=MUTED, bd=0, font=(FONT, 9),
                  activebackground=BG, activeforeground=FG, cursor="hand2",
                  command=d.destroy).pack(pady=(0, 16))

        self._sync_settings_key()
        self._prompt_toggled(self.prompt_var.get())

        # في نص النافذة الرئيسية، ومحصور جوّه الشاشة
        d.update_idletasks()
        w, h = 430, d.winfo_reqheight()
        x = self.winfo_rootx() + (self.winfo_width() - w) // 2
        y = max(10, min(self.winfo_rooty() + 30,
                        d.winfo_screenheight() - h - 60))
        d.geometry(f"{w}x{h}+{max(10, x)}+{y}")

    def _prompt_toggled(self, on):
        """
        وضع البرومبت بيلغي التنظيف — البرومبت أصلاً بيتكتب مرتّب، ونداء واحد
        بدل اتنين. فبنطفّي سطر التنظيف بصريًا عشان يبان إنه مش مؤثّر دلوقتي.
        """
        row = getattr(self, "polish_row", None)
        if not row:
            return
        row._l1.config(fg=DIM if on else FG)
        if row._l2:
            row._l2.config(text=R("وضع البرومبت شغّال — التنظيف مش محتاجه" if on
                                  else "بيصلّح الترقيم والأخطاء ويحافظ على العامية"),
                           fg="#3a3f4f" if on else DIM)

    def _settings_pid(self):
        name = self.prov_var.get()
        for p in providers.ORDER:
            if providers.meta(p)["name"] == name:
                return p
        return providers.DEFAULT

    def _sync_settings_key(self):
        pid = self._settings_pid()
        m = providers.meta(pid)
        self.skey_lbl.config(text=R(f"مفتاح {m['name']} — {m['key_hint']}"))
        self.skey_var.set(self._key_drafts.get(pid, ""))
        self._last_pid = pid

    def _provider_changed(self):
        """
        مهم: بنحتفظ باللي المستخدم كتبه للمزوّد القديم قبل ما نبدّل.
        """
        prev = getattr(self, "_last_pid", None)
        typed = self.skey_var.get().strip()
        new = self._settings_pid()
        note = ""

        if typed and prev and prev != new:
            new_start = providers.meta(new)["key_start"]
            old_start = providers.meta(prev)["key_start"]
            if new_start and typed.startswith(new_start):
                self._key_drafts[new] = typed
                note = f"المفتاح ده بتاع {providers.meta(new)['name']} — نقلته لمكانه."
            elif not old_start or typed.startswith(old_start):
                self._key_drafts[prev] = typed

        self._sync_settings_key()
        self._set_smsg(note, VIO_GLOW if note else MUTED)
        self.save_btn.config(text=R("حفظ"))

    def _set_smsg(self, text, color=MUTED):
        if getattr(self, "smsg", None) and self.smsg.winfo_exists():
            self.smsg.config(text=R(text) if text else "", fg=color)

    def _save(self):
        pid = self._settings_pid()
        key = self.skey_var.get().strip().strip('"').strip("'")
        self._key_drafts[pid] = key

        old_key = providers.read_keys(core.ENV_PATH).get(pid, "")
        old_pid = self.cfg.get("provider")
        need_check = key and (key != old_key or pid != old_pid)

        if not key:
            self._set_smsg(f"محطّتش مفتاح لـ{providers.meta(pid)['name']} — "
                           "من غيره مش هيعرف يفرّغ كلامك.", AMBER)
            return

        if not need_check:
            self._apply(pid, key, verified=False)
            return

        self.save_btn.config(text=R("بتأكد من المفتاح…"), state="disabled")
        self._set_smsg("")

        def work():
            ok, err = providers.verify(pid, key)
            self.after(0, lambda: done(ok, err))

        def done(ok, err):
            self.save_btn.config(state="normal")
            if ok:
                self._apply(pid, key, verified=True)
            else:
                self.save_btn.config(text=R("حفظ"))
                self._set_smsg(err + " — متحفظش لحد ما يظبط.", RED)

        threading.Thread(target=work, daemon=True).start()

    def _apply(self, pid, key, verified):

        """الحفظ الفعلي + التطبيق على طول من غير إعادة تشغيل."""
        providers.write_key(core.ENV_PATH, pid, key)

        old_keys = (self.cfg.get("hotkey_normal"), self.cfg.get("hotkey_prompt"), self.cfg.get("hotkey_translate"))
        self.cfg["provider"]         = pid
        self.cfg["hotkey_normal"]    = HK_KEY.get(self.hk_norm_var.get(), self.hk_norm_var.get())
        self.cfg["hotkey_prompt"]    = HK_KEY.get(self.hk_prmt_var.get(), self.hk_prmt_var.get())
        self.cfg["hotkey_translate"] = HK_KEY.get(self.hk_trns_var.get(), self.hk_trns_var.get())
        self.cfg["hotkey"]           = self.cfg["hotkey_normal"]
        self.cfg["polish"]           = bool(self.polish_var.get())
        self.cfg["prompt_mode"]      = bool(self.prompt_var.get())
        self.cfg["auto_paste"]       = bool(self.paste_var.get())
        self.cfg["minimize_to_tray"] = bool(self.tray_var.get())
        self.cfg["check_updates"]    = bool(self.upd_var.get())
        self.cfg["floating_button"]  = bool(self.float_var.get())
        core.save_config(self.cfg)
        self._wave_apply_setting()

        new_keys = (self.cfg.get("hotkey_normal"), self.cfg.get("hotkey_prompt"), self.cfg.get("hotkey_translate"))
        if self.engine:
            self.engine.reset_client()                   # المزوّد/المفتاح
            if new_keys != old_keys:
                self.engine.restart_hotkey()             # الأزرار الثلاثة — لايف

        self._render_provider(); self._render_mode(); self._set_hint()

        name = providers.meta(pid)["name"]
        self._set_smsg(f"اتحفظ ✓ — شغّال دلوقتي على {name}"
                       + (" والمفتاح اتجرّب وردّ تمام." if verified else "."), GREEN)
        self.save_btn.config(text=R("اتحفظ ✓"))
        self.after(2500, lambda: self.save_btn.winfo_exists()
                                 and self.save_btn.config(text=R("حفظ")))

    # ── الدايرة ──
    def _circle(self, color, level=0.0):
        c = self.canvas
        c.delete("all")
        cx = cy = 102
        # حلقة خارجية بتكبر مع الصوت وقت التسجيل
        rr = 88 + level * 12
        c.create_oval(cx - rr, cy - rr, cx + rr, cy + rr,
                      outline=VIO_GLOW if level > .04 else VIO_DK,
                      width=3 + level * 4)
        c.create_oval(cx - 66, cy - 66, cx + 66, cy + 66, fill=color, outline="")
        s, bw = 74, 74 * .30
        x0, x1 = cx - bw / 2, cx + bw / 2
        top, bot, r = cy - s * .38, cy + s * .06, bw / 2
        w = max(3, int(s * .07))
        c.create_oval(x0, top, x1, top + 2 * r, fill="white", outline="")
        c.create_oval(x0, bot - 2 * r, x1, bot, fill="white", outline="")
        c.create_rectangle(x0, top + r, x1, bot - r, fill="white", outline="")
        c.create_arc(cx - s * .24, cy - s * .20, cx + s * .24, cy + s * .22,
                     start=200, extent=140, style="arc", outline="white", width=w)
        c.create_line(cx, cy + s * .22, cx, cy + s * .36, fill="white", width=w)
        c.create_line(cx - s * .14, cy + s * .38, cx + s * .14, cy + s * .38,
                      fill="white", width=w)

    def _pulse(self):
        if not self._pulse_on:
            return
        lvl = 0.0
        try:
            lvl = self.engine.rec.level
        except Exception:
            pass
        self._circle(RED, lvl)
        self.after(70, self._pulse)

    # ── الموجة العائمة فوق كل البرامج (تظهر وقت التسجيل وتختفي تلقائياً) ──
    def _wave_get_or_create(self):
        # لو الشباك اتمسح لأي سبب، نعمله من جديد بدل ما الموجة تختفي للأبد
        if self.wave is not None and not self._wave_alive():
            core.log_error(RuntimeError("الموجة العائمة كانت ممسوحة — اتعملت من جديد"), "overlay/recreate")
            self.wave = None
        if self.wave is None:
            self.wave = WaveOverlay(self, on_click=self._toggle_record,
                                    on_menu=self._tray_show,
                                    on_cancel=self._cancel_record)
        return self.wave

    def _wave_alive(self):
        try:
            return bool(self.wave.winfo_exists())
        except Exception:
            return False

    def _wave_apply_setting(self):
        """بعد تغيير إعداد الزرار العائم: يظهر/يختفي فورًا (من غير ما نقطع تسجيل شغّال)."""
        if not self.engine:
            return
        if self.wave is None and not WaveOverlay.enabled():
            return
        w = self._wave_get_or_create()
        if w._state in ("idle", "ready"):
            w.hide()

    def _wave_show(self, mode="normal"):
        w = self._wave_get_or_create()
        w.set_state("rec", mode=mode)

    def _wave_hide(self):
        if self.wave is not None and self._wave_alive():
            self.wave.hide()

    def _wave_sync(self):
        # Auto-hide: لا نظهر الـ Pill عند الـ sync العادي ليبقى مخفياً حتى يبدأ التسجيل
        pass

    def _on_map(self, e):
        pass

    def _on_unmap(self, e):
        pass

    def set_state(self, st, msg=None, mode=None):
        self.after(0, lambda: self._set_state(st, msg, mode))

    def _set_state(self, st, msg=None, mode=None):
        color, txt = STATE.get(st, (MUTED, st))
        # core بيبعت الوضع (normal/prompt/translate) مكان الرسالة
        if msg in WaveOverlay.MODE_COLORS:
            mode, msg = msg, None
        if msg:
            txt = msg
        self.status.config(text=R(txt), fg=RED if st == "err" else FG)
        self._ui_state = st
        if st == "ready" and WaveOverlay.enabled():
            self._wave_get_or_create()           # الزرار العائم يبان أول ما المحرك يجهز
        if st == "rec":
            self._pulse_on = True
            self._pulse()
            w = self._wave_get_or_create()
            w.set_state("rec", mode=mode or "normal")
        else:
            self._pulse_on = False
            self._circle(color)
            if self.wave is not None and self._wave_alive():
                self.wave.set_state(st, mode=mode)
        if st == "done":
            # لو بدأ تسجيل جديد قبل ما الـ1.5 ثانية تخلص، مانرجّعش "جاهز" فوقه
            self.after(1500, lambda: self._ui_state == "done" and self._set_state("ready", None))

    def show_text(self, t):
        self.after(0, lambda: self._set_text(t))

    def _set_text(self, t):
        self.last_text = t
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", R(t))
        self.text.tag_add("rtl", "1.0", "end")
        self.text.config(state="disabled")

    def _copy(self):
        t = (self.last_text or "").strip()
        if not t or t == "…":
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(t)
            self.update_idletasks()
        except Exception:
            return
        self.copy_btn.config(text=R("اتنسخ ✓"), fg=GREEN)
        self.after(1500, lambda: self.copy_btn.config(text=R("نسخ"), fg=MUTED))

    def _render_provider(self):
        m = providers.meta(self.cfg.get("provider"))
        self.prov_lbl.config(text=R("عن طريق " + m["name"]))

    def _render_mode(self):
        if self.cfg.get("prompt_mode"):
            self.mode_lbl.pack(side="left", padx=(8, 0))
        else:
            self.mode_lbl.pack_forget()

    def _set_hint(self):
        hn = HK_LABEL.get(self.cfg.get("hotkey_normal", self.cfg.get("hotkey", "ctrl_r")), "Ctrl يمين")
        hp = HK_LABEL.get(self.cfg.get("hotkey_prompt", "alt_r"), "Alt يمين")
        ht = HK_LABEL.get(self.cfg.get("hotkey_translate", "shift_r"), "Shift يمين")
        self.hint.config(text=R(f"عادي: {hn} · برومبت: {hp} · ترجمة: {ht}"))

    def _toggle_record(self):
        if not self.engine:
            return
        self.engine.end() if self.engine.recording else self.engine.begin(mode="normal")

    def _cancel_record(self):
        if not self.engine:
            return
        if hasattr(self.engine, "cancel"):
            self.engine.cancel()
        self._wave_hide()

    # ── المحرّك ──
    def _start_engine(self):
        def boot():
            try:
                app = core.App()
                app.on_state = self.set_state
                app.on_text  = self.show_text
                app.on_unplaced = lambda t: self.after(0, lambda: ResultToast.show_for(self, t))
                self.engine = app
                app.start_hotkey()
                self.after(0, lambda: (self._set_state("ready", None), self._set_hint()))
            except Exception as e:
                s = str(e).lower()
                msg = ("مفيش ميكروفون متوصّل" if "device" in s or "portaudio" in s
                       else "الميكروفون مش شغّال")
                self.after(0, lambda: self._set_state("err", msg))
        threading.Thread(target=boot, daemon=True).start()

    # ── أيقونة جنب الساعة ──
    def _start_tray(self):
        try:
            import pystray
            from PIL import Image
            img = Image.open(core.asset("emlaa.png"))
            menu = pystray.Menu(
                pystray.MenuItem("فتح إملاء", self._tray_show, default=True),
                pystray.MenuItem("سجل التسجيلات", lambda: self.after(0, self._open_history)),
                pystray.MenuItem("الإعدادات", lambda: self.after(0, self._open_settings)),
                pystray.MenuItem("تسجيل / إيقاف", self._tray_rec),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("خروج", self._tray_quit),
            )
            self.tray = pystray.Icon("emlaa", img, "إملاء — صوت إلى نص عربي", menu)
            self.tray.run()
        except Exception as e:
            # من غير أيقونة التراي، قفل النافذة بيقفل البرنامج كله — لازم يتسجّل
            core.log_error(e, "tray/start")
            self.tray = None

    # ── فيه نسخة جديدة؟ ──
    def _check_update(self):
        """
        بيسأل سيرفرنا عن آخر إصدار في ثريد جانبي — عشان لو النت بطيء
        البرنامج ما يستناش. أي فشل بيعدّي في صمت.
        """
        if not self.cfg.get("check_updates", True):
            return

        def work():
            info = core.check_update(APP_VERSION)
            if info:
                self.after(0, lambda: self._show_update(info))

        threading.Thread(target=work, daemon=True).start()

    def _show_update(self, info):
        """شريط صغير فوق — مش نافذة بتقطع على المستخدم."""
        if getattr(self, "_upd_bar", None) or not hasattr(self, "status"):
            return
        bar = tk.Frame(self, bg=VIO_DK, cursor="hand2")
        txt = (f"فيه نسخة جديدة ({info['version']}) — نزّلها"
               + (f" · {info['notes']}" if info.get("notes") else ""))
        tk.Label(bar, text=R("⬆  " + txt), bg=VIO_DK, fg="white",
                 font=(FONT, 9, "bold"), cursor="hand2",
                 wraplength=410, justify="right").pack(pady=7, padx=12)
        for w in [bar] + list(bar.winfo_children()):
            w.bind("<Button-1>", lambda e, u=info["url"]: open_link(u))
        bar.pack(fill="x", before=self.winfo_children()[0])
        self._upd_bar = bar
        self._fit(452)

    def _watch_show_request(self):
        """
        لو المستخدم دوس على الـexe تاني وهو شغّال، النسخة التانية بتقفل نفسها
        وتسيب علامة — وإحنا بنفتح النافذة بدل ما يفتكر إن البرنامج مش راضي يشتغل.
        """
        try:
            if os.path.exists(core.SHOW_PATH):
                os.remove(core.SHOW_PATH)
                self._tray_show()
        except Exception:
            pass
        self.after(1200, self._watch_show_request)

    def _tray_show(self, *a):
        self.after(0, lambda: (self.deiconify(), self.lift(), self.focus_force()))

    def _tray_rec(self, *a):
        self.after(0, self._toggle_record)

    def _tray_quit(self, *a):
        self.after(0, self._quit)

    def _on_close(self):
        if self.cfg.get("minimize_to_tray", True) and self.tray:
            self.withdraw()
        else:
            self._quit()

    def _quit(self):
        self._quitting = True
        try:
            if self.tray:
                self.tray.stop()
        except Exception:
            pass
        try:
            if self.engine:
                self.engine.shutdown()
        except Exception:
            pass
        self.destroy()


def _log_crash(exc):
    """
    في وضع الـexe مفيش نافذة سوداء تعرض الأخطاء — فبنكتبها في ملف جنب البرنامج
    ونعرض رسالة للمستخدم بدل ما البرنامج يختفي من غير سبب.
    """
    import traceback, datetime
    p = "?"
    try:
        p = os.path.join(core.BASE, "emlaa-error.log")
        with open(p, "a", encoding="utf-8") as f:
            f.write(chr(10) + "=" * 60 + chr(10))
            f.write(str(datetime.datetime.now()) + chr(10))
            f.write("".join(traceback.format_exception(exc)))
    except Exception:
        pass
    try:
        from tkinter import messagebox
        messagebox.showerror("Emlaa", "البرنامج مقدرش يفتح." + chr(10) * 2 +
                             "التفاصيل اتسجّلت في:" + chr(10) + str(p))
    except Exception:
        pass


if __name__ == "__main__":
    if not core.single_instance():
        # إملاء شغّال بالفعل — نفتح نافذته ونخرج بدل ما نبقى نسختين
        core.request_show()
        raise SystemExit(0)
    # الواجهة الجديدة (HTML جوّه نافذة ويندوز). لو WebView2 / pywebview مش موجودين
    # بنرجع للواجهة القديمة بدل ما البرنامج ما يفتحش خالص.
    web_err = None
    if "--classic" not in sys.argv:
        try:
            import app_web
            app_web.run(APP_VERSION, BRAND_NAME, BRAND_URL, HOTKEYS)
            raise SystemExit(0)
        except SystemExit:
            raise
        except Exception as e:
            web_err = e
            core.log_error(e, "ui/web-start (رجعنا للواجهة القديمة)")
    try:
        EmlaaClassic().mainloop()
    except Exception as e:
        _log_crash(e)
        raise SystemExit(1)
