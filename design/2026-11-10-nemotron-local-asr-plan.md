# Optional Nemotron 3.5 local ASR — implementation plan

2026-11-10 · branch `T3-CODE/add-optional-nemotron-local-asr` · implementation and parent code/runtime validation complete; interactive recording UI not exercised.

Each step is a reviewable slice; the parent runs the full suite
(`venv/Scripts/python -m unittest discover -s tests -p unit_*.py`) after each
milestone that touches existing code.

## Step 1 — shared primitives (`source/asr_pack.py`)

- `sha256_file(path)` — SHA-256 in 1 MB chunks.
- `stream_download(url, dest, sha256, size, progress, done, total, opener, cancel)`
  — `.part` file, size check, SHA-256 check, `os.replace`, cancel event checked
  per chunk.
- `run(cmd, **kw)` — `subprocess.run` with `capture_output` + `CREATE_NO_WINDOW`.
- `clear_dir(path)`, `remove_inside(root, rels)`, `read_json(path)`,
  `write_json_atomic(path, data)`.

**Done when:** the module imports cleanly and the existing Whisper tests still
pass after `offline.py` delegates to it.

## Step 2 — `source/offline.py` delegates to `asr_pack`

Keep the existing private names as wrappers so the tests that patch them keep
working: `_sha256_file`, `_stream_download`, `_run`, `_clear_staging`,
`_remove_inside`, `CREATE_NO_WINDOW`, `DOWNLOAD_TIMEOUT`.

**Done when:** `tests/unit_offline.py` is unchanged and green.

## Step 3 — the Nemotron engine (`source/nemotron.py`)

- Pins (runtime + model URLs, sizes, SHA-256).
- `_dirs()`, `_open()`, `_opener` hook.
- `installed()`, `verify()`, `cached_verification()` (cached on the manifest
  identity).
- `download(progress, cancel)`: staging → model → runtime archive → safe
  extraction → `nemo-speech.exe --version` smoke test → publish → manifest
  last → stale cleanup.
- `remove()`, `residual()`.
- `build_cmd(wav, model_path, language, out_path)`,
  `language_code(language)`, `transcribe(wav, language)`.

**Done when:** `tests/unit_nemotron.py` is green (all offline, mocked).

## Step 4 — the facade (`source/offline.py`)

- `installed()` → Whisper pack id, else the Nemotron pack id.
- `verify()` / `cached_verification()` → route to the installed engine.
- `download(pack, progress)` → dispatch; after a successful install remove the
  other engine's files (under the shared lock).
- `remove()` / `residual()` → both engines.
- `transcribe(wav, language)` → dispatch to the installed engine.
- `packs()`, `engine_label(pack)`, `engine_title(pack)`, `cancel()`.

**Done when:** `tests/unit_offline.py` + `tests/unit_local_asr_wiring.py` green.

## Step 5 — wiring (`source/chains.py`, `source/app_web.py`, `source/emlaa.py`)

- `chains.py`: `last_stt_model = offline.engine_label(pack)`.
- `app_web.py`: `offline_status()` / `bootstrap()` list all packs; the
  provider name becomes «محلي»; new `offline_cancel()`.
- `emlaa.py`: the classic UI shows the local engine title.

**Done when:** the wiring tests are green.

## Step 6 — the web UI (`source/ui/index.html`, `app.js`, `i18n.js`)

- Label for the new pack in `OFFLINE_MODEL_LABEL`.
- Cancel button next to the progress bar.

**Done when:** the page loads and the section shows the three packs.

## Step 7 — tests

- `tests/unit_nemotron.py` — install/verify/remove/transcribe/cancel/language
  mapping/path safety, all mocked (no network, no real binaries).
- `tests/unit_local_asr_wiring.py` — the facade dispatch, the engine label in
  the history entry, the API payload, the cancel API.

**Done when:** both files are green with the whole suite.

## Step 8 — docs

- `README.md`: the local models section (requirements, sizes, source URLs,
  licenses and attribution) in Arabic **and** in the English summary; the
  settings table row; the developer file list.
- `Emlaa.spec`: add the new modules to `hiddenimports` (defensive, like
  `app_web` / `chains`).

## Step 9 — parent review + real smoke test

The parent obtains the binaries and runs, on a real Windows box:

```
nemo-speech transcribe sample.wav --model <gguf> --language ar-AR --format text --output out.txt --force
```

and then the same through Emlaa (download the pack in Settings → record → check
the transcript and the engine shown in History).

## Parent validation — 2026-11-10

- Updated the branch to current `origin/main` (`f243742`, v1.26) before final tests.
- Full unit suite: **995 tests passed**. Python compilation, JavaScript syntax,
  and `git diff --check` passed. Existing provider tests emit ResourceWarnings.
- Downloaded the separate official model/runtime using `nemotron.download()`
  into an isolated scratch data folder; `offline.installed()` returned
  `nemotron-3.5` and `offline.verify()` returned `True`.
- Actual CPU transcription through `offline.transcribe(..., None)` passed with
  English audio synthesized by Windows and Arabic audio from public Google
  FLEURS (`ar_eg`, test row 0). These are smoke tests, not accuracy benchmarks.
- The runtime archive contains a single top-level folder, `bin/nemo-speech.exe`,
  GGML/NeMo DLLs, and MSVC runtime DLLs. Extracted archive size: 33,072,106 bytes;
  installed model plus runtime: approximately 775 MB (751 MB download).
- Review fixed `_dirs` shadowing in cleanup, preserved raw archive names in
  path validation, and added coverage for cancellation just before publishing.
- Interactive microphone/UI recording and Microsoft Store packaging were not
  tested. The existing packaged-app restriction on offline downloads remains.
