# -*- coding: utf-8 -*-
"""
اختبار عزل F3 — بيمنع الاختبارات إنها تلمس ملفات المستخدم الحقيقية.

مشكلة: الاختبارات دي كانت بتعدّي على الـhistory.json والـrecordings الحقيقيين
(واحدة منها مسحت ملفات صوت فعلًا). مش قادرين نفحص الإعداد على مستوى الموديول لكل
اختبار تاني من هنا مباشرة، فبنعمل فحص انحدار: بنشغّل التلات اختبارات المعروفة
in-process والمؤشرات (HISTORY_PATH / RECORDINGS_DIR) على ملفات سينتيل مؤقتة،
وبعدين نتأكد إن ملفات السينتيل لسه بايت-بايت زي ما هي — لو أي اختبار رجع يلمس
الملفات الحقيقية (نسي الترقيعة) هيتغيّر السينتيل والاختبار ده يفشل.
"""
import io
import os
import sys
import tempfile
import unittest
from unittest import mock

# source مش حزمة (مفيش __init__.py)، فبنضيفه للمسار عشان الاستيراد يشتغل من جذر الـrepo
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

# بنضيف فولدر tests نفسه للمسار عشان loadTestsFromName("unit_process...") يلاقي
# الموديولات بالاسم — بيشتغل تحت discover (اللي بيضيف tests) أو أي استدعاء تاني.
_tests_dir = os.path.dirname(os.path.abspath(__file__))
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

import core  # noqa: E402


def _read_bytes(path):
    """قراية بايتات ملف من غير ما نسيب مقبض مفتوح (ResourceWarning)."""
    with open(path, "rb") as f:
        return f.read()


# التلات اختبارات اللي كانت بتوصل لملفات المستخدم الحقيقية (قبل الإصلاح).
_TARGETS = (
    "unit_process.TestHistoryBypassFlag.test_bypass_key_stored_only_when_true",
    "unit_edit.TestSaveSettingsHotkey.test_duplicate_hotkey_rejected",
    "unit_edit.TestSaveSettingsHotkey.test_edit_hotkey_can_be_off_without_conflict",
)


class TestUserFilesUntouched(unittest.TestCase):
    def test_target_tests_leave_sentinel_history_and_recordings_intact(self):
        with tempfile.TemporaryDirectory() as d:
            hist = os.path.join(d, "history.json")
            recs = os.path.join(d, "recordings")
            os.makedirs(recs)
            # سينتيل «حقيقي»: ١٢ عنصر (أكتر من حد الـ١٠ — أي history_prune هيعيد كتابته)
            # وتسجيل يتيم مش في السجل (أي recordings_prune هيمسحه). سينتيل نضيف كان
            # بيعدّي حتى لو الاختبار بيشغّل التنضيف الحقيقي — زي اللي مسح ملفات المستخدم.
            with open(hist, "w", encoding="utf-8") as f:
                f.write("[" + ", ".join('{"id": %d, "result": "sentinel-%d"}' % (i, i)
                                        for i in range(12, 0, -1)) + "]")
            rec_file = os.path.join(recs, "999.mp3")
            with open(rec_file, "wb") as f:
                f.write(b"SENTINEL-RECORDING-BYTES")

            hist_before = _read_bytes(hist)
            rec_before = _read_bytes(rec_file)

            loader = unittest.TestLoader()
            suite = unittest.TestSuite()
            for name in _TARGETS:
                suite.addTest(loader.loadTestsFromName(name))

            with mock.patch.object(core, "HISTORY_PATH", hist), \
                    mock.patch.object(core, "RECORDINGS_DIR", recs):
                result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)

            self.assertTrue(result.wasSuccessful(), "التلات اختبارات لازم ينجحوا جوّه فحص العزل")
            self.assertEqual(_read_bytes(hist), hist_before,
                             "اختبار لمس history السينتيل — راجع ترقيع HISTORY_PATH")
            self.assertEqual(os.listdir(recs), ["999.mp3"],
                             "اختبار مسح تسجيلات من recordings السينتيل — راجع ترقيع RECORDINGS_DIR/history_prune")
            self.assertEqual(_read_bytes(rec_file), rec_before,
                             "اختبار لمس recordings السينتيل — راجع ترقيع RECORDINGS_DIR/history_prune")


if __name__ == "__main__":
    unittest.main()
