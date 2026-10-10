# Keep Failed Recordings Implementation Plan

> **For agentic workers:** implement task-by-task inline (orchestrator), TDD, commit per task.

**Goal:** A recording whose processing fails is kept (MP3 + WAV) as a failed History entry with
its error, the user is told with an "Open History" toast, and a "Manual transcribe" button
re-runs transcription + the feature's processing on the saved audio.

**Architecture:** Storage rules in `core` (failed entries outside the caps, WAV kept while
failed); `process`'s text processing extracted into `convert_text` shared with a new
`retranscribe(rid)`; `process`/`_process_edit` keep failures and call an `on_failed` hook;
`app_web` bridges `history_retry` and shows a failure toast; the History page renders failed
rows with a retry button.

**Tech Stack:** Python 3.12, pywebview + vanilla JS, Tk (toasts, classic UI), unittest.

**Spec:** `design/2026-10-11-keep-failed-recordings-spec.md`

## Global Constraints

- Tests: `venv/Scripts/python -m unittest discover -s tests -p "unit_*.py"` green after every task.
- Unit tests touch no network, real keys, microphone, clipboard, keyboard hook, real
  `config.json`/`.env`/`history.json`/`recordings/` (patch `HISTORY_PATH`, `RECORDINGS_DIR`,
  `ENV_PATH`; fake `lameenc`).
- Successful history entries keep their current shape; a failed entry is marked only by
  `"status": "failed"` plus `"error"`.
- A successful password-field transcript is never stored; a failed password-field recording is
  kept (user decision).
- Comments follow the files' style (Egyptian Arabic, explaining *why*); every new Arabic UI
  string has an `EN` entry in `source/ui/i18n.js`.
- No new third-party dependency.

---

### Task 1: storage — failed entries, WAV retention, stats

**Files:** `source/core.py` (history section ~265–446). Test `tests/unit_failed_recordings.py` (new).

**Produces:**
- `FAILED = "failed"`; `_is_failed(entry) -> bool`.
- `_trim(items) -> list` — every failed entry plus the first `history_cap()` successful ones,
  order preserved; used by `history_add` and `history_prune` (prune writes only when the trimmed
  list differs).
- `_history_insert(entry) -> bool` — checked write under `_store_lock`; `history_add` returns
  the id only when it returns True (callers handle `None`).
- `history_clear` takes `_store_lock` and removes every WAV with its MP3.
- `history_delete` removes the WAV of deleted ids explicitly (prune never deletes failed audio).
- `history_get(limit=None)` supports a full read; `Api.history` and `history_stats` use it.
- `failed_wav_path(rid) -> str` = `recordings/<id>.wav`.
- `keep_failed_recording(mode, wav, error, app="", raw="", dur=None) -> int | None`: outside the
  lock write `<id>.wav.tmp` + `<id>.json.tmp`; under the lock `os.replace` both and checked
  insert as one step; best-effort MP3 after; failure before publish → `None` and the caller keeps
  its temp WAV; entry has `result=""`, `words=0`.
- `failed_sidecar_path(rid)`; Recovery in `recordings_prune` re-inserts sidecar entries (not
  tombstones) whose id is missing from a successfully read History.
- `_allocate_id() -> int` under `_store_lock`, shared by `history_add` and
  `keep_failed_recording`: `max(now_ms, last + 1)`, skipping ids present in History or on disk;
  unique temp suffixes.
- `_remove_failed_files(rid)`: sidecar first (tombstone on failure), then WAV, then MP3.
- `history_entry(rid) -> dict | None`.
- `history_resolve(rid, raw, result, engine) -> bool` (under the lock: False if the entry is
  gone or not failed; else drops `status`/`error`, sets fields, `recorded` = old `time`, `time` =
  now, moves it to index 0, then removes the WAV) and `history_fail_again(rid, error) -> bool`.
- `recordings_prune()`: reads the retrying set under the lock; never touches an id with a WAV or
  being retried; keeps MP3s of the first `AUDIO_KEEP` successful entries in History order;
  `_remove_stray_tmp` removes `.mp3.tmp`/`.wav.tmp`/`.json.tmp` only when older than 10 minutes.
- `history_resolve`/`history_delete`/`history_clear` delete files only after their History write
  succeeded; `history_resolve` applies `_trim` and updates `time`/`time_display`/`date_display`
  (keeps `dur`, sets `recorded`).
- Existing tests to update: the stray-temp cleanup test in `tests/unit_process.py` (now age-based).
- `history_stats` ignores failed entries.

- [ ] Step 1: failing tests — trim keeps failed beyond cap (cap 10 with 12 successes + 2
  failures → 12 entries); prune never deletes failed MP3/WAV/sidecar and re-lists a missing
  failed entry from its sidecar (Recovery), deletes nothing on corrupt history; resolution
  deletes sidecar → WAV → MP3 only after its History write succeeded, and a failed sidecar
  removal leaves a tombstone; keep_failed_recording writes entry+WAV+sidecar(+MP3); distinct ids
  under a fixed clock; resolve and fail_again; stats ignore failed.
- [ ] Steps 2–5: implement → green → commit `feat(history): keep failed recordings with their audio`.

### Task 2: `convert_text` (behavior-preserving extraction)

**Files:** `source/core.py` (`process` ~1735–1785). Test `tests/unit_failed_recordings.py`.

**Produces:** `Converted = namedtuple("Converted", "out raw bypass snippet ai_failed")`;
`convert_text(client, mode, text, app) -> Converted` holding the empty-AI, prompt, translate,
snippet, bypass/light_clean and polish(profile) rules; `process` keeps its `early_secure` branch
and emits the prompt/translate states before calling it; `fix_mixed` stays in `process` (it
needs the insertion target) and is also applied by `retranscribe` for normal mode outside dev
apps.

- [ ] Steps: direct tests (prompt, translate, empty AI list, snippet, bypass, polish profile) →
  extract → full suite green (parity) → commit `refactor(core): share text conversion`.

### Task 3: keep failures in `process` and `_process_edit`

**Files:** `source/core.py` (`process`, `_process_edit`, `App.on_failed`). Tests
`tests/unit_failed_recordings.py`; update `tests/unit_process.py` / `tests/unit_edit.py` where an
empty transcript expected state `ready`.

**Produces:** `App.on_failed(rid, message)` hook (no-op default). `process` tracks `text`,
`protected` (early/late secure), `rid`, `audio_saved`; empty transcript → kept, state `err`;
`except` → save the MP3 for an existing `rid`, or keep as failed when no `rid` and (no `text` or
not `protected`), `raw = text or ""`. Edit returns early into `_process_edit`, which wraps its
own body: transcription raise / empty instruction / `edit()` None → keep (raw = instruction);
History entry + MP3 written **before** delivery (`clip_failed` keeps them; update the existing
`tests/unit_edit.py` expectation that a clipboard failure saves nothing). `process` also keeps
the recording when `history_add` returns `None` (non-protected), never deletes its temp WAV when
`keep_failed_recording` returned `None` (logs the path), and the `finally` stays responsible for
`busy`, temp cleanup and pending hotkeys even when `on_failed`/`on_state` raise.

- [ ] Steps: failing tests (STT raise → entry+files+hook; empty → failed; raise after
  `history_add` → no duplicate; password-field failure kept; edit exits) → implement → green →
  commit `feat(core): keep the audio of failed recordings`.

### Task 4: `retranscribe`

**Files:** `source/core.py`. Test `tests/unit_failed_recordings.py`.

**Produces:** `retranscribe(rid, client_factory=None) -> dict` per the spec; `_retrying` id set
(under `_store_lock`) refuses concurrent retries and is passed to prune; fresh
`chains.FeatureClient(feature(mode), read_key_pools(ENV_PATH))` with the current dictionary and
snippet triggers; works on a private WAV copy made under the lock; `convert_text` result carries
`ai_failed` (prompt/translate with AI items and `ai_ok` false) → resolved with the raw transcript
plus a `note`; `fix_mixed` only when not raw, no snippet, not a dev app; commit via
`history_resolve` (False → "التسجيل اتمسح"); snippet → `[اختصار] trigger`; never pastes, copies or
calls `on_text`.

- [ ] Steps: failing tests (success resolves + WAV removed; empty transcript stays failed; error
  stays failed with new message; not-failed/missing refused; concurrent refused; fresh client
  not `App.client`) → implement → green → commit `feat(core): transcribe a failed recording again`.

### Task 5: bridge + failure toast

**Files:** `source/app_web.py` (`Api.history_retry`, `Api.history` full list,
`Controller.on_failed`, engine wiring), `source/emlaa.py` (`FailedToast`, shared toast base with
`ResultToast`; classic `_start_engine` wires `on_failed` with `_open_history` as the button). Tests
`tests/unit_failed_recordings.py`, `tests/unit_toast.py`.

- [ ] Steps: failing tests (`history_retry` passes through; engine gets `on_failed`; toast button
  calls the open-history callback) → implement → green → commit
  `feat(ui): tell the user a failed recording was kept`.

### Task 6: History page

**Files:** `source/ui/app.js` (`renderHistory`, click handler, `renderLast`, `renderRecent`,
`renderChart` skips failed, `go`/nav allow History when `canRun` is false; the retry response's
`result`/`note` is shown in a toast with a Copy action),
`source/ui/app.css`, `source/ui/i18n.js`. Static test in `tests/unit_app_web_keys.py`.

- [ ] Steps: implement failed row (tag, error, retry button with busy state, no copy), home
  rules, EN strings → browser check with a stubbed API (failed row, retry success/failure,
  delete) → commit `feat(ui): manual transcription in History`.

### Task 7: classic UI + docs

**Files:** `source/emlaa.py` (`_open_history` rows), `README.md`, `PRIVACY.md`,
`ابدأ من هنا.txt`.

- [ ] Steps: failed rows show the error without copy; docs describe keeping failed recordings
  and Manual transcribe; docs-guard → commit `docs: failed recordings and manual transcription`.

### Task 8: verification

- Full suite + compileall; clean-code-guard and test-guard on the diff; PyInstaller build and
  smoke launch; live check (invalid key → toast + History entry; fix key → Manual transcribe);
  `superpowers:requesting-code-review`.

---

## Debate round 1 — verdicts (Codex `gpt-6.1-sol`, effort high, read-only)

| # | Finding | Sev | Verdict | Reason |
|---|---|---|---|---|
| 1 | Swallowed write/save errors can delete the only copy | P1 | accept | WAV copied first and checked; checked history insert; MP3 best-effort (spec Audio files, T1) |
| 2 | Entry written but MP3 lost when on_text/paste raises | P1 | accept | except path saves the MP3 for an existing `rid` (spec, T3) |
| 3 | Successful password transcript kept after a later error | P1 | accept | keep only when transcription failed or outside a password context (spec case 3, T3) |
| 4 | Retry "succeeds" when AI processing silently fell back | P1 | partial | transcript is safe: resolve with the raw text plus a "couldn't convert" note, same as live dictation; not kept as failed |
| 5 | `history_clear` races writers outside the lock | P1 | accept | under `_store_lock` (T1) |
| 6 | Delete/prune during a retry | P1 | accept | retrying ids skipped by prune; commit re-checks under the lock, delete wins (spec steps 1, 6; T4) |
| 7 | Prune deletes a live `.mp3.tmp` | P1 | accept | stray temp files removed only after 10 minutes (T1) |
| 8 | Corrupt history → backup → next prune deletes failed audio | P1 | accept | failed audio is deleted only by explicit actions; prune skips every id with a WAV (spec Retention) |
| 9 | Resolved old entry trimmed before the user copies it | P1 | accept | resolution moves it to the top with `time` = now; the response carries the result (spec step 6) |
| 10 | Edit `clip_failed` loses the audio | P1 | accept | edit writes entry + MP3 before delivery (spec, T3) |
| 11 | Edit `rid` invisible to the outer handler → duplicate | P2 | accept | `_process_edit` owns all its failure handling (spec, T3) |
| 12 | Failed entries beyond the 1000/100 read limits | P2 | partial | web UI and stats read the full list; the classic fallback keeps 100 |
| 13 | WAV temp leftovers | P2 | accept | `.wav.tmp` included in the age-based cleanup (T1) |
| 14 | Weekly chart counts failed edit words | P2 | accept | failed `words` = 0 and the chart skips failed rows (spec, T6) |
| 15 | History unreachable when nothing can transcribe | P2 | accept | History allowed with `canRun` false (spec UI, T6) |
| 16 | Classic UI never shows the failure toast | P2 | accept | classic `_start_engine` wires `on_failed` (spec, T5) |

## Debate round 2 — verdicts (Codex `gpt-6.1-sol`, effort high, read-only)

Round-1 items 2, 3, 4, 5, 7, 9–16 confirmed fixed; items 1, 6, 8 completed below.

| # | Finding | Sev | Verdict | Reason |
|---|---|---|---|---|
| 1 | WAV copy failure still deletes the temp WAV | P1 | accept | `process` keeps its temp WAV when keeping failed and logs the path (spec Audio files, T3) |
| 6 | Explicit delete can pull the audio from under a running retry | P1 | accept | retry works on a private copy made under the lock (spec step 1, T4) |
| 8 | Orphan-WAV test contradicts the rule; lost rows unreachable | P1 | accept | orphan-delete test removed; sidecar + Recovery re-list failed entries (spec Recovery, T1) |
| 17 | `history_add` returns an id after a failed write | P1 | accept | id only after a successful write; `process` keeps the recording on `None` (spec, T1/T3) |
| 18 | `history_clear` between WAV publish and insert | P1 | accept | publish and insert are one step under the lock (spec, T1) |
| 19 | `AUDIO_KEEP` ordered by id, not by the moved entry | P2 | accept | quota by History order over successful entries (spec Retention, T1) |
| 20 | Resolution can exceed the cap | P2 | accept | `history_resolve` applies `_trim` (T1) |
| 21 | Display time fields inconsistent after resolution | P3 | accept | all three time fields updated, `dur` kept, `recorded` set (spec step 6) |
| 22 | Retry `fix_mixed` broader than live | P2 | accept | same conditions as live: not raw, no snippet, not a dev app (spec step 6, T4) |
| 23 | Full History read is unbounded | P2 | reject | failed entries accumulate only on failures and the page already renders up to 1000 rows; paging is out of scope (noted in spec) |
| 24 | Test plan misses conflicting existing tests and hook failures | P2 | accept | conflicting tests named for update; hook, retry-cleanup, concurrency, no-paste cases added (spec Testing, T1/T3/T4) |

## Debate round 3 — verdicts (Codex `gpt-6.1-sol`, effort high, read-only)

Round-2 items 1, 6, 17–22, 24 confirmed fixed; #8 completed below.

| # | Finding | Sev | Verdict | Reason |
|---|---|---|---|---|
| 1 | Test list still asks prune to delete orphan/resolved WAVs | P1 | accept | replaced by Recovery and explicit-resolution tests (T1) |
| 2 | Clock-derived ids can collide and overwrite files | P1 | accept | one allocator under the lock skipping ids in History or on disk; unique temp names (spec IDs, T1) |
| 3 | A failed file delete lets Recovery resurrect the entry | P2 | accept | sidecar removed first, tombstone on failure, Recovery skips tombstones (spec Audio files, T1) |
