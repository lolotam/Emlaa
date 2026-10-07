# -*- coding: utf-8 -*-
"""
اختبارات مفضلة الحافظة: النسخة المفضّلة مش بتتمسح أبدًا — لا بالمسح ولا بالمسح الجماعي
ولا بـ«امسح الكل» ولا بالقص التلقائي (CLIP_CAP) — وبتفضل مفضّلة لو نفس النص اتنسخ تاني.
كل الاختبارات على clipboard.json مؤقت، مش ملف المستخدم.
"""
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

# source مش حزمة (مفيش __init__.py)، فبنضيفه للمسار عشان الاستيراد يشتغل من جذر الـrepo
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import core     # noqa: E402
import app_web  # noqa: E402


class _Base(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = mock.patch.object(core, "CLIP_PATH", os.path.join(tmp.name, "clipboard.json"))
        p.start()
        self.addCleanup(p.stop)

    def _seed(self, *texts):
        # clip_add بيحط الجديد فوق ورقم النسخة من الوقت بالملّي ثانية — بنستنى ملّي
        # ثانيتين بين كل نسخة عشان الأرقام متتكررش. بنرجّع الأرقام بنفس ترتيب texts
        for t in reversed(texts):
            core.clip_add(t, "app.exe")
            time.sleep(0.002)
        ids = {e["text"]: e["id"] for e in core.clip_get()}
        return [ids[t] for t in texts]

    def _texts(self):
        return [i["text"] for i in core.clip_get()]


class TestClipFavorites(_Base):

    def test_set_and_unset_fav(self):
        a, = self._seed("a")
        self.assertTrue(core.clip_set_fav(a, True))
        self.assertTrue(core.clip_get()[0]["fav"])
        self.assertTrue(core.clip_set_fav(a, False))
        self.assertNotIn("fav", core.clip_get()[0])

    def test_set_fav_unknown_id(self):
        self._seed("a")
        self.assertFalse(core.clip_set_fav(123, True))

    def test_delete_skips_favorites(self):
        a, b = self._seed("a", "b")
        core.clip_set_fav(a, True)
        core.clip_delete([a, b])
        self.assertEqual(self._texts(), ["a"])

    def test_clear_keeps_favorites(self):
        a, b, c = self._seed("a", "b", "c")
        core.clip_set_fav(b, True)
        core.clip_clear()
        self.assertEqual(self._texts(), ["b"])

    def test_copying_a_favorite_again_keeps_it_favorite(self):
        a, b = self._seed("a", "b")
        core.clip_set_fav(b, True)
        e = core.clip_add("b", "other.exe")
        self.assertTrue(e["fav"])
        items = core.clip_get()
        self.assertEqual([i["text"] for i in items], ["b", "a"])
        self.assertTrue(items[0]["fav"])

    def test_cap_never_drops_favorites(self):
        with mock.patch.object(core, "CLIP_CAP", 3):
            a, = self._seed("old-fav")
            core.clip_set_fav(a, True)
            for t in ("n1", "n2", "n3", "n4", "n5"):
                core.clip_add(t)
                time.sleep(0.002)
            texts = self._texts()
        # المفضلة القديمة فضلت، والعادية اتقصّت لـ CLIP_CAP - عدد المفضلة
        self.assertIn("old-fav", texts)
        self.assertEqual(texts, ["n5", "n4", "old-fav"])

    def test_cap_with_more_favorites_than_cap_keeps_all_favorites(self):
        for i in self._seed("f1", "f2"):
            core.clip_set_fav(i, True)
        with mock.patch.object(core, "CLIP_CAP", 1):
            core.clip_add("n1")
            self.assertEqual(sorted(self._texts()), ["f1", "f2"])


class TestClipFavApi(_Base):

    def _api(self):
        class _Ctrl:
            pass
        return app_web.Api(_Ctrl())

    def test_clips_fav_returns_items(self):
        a, = self._seed("a")
        r = self._api().clips_fav(a, True)
        self.assertTrue(r["ok"])
        self.assertTrue(r["items"][0]["fav"])

    def test_clips_fav_rejects_bad_id(self):
        self._seed("a")
        api = self._api()
        self.assertFalse(api.clips_fav("x", True)["ok"])
        self.assertFalse(api.clips_fav(True, True)["ok"])
        self.assertFalse(api.clips_fav(999, True)["ok"])

    def test_clips_clear_returns_the_kept_favorites(self):
        a, b = self._seed("a", "b")
        core.clip_set_fav(a, True)
        items = self._api().clips_clear()
        self.assertEqual([i["text"] for i in items], ["a"])


if __name__ == "__main__":
    unittest.main()
