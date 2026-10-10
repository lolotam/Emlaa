# Keep failed recordings and transcribe them manually — design

Revision 4 · 2026-10-11 (after debate rounds 1–3) · branch `feat/keep-failed-recordings`

## Problem

A recording whose transcription fails is lost. `App.process` deletes the temporary WAV in its
`finally` block, and the audio is only kept (`recording_save`) after `history_add` created an
entry — which happens only after a successful transcription. So when every item of the
feature's STT list fails (network, key, quota, model) or the transcript comes back empty, the
user gets an error message and the audio is gone. The user wants the audio of every recording
kept, the failed session listed in History with its error, and a **Manual transcribe** button
that retries on the saved audio so the result can be copied by hand.

## Decisions (made with the user)

| Question | Decision |
|---|---|
| What "Manual transcribe" does | Transcribe again **and** apply the feature's normal processing (clean-up for normal, prompt, translate). The result is shown in History for manual copy; it is never typed or pasted. |
| How long a failed recording is kept | Until it is transcribed successfully or deleted by the user — outside the "last 10" limits. |
| Password fields | A **failed** recording in a password field is kept like any other (explicit user decision; successful password transcripts are still never stored). |
| Notification at failure | A message with the reason plus an **Open History** button. |

## Scope

### What counts as a failed recording (kept)

Audio exists and no History entry was written for it, because:
1. `FeatureClient.transcribe` raised (all STT items failed — any error type) — kept in every
   field, password fields included (user decision);
2. the transcript is empty ("مطلعش نص");
3. an exception after a **successful** transcription but before `history_add`, **outside a
   password context** (neither `early_secure` nor `late_secure`) — kept with the transcript as
   `raw`, so nothing said is lost. Inside a password context a successful transcript is never
   stored (privacy rule unchanged);
4. edit mode (handled entirely inside `_process_edit`, which owns its failures): the
   instruction transcription raised or came back empty, or `edit()` returned `None` (the
   instruction transcript is kept as `raw`).

A History entry that already exists always gets its audio: if anything after `history_add`
raises before `recording_save` ran, the exception path saves the MP3 for that id. Edit mode
writes its History entry and MP3 **before** delivering the result, so a `clip_failed` delivery
no longer loses the audio (the selection itself is still never stored).

### Not kept (no change)

- Cancelled recordings (`Esc`), recordings too short to produce a WAV, microphone failures —
  there is no audio, or the user discarded it.
- The password-field refusal "الفوكس اتنقل من خانة الباسورد — مكتبتش حاجة": the transcription
  succeeded and the transcript is a password typed nowhere; it is a deliberate safety refusal,
  not a failure.
- A failure after a History entry exists (for example the paste step): the session is already
  in History, and its audio is saved by the exception path (see above).

## Data

### History entry

Successful entries are unchanged. A failed entry:

```json
{"id": 1760000000000, "time": "...", "time_display": "...", "date_display": "...",
 "mode": "normal|prompt|translate|edit", "raw": "", "result": "", "words": 0,
 "dur": 4.2, "app": "chrome", "status": "failed", "error": "<friendly_error text>"}
```

`raw` holds the transcript for case 3 and the instruction transcript for case 4, otherwise
`""`; `words` is always `0` for a failed entry, so it never counts as dictation. Entries without
`status` are successful (all existing history stays valid). On successful manual transcription
the entry gets `time` = resolution time (so the cap keeps it as the newest), keeps the original
in `recorded`, and moves to the top of the list.

### Audio files

- `recordings/<id>.mp3` — playback/download, written with the existing `recording_save`.
- `recordings/<id>.wav` — a copy of the original WAV, kept **only while the entry is failed**,
  because manual transcription needs the original audio (providers and offline Whisper take the
  WAV; there is no MP3 decoder in the app). A WAV on disk is also the durable marker that the
  recording failed: see Retention.

- `recordings/<id>.json` — a sidecar holding the failed entry itself, so a failed recording
  can always be listed again (see Recovery).

IDs: one allocator for successful and failed entries, under `_store_lock`:
`max(now_ms, last_id + 1)`, skipping any id already in History or with an audio/sidecar file, so
a clock that moved back can never overwrite another recording. Temp files carry a unique suffix
(`<id>.<random>.wav.tmp`).

Write order in `keep_failed_recording`: (0) allocate the id under the lock; (1) outside the
lock, copy the WAV and write the sidecar to unique temp files; (2) **under `_store_lock`, as one step**: `os.replace` both into place
and insert the History entry with a checked write — so `history_clear` can never run between
publishing the audio and inserting its row; (3) the MP3 is best-effort, after the lock. If step
1 or the publish fails, `None` is returned, nothing is half-published, and `process` **does not
delete** its temporary WAV — it logs the temp path ("الصوت لسه في …") so the audio is never
destroyed by our own cleanup. If only the History write fails, the WAV and sidecar are published
and Recovery will list the entry again.

**Crash-safe file protocol** (PR #17 review, round 2). The files on disk must say unambiguously
what was in progress if the app dies between two steps:
- Publish: WAV first, then the sidecar. A `<id>.wav` without a sidecar therefore always means an
  interrupted publish, and Recovery restores it as a failed entry built from the WAV
  (`RECOVERED_ERROR`, time from the id, `dur` from the WAV, mode `normal`).
- Removal (explicit delete, clear, successful resolution): the sidecar is first replaced (temp +
  `os.replace`) by a tombstone `{"deleted": true}`. `history_delete` and `history_clear` write it
  **before** their History write and restore the sidecars if that write fails. Then the WAV
  (and MP3) are removed, and the sidecar last, only once the WAV is gone. A WAV with a tombstone
  means an interrupted removal: Recovery finishes it, even when the History row is still
  there (a failed row is dropped; a resolved row keeps its MP3), deleting files only after the
  History write succeeds. A sidecar without a WAV is leftover and is
  removed. So neither a crash nor a failed file delete can lose a recording or resurrect one that
  was deleted or resolved.

`history_add` returns the id **only after a successful write** (it returned the id even when
the write failed, so a caller assumed a row that did not exist). `process` treats a `None` from
`history_add` as "no entry": outside a password context the recording is kept as failed with
the transcript as `raw`.

### Retention

- `history_add` / `history_prune` trim only successful entries to `history_cap()`; failed
  entries are always kept.
- **Failed audio is deleted only by an explicit action** — `history_delete` of that id,
  `history_clear`, or a successful `retranscribe` — and only **after** the History write for that
  action succeeded. `recordings_prune` never deletes the MP3, WAV or sidecar of an id that has a
  `<id>.wav`, nor an id being retried; the retrying set is read under `_store_lock` on every
  prune.
- MP3s of successful entries: the first `AUDIO_KEEP` **successful** entries in History order
  (newest first — so a just-resolved entry, moved to the top, keeps its audio) are kept; failed
  and retrying ids are outside this quota; the rest are deleted; a corrupt file deletes nothing.

### Recovery

`recordings_prune` (under the lock, after a successful read of `history.json`) re-inserts the
sidecar entry (or, without a sidecar, an entry built from the WAV) of every `<id>.wav` whose
id is missing from History (finishing the removal of tombstoned ones), at its
time-ordered position, outside the success cap like any failed entry — so a corrupt or reset
`history.json` (which `_load_for_write` backs up and replaces with `[]`) can never make a failed
recording unreachable. Explicit deletion removes the WAV, sidecar and MP3, so a deleted entry is
never resurrected.
- Stray temp files (`.mp3.tmp`, `.wav.tmp`) are removed only when older than 10 minutes, so a
  prune never deletes a temp file another thread is still writing.
- `history_clear` takes `_store_lock` (it removed the file outside the lock, racing writers that
  could write the old list back) and removes all WAVs with their MP3s.

### Stats

`history_stats` reads the full list and ignores failed entries (count, words, speed) — a
failure is not dictation. The weekly chart in the UI skips them too. `Api.history()` returns the
full list (no 1000 cap) so every failed entry stays reachable; the classic UI passes
`limit=100` explicitly. (Paging is out of scope: failed entries accumulate only on failures,
and the page already renders up to 1000 rows.)

## Engine

### Saving a failure (`core`)

`keep_failed_recording(mode, wav, error, app="", raw="", dur=None) -> id | None` writes the
failed entry, saves the MP3 and copies the WAV beside it, then prunes. Any storage error is
logged and returns `None` (the original error is still reported to the user).

`App.process` tracks three facts: `text` (set once transcription succeeded), `protected`
(`early_secure` or `late_secure` seen), and `rid`/`audio_saved`:
- computes `dur` before transcription so a failure can record it;
- empty transcript → keep as failed with the existing message, state `err` (was `ready`);
- `except` → `rid` set and audio not saved → `recording_save(rid, wav)`; no `rid` and (no
  `text` or not `protected`) → keep as failed (`raw = text or ""`); the user still sees
  `friendly_error(e)`;
- every kept failure calls the new hook `on_failed(rid, message)`;
- the WAV is still deleted in `finally`, after any keep/save above.

Edit mode returns from `process` into `_process_edit`, which owns all of its failure handling
(its own try/except), so the outer handler never creates a duplicate for edit.

### Shared conversion

The text processing in `process` (snippet expansion, bypass/light clean, polish with the
per-app profile, prompt, translate, empty-AI rules, `fix_mixed` for normal) moves into one
function used by both `process` and manual transcription:

`convert_text(client, mode, text, app) -> Converted(out, raw, bypass, snippet)`

It has no UI side effects; `process` still emits its "بجهّز البرومبت…/بترجم الكلام…" states
before calling it. Password-field handling stays in `process` (no conversion when
`early_secure`), so behavior is unchanged.

### Manual transcription

`retranscribe(rid) -> {"ok": True, "result": str} | {"ok": False, "err": str}`:
1. Under `_store_lock`, load the entry; refuse unless it exists, is failed, its WAV exists, and
   no retry of that id is running; mark the id as retrying (prune skips it, a second retry is
   refused) and copy the WAV to a private work file. Network calls run outside the lock on that
   copy, so an explicit delete during the retry cannot pull the audio from under a provider.
2. Build a **fresh** `chains.FeatureClient(feature(mode), pools)` with the current settings and
   dictionary — never the engine's cached client, whose per-operation state (`ai_ok`,
   `last_chat`) belongs to live dictation.
3. Transcribe the WAV with automatic language detection (same as live dictation; edit mode uses
   `None` as today).
4. Empty transcript → still failed, error "مطلعش نص".
5. Normal/prompt/translate → `convert_text`; edit → the instruction transcript itself (the
   selection was never stored, so the edit cannot be replayed).
6. Commit under `_store_lock`: re-read; if the entry was deleted meanwhile, delete wins — return
   `{"ok": False, "err": "التسجيل اتمسح"}` and do not recreate it. Otherwise the entry becomes a
   normal entry (`status`/`error` removed; `raw`, `result`, `words`, `engine` set; `time`,
   `time_display`, `date_display` = now, `recorded` = original `time`, `dur` unchanged; moved to
   the top; `_trim` applied; snippet results shown as `[اختصار] <trigger>`); only after that
   write succeeded are the WAV and sidecar deleted. The response carries `result`, so the UI can
   show it for copying even if the row is trimmed later. Normal mode applies `fix_mixed` exactly
   as live dictation does: not raw, no snippet, not a dev app (no insertion target exists, so the
   terminal rule doesn't apply).
7. Processing that fails while transcription succeeded (prompt/translate with AI items and
   `ai_ok` false) resolves the entry with the raw transcript and returns
   `{"ok": True, "result": raw, "note": "مقدرتش أحوّله — ده الكلام زي ما اتقال"}` — the same
   outcome live dictation gives; the transcript is what the user needs to keep.
8. Transcription failure → the entry stays failed with the new `friendly_error` text.
9. The retrying mark and the work copy are cleared in `finally`; prune runs after.
10. Manual transcription never types, pastes, copies or calls `on_text`.

## Bridge and UI

- `Api.history_retry(rid)` → `core.retranscribe(rid)` (runs on pywebview's call thread; the
  page awaits it). `Api.history()` items already carry `audio`; failed items also carry
  `status` and `error`.
- `Controller.on_failed(rid, msg)` shows a Tk toast (sibling of `ResultToast`, same placement and
  hover/expire rules): title "التفريغ فشل — التسجيل اتحفظ في السجل", the reason, and an
  **افتح السجل** button that opens the window on the History page.
- History is reachable even when nothing can transcribe (`canRun` false): the History nav item
  stays enabled and `go("history")` is allowed, so kept recordings can be played, downloaded and
  deleted; a retry then reports the setup error.
- History page, failed row: a red "فشل التفريغ" tag, the error text in place of the result, the
  audio wave/play and download as for any recording, a **تفريغ يدوي** button, delete; no copy
  button until it succeeds. While retrying, the button is disabled and reads "بيفرّغ…";
  afterwards the list reloads and a toast reports success or the new error.
- Home: "Last result" skips failed entries; "Recent" shows a failed row as "⚠ فشل التفريغ".
- Classic Tk UI: `_start_engine` wires `on_failed` to the same failure toast, whose button opens
  the classic history window; there a failed entry shows "⚠ فشل التفريغ — <error>" and a
  **تفريغ يدوي** button instead of copy (PR #17 gate review: the toast sends classic users there,
  so it must offer the action). The retry runs in a thread; success shows the result in
  `ResultToast` (with Copy) and the list reloads; a failure shows the new error in the row.
- Every new Arabic string has an `EN` entry in `i18n.js`.

## Privacy

The previous invariant "a password-field transcript never reaches history or saved recordings"
becomes: **a successful password-field transcript never reaches an AI model, history, saved
recordings, clipboard or toast; a failed password-field recording is kept like any failed
recording, and manual transcription processes it like any other** (user decision). README and
PRIVACY.md state that failed recordings are kept on the device until transcribed or deleted.

## Testing

- History: trimming keeps failed entries beyond the cap; stats ignore failed entries over the
  full list; `Api.history` returns more than 1000 entries.
- Storage order: WAV copy failure → nothing written, `None`; checked history write failure →
  WAV kept, `None`; MP3 failure → entry and WAV still kept.
- Prune: never deletes a failed MP3/WAV (even after "corrupt history → backup → new entry →
  prune"); deletes MP3s of trimmed successful entries; leaves fresh temp files, removes old ones.
- `history_clear` under the lock removes WAVs and MP3s; delete of a failed id removes both.
- `process`: STT error → one failed entry + WAV + MP3 + `on_failed`; empty transcript → failed;
  exception after `history_add` (on_text/paste) → no duplicate **and** the MP3 exists; password
  field STT failure → kept; password field exception **after** a successful transcription → not
  kept; non-password exception after transcription → kept with `raw`; cancel/too short → nothing.
- `_process_edit`: each failure exit keeps one failed edit entry; `clip_failed` keeps the edit
  entry and its MP3; an exception from `on_state("done")` after the save creates no duplicate.
- `retranscribe` additionally: delete before/while the provider reads the audio wins (no
  recreation, error returned, no files left); prune during a retry keeps the WAV; AI failure
  resolves with the raw transcript and a note; a resolved old entry survives the cap and keeps
  its MP3 with more than `AUDIO_KEEP` newer successes; resolving several entries applies the cap;
  two different ids retried while dictation runs; the retrying mark is cleared after an
  exception; edit retries return the instruction only; no paste/clipboard/`on_text` calls;
  raw-mode and snippet results skip `fix_mixed`.
- Storage contracts: `history_add` returns `None` on a failed write and `process` then keeps the
  recording; `history_resolve`/`history_delete` write failures delete no file; `history_clear`
  between WAV copy and publish leaves a consistent state; WAV publish failure leaves the
  temporary WAV in place.
- Recovery: corrupt history → backup → prune re-inserts failed entries from sidecars, files
  intact; a deleted failed entry is not resurrected; a failed sidecar removal leaves a tombstone
  that Recovery skips (then the cap is reached and prune runs again).
- IDs: a fixed clock / repeated timestamp allocates distinct ids and never overwrites another
  recording's files.
- Hooks: `on_failed` or `on_state("err")` raising does not lose the kept recording, and `busy`
  is cleared.
- UI: failed rows are excluded from the weekly chart; History opens with `canRun` false.
- `convert_text`: existing process tests stay green (behavior parity), plus direct cases.
- `retranscribe`: success resolves the entry and removes the WAV; failure keeps it failed with
  the new error; non-failed/missing ids refused; a concurrent retry refused; it uses a fresh
  client, not the engine's.
- Bridge: `history_retry` returns the core result.
- Static UI: new strings have EN entries.
- Live: dictate with an invalid key / offline → the toast appears, the entry is in History,
  Manual transcribe after fixing the key succeeds.
