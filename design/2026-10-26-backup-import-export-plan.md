# Settings backup, Google sign-in, and Drive export — implementation plan

> **For agentic workers:** implement task-by-task. Do not start a task before
> the one it lists as a dependency is green. Tasks 4–6 are part of the same
> delivery as the file backup. Their tests inject a fake client id and a fake
> transport. The constant committed in the tree stays `""`, and an empty id
> never opens a socket and never calls Google. That is the live-sign-in gate.
> It is not a reason to leave the modules unwritten.

**Goal:** From Settings, the user downloads one zip of settings, API keys,
history, clipboard, and recordings, and restores it as a full replace. The
same zip can be uploaded to a visible `Emlaa/emlaa-backup.zip` in their
Google Drive after an optional Google sign-in.

**Architecture:** `backup.py` owns the zip and the atomic swap.
`google_auth.py` owns the loopback sign-in and `google.json`.
`drive_backup.py` owns the Drive REST calls. `app_web.Api` and the classic
settings window call those modules. Neither UI implements zip or HTTP itself.

**Tech Stack:** Python 3.12 stdlib (`zipfile`, `urllib`, `http.server`,
`hashlib`), pywebview, Tk, unittest. No new dependency.

**Spec:** `design/2026-10-26-backup-import-export-spec.md`

## Global Constraints

- Tests: `venv/Scripts/python -m unittest discover -s tests -p "unit_*.py"`
  green after every task.
- Unit tests touch no network, real keys, microphone, clipboard, keyboard
  hook, browser, or the real `config.json` / `.env` / `history.json` /
  `clipboard.json` / `recordings\` / `google.json`. Patch the paths. Inject
  the HTTP transport and the clock.
- `GOOGLE_CLIENT_ID` in the repository stays `""`. Do not copy Postora's
  client id. An empty id never opens a socket and never calls Google.
- The zip format is `emlaa-backup` version 1, as the spec defines. A damaged
  zip or a newer version writes nothing.
- Restore is a full replace of settings, known key pools, history, clipboard,
  and pattern-matching recording files. Unrelated `.env` lines and
  non-matching names in `recordings\` stay. `google.json` is not inside the
  zip and is not replaced by restore.
- Lock order is `_backup_lock`, then `_key_lock` when `.env` is involved,
  then `_store_lock`, then `_clip_lock`. `save_config`, classic settings
  saves, overlay config saves, and web key writers take `_backup_lock`
  (key writers take it before `_key_lock`). `save_config` becomes an atomic
  replace. Restore does not call the old swallowing writer.
- Busy handling registers the operation under `App`'s `_state_lock` before
  any dialog or Drive call. `begin`, hotkey capture, and manual transcribe
  refuse while it is registered. The live `App` is passed in. A boolean read
  before building the zip is not the gate.
- Drive upload creates `emlaa-backup.incoming.zip` and only then renames it.
  The rename is the commit: the new file id is stored before any delete.
  A failed upload leaves the previous canonical file in place. Lookup is by
  name inside the app-created `Emlaa` folder, with stored ids as a hint.
- Comments follow the files' style (Egyptian Arabic, explaining why). Every
  new Arabic UI string has an `EN` entry in `source/ui/i18n.js`.
- No new third-party dependency. Restore writes the manifest documents
  itself. It does not call `save_config`, which remains the live settings
  writer.
- No automatic upload and no automatic restore.

---

### Task 1: zip format

**Files:** `source/backup.py` (new). Test `tests/unit_backup.py` (new).

**Depends on:** nothing.

**Produces:**

- `FORMAT = "emlaa-backup"`, `VERSION = 1`, recording-name check
  `^[0-9]+\.(mp3|wav|json)$`.
- `build_zip(config, keys, history, clipboard, recordings, now) -> bytes`.
  `recordings` is `{filename: bytes}`. Members are `manifest.json` plus
  `recordings/<filename>` only.
- `read_zip(data) -> dict` with the manifest fields and a `files` map of
  filename to bytes. Raises `BackupError` with a stable `code`:
  `damaged`, `newer`, `too_large`.
- Rejects: bad format, version other than the integer 1 (`true`, `1.0`,
  and `"1"` are damaged; `2` is `newer`), missing required fields, extra
  members, `..`, backslash, absolute names, manifest/member mismatch,
  `recordings` not a sorted array of strings, `keys` not an object of
  string arrays, unknown provider id, non-object `config`, non-list
  `history` or `clipboard`, a member past 512 MiB, a total past 2 GiB,
  more than 5,000 members. Oversize uses code `too_large` and the same
  user-facing damaged sentence as `damaged`.
- Does not touch disk.

- [ ] Failing tests for every reject above, including a string-valued key
  pool and JSON `true` as the version, plus one round-trip of bytes.
- [ ] Implement until `unit_backup.py` is green.

### Task 2: snapshot and atomic restore

**Files:** `source/backup.py`, `source/core.py` (`_backup_lock`, atomic
`save_config`, `begin` refuses while a backup is registered; history
recovery unchanged), `source/providers.py` (pool-line parser shared with
restore; `read_key_pools` stays the loose runtime reader and is not used
for a snapshot). Test `tests/unit_backup.py`.

**Depends on:** Task 1.

**Produces:**

- `export_snapshot(base_dir) -> bytes` reading the four documents and the
  matching recording files under the lock order. Missing documents become
  `{}`, `{}`, `[]`, `[]`. An existing file that cannot be read or decoded,
  including a `.env` that is not valid UTF-8, raises `BackupError` and
  does not return a zip. Does not call `read_key_pools`. Does not prune
  or migrate.
- `restore_snapshot(base_dir, data) -> None` implementing the spec's apply
  order, including the recording journal taken before any delete. Pool
  lines are removed with the same assignment parsing the reader uses
  (`GROQ_API_KEY = old`, duplicates). `os.environ` changes only after the
  recording writes succeed, and a failed attempt restores the previous
  provider variables.
- `reload_app(app)` from the spec's step 7, shared by both UIs. It replaces
  `core.CFG` and `self.cfg` when the classic window exists, rebinds
  hotkeys and the overlay, and returns the config the pages paint from.
- `begin_backup(app)` / `end_backup(app)` registering under `_state_lock`.
  `App.begin`, hotkey capture, and `retranscribe` take that same lock and
  refuse while the flag is set. Dialogs and Drive calls happen only after
  `begin_backup` succeeds.

- [ ] Tests: round-trip on a temp directory; omitted provider line removed,
  including a line with spaces around `=`; unrelated `.env` line kept;
  unreadable `.env` does not produce a zip; matching recording absent from
  the zip deleted; `notes.txt` kept; history-replace failure restores
  config and deletes nothing; a failure after one recording was deleted
  and another replaced restores both and removes a file that did not exist
  before; a failure after one pool was staged leaves `os.environ`
  unchanged; `reload_app` is invoked on success and not on failure.
- [ ] Implement until green.

### Task 3: web Settings, file export and restore

**Files:** `source/ui/index.html`, `source/ui/app.js`, `source/ui/i18n.js`,
`source/app_web.py`. Test `tests/unit_backup_api.py` (new).

**Depends on:** Task 2.

**Produces:**

- Settings group **نسخة احتياطية** after the "البرنامج" group, with the
  warning sentence, Download backup, and Restore from file.
- `Api.backup_export` calls `begin_backup` before the webview save dialog
  (suggested name `emlaa-backup.zip`). Busy returns the wait sentence and
  does not open the dialog. Cancel returns `{ok: false, err: ""}` and
  writes nothing. Success calls `reload_app` only when a restore ran;
  export does not reload.
- `Api.backup_import` confirms with the spec's Arabic sentence, then
  `begin_backup`, then the open dialog. Before `restore_snapshot`, the
  page's in-flight save is awaited and `SAVE.timer` / `SAVE.again` are
  cleared. After success the page replaces `S.features` and the form from
  `reload_app` before any new `scheduleSave` can run. Cancel writes nothing.
- `Api.backup_status` returns `clientConfigured: false` and `signedIn: false`
  until Task 6. The Drive controls are present and disabled, with the
  not-configured sentence, so Task 6 only turns them on.
- Buttons disable while a call is in flight. New Arabic strings have `EN`
  entries.

- [ ] API test with dialogs and paths patched: cancel writes nothing; a
  good zip restores; a damaged zip returns `err` and leaves the temp
  directory unchanged; busy returns the wait sentence.
- [ ] Static check: every new Arabic string in `index.html` / `app.js` is a
  key in `EN`.

### Task 4: Google sign-in, inert without a client id

**Files:** `source/google_auth.py` (new). Test `tests/unit_google_auth.py`
(new).

**Depends on:** nothing for the module. Wiring is Task 6. Implement it in
this delivery. Tests pass a fake client id into `sign_in`. The committed
constant stays `""`.

**Produces:**

- `GOOGLE_CLIENT_ID = ""`.
- `sign_in(client_id, transport, listener, opener, clock) -> account`.
  Empty `client_id` raises `BackupError("unconfigured")` before any of
  those collaborators are called.
- PKCE S256, `state`, loopback on `127.0.0.1` only, five-minute timeout,
  scopes from the spec, token exchange with the verifier, id_token checks
  (audience, issuer, expiry, email) without signature verification.
- `google.json` in the data directory: account, refresh token, folder id,
  file id, `backedUpAt`, `error`. Access token is memory only.
- `access_token()` refreshes with the refresh token via the injected
  transport. Refresh failure raises `BackupError("reauth")` and does not
  write local documents.
- `sign_out()` deletes `google.json` and the memory token and does not
  call the transport.
- A second `sign_in` replaces `google.json`, including folder and file ids.

- [ ] Tests with fake listener and transport. Assert the empty id calls
  nothing. Assert a mismatched `state` or a bad audience writes no file.
  Assert sign-out leaves no `google.json` and no transport call.

### Task 5: Drive upload and download

**Files:** `source/drive_backup.py` (new). Test `tests/unit_drive_backup.py`
(new).

**Depends on:** Tasks 2 and 4.

**Produces:**

- `upload(zip_bytes, auth, transport) -> {fileId, backedUpAt}`.
  Resolves the `Emlaa` folder and `emlaa-backup.zip` by the spec's name
  rules, including a `google.json` with no ids and a stored id that 404s.
  Uploads `emlaa-backup.incoming.zip`. On rename success, stores the new
  id, the success time, and a cleared error before deleting the previous
  file. A delete failure after that store keeps the new id. On upload or
  rename failure, deletes the incoming id if one exists, leaves the
  previous id stored, and keeps the upload error if the incoming delete
  also fails.
- `download(auth, transport) -> bytes` resolves the canonical file by name.
  No visible file raises `BackupError("no_drive_file")` and does not call
  `restore_snapshot`.
- `restore(auth, transport, base_dir)` downloads to a temp file and calls
  `restore_snapshot`. A damaged zip does not delete the Drive file.
- `begin_backup` runs before the zip is built and before any Drive call.

- [ ] Fake transport tests: failed upload keeps the old file id and issues
  a delete for the incoming id; rename then a failed old-file delete still
  stores the new id; a second PC with a stale id downloads the name match;
  an empty `google.json` finds an existing folder instead of creating
  another; missing file does not call restore; damaged download does not
  change the temp data directory.

### Task 6: wire Google and Drive into web Settings

**Files:** `source/app_web.py`, `source/ui/app.js`, `source/ui/index.html`,
`source/ui/i18n.js`. Test `tests/unit_backup_api.py`.

**Depends on:** Tasks 3, 4, and 5. Same empty-constant rule as Task 4.

**Produces:**

- `google_sign_in`, `google_sign_out`, `drive_backup`, `drive_restore`,
  and a finished `backup_status` (email, name, picture, `backedUpAt`,
  `error`, `clientConfigured`, `signedIn`). The status payload has no
  token and no refresh token.
- The page shows the account, enables the Drive buttons when signed in,
  confirms before `drive_restore`, and shows "جاري…" plus the status
  sentences from the spec.
- Empty client id: the sign-in button returns the not-configured sentence
  and the Drive buttons stay disabled.

- [ ] API tests with fake auth and transport covering status shape,
  unconfigured sign-in, and drive restore confirm already done by the page
  (the API itself does not prompt).

### Task 7: classic settings window

**Files:** `source/emlaa.py`. Test: extend `tests/unit_backup_api.py` or
`tests/unit_classic.py` only if a pure helper is extracted. The Tk widgets
are not unit-tested; the helper that maps a button to the core call is.

**Depends on:** Tasks 2, 3, and 6 for the Drive buttons. The file buttons
can land with Task 3 if the Drive buttons are disabled the same way.

**Produces:**

- A "نسخة احتياطية" block in `_open_settings` with the same actions,
  warning, confirm, and status text. Dialogs are Tk file dialogs. Calls
  go to `backup.py` / `drive_backup.py`, not a second implementation.

- [ ] Helper test: busy and damaged errors surface as the same Arabic
  strings the web API returns.

### Task 8: privacy copy

**Files:** `PRIVACY.md`, `README.md`, `source/ui/index.html` (the privacy
paragraph at the sidebar), `source/ui/i18n.js` (the `EN` entry whose key
is that same Arabic sentence).

**Depends on:** Task 3. Mention Drive as the exception even though the
button is disabled until a client id exists, because the sentence must be
true on the day the id is pasted.

**Produces:** the privacy section the spec describes, in Arabic and
English, and the home sentence's `EN` value updated with the Arabic source.

- [ ] Change the Arabic sentence in `index.html` and the matching `EN`
  key together. Read `PRIVACY.md`, `README.md`, and both languages of the
  home sentence, and confirm they name keys, history, clipboard,
  recordings, the user's own Drive folder `Emlaa`, and that sign-out does
  not delete the file.

## Debate round 1

Read-only Codex review, 2026-10-26. Invocation `--model gpt-6.1-sol --effort high`
(smoke-tested with the same flags; the relay records the requested model, not
an API-confirmed id). Sandbox `read-only`. `touchedFiles` matched the
pre-debate tree: `tools/store/store.json`, the two new design docs, and
`logo-concepts/`. No debate edit.

| # | Finding | Sev | Verdict | Reason |
|---|---------|-----|---------|--------|
| 1 | Client-id gate skips Google and Drive | P1 | accept | The spec requires the modules, inert while the constant is empty. The plan's "do not implement until an id is pasted" let Done-when pass without them. The gate is now live calls only. |
| 2 | Restore never reloads the running app | P1 | accept | `reload_app` is now step 7 and is shared by both UIs, including classic `self.cfg`. |
| 3 | Recording rollback skips files already deleted | P1 | accept | The journal is taken before any delete, and the tests cover a failure after a delete and a replace. |
| 4 | Named locks miss `save_config` and `_key_lock` | P1 | accept | `save_config` at `core.py` writes with no lock. Key writes use `Api._key_lock` only. Both now take `_backup_lock` first. |
| 5 | Busy check does not keep the app idle | P1 | accept | `App.begin` uses `_state_lock`, which the old plan never held. Registration happens before dialogs. |
| 6 | A queued autosave overwrites the restore | P1 | accept | `app.js` keeps `SAVE.timer`, `SAVE.running`, and `SAVE.again`. Restore drains that queue and repaints the form before another save. |
| 7 | `_set_pool` misses spaced assignments | P2 | accept | `read_key_pools` strips around `=`; `_set_pool` matches `NAME=` only. Restore uses the reader's parse. |
| 8 | Rollback leaves `os.environ` half-updated | P2 | accept | Provider variables publish only after recordings succeed, and a failure restores the previous values. |
| 9 | Export can succeed with an unreadable `.env` | P1 | accept | `read_key_pools` swallows errors. The snapshot reader fails the export instead. |
| 10 | Two PCs cannot find the current Drive file | P1 | accept | A cached id dies when the other PC deletes it. Lookup is by name; stored ids are a hint. |
| 11 | New Drive file id stored too late | P2 | accept | The id is stored at rename, before the old-file delete. Incoming-delete failure does not hide the upload error. |
| 12 | Validation checklist is not the schema | P2 | accept | Required fields, key-pool types, and `int`-not-`bool` version are now explicit. `too_large` stays an internal code with the damaged sentence. |
| 13 | Privacy task skips `index.html` | P2 | accept | The Arabic sentence is in the sidebar markup. The task now changes that sentence and its `EN` key together. |

## Done when

- `unit_*.py` is green.
- A temp-directory round-trip restores keys, history, clipboard, and a
  recording, and deletes a recording that was not in the zip.
- With `GOOGLE_CLIENT_ID` still empty, Sign in does not open a port.
- The spec's live check (second data directory, real client id) is still
  manual and is not claimed by the unit run.
