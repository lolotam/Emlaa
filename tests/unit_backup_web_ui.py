# -*- coding: utf-8 -*-
"""
واجهة النسخة الاحتياطية في الإعدادات — قراية source/ui كنص.
مفيش شبكة ولا إعدادات حقيقية ولا متصفح: الاستعادة تملى الفورم، والحفظ متقفّل
طول ما الاستعادة شغّالة، والأزرار ترجع تشتغل، ورسالة الغلط تفضل ظاهرة.
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _function_body(src, name):
    """جسم الدالة من أول { لحد قفلها، بأقواس متداخلة."""
    match = re.search(r"function\s+%s\s*\(" % re.escape(name), src)
    if not match:
        raise AssertionError("الدالة %s مش موجودة" % name)
    start = src.find("{", match.end())
    depth = 0
    for index in range(start, len(src)):
        char = src[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return src[start:index + 1]
    raise AssertionError("الدالة %s مش متقفلة" % name)


class TestBackupWebUi(unittest.TestCase):
    """سلوك واجهة النسخة في app.js والترجمة في i18n.js."""

    @classmethod
    def setUpClass(cls):
        cls.js = _read(os.path.join("source", "ui", "app.js"))
        cls.i18n = _read(os.path.join("source", "ui", "i18n.js"))

    def test_successful_restore_refills_settings_from_the_returned_boot(self):
        body = _function_body(self.js, "applyRestoredBoot")
        guard = "if (!r || !r.boot || !(r.ok || !r.err)) return;"
        self.assertIn(guard, body)
        self.assertLess(body.index(guard), body.index("fillSettings()"))
        features = "S.features = JSON.parse(JSON.stringify(r.boot.features));"
        self.assertIn(features, body)
        self.assertLess(body.index(features), body.index("fillSettings()"))
        self.assertIn("applyBoot();", body)
        for call in ("backup_import", "drive_restore"):
            after = self.js.split("api().%s()" % call, 1)[1]
            handler = after.split("finally", 1)[0]
            self.assertIn("applyRestoredBoot(r);", handler)
            self.assertIn('$("#backupStatus").textContent = r.err;', handler)
            self.assertNotIn("fillSettings()", handler)

    def test_schedule_save_does_not_arm_a_timer_while_held(self):
        body = _function_body(self.js, "scheduleSave")
        hold = body.index("if (SAVE.hold) return;")
        arm = body.index("setTimeout(saveSettings")
        self.assertLess(hold, arm)
        self.assertNotIn("setTimeout", body[:hold])

    def test_backup_busy_reenables_local_buttons_and_toggles_sign_out(self):
        busy = _function_body(self.js, "backupBusy")
        self.assertIn(
            '["#backupExport", "#backupImport", "#googleSignIn", "#driveBackup", "#driveRestore", "#googleSignOut"]',
            busy)
        enable = '["#backupExport", "#backupImport", "#googleSignIn", "#googleSignOut"]'
        self.assertIn(enable, busy)
        self.assertNotIn("driveBackup", enable)
        self.assertNotIn("driveRestore", enable)
        self.assertLess(busy.index("finally"), busy.index("b.disabled = false"))
        self.assertLess(busy.index("b.disabled = false"), busy.index("paintBackup(status, keepLine)"))
        paint = _function_body(self.js, "paintBackup")
        self.assertIn('$("#googleSignOut").hidden = !signed;', paint)
        self.assertIn('$("#driveBackup").disabled = !driveOn;', paint)
        self.assertIn('$("#driveRestore").disabled = !driveOn;', paint)

    def test_operation_error_is_not_unconditionally_overwritten(self):
        busy = _function_body(self.js, "backupBusy")
        paint = _function_body(self.js, "paintBackup")
        self.assertIn('const keepLine = line.textContent !== "جاري…";', busy)
        self.assertIn("paintBackup(status, keepLine);", busy)
        self.assertLess(paint.index("if (keepLine) return;"), paint.index('$("#backupStatus")'))
        drive_line = paint.index('line.textContent = "فيه نسخة في Drive.";')
        self.assertGreater(drive_line, paint.index("if (keepLine) return;"))
        # تحديث الحالة عند الفتح لسه يستبدل السطر — الحفظ بس لغلط العملية الحالية
        self.assertIn("paintBackup(await api().backup_status());", self.js)

    def test_english_entries_for_the_rendered_backup_strings(self):
        for ar, en in (
            ("فيه نسخة في Drive.", "Drive has a backup."),
            ("استنى لحد ما التسجيل أو التفريغ يخلّص", "Wait until recording or transcription finishes"),
        ):
            self.assertIn('"%s": "%s"' % (ar, en), self.i18n, ar)
        paint = _function_body(self.js, "paintBackup")
        self.assertIn('line.textContent = "فيه نسخة في Drive.";', paint)
        self.assertNotIn("فيه نسخة في Drive من {time}.", paint)


if __name__ == "__main__":
    unittest.main()
