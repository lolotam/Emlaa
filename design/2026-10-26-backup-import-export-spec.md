# Settings backup, Google sign-in, and Drive export — design

Revision 2 · 2026-10-26 · decisions confirmed with the user; debate round 1 folded in

## Problem

Emlaa keeps everything that matters in local files next to the app (or in
`%LOCALAPPDATA%\Emlaa` for the Store build): `config.json`, `.env` key pools,
`history.json`, `clipboard.json`, and `recordings\`. Reinstalling, moving
machines, or losing that folder loses the setup, the keys, the history, and
the audio. There is no account and no copy anywhere else.

Postora Browser Agent (`E:\Dev\Projects\Postora_Browser_Agent`,
`src/lib/backup.js`, `src/lib/drive-backup.js`, `src/lib/google-account.js`)
already has the shape to copy: a private backup file, optional Google sign-in,
and a Drive copy the user can restore. Emlaa is a Windows desktop app, so the
Chrome extension flow (`chrome.identity`, hidden `drive.appdata`) does not
apply. The behavior below is that feature, adapted to the decisions in the
table.

## Decisions

| Question | Decision |
|---|---|
| What is inside the backup | Everything the user named: settings, API key pools, history, clipboard, and the recordings folder (`.mp3`, failed `.wav`, `.json` sidecars). |
| What stays out | Offline Whisper models (`offline\`), `emlaa-error.log`, `history.corrupt-*.json`, `.show-request`, `google.json`, in-memory tokens, temp files. |
| Restore | Full replace, after a confirm. Settings, keys, history, clipboard, and pattern-matching recording files become the backup. Pattern-matching recordings on this PC that are not in the zip are deleted. |
| A bad backup | Changes nothing. Newer format versions are rejected. |
| Package | One zip, `emlaa-backup.zip`, for both the local file and Drive. Plain, no password. |
| Drive | One visible file, `Emlaa/emlaa-backup.zip`, in the user's My Drive. Uploaded only when they press the button. Overwrites that file. |
| Sign-in | Optional. The app runs without it. Drive actions need a signed-in account. Sign-in does not upload and does not restore. |
| Sign-out | Forgets the account on this PC. The Drive file stays. |
| Two PCs | They share that one file. The last successful backup is what Restore returns. A different Google account uses that account's own file. |
| Permission | `drive.file` only. Emlaa sees files this OAuth client created, not the rest of Drive. |
| Google client | A new Desktop OAuth client for Emlaa. `GOOGLE_CLIENT_ID` is an empty placeholder. Postora's client id is not copied. Live sign-in does not open a browser and does not call Google until that constant is a non-empty id. |
| Failed Drive upload | The previous `emlaa-backup.zip` stays as it was. |

## Scope

In:

- Building and reading the zip.
- Save-dialog export and open-dialog restore in the web Settings page, and the
  same actions in the classic Tk settings window (`--classic`, or when
  WebView2 is missing).
- Optional Google sign-in (name, email, picture) and the Drive button pair,
  inert until a client id is pasted into the placeholder.
- `PRIVACY.md`, `README.md`, and the home-page privacy sentence updated so
  they describe the Drive upload.

Out:

- Password encryption of the zip.
- Automatic upload on every settings change, and automatic restore on sign-in.
- A hidden `appDataFolder` backup.
- Backing up or restoring the offline model cache or the error log.
- Merging two backups. Last successful upload wins.
- Copying Postora's client id, and any Emlaa server of our own.

## Backup format

Zip, UTF-8, no zip encryption. Two kinds of members only:

- `manifest.json` at the zip root.
- `recordings/<id>.mp3`, `recordings/<id>.wav`, `recordings/<id>.json`, where
  `<id>` is decimal digits.

Anything else (absolute paths, `..`, backslashes, extra directories, a second
slash, a different extension) makes the zip damaged. Read members as
`ZipInfo` names, never as paths joined onto a user-controlled prefix without
checking the name first.

`manifest.json`:

```json
{
  "format": "emlaa-backup",
  "version": 1,
  "exportedAt": "2026-10-26T15:00:00Z",
  "config": {},
  "keys": {"groq": ["gsk_..."]},
  "history": [],
  "clipboard": [],
  "recordings": ["123.mp3", "456.wav", "456.json"]
}
```

- `format` is exactly `emlaa-backup`. `version` is an `int` and not a `bool`
  (so JSON `true` is damaged, not version 1). A number greater than 1 is
  rejected with the newer-version error. A missing version, a lower version,
  or any other type is damaged.
- Every manifest field above is required. `keys` is an object. Each value is
  an array of strings. A string where an array belongs is damaged, not a pool
  to be joined character by character. `recordings` is an array of strings
  already in sorted order.
- `config` is a JSON object: the on-disk `config.json` object, not
  `load_config()`'s merged result. Export of a missing file uses `{}`.
  Dictionary and snippets ride along because they live in that object.
- `history` and `clipboard` are JSON arrays, the on-disk lists. A missing file
  exports `[]`.
- `keys` is an object whose keys are provider ids in `providers.PROVIDERS` and
  whose values are arrays of non-empty strings, in pool order, as
  `read_key_pools` returns them. Providers with no keys are omitted.
- `recordings` is the sorted list of file names under `recordings\` that match
  `^[0-9]+\.(mp3|wav|json)$`. The set in the manifest and the set of
  `recordings/*` members in the zip are the same set. A name in one and not
  the other is damaged.

Safety bounds, so a hostile zip cannot fill the disk. Crossing any bound is
damaged (`BackupError` code `too_large`) and writes nothing. The user-facing
sentence is the same damaged-file sentence:

- at most 5,000 zip members
- at most 2 GiB total uncompressed size
- at most 512 MiB for one member

Export reads `config.json`, `.env`, `history.json`, `clipboard.json`, and the
matching recording files while it holds the locks in
[Lock order](#lock-order). It does not prune, migrate, or rewrite those files.
A missing document exports as `{}` or `[]`, and a missing `.env` exports no
keys. A file that exists but cannot be read or decoded fails the export.
`read_key_pools` is not the snapshot reader: it swallows errors and can return
a partial map, and restoring that map would delete the keys it failed to read.
Non-provider lines in `.env` are not part of the manifest.

## Local export and restore

Export opens a save dialog (webview save dialog, or Tk `asksaveasfilename` in
the classic window). The suggested name is `emlaa-backup.zip`. Cancelling the
dialog writes nothing. The settings screen keeps this warning visible, in
Arabic with an `EN` entry:

> الملف فيه مفاتيح الـAPI والسجل والحافظة وتسجيلات الصوت. خليه عندك وما تبعتهوش لحد.

Restore opens a file dialog after the user confirms. Cancelling either step
writes nothing. The confirm, in Arabic with an `EN` entry:

> الاستعادة هتستبدل الإعدادات والمفاتيح والسجل والحافظة والتسجيلات الموجودة على الجهاز ده بالنسخة دي. التسجيلات اللي مش في النسخة هتتمسح. تكمّل؟

The same confirm is used for Restore from file and Restore from Drive.

Busy refusal: if `App.recording`, `App.busy`, `App.capturing`, or
`core._retrying` is non-empty, export and both restores return

> استنى لحد ما التسجيل أو التفريغ يخلّص.

and do not open a dialog and do not touch Drive. The check is not a single
boolean read. Under the same `_state_lock` that `App.begin` uses, the
operation is registered, and `begin`, hotkey capture, and manual transcribe
refuse to start while it is registered. The dialog and any Drive call happen
only after that registration. The destructive phase of restore checks the
registration again under that lock and aborts with the documents untouched
if a recording has already entered. The web and classic windows pass the
live `App` into this gate. There is no second busy check hidden inside zip
construction after a dialog has already opened.

Validation finishes before any destination file is replaced. A damaged zip, a
newer version, a manifest that is not the schema above, or a recording member
that fails the name or size rules leaves every destination file as it was.

## Lock order

Backup, `save_config`, classic settings saves, overlay saves that write
`config.json`, and the web key writers (`_key_lock` in `app_web.py`) share
one `_backup_lock`. Acquisition order, always, is `_backup_lock`, then
`_key_lock` when the key file is involved, then `_store_lock`, then
`_clip_lock`. `save_config` takes `_backup_lock` and writes atomically
(temp file plus `os.replace`); a restore does not call today's `save_config`,
which swallows errors and truncates the destination directly. Key writers
take `_backup_lock` before `_key_lock`.

## Apply order

All under the lock order above.

1. Copy the current `config.json`, `.env`, `history.json`, and `clipboard.json`
   aside (a missing file is recorded as missing). Copy aside every
   pattern-matching recording that will be deleted or replaced, and record
   which destination names were originally absent.
2. Write the new documents to temp files in the same directory and
   `os.replace` them into place. Use the atomic replace helper.
3. Key pools are staged in the copy of `.env`, not published to `os.environ`
   yet. For every id in `providers.PROVIDERS`, the new pool replaces every
   assignment the pool reader would accept for that id, including
   `GROQ_API_KEY = old` and duplicate lines. A missing id removes those
   lines. Every other `.env` line stays. An unknown provider id inside
   `keys` rejects the whole zip before step 1.
4. If any replace in steps 2–3 fails, put the document copies back and stop.
   Recordings are still the originals, because nothing in `recordings\` has
   been deleted yet. `os.environ` is unchanged.
5. Only after 2–3 succeed, delete the pattern-matching names that are not in
   the manifest, then write the manifest's recording files by the same
   temp-and-replace path. Leave every non-matching name in that folder alone.
   If a recording write fails, put the four documents back, restore
   `os.environ` provider variables to the pre-restore values, put back every
   recording copied aside, and delete any destination that was originally
   absent and was created in this attempt. A file that cannot be put back is
   named in the error. The copies live until this step finishes.
6. Publish provider variables to `os.environ` only after step 5 succeeds.
   Drop the copies.
7. Reload the running app from disk before returning success. One shared
   function does this for both UIs: replace `core.CFG`, the classic window's
   `self.cfg` when that window exists, key pools already published in step 6,
   hotkeys, float/overlay, history, clipboard, and dictionary. The web page
   waits until any in-flight settings save finishes, drops `SAVE.timer` and
   `SAVE.again`, then replaces `S.features` and the settings form from the
   reloaded config so a queued autosave cannot write the pre-restore form
   back. The classic window reloads its widgets and key drafts from disk
   before it closes the operation. Do not start a recording.

Restore does not call `recordings_prune` itself. The next ordinary prune still
runs the existing recovery rules (a restored `.wav` whose id is not in history
can be reattached; a `.json` sidecar with no `.wav` can be removed). That is
current startup behavior, not an extra backup pass.

`google.json` is not read or written by export or restore.

## Google sign-in

Module constant `GOOGLE_CLIENT_ID = ""` in the new Google module. While it is
empty, Sign in with Google returns

> تسجيل الدخول بجوجل لسه مش متفعّل في النسخة دي.

and does not open a browser, bind a port, or call Google. Drive backup and
Drive restore return that same error when no account is signed in, and the
not-configured error when the constant is empty.

When the constant is non-empty, sign-in is the desktop installed-app flow.
No client secret is stored.

- System browser. Authorization code with PKCE (`S256`).
- Redirect `http://127.0.0.1:<ephemeral-port>/` bound only on loopback.
- `state` checked. One accepted request, then the listener closes. The wait
  is five minutes, then sign-in fails and the port closes.
- Scopes: `openid`, `email`, `profile`,
  `https://www.googleapis.com/auth/drive.file`.
- Token exchange at `https://oauth2.googleapis.com/token` with the code and
  the verifier. `access_type=offline` so Google returns a refresh token.
- The id_token is checked the way Postora checks it: audience is this client
  id, issuer is `accounts.google.com` or `https://accounts.google.com`,
  expiry is in the future, email is present. The signature is not verified.
  The token is accepted only as the reply to this loopback request.
- The access token stays in memory. The refresh token, account
  `{email, name, picture}`, Drive folder id, file id, last success time, and
  last error are stored in `google.json` next to `config.json`. That file is
  outside the zip.
- A later Drive call uses the memory access token, or refreshes it with the
  refresh token. Refresh failure asks the user to sign in again and does not
  change local data or the Drive file.
- Sign out deletes `google.json` and the memory token. It does not call Drive.
- Signing in with another Google account replaces `google.json`, so the next
  lookup is that account's `Emlaa` folder, not the previous file id.

## Drive

All Drive calls use `https://www.googleapis.com/drive/v3` and the access
token. No call runs while the client id is empty or nobody is signed in.

Folder and file are found by name inside the files this client created, not
only by the ids in `google.json`. Those ids are a hint.

- Folder name `Emlaa`, mime type `application/vnd.google-apps.folder`. If the
  stored folder id still exists, use it. If it is missing or Google says it
  is gone, use the most recently modified folder with that name. If none
  exists, create one. Never create a second folder while one is visible.
- File name `emlaa-backup.zip` inside that folder. Download and the status
  lookup use this name. A stored file id that 404s, or that is not the
  current name match, is replaced by the name match. A fresh install with an
  empty `google.json` finds the file the same way. If several files share the
  canonical name, the most recently modified one is the backup; the next
  successful upload deletes the others.

Backup button:

1. Build the same zip as local export (including the busy registration).
2. Resumable-upload it as a new file `emlaa-backup.incoming.zip` in that folder.
3. When Google confirms the upload, rename that file to `emlaa-backup.zip`.
   The rename is the commit. Store the new file id, the success time, and a
   cleared error immediately, before deleting anything.
4. Delete the previous canonical id when it is a different id, and delete
   other visible files with the canonical name and a different id.
5. If the upload or the rename fails, delete the incoming file when one was
   created, leave the previous canonical file and the previously stored id in
   place, store the upload error, and leave local data unchanged. A failure
   while deleting the incoming file does not replace that upload error.
6. If the rename succeeded and a later delete fails, the new id stays stored.
   The next successful backup retries that delete.

There is no size cap beyond the zip bounds above. The button label shows
"جاري…" until the call returns. The status line shows the last success time,
or the last error, or that there is no Drive file yet.

Restore button: confirm, then download `emlaa-backup.zip` (`alt=media`) to a
temp file and run the same restore as a local zip. No Drive file → 

> لسه مفيش نسخة في Google Drive.

A failed download or a damaged zip changes nothing locally and does not delete
the Drive file.

Sign-in does not look up the file to restore it. After a successful sign-in
the status line may show the file's modified time when a lookup succeeds:

> فيه نسخة في Drive من {time}.

That lookup failing still leaves the user signed in.

The screen keeps this note, with an `EN` entry:

> الملف في فولدر Emlaa على Google Drive بتاعك، وآخر نسخة بتستبدل اللي قبلها. تسجيل الخروج ما بيمسحهاش.

## UI

Web Settings (`source/ui/index.html`), a new group **نسخة احتياطية** after the
"البرنامج" group and before the save bar:

- The warning sentence.
- Download backup. Restore from file.
- Sign in with Google. When signed in: name, email, picture, Sign out.
- Back up now. Restore from Drive. The Drive note. A status line.

Buttons disable while a backup or restore call is running. Strings that the
page renders in Arabic get `EN` entries in `source/ui/i18n.js`.

Classic Tk settings window (`emlaa.py`, `_open_settings`) gets the same
actions and the same strings. It calls the same core functions. It does not
grow a second copy of the zip or Drive logic.

`Api` methods on the web side, each returning `{ok: true, ...}` or
`{ok: false, err}`:

- `backup_export()` — save dialog, then write.
- `backup_import()` — the page has already confirmed; open dialog, then restore.
- `google_sign_in()` / `google_sign_out()`
- `drive_backup()` / `drive_restore()` — the page has already confirmed restore.
- `backup_status()` — `{clientConfigured, signedIn, email, name, picture, backedUpAt, error}` for painting the section. No token in this payload.

## Privacy

`PRIVACY.md` and `README.md` gain a short section: the backup zip contains API
keys, history, clipboard text, and recordings; it stays wherever the user
saves it; pressing the Drive button uploads that zip to a folder named `Emlaa`
in the user's own Google Drive; Emlaa has no server in that path; signing out
does not delete the Drive file; file export and restore work with no Google
account. The home sentence that says history, clipboard, and audio stay only
on this device stays true for normal use, and gains a clause that the Drive
button is the exception.

The Store build and the portable build use the same code. Data is read from
whichever `BASE` the process already uses.

## Testing

Unit tests only. No network, no browser, no real `config.json`, `.env`,
history, clipboard, or recordings. Patch the paths. Fake the HTTP transport
and the clock.

- Round-trip: config, keys, history, clipboard, and recording bytes survive
  export → import in a fresh directory.
- Full replace: a local recording name that is not in the zip is deleted; a
  non-matching file in `recordings\` is not; a provider omitted from `keys`
  loses its `.env` line; an unrelated `.env` line remains.
- Damaged input writes nothing: bad format, version 2, path traversal,
  manifest/member mismatch, unknown provider id, truncated JSON, a member
  over the size bound. A failure on the document replace restores the previous
  documents and does not delete recordings.
- Busy refusal writes nothing and does not call the Drive transport.
- Empty `GOOGLE_CLIENT_ID` does not call the transport. Sign-out removes
  `google.json` and does not call the transport.
- Drive: a failed upload leaves the previous file id in place and deletes the
  incoming id; a successful upload renames, then deletes the previous id;
  restore of a missing file leaves local data alone.
- New Arabic UI strings have `EN` entries.

## Live check after implementation

Not part of the unit run. With a real client id, sign in, back up a PC that
has one history row and one recording, sign out, and restore onto a second
data directory. Keys, history, clipboard, and the recording match, and a
recording that existed only on the second directory is gone.
