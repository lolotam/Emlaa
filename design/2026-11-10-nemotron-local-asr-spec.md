# Optional Nemotron 3.5 local ASR — design

2026-11-10 · branch `T3-CODE/add-optional-nemotron-local-asr` · status: reviewed; 995 unit tests, Windows build, and English/Arabic CPU smoke tests passed. Interactive recording UI remains untested.

## Problem

Emlaa's offline transcription is whisper.cpp only. The two bundled Whisper packs
(`base`, `small-q5_1`) remain available. NVIDIA publishes **Nemotron 3.5 ASR Streaming 0.6B**, a 0.6B-parameter
multilingual model (Arabic and English are both transcription-ready) that runs
locally on the official **NeMo-Speech.cpp** runtime. The user wants it as an
**additional, optional** local model — not a replacement: Whisper stays the
default, and both engines keep working.

## User requirements and implementation decisions

| Question | Decision |
|---|---|
| Where does the model live? | A **separate copy owned by Emlaa**, downloaded by Emlaa into its own data folder. Never reuse and never delete files belonging to the other project (T3). |
| Replace Whisper? | No. Whisper downloads, manifests, defaults and fallback behaviour stay exactly as they are. Nemotron is one more selectable local pack. |
| Which workflow? | The existing **record → transcribe** workflow only. No streaming microphone mode, no new feature tabs, no change to the four features. |
| How many local models installed at once? | **One pack at a time**, like today's two Whisper packs: downloading a pack removes the previously installed one (otherwise a 750 MB orphan would sit on disk with no UI to remove it). |
| Paid APIs? | None. Everything runs on the user's machine. |

## Pinned artifacts (verified against the upstream releases, not guessed)

### Runtime — NeMo-Speech.cpp

| | |
|---|---|
| Release | `v0.3.0` (published 2026-10-30) — <https://github.com/NVIDIA/NeMo-Speech.cpp/releases/tag/v0.3.0> |
| Asset | `nemo-speech-0.3.0-windows-x86_64-cpu.zip` |
| URL | `https://github.com/NVIDIA/NeMo-Speech.cpp/releases/download/v0.3.0/nemo-speech-0.3.0-windows-x86_64-cpu.zip` |
| Size | `8694509` bytes |
| SHA-256 | `4ed9740e361e4653f56c3dce7d1e81883a1c8b831c1bd7d01567fff1130b5b05` |

The checksum is identical in the GitHub asset `digest`, in the release's
`SHA256SUMS`, and in the adjacent `…zip.sha256` asset.

The **CPU** archive is chosen on purpose: it needs no GPU toolkit and no
GPU driver. CPU compatibility and speed still depend on the machine. The release also ships
`windows-x86_64-vulkan` (22 MB) and `windows-x86_64-cuda` (508 MB) archives;
those need a matching driver and are not pinned here.

Archive layout (per `scripts/windows/package-release.ps1`): `bin/nemo-speech.exe`
plus every DLL it imports, then `lib/`, `include/`, `share/`. The whole tree is
extracted, because the packaging script guarantees the imported DLLs ship in
`bin/`.

### Model — Nemotron 3.5 ASR Streaming 0.6B

| | |
|---|---|
| Repo | `nvidia/nemotron-3.5-asr-streaming-0.6b` — <https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b> |
| Revision | `ea30d66debe3740a08b573244286791d423d6b3e` (pinned in the URL) |
| File | `nemotron-3.5-asr-streaming-0.6b.q8_0.gguf` |
| URL | `https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b/resolve/ea30d66debe3740a08b573244286791d423d6b3e/nemotron-3.5-asr-streaming-0.6b.q8_0.gguf` |
| Size | `742090464` bytes |
| SHA-256 | `3fc991d3badad7277c11030a7519832cddaf2057aafed6d4b25147e953a070b1` |
| License | OpenMDW-1.1 — <https://openmdw.ai/license/1-1/> |

This is the file the model card recommends (`nemotron-3.5-asr-streaming-0.6b.q8_0.gguf`).
It is **not** the older `…-q8_0.gguf` variant used by the other project, so no
binary compatibility with that file is assumed.

The GGUF header was read to confirm the language codes the runtime accepts:
the `asr.rnnt.prompt_dictionary` metadata contains `en`/`en-US` (slot 0),
`ar`/`ar-AR` (slot 7) and `auto` (slot 101).

### CLI contract (read from the v0.3.0 sources)

```
nemo-speech transcribe INPUT --model MODEL --language CODE --format text --output FILE --force
```

- `--language` / `-l` takes a language code; `auto` selects the model's own
  language-ID detection. Unknown codes fall back to `auto`.
- `--output` writes the plain transcript to a file; **without `--force` the
  command refuses to overwrite an existing file**, so Emlaa always passes
  `--force` and removes the stale output first.
- Plain text output is the transcript only (`render()` → `text + "\n"`); the
  runtime strips the `<xx-YY>` language tag from the transcript before printing.
- Diagnostics go to stderr, the result to stdout (or to `--output`).
- Exit code is 0 on success, non-zero on failure.

## Architecture

### New module `source/nemotron.py`

One local ASR engine, self-contained, mirroring the shape of the Whisper engine
in `source/offline.py`:

| Function | Meaning |
|---|---|
| `installed()` | Pack id (`nemotron-3.5`) when the runtime + model are both on disk and consistent with the manifest, else `None`. |
| `download(progress, cancel)` | Downloads runtime + model into a staging folder, verifies size and SHA-256, extracts, smoke-tests `nemo-speech.exe --version`, then publishes the files and writes the manifest **last**. |
| `verify()` / `cached_verification()` | SHA-256 of every manifest file, cached per manifest identity (the model is 742 MB — hashing it on every dictation is not acceptable). |
| `transcribe(wav, language)` | Runs `nemo-speech transcribe` and returns the clean transcript. |
| `remove()` / `residual()` | Removes the pack (and any leftovers of a damaged install). |

Layout under `core.BASE` (`offline/nemo/`), deliberately **separate from the
Whisper tree** so neither engine can delete the other's files by accident:

```
offline/nemo/runtime/bin/nemo-speech.exe   (+ the DLLs it imports)
offline/nemo/models/nemotron-3.5-asr-streaming-0.6b.q8_0.gguf
offline/nemo/manifest.json
offline/nemo/.staging/                      (during a download)
```

### New module `source/asr_pack.py`

The rules that are identical for both engines live here once: verified download
(`.part` file → size check → SHA-256 check → `os.replace`), atomic manifest
write, hash of a file in 1 MB chunks, hidden-window subprocess runner,
recursive delete, and "remove only paths that stay inside the root".

`source/offline.py` keeps its existing private names (`_sha256_file`,
`_stream_download`, `_run`, `_clear_staging`, `_remove_inside`) as thin
delegating wrappers, so the existing tests that patch those names keep working.

### `source/offline.py` becomes the facade over the two engines

| Public function | Whisper (unchanged behaviour) | Nemotron |
|---|---|---|
| `installed()` | pack id from `offline/manifest.json` | pack id from `offline/nemo/manifest.json` |
| `download(pack, progress)` | existing implementation | `nemotron.download()` |
| `verify()` / `cached_verification()` | existing implementation | `nemotron.verify()` |
| `remove()` / `residual()` | existing implementation | `nemotron.remove()` |
| `transcribe(wav, language)` | existing implementation | `nemotron.transcribe()` |
| `packs()` | **new** — the selectable packs with their download size | |
| `engine_label(pack)` | **new** — `"whisper.cpp base"` | `"nemotron-3.5-asr-streaming-0.6b"` |
| `engine_title(pack)` | **new** — `"Whisper محلي"` | `"Nemotron محلي"` |
| `cancel()` | **new** — cancels a running download (both engines) | |

Cross-engine exclusivity: the new pack is installed **first**; only when that
succeeds is the other engine's install removed (under the shared lock). A failed
download therefore never destroys a working installation.

### Language mapping

| Emlaa | Runtime | |
|---|---|---|
| `None` | `auto` | the model detects the language itself (what Emlaa always passes today) |
| `"ar"` | `ar-AR` | |
| `"en"` | `en-US` | |
| anything else | `auto` | |

Unlike Whisper, Nemotron is **not** forced back to Arabic when the transcript
looks Latin: its language-ID detection is part of the model, and forcing the
Arabic prompt on English speech would corrupt it.

### Download safety

- Everything is downloaded into `offline/nemo/.staging`; the staging folder is
  wiped before a download and after a failure.
- The model and the runtime archive are checked against their pinned size and
  SHA-256 before anything is published.
- The archive is extracted with strict path safety: any member with `..`, an
  absolute path, a drive letter or a backslash aborts the whole extraction, and
  the final path of every member must stay inside the destination.
- `nemo-speech.exe --version` must succeed before anything is published.
- The manifest is written **last**, atomically (`tmp` + `os.replace`).
- A download can be cancelled: the chunk loop checks a `threading.Event`, and a
  cancelled download raises, wipes the staging folder and leaves no partial
  installation.

### Transcribe safety

- The subprocess runs with `CREATE_NO_WINDOW` (no console window stealing
  focus) and a 300 s timeout — the Whisper path keeps its 120 s.
- The output file is removed before the run (a stale file must never be read as
  a result) and the command is given `--force`.
- A non-zero exit code, a timeout or a missing/empty output file raise a
  `RuntimeError` with a clear Arabic message; the stderr tail is included in
  the error so the failure is diagnosable from the log.
- The transcript is stripped of the runtime's trailing language tag and
  surrounding whitespace — the clipboard receives the transcript only.

## UI

The existing Settings → «التفريغ من غير إنترنت» section is reused:

- The model dropdown lists the three packs with their **total** download size
  (model + runtime): `base` ≈ 156 MB, `small-q5_1` ≈ 198 MB, `nemotron-3.5` ≈ 751 MB.
  (The Whisper numbers grow by the 8 MB runtime — the old figure showed the
  model file only.)
- The status line shows the installed pack and its size.
- The chain row of the local provider shows the installed pack id.
- A **cancel** button appears next to the progress bar while a download runs.
- The provider name in the feature chains becomes «محلي» (it used to say
  «محلي · Whisper», which would be wrong with Nemotron installed).

## Engine reporting

`chains.FeatureClient` records the engine of the operation:

| Pack | `stt` | `stt_model` |
|---|---|---|
| `base` / `small-q5_1` | `offline` | `whisper.cpp base` (unchanged) |
| `nemotron-3.5` | `offline` | `nemotron-3.5-asr-streaming-0.6b` |

## Not in scope

- Streaming / live microphone transcription with Nemotron.
- Running both local engines side by side.
- Bundling the runtime or the model in `Emlaa.exe` — both are downloaded at
  runtime from NVIDIA's official URLs.
- Publishing, tagging, releasing or merging this work.

## Risks / to verify in the real smoke test

1. The Windows CPU archive must run on a plain Windows 10/11 x64 box (MSVC
   runtime present). The parent obtains the binaries and runs the real command.
2. `nemo-speech` must find the model next to nothing in particular — the GGUF
   is self-contained (tokenizer included), so only the file path matters.
3. Each subprocess loads the model (742 MB mmap). The 300 s timeout bounds a run;
   performance depends on the CPU and recording length.
4. Download size is ~751 MB; extracted runtime and staging require additional disk space.

## Sources

- Model card: <https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b>
- Runtime: <https://github.com/NVIDIA/NeMo-Speech.cpp> (Apache-2.0, third-party
  notices included in the release archive)
- Model license: OpenMDW-1.1 — <https://openmdw.ai/license/1-1/>
