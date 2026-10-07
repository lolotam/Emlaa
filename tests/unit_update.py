# -*- coding: utf-8 -*-
"""
اختبارات إعادة التشغيل بعد التحديث: النسخة الجديدة لازم تتشغّل كنسخة مستقلة من PyInstaller
(مش «عملية فرعية» بتدوّر على python312.dll في فولدر _MEI بتاع النسخة القديمة اللي اتمسح).
"""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

# source مش حزمة (مفيش __init__.py)، فبنضيفه للمسار عشان الاستيراد يشتغل من جذر الـrepo
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import core  # noqa: E402

_PYI = {
    "_PYI_APPLICATION_HOME_DIR": r"E:\Dev\Temp\_MEI123456",
    "_PYI_ARCHIVE_FILE": r"E:\notk\Emlaa.exe",
    "_PYI_PARENT_PROCESS_LEVEL": "1",
    "_MEIPASS2": r"E:\Dev\Temp\_MEI123456",
}


class TestIndependentEnv(unittest.TestCase):

    def test_drops_pyinstaller_vars_and_sets_reset(self):
        with mock.patch.dict(os.environ, {**_PYI, "EMLAA_KEEP": "yes"}):
            env = core.independent_env()
        for k in _PYI:
            self.assertNotIn(k, env)
        self.assertEqual(env["PYINSTALLER_RESET_ENVIRONMENT"], "1")
        self.assertEqual(env["EMLAA_KEEP"], "yes")

    def test_drops_cert_paths_inside_the_old_bundle(self):
        # core بيحط SSL_CERT_FILE على certifi جوّه _MEI — الفولدر ده بيتمسح بعد ما القديمة تقفل
        with tempfile.TemporaryDirectory() as mei:
            cert = os.path.join(mei, "certifi", "cacert.pem")
            with mock.patch.object(sys, "_MEIPASS", mei, create=True), \
                    mock.patch.dict(os.environ, {"SSL_CERT_FILE": cert, "REQUESTS_CA_BUNDLE": cert}):
                env = core.independent_env()
        self.assertNotIn("SSL_CERT_FILE", env)
        self.assertNotIn("REQUESTS_CA_BUNDLE", env)

    def test_keeps_user_cert_paths_outside_the_bundle(self):
        with tempfile.TemporaryDirectory() as mei, tempfile.TemporaryDirectory() as other:
            user = os.path.join(other, "corp-ca.pem")
            # فولدر اسمه بيبدأ بنفس اسم _MEI مش جوّاه
            sibling = mei + "x" + os.sep + "cacert.pem"
            with mock.patch.object(sys, "_MEIPASS", mei, create=True), \
                    mock.patch.dict(os.environ, {"SSL_CERT_FILE": user, "REQUESTS_CA_BUNDLE": sibling}):
                env = core.independent_env()
        self.assertEqual(env["SSL_CERT_FILE"], user)
        self.assertEqual(env["REQUESTS_CA_BUNDLE"], sibling)

    def test_does_not_touch_the_current_process_env(self):
        with mock.patch.dict(os.environ, _PYI):
            core.independent_env()
            self.assertEqual(os.environ["_PYI_ARCHIVE_FILE"], _PYI["_PYI_ARCHIVE_FILE"])
            self.assertNotIn("PYINSTALLER_RESET_ENVIRONMENT", os.environ)


class TestInstallUpdateRestart(unittest.TestCase):

    def test_restart_runs_with_independent_env(self):
        with tempfile.TemporaryDirectory() as d:
            exe = os.path.join(d, "Emlaa.exe")
            new = exe + ".download"
            for path, data in ((exe, b"MZold"), (new, b"MZnew")):
                with open(path, "wb") as f:
                    f.write(data)
            with mock.patch.object(sys, "executable", exe), \
                    mock.patch.dict(os.environ, _PYI), \
                    mock.patch.object(subprocess, "Popen") as popen:
                core.install_update(new)
            with open(exe, "rb") as f:
                self.assertEqual(f.read(), b"MZnew")
            env = popen.call_args.kwargs["env"]
            self.assertEqual(env["PYINSTALLER_RESET_ENVIRONMENT"], "1")
            for k in _PYI:
                self.assertNotIn(k, env)


if __name__ == "__main__":
    unittest.main()
