# -*- coding: utf-8 -*-
import http.client
import os
import tempfile
import threading
import unittest
import urllib.error
from unittest import mock

import tkinter as tk

import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import app_web  # noqa: E402
import backup  # noqa: E402
import core  # noqa: E402
import drive_backup  # noqa: E402
import emlaa  # noqa: E402
import google_auth  # noqa: E402


def _plain(text):
    return str(text).replace("\u202b", "").replace("\u202c", "")


def _buttons(widget):
    found = []
    for child in widget.winfo_children():
        if isinstance(child, tk.Button):
            found.append(child)
        found.extend(_buttons(child))
    return found


def _live_app():
    app = mock.Mock(recording=False, busy=False, capturing=False, backing_up=False)
    app._state_lock = threading.Lock()
    return app


class WebSurfaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = self.tmp.name
        self.patches = [
            mock.patch.object(core, "BASE", self.base),
            mock.patch.object(backup, "reload_app", return_value={}),
        ]
        for patch in self.patches:
            patch.start()
        self.ctrl = mock.Mock()
        self.ctrl.engine = None
        self.ctrl.window = mock.Mock()
        self.ctrl.start_engine = mock.Mock()
        self.api = app_web.Api(self.ctrl)

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self.tmp.cleanup()

    def _selected(self, payload=b"zip"):
        path = os.path.join(self.base, "in.zip")
        with open(path, "wb") as handle:
            handle.write(payload)
        self.ctrl.window.create_file_dialog.return_value = path
        return path

    def test_restore_starts_engine_when_boot_can_run(self):
        self._selected()
        with mock.patch.object(backup, "restore_snapshot") as restore, \
             mock.patch.object(self.api, "bootstrap", return_value={"canRun": True}):
            result = self.api.backup_import()
        self.assertTrue(result["ok"])
        self.assertTrue(result["boot"]["canRun"])
        restore.assert_called_once()
        self.ctrl.start_engine.assert_called_once()

    def test_restore_skips_engine_when_boot_cannot_run(self):
        self._selected()
        with mock.patch.object(backup, "restore_snapshot"), \
             mock.patch.object(self.api, "bootstrap", return_value={"canRun": False}):
            result = self.api.backup_import()
        self.assertTrue(result["ok"])
        self.ctrl.start_engine.assert_not_called()

    def test_restore_restarts_hotkey_on_the_live_app(self):
        app = _live_app()
        self.ctrl.engine = app
        self._selected()
        with mock.patch.object(backup, "restore_snapshot"), \
             mock.patch.object(self.api, "bootstrap", return_value={"canRun": True}):
            self.api.backup_import()
        app.restart_hotkey.assert_called_once()
        self.ctrl.start_engine.assert_called_once()

    def test_drive_restore_starts_engine_with_injected_client_id(self):
        with open(google_auth.__file__, encoding="utf-8") as handle:
            self.assertIn('GOOGLE_CLIENT_ID = ""', handle.read())
        with mock.patch.object(google_auth, "GOOGLE_CLIENT_ID", "fake-client"), \
             mock.patch.object(google_auth, "access_token", return_value="tok"), \
             mock.patch.object(drive_backup, "restore"), \
             mock.patch.object(self.api, "bootstrap", return_value={"canRun": True}), \
             mock.patch("urllib.request.urlopen", side_effect=AssertionError("socket")):
            result = self.api.drive_restore()
        self.assertTrue(result["ok"])
        self.ctrl.start_engine.assert_called_once()
        self.assertEqual(google_auth.GOOGLE_CLIENT_ID, "")

    def test_empty_client_drive_does_not_open_a_socket_or_start_the_engine(self):
        self.assertEqual(google_auth.GOOGLE_CLIENT_ID, "")
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("socket")), \
             mock.patch.object(drive_backup, "restore", side_effect=AssertionError("drive")), \
             mock.patch.object(drive_backup, "upload", side_effect=AssertionError("drive")):
            restore = self.api.drive_restore()
            upload = self.api.drive_backup()
            sign_in = self.api.google_sign_in()
        self.assertFalse(restore["ok"])
        self.assertFalse(upload["ok"])
        self.assertFalse(sign_in["ok"])
        self.ctrl.start_engine.assert_not_called()

    def test_transport_failure_returns_unreadable_and_reauth_stays_reauth(self):
        with mock.patch.object(google_auth, "GOOGLE_CLIENT_ID", "fake-client"), \
             mock.patch.object(google_auth, "access_token", side_effect=urllib.error.URLError("down")), \
             mock.patch("urllib.request.urlopen", side_effect=AssertionError("socket")):
            failed = self.api.drive_backup()
        self.assertEqual(failed["err"], backup.message_for("unreadable"))
        with mock.patch.object(google_auth, "GOOGLE_CLIENT_ID", "fake-client"), \
             mock.patch.object(google_auth, "access_token", side_effect=backup.BackupError("reauth")):
            again = self.api.drive_backup()
        self.assertEqual(again["err"], backup.message_for("reauth"))
        with mock.patch.object(google_auth, "GOOGLE_CLIENT_ID", "fake-client"), \
             mock.patch.object(google_auth, "access_token", side_effect=http.client.IncompleteRead(b"x")):
            cut = self.api.drive_backup()
        self.assertEqual(cut["err"], backup.message_for("unreadable"))

    def test_export_failure_keeps_the_previous_zip(self):
        dest = os.path.join(self.base, "emlaa-backup.zip")
        with open(dest, "wb") as handle:
            handle.write(b"previous")
        self.ctrl.window.create_file_dialog.return_value = dest
        with mock.patch.object(backup, "export_snapshot", return_value=b"new-zip"), \
             mock.patch.object(os, "fsync", side_effect=OSError("full")):
            result = self.api.backup_export()
        self.assertEqual(result["err"], backup.message_for("unreadable"))
        with open(dest, "rb") as handle:
            self.assertEqual(handle.read(), b"previous")
        self.assertFalse(any(name.endswith(".part") for name in os.listdir(self.base)))

    def test_export_replaces_the_previous_zip_only_after_the_write(self):
        dest = os.path.join(self.base, "emlaa-backup.zip")
        with open(dest, "wb") as handle:
            handle.write(b"previous")
        self.ctrl.window.create_file_dialog.return_value = dest
        with mock.patch.object(backup, "export_snapshot", return_value=b"new-zip"):
            result = self.api.backup_export()
        self.assertTrue(result["ok"])
        with open(dest, "rb") as handle:
            self.assertEqual(handle.read(), b"new-zip")

    def test_oversized_import_returns_the_damaged_sentence_without_restore(self):
        path = os.path.join(self.base, "big.zip")
        with open(path, "wb") as handle:
            handle.write(b"x" * 20)
        self.ctrl.window.create_file_dialog.return_value = path
        with mock.patch.object(google_auth, "BACKUP_READ_CAP", 8), \
             mock.patch.object(backup, "restore_snapshot", side_effect=AssertionError("restore")):
            result = self.api.backup_import()
        self.assertEqual(result["err"], backup.MESSAGES["damaged"])
        self.ctrl.start_engine.assert_not_called()

    def test_file_within_the_cap_still_reaches_restore(self):
        path = os.path.join(self.base, "small.zip")
        with open(path, "wb") as handle:
            handle.write(b"x" * 8)
        self.ctrl.window.create_file_dialog.return_value = path
        with mock.patch.object(google_auth, "BACKUP_READ_CAP", 8), \
             mock.patch.object(backup, "restore_snapshot") as restore, \
             mock.patch.object(self.api, "bootstrap", return_value={"canRun": False}):
            result = self.api.backup_import()
        self.assertTrue(result["ok"])
        restore.assert_called_once()


class ClassicSurfaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.ui = emlaa.EmlaaClassic.__new__(emlaa.EmlaaClassic)
        self.ui.engine = None
        self.ui.cfg = {"polish": True, "provider": "groq"}
        self.ui._dlg = None
        self.ui._start_engine = mock.Mock(side_effect=AssertionError("recording"))
        self.parent = tk.Frame(self.root)
        self.ui._backup_section(self.parent)
        self.ui._mb = mock.Mock()
        self.ui._fd = mock.Mock()
        self.opened = []
        self.destroyed = []
        self.ui._open_settings = lambda: self.opened.append(dict(self.ui.cfg))

    def _prepare_dialog(self):
        destroyed = self.destroyed

        class Dialog:
            def destroy(self):
                destroyed.append(True)

        self.ui._dlg = Dialog()

    def test_sign_out_control_calls_sign_out_and_not_drive(self):
        self.assertEqual(google_auth.GOOGLE_CLIENT_ID, "")
        button = next(b for b in _buttons(self.parent) if _plain(b.cget("text")) == "تسجيل الخروج")
        with mock.patch.object(core, "BASE", self.tmp.name), \
             mock.patch("urllib.request.urlopen", side_effect=AssertionError("socket")), \
             mock.patch.object(drive_backup, "upload", side_effect=AssertionError("drive")), \
             mock.patch.object(drive_backup, "restore", side_effect=AssertionError("drive")):
            google_auth.write_state(self.tmp.name, {"refreshToken": "secret-refresh", "account": {"email": "a@b.c"}})
            button.invoke()
        self.assertFalse(os.path.exists(google_auth.state_path(self.tmp.name)))
        self.ui._start_engine.assert_not_called()

    def test_import_rebuilds_settings_from_the_reloaded_cfg(self):
        path = os.path.join(self.tmp.name, "in.zip")
        with open(path, "wb") as handle:
            handle.write(b"zip")
        self.ui._mb.askyesno.return_value = True
        self.ui._fd.askopenfilename.return_value = path
        self.ui.polish_var = mock.Mock()
        self.ui.polish_var.get.return_value = True
        self._prepare_dialog()
        with mock.patch.object(backup, "restore_snapshot"), \
             mock.patch.object(core, "load_config", return_value={"polish": False, "provider": "openai"}):
            self.ui._backup_import()
        self.assertEqual(self.destroyed, [True])
        self.assertEqual(self.opened, [{"polish": False, "provider": "openai"}])
        self.assertEqual(self.ui.cfg["polish"], False)
        self.ui._start_engine.assert_not_called()
        self.ui.polish_var.get.assert_not_called()

    def test_drive_restore_rebuilds_settings_too(self):
        self.ui._mb.askyesno.return_value = True
        self._prepare_dialog()
        with mock.patch.object(google_auth, "GOOGLE_CLIENT_ID", "fake-client"), \
             mock.patch.object(google_auth, "access_token", return_value="tok"), \
             mock.patch.object(drive_backup, "restore") as restore, \
             mock.patch.object(drive_backup, "upload", side_effect=AssertionError("drive")), \
             mock.patch("urllib.request.urlopen", side_effect=AssertionError("socket")), \
             mock.patch.object(core, "load_config", return_value={"polish": False}):
            self.ui._drive_restore()
        restore.assert_called_once()
        self.assertEqual(self.opened, [{"polish": False}])
        self.assertEqual(google_auth.GOOGLE_CLIENT_ID, "")
        self.ui._start_engine.assert_not_called()

    def test_failed_restore_keeps_the_open_settings_window(self):
        path = os.path.join(self.tmp.name, "big.zip")
        with open(path, "wb") as handle:
            handle.write(b"x" * 20)
        self.ui._mb.askyesno.return_value = True
        self.ui._fd.askopenfilename.return_value = path
        self._prepare_dialog()
        with mock.patch.object(google_auth, "BACKUP_READ_CAP", 8), \
             mock.patch.object(backup, "restore_snapshot", side_effect=AssertionError("restore")):
            self.ui._backup_import()
        self.assertEqual(self.destroyed, [])
        self.assertEqual(self.opened, [])
        self.assertEqual(self.ui._backup_msg.cget("text"), backup.MESSAGES["damaged"])

    def test_classic_transport_errors_stay_inside_the_handler(self):
        with mock.patch.object(google_auth, "GOOGLE_CLIENT_ID", "fake-client"), \
             mock.patch.object(google_auth, "access_token", side_effect=urllib.error.URLError("down")), \
             mock.patch("urllib.request.urlopen", side_effect=AssertionError("socket")):
            self.ui._drive_backup()
        self.assertEqual(self.ui._backup_msg.cget("text"), backup.message_for("unreadable"))
        with mock.patch.object(google_auth, "GOOGLE_CLIENT_ID", "fake-client"), \
             mock.patch.object(google_auth, "access_token", side_effect=backup.BackupError("reauth")):
            self.ui._drive_backup()
        self.assertEqual(self.ui._backup_msg.cget("text"), backup.message_for("reauth"))

    def test_classic_export_failure_keeps_the_previous_zip(self):
        dest = os.path.join(self.tmp.name, "emlaa-backup.zip")
        with open(dest, "wb") as handle:
            handle.write(b"previous")
        self.ui._fd.asksaveasfilename.return_value = dest
        with mock.patch.object(backup, "export_snapshot", return_value=b"new-zip"), \
             mock.patch.object(os, "fsync", side_effect=OSError("full")):
            self.ui._backup_export()
        self.assertEqual(self.ui._backup_msg.cget("text"), backup.message_for("unreadable"))
        with open(dest, "rb") as handle:
            self.assertEqual(handle.read(), b"previous")
        self.assertFalse(any(name.endswith(".part") for name in os.listdir(self.tmp.name)))

    def test_empty_client_classic_drive_does_not_open_a_socket(self):
        self.assertEqual(google_auth.GOOGLE_CLIENT_ID, "")
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("socket")):
            self.ui._drive_backup()
            self.ui._drive_restore()
            self.ui._google_sign_in()
        self.assertIn("مش متفعّل", self.ui._backup_msg.cget("text"))
        self.ui._mb.askyesno.assert_not_called()


class PrivacyCopyTests(unittest.TestCase):
    def test_readme_and_privacy_admit_the_drive_backup(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "README.md"), encoding="utf-8") as handle:
            readme = handle.read()
        with open(os.path.join(root, "PRIVACY.md"), encoding="utf-8") as handle:
            privacy = handle.read()
        self.assertNotIn("There are no accounts", privacy)
        self.assertNotIn("الاتصال الوحيد غير المزوّد", readme)
        self.assertIn("## Backup file and Google Drive", privacy)
        self.assertIn("Emlaa has no server on that path", privacy)
        self.assertIn("until a client id is configured", privacy)
        self.assertIn("keys, history, clipboard and recordings", privacy)
        self.assertIn("إملاء مالوش سيرفر", readme)
        self.assertIn("معرّف عميل جوجل", readme)
        self.assertIn("Emlaa has no server on that path", readme)
        self.assertIn("until a client id is configured", readme)
        self.assertIn("### نسخة احتياطية", readme)
