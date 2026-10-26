# -*- coding: utf-8 -*-
"""
نسخة الإعدادات — ملف zip واحد فيه الإعدادات والمفاتيح والسجل والحافظة والتسجيلات.

ليه ملف لوحده: الاستعادة لازم تبقى صفقة واحدة (يا تنجح كلها يا تسيب الجهاز زي ما هو)،
وملف المفاتيح بيتقرأ هنا قراءة صارمة لأن read_key_pools بيبلع أخطاء القراية،
والاستعادة بنسخة ناقصة كانت هتمسح مفاتيح لسه موجودة.
"""
import io
import json
import os
import re
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone

import core
import providers

FORMAT = "emlaa-backup"
VERSION = 1
REC_NAME = re.compile(r"^[0-9]+\.(mp3|wav|json)$")
MAX_MEMBERS = 5000
MAX_TOTAL = 2 * 1024 ** 3
MAX_ONE = 512 * 1024 ** 2

# الجملة اللي يشوفها المستخدم. too_large ملف بايظ من برّه، والكود الداخلي بس اللي بيفرّق.
MESSAGES = {
    "damaged": "الملف ده مش نسخة إملاء صالحة.",
    "newer": "النسخة دي معمولة بإصدار أحدث من إملاء.",
    "too_large": "الملف ده مش نسخة إملاء صالحة.",
    "busy": "استنى لحد ما التسجيل أو التفريغ يخلّص.",
    "unconfigured": "تسجيل الدخول بجوجل لسه مش متفعّل في النسخة دي.",
    "reauth": "جوجل محتاج تسجيل دخول تاني.",
    "no_drive_file": "لسه مفيش نسخة في Google Drive.",
    "unreadable": "معرفتش أقرأ ملفات النسخة — مفيش حاجة اتغيّرت.",
    "cancelled": "",
}


class BackupError(Exception):
    def __init__(self, code, detail=""):
        self.code = code
        super().__init__(detail or code)


def message_for(code):
    return MESSAGES.get(code, MESSAGES["damaged"])


def _fail(code):
    raise BackupError(code)


def _stamp(now):
    if isinstance(now, str):
        return now
    if isinstance(now, datetime):
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _fail("damaged")


def _check_keys(keys):
    if not isinstance(keys, dict):
        _fail("damaged")
    clean = {}
    for pid, pool in keys.items():
        if pid not in providers.PROVIDERS:
            _fail("damaged")
        if isinstance(pool, str) or not isinstance(pool, list):
            _fail("damaged")
        out = []
        for item in pool:
            if not isinstance(item, str) or not item.strip():
                _fail("damaged")
            out.append(item.strip())
        if out:
            clean[pid] = out
    return clean


def _check_recordings(names):
    if not isinstance(names, list) or any(not isinstance(n, str) for n in names):
        _fail("damaged")
    if names != sorted(names) or len(names) != len(set(names)):
        _fail("damaged")
    if any(REC_NAME.fullmatch(n) is None for n in names):
        _fail("damaged")
    return names


def build_zip(config, keys, history, clipboard, recordings, now):
    """recordings = {اسم الملف: bytes}. مفيش أعضاء غير manifest.json و recordings/<اسم>."""
    if not isinstance(config, dict) or not isinstance(history, list) or not isinstance(clipboard, list):
        _fail("damaged")
    if not isinstance(recordings, dict):
        _fail("damaged")
    keys = _check_keys(keys)
    names = sorted(recordings)
    _check_recordings(names)
    manifest = {
        "format": FORMAT,
        "version": VERSION,
        "exportedAt": _stamp(now),
        "config": config,
        "keys": keys,
        "history": history,
        "clipboard": clipboard,
        "recordings": names,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False).encode("utf-8"))
        for name in names:
            blob = recordings[name]
            if not isinstance(blob, (bytes, bytearray)):
                _fail("damaged")
            zf.writestr(f"recordings/{name}", bytes(blob))
    return buf.getvalue()


def _member_ok(name):
    if name.endswith("/") or "\\" in name or name.startswith("/") or ".." in name.split("/"):
        return False
    if name == "manifest.json":
        return True
    if not name.startswith("recordings/"):
        return False
    rest = name[len("recordings/"):]
    return "/" not in rest and REC_NAME.fullmatch(rest) is not None


def read_zip(data):
    if not isinstance(data, (bytes, bytearray)):
        _fail("damaged")
    try:
        zf = zipfile.ZipFile(io.BytesIO(bytes(data)))
    except zipfile.BadZipFile:
        _fail("damaged")
    infos = zf.infolist()
    if len(infos) > MAX_MEMBERS:
        _fail("too_large")
    total = 0
    seen = []
    for info in infos:
        if info.flag_bits & 0x1:
            _fail("damaged")
        if info.file_size > MAX_ONE:
            _fail("too_large")
        total += info.file_size
        if total > MAX_TOTAL:
            _fail("too_large")
        if not _member_ok(info.filename):
            _fail("damaged")
        seen.append(info.filename)
    if len(seen) != len(set(seen)) or "manifest.json" not in seen:
        _fail("damaged")
    try:
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, RuntimeError):
        _fail("damaged")
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        _fail("damaged")
    version = manifest.get("version", None)
    # bool فرع من int في بايثون — true مش إصدار 1
    if isinstance(version, bool) or not isinstance(version, int):
        _fail("damaged")
    if version > VERSION:
        _fail("newer")
    if version != VERSION:
        _fail("damaged")
    for field in ("exportedAt", "config", "keys", "history", "clipboard", "recordings"):
        if field not in manifest:
            _fail("damaged")
    if not isinstance(manifest["exportedAt"], str):
        _fail("damaged")
    if not isinstance(manifest["config"], dict):
        _fail("damaged")
    if not isinstance(manifest["history"], list) or not isinstance(manifest["clipboard"], list):
        _fail("damaged")
    keys = _check_keys(manifest["keys"])
    names = _check_recordings(manifest["recordings"])
    files = {}
    for name in seen:
        if name == "manifest.json":
            continue
        files[name[len("recordings/"):]] = zf.read(name)
    if set(files) != set(names):
        _fail("damaged")
    return {
        "exportedAt": manifest["exportedAt"],
        "config": manifest["config"],
        "keys": keys,
        "history": manifest["history"],
        "clipboard": manifest["clipboard"],
        "recordings": names,
        "files": files,
    }


def _locked():
    """ترتيب الأقفال: النسخة، وبعدين السجل، وبعدين الحافظة. قفل المفاتيح بيتاخد قبلهم عند الكتابة."""
    return core._backup_lock, core._store_lock, core._clip_lock


def _read_json_file(path, expect):
    """ملف ناقص = قيمة فاضية. ملف موجود ومتقراش = غلط، مش نسخة ناقصة."""
    if not os.path.exists(path):
        return expect()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, UnicodeError, json.JSONDecodeError):
        _fail("unreadable")
    if not isinstance(data, type(expect())):
        _fail("unreadable")
    return data


def _read_env_pools(path):
    if not os.path.exists(path):
        return {}, ""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except (OSError, UnicodeError):
        _fail("unreadable")
    pools = {}
    for line in text.splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        name, value = raw.split("=", 1)
        name = name.strip()
        for pid, meta in providers.PROVIDERS.items():
            if name == meta["env"]:
                pool = providers._split_pool(value)
                if pool:
                    pools[pid] = pool
    return pools, text


def _recording_names(directory):
    try:
        names = os.listdir(directory)
    except FileNotFoundError:
        return {}
    out = {}
    for name in names:
        if REC_NAME.fullmatch(name):
            with open(os.path.join(directory, name), "rb") as f:
                out[name] = f.read()
    return out


def _contended(app):
    if app is None:
        return False
    return bool(app.recording or app.busy or getattr(app, "capturing", False) or core._retrying)


def begin_backup(app):
    """بيحجز العملية تحت نفس قفل begin عشان التسجيل ما يبدأش في نص النسخ."""
    if app is None:
        return
    with app._state_lock:
        with core._store_lock:
            if _contended(app) or getattr(app, "backing_up", False):
                _fail("busy")
            app.backing_up = True


def end_backup(app):
    if app is None:
        return
    with app._state_lock:
        app.backing_up = False


def export_snapshot(base_dir, app=None):
    if app is not None and not getattr(app, "backing_up", False) and _contended(app):
        _fail("busy")
    locks = _locked()
    with locks[0], locks[1], locks[2]:
        config = _read_json_file(os.path.join(base_dir, "config.json"), dict)
        history = _read_json_file(os.path.join(base_dir, "history.json"), list)
        clipboard = _read_json_file(os.path.join(base_dir, "clipboard.json"), list)
        keys, _text = _read_env_pools(os.path.join(base_dir, ".env"))
        recordings = _recording_names(os.path.join(base_dir, "recordings"))
    return build_zip(config, keys, history, clipboard, recordings, datetime.now(timezone.utc))


def _atomic_json(path, obj):
    core._replace_json(path, obj)


def _atomic_text(path, text):
    tmp = path + "." + os.urandom(4).hex() + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _copy_aside(path, folder, label):
    if not os.path.exists(path):
        return False
    dest = os.path.join(folder, label)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copy2(path, dest)
    return True


def _put_back_file(path, folder, label, existed):
    src = os.path.join(folder, label)
    if existed and os.path.exists(src):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        shutil.copy2(src, path)
    elif not existed and os.path.exists(path):
        os.remove(path)


def restore_snapshot(base_dir, data, app=None):
    if app is not None and not getattr(app, "backing_up", False) and _contended(app):
        _fail("busy")
    parsed = read_zip(data)
    journal = tempfile.mkdtemp(prefix="emlaa-restore-")
    env_before = {meta["env"]: os.environ.get(meta["env"]) for meta in providers.PROVIDERS.values()}
    try:
        _apply(base_dir, parsed, journal, app)
        _publish_env(parsed["keys"])
        reload_app(app)
    except Exception:
        _restore_env(env_before)
        raise
    finally:
        shutil.rmtree(journal, ignore_errors=True)


def _publish_env(keys):
    for pid, meta in providers.PROVIDERS.items():
        pool = keys.get(pid) or []
        if pool:
            os.environ[meta["env"]] = ",".join(pool)
        else:
            os.environ.pop(meta["env"], None)


def _restore_env(saved):
    for name, value in saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def _apply(base_dir, parsed, journal, app):
    cfg_path = os.path.join(base_dir, "config.json")
    env_path = os.path.join(base_dir, ".env")
    hist_path = os.path.join(base_dir, "history.json")
    clip_path = os.path.join(base_dir, "clipboard.json")
    rec_dir = os.path.join(base_dir, "recordings")
    locks = _locked()
    with locks[0], locks[1], locks[2]:
        if app is not None and _contended(app):
            _fail("busy")
        had = {
            "config.json": _copy_aside(cfg_path, journal, "config.json"),
            ".env": _copy_aside(env_path, journal, ".env"),
            "history.json": _copy_aside(hist_path, journal, "history.json"),
            "clipboard.json": _copy_aside(clip_path, journal, "clipboard.json"),
        }
        _text_pools, env_text = _read_env_pools(env_path) if had[".env"] else ({}, "")
        new_env = providers.render_env(env_text, parsed["keys"])
        existing = _recording_names(rec_dir)
        saved_recs = {}
        for name in set(existing) | set(parsed["files"]):
            if name in existing:
                saved_recs[name] = existing[name]
                _copy_aside(os.path.join(rec_dir, name), journal, os.path.join("recordings", name))
        try:
            _atomic_json(cfg_path, parsed["config"])
            _atomic_text(env_path, new_env)
            _atomic_json(hist_path, parsed["history"])
            _atomic_json(clip_path, parsed["clipboard"])
        except Exception:
            _rollback_docs(base_dir, journal, had)
            raise
        if app is not None and _contended(app):
            _rollback_docs(base_dir, journal, had)
            _fail("busy")
        os.makedirs(rec_dir, exist_ok=True)
        try:
            for name in existing:
                if name not in parsed["files"]:
                    os.remove(os.path.join(rec_dir, name))
            for name, blob in parsed["files"].items():
                dest = os.path.join(rec_dir, name)
                tmp = dest + ".incoming"
                with open(tmp, "wb") as f:
                    f.write(blob)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, dest)
        except Exception as exc:
            _rollback_docs(base_dir, journal, had)
            lost = _rollback_recordings(rec_dir, saved_recs, set(existing))
            if lost:
                raise BackupError("damaged", "ما قدرتش أرجّع: " + ", ".join(lost)) from exc
            raise


def _rollback_docs(base_dir, journal, had):
    for name, existed in had.items():
        _put_back_file(os.path.join(base_dir, name), journal, name, existed)


def _rollback_recordings(rec_dir, saved, originally):
    lost = []
    for name, blob in saved.items():
        dest = os.path.join(rec_dir, name)
        try:
            tmp = dest + ".rollback"
            with open(tmp, "wb") as f:
                f.write(blob)
            os.replace(tmp, dest)
        except OSError:
            lost.append(name)
    if os.path.isdir(rec_dir):
        for name in os.listdir(rec_dir):
            if REC_NAME.fullmatch(name) and name not in originally:
                try:
                    os.remove(os.path.join(rec_dir, name))
                except OSError:
                    lost.append(name)
    return lost


def reload_app(app=None):
    """بعد الاستعادة الناجحة بس: الذاكرة تبقى زي الملف، مش العكس."""
    fresh = core.load_config()
    if isinstance(core.CFG, dict):
        core.CFG.clear()
        core.CFG.update(fresh)
    if app is None:
        return dict(core.CFG)
    if hasattr(app, "cfg") and isinstance(getattr(app, "cfg"), dict):
        app.cfg.clear()
        app.cfg.update(fresh)
    if hasattr(app, "restart_hotkey"):
        try:
            app.restart_hotkey()
        except Exception:
            pass
    return dict(core.CFG)
