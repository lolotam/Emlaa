# -*- coding: utf-8 -*-
"""
نسخة Google Drive في فولدر ظاهر اسمه Emlaa. المعرّف المخزّن تلميح؛
الاسم هو اللي بيلاقي الملف لما جهاز تاني يستبدله.
"""
import json
import urllib.parse

import backup
import google_auth

FILES = "https://www.googleapis.com/drive/v3/files"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
FOLDER = "application/vnd.google-apps.folder"
CANONICAL = "emlaa-backup.zip"
INCOMING = "emlaa-backup.incoming.zip"


def _auth_header(token):
    return {"Authorization": "Bearer " + token}


def _json(body):
    try:
        return json.loads((body or b"{}").decode("utf-8") or "{}")
    except (UnicodeError, json.JSONDecodeError, AttributeError):
        return {}


def _q(name, mime=None, parent=None):
    parts = [f"name = '{name}'", "trashed = false"]
    if mime:
        parts.append(f"mimeType = '{mime}'")
    if parent:
        parts.append(f"'{parent}' in parents")
    return " and ".join(parts)


def _list(transport, token, query):
    url = FILES + "?" + urllib.parse.urlencode({
        "q": query, "fields": "files(id,name,modifiedTime)", "orderBy": "modifiedTime desc",
    })
    status, _headers, body = transport("GET", url, _auth_header(token), None)
    if status != 200:
        raise backup.BackupError("reauth")
    return _json(body).get("files") or []


def resolve_folder(base_dir, transport, token):
    state = google_auth.read_state(base_dir)
    stored = state.get("folderId")
    if stored:
        status, _headers, body = transport("GET", f"{FILES}/{stored}?fields=id,trashed", _auth_header(token), None)
        if status == 200 and not _json(body).get("trashed"):
            return stored
    found = _list(transport, token, _q("Emlaa", FOLDER))
    if found:
        return found[0]["id"]
    status, _headers, body = transport("POST", FILES, {**_auth_header(token), "Content-Type": "application/json"},
                                       json.dumps({"name": "Emlaa", "mimeType": FOLDER}).encode("utf-8"))
    if status not in (200, 201):
        raise backup.BackupError("reauth")
    return _json(body)["id"]


def resolve_file(base_dir, transport, token, folder_id):
    found = _list(transport, token, _q(CANONICAL, parent=folder_id))
    if not found:
        return None
    return found[0]


def upload(base_dir, zip_bytes, transport, token, now_ms):
    state = google_auth.read_state(base_dir)
    folder = resolve_folder(base_dir, transport, token)
    state["folderId"] = folder
    previous = state.get("fileId")
    status, headers, body = transport(
        "POST",
        UPLOAD + "?uploadType=resumable",
        {**_auth_header(token), "Content-Type": "application/json", "X-Upload-Content-Type": "application/zip"},
        json.dumps({"name": INCOMING, "parents": [folder]}).encode("utf-8"),
    )
    if status not in (200, 201):
        state["error"] = backup.message_for("reauth")
        google_auth.write_state(base_dir, state)
        raise backup.BackupError("reauth")
    location = headers.get("Location") or headers.get("location")
    status, _headers, body = transport("PUT", location, {**_auth_header(token), "Content-Type": "application/zip"}, zip_bytes)
    if status not in (200, 201):
        _delete_quiet(transport, token, _json(body).get("id") if body else None)
        state["error"] = backup.message_for("reauth")
        google_auth.write_state(base_dir, state)
        raise backup.BackupError("reauth")
    incoming_id = _json(body)["id"]
    status, _headers, body = transport(
        "PATCH", f"{FILES}/{incoming_id}",
        {**_auth_header(token), "Content-Type": "application/json"},
        json.dumps({"name": CANONICAL}).encode("utf-8"),
    )
    if status != 200:
        _delete_quiet(transport, token, incoming_id)
        state["error"] = backup.message_for("reauth")
        google_auth.write_state(base_dir, state)
        raise backup.BackupError("reauth")
    new_id = _json(body)["id"]
    # إعادة التسمية هي لحظة الاعتماد: المعرّف يتسجل قبل مسح القديم
    state["fileId"] = new_id
    state["backedUpAt"] = now_ms
    state["error"] = None
    google_auth.write_state(base_dir, state)
    if previous and previous != new_id:
        _delete_quiet(transport, token, previous)
    for extra in _list(transport, token, _q(CANONICAL, parent=folder)):
        if extra["id"] != new_id:
            _delete_quiet(transport, token, extra["id"])
    return {"fileId": new_id, "backedUpAt": now_ms}


def _delete_quiet(transport, token, file_id):
    if not file_id:
        return
    try:
        transport("DELETE", f"{FILES}/{file_id}", _auth_header(token), None)
    except Exception:
        return


def download(base_dir, transport, token):
    folder = resolve_folder(base_dir, transport, token)
    found = resolve_file(base_dir, transport, token, folder)
    if not found:
        raise backup.BackupError("no_drive_file")
    status, _headers, body = transport("GET", f"{FILES}/{found['id']}?alt=media", _auth_header(token), None)
    if status != 200:
        raise backup.BackupError("no_drive_file")
    state = google_auth.read_state(base_dir)
    state["folderId"] = folder
    state["fileId"] = found["id"]
    google_auth.write_state(base_dir, state)
    return body


def restore(base_dir, transport, token, app=None):
    data = download(base_dir, transport, token)
    backup.restore_snapshot(base_dir, data, app)
    return data
