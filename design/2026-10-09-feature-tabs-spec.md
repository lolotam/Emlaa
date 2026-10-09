# Feature tabs: per-feature hotkeys and provider chains — design

Date: 2026-10-09 · Branch: `feat/feature-tabs` · Base: `main` @ `00a2650` (v1.19)
Revision 3 — after Codex debate rounds 1 and 2 (verdicts at the end of the plan).

## Problem

1. **Hotkeys.** Only a fixed list of keys can be chosen (`emlaa.HOTKEYS`), matched by pynput
   `Key` *name*. Right Alt fails on keyboards where Windows reports it as AltGr: pynput's
   `Key.alt_r` is an *extended* `KeyCode(vk=VK_RMENU)` and `Key.alt_gr` is not, so they compare
   unequal although both are `VK_RMENU` (`pynput/keyboard/_win32.py:117-118`). F7/F8 fail on
   laptops whose top row sends media keys unless Fn is held. Hotkeys are never suppressed, so
   the focused app also receives F7 (caret browsing in browsers).
2. **One provider for everything.** `CFG["provider"]` drives transcription *and* AI processing
   for every mode (`core.App.client`, `core.py:1243`). Fallback order is hard-coded per
   provider (`PROVIDERS[...]["stt_alt"/"chat_alt"]`). A user cannot transcribe with Deepgram
   and polish with Groq, or give the prompt mode a different model than normal dictation.

## Decisions (made with the user)

| # | Decision |
|---|---|
| D1 | Four feature tabs at the top of Settings: **normal · prompt · translate · edit**. |
| D2 | Each tab holds: the hotkey, an ordered **transcription (STT) list**, an ordered **AI-processing list**. Each list item is `provider + model`. The first item runs; on failure the next one runs. |
| D3 | API keys stay **shared** per provider (existing key pools in `.env`), in one Keys section below the tabs. |
| D4 | Page layout: the 4 tabs, then the Keys section, then the general settings (typing, offline model download, app), on one scrolling page with one Save button. |
| D5 | Hotkeys are **recorded from the keyboard**: "one key" or "two keys"; the app saves what the keyboard actually sent. |
| D6 | The recording hotkey is **suppressed** (other apps don't receive it), except bare modifiers (Ctrl, Shift, Alt, Win) used as a single-key hotkey, which keep passing through. |
| D7 | The local Whisper model is an STT list item (`provider: "local"`), replacing the global `offline_mode` switch. |
| D8 | Approach A: one engine runs any feature from its plan; **the user's list is the only fallback order** (no hidden per-provider model fallbacks inside an item). Existing configs migrate automatically, and migration turns today's hidden fallbacks into visible list items so behavior does not change. |
| D9 | One PR. |

## Privacy invariant (unchanged, stated precisely)

A dictation into a password field still sends its **audio to transcription** (existing design
decision, lolotam/Emlaa#2); with a list, transcription may move down the STT list exactly as
it would move to a fallback today. The transcript of a password field never reaches an **AI
model**, the history, the saved recordings, the clipboard or the toast. Tests assert these
five, not "no model".

## Settings schema

`CFG["features"]` — the single source of truth for hotkeys and chains:

```json
{
  "normal":    {"hotkey": [163],      "stt": [{"provider": "groq", "model": "whisper-large-v3-turbo"},
                                              {"provider": "groq", "model": "whisper-large-v3"},
                                              {"provider": "local", "model": ""}],
                                      "ai":  [{"provider": "groq", "model": "qwen/qwen3.8-27b"}]},
  "prompt":    {"hotkey": [165],      "stt": [...], "ai": [...]},
  "translate": {"hotkey": [161],      "stt": [...], "ai": [...]},
  "edit":      {"hotkey": [],         "stt": [...], "ai": [...]}
}
```

- `hotkey`: `[]` (no hotkey), `[vk]` (any key, modifier or not), or `[mod, vk]` where `mod` is
  a modifier vk and `vk` is **not** a modifier. Other two-key shapes are invalid.
- `stt` / `ai`: lists of `{"provider": <pid>, "model": <id>}`. `provider` ∈ `providers.ORDER`
  (+ `"local"` for STT only). `model` is the explicit model id; `""` for `local`.
- `deepgram` and `local` are STT-only and never valid in `ai`.

### Validation (`smart.validate_features`) — on save only

- all four features present; every `stt` list non-empty; `ai` non-empty for prompt, translate,
  edit (normal may be empty = raw); providers known; STT-only providers absent from `ai`;
- hotkey shape as above: vk ints 1–254 only; `0x1B` (Esc) never in a hotkey; a typing key
  (letters, digits, Space, Enter, Tab, Backspace, Delete, arrows, Home/End/PgUp/PgDn, numpad,
  punctuation) is refused **alone** — it would be suppressed in every app — but allowed after
  a modifier (Ctrl + A);
- every non-local `stt` item names a model;
- no two features with the same **non-empty** hotkey (several features may have `[]`); a
  **single modifier hotkey** may not be the modifier of another feature's combo (Right Ctrl
  alone + Right Ctrl+F8 would make the Ctrl press start one mode and the F8 cancel it).

Migration output must always pass validation (tested for every migration case).

### Migration (`core.load_config`) — computed, never written at load

When the loaded file has no `features`, `load_config` **computes** them from the old keys and
keeps `features_custom = False`. It never writes the file at load time — a config file that
failed to parse is not overwritten, and importing `core` in tests writes nothing. The computed
features are persisted the first time the user saves settings.

- Migration reads the **raw file keys before** merging `DEFAULTS` (a file holding only the
  legacy `{"hotkey": "f8"}` must migrate to F8, not to the default `ctrl_r`).
- hotkeys: `hotkey_normal` (or legacy `hotkey`), `hotkey_prompt`, `hotkey_translate`,
  `hotkey_edit` mapped name → vk (`ctrl_r`→`0xA3`, `alt_r`→`0xA5`, `shift_r`→`0xA1`,
  `caps_lock`→`0x14`, `scroll_lock`→`0x91`, `f6`..`f12`→`0x75`..`0x7B`, `""`→`[]`).
- stt (all four features): today's effective order for `provider` — the chosen model
  (`models[provider]`) followed by the remaining entries of `stt` + `stt_alt` — one item per
  model; then `local` appended when `offline_mode == "fallback"` and a pack is installed.
  `offline_mode == "always"` → `[local]` only.
- ai (all four features): the first of `[provider] + CHAT_HELPERS` that has a chat model and a
  key pool, expanded to one item per model of `chat` + `chat_alt`. When no chat provider has a
  key: `ai = []` for normal; prompt/translate/edit get the first chat provider's models (saving
  then works and the run reports the missing key, as today).
- Intended behavior change (accepted): a Deepgram user with no chat key migrates to
  `normal.ai = []`, which is raw — the small local clean-up (`light_clean`, `fix_mixed`) that
  ran before is skipped. Empty AI list = raw is the user-facing rule chosen in design.

## Readiness (`core.can_run()`)

True when at least one feature has an STT item that is usable now: a provider with a non-empty
key pool, or `local` with an installed pack. It replaces every `keys.get(provider)` gate:
engine start (`app_web.py:507`), `save_settings` key requirement (`app_web.py:737`),
`bootstrap.canRun`, `Api.key_remove` (removing a key is refused only when `can_run` would be
false with the pools **after** removal), and the classic UI's equivalents. The welcome screen still asks for one
provider key; after it is saved and `features_custom` is false, features are recomputed from
that provider.

## Engine

### `providers.Client` — strict mode

`Client(pid, key, model=..., keys=..., strict=True, chat_model=...)`: `_stt_models()` returns
`[model]` only and chat uses `[chat_model]` only; `helper` is ignored. Non-strict behavior is
unchanged. Key-pool rotation (`_run`) is kept: rotating keys for the same provider/model is not
a model fallback. Two separate things, never mixed:
- **migration orders** — `providers.stt_order(pid, chosen)` (today's `_stt_models()` order) and
  `providers.chat_models(pid)` (`chat` + `chat_alt`);
- **UI catalogs** — `providers.stt_catalog(pid)` = every id in `MODELS[pid]` plus every id of
  the migration order (OpenAI shows `gpt-4o-transcribe`, `gpt-4o-mini-transcribe`, `whisper-1`),
  and `chat_models(pid)` for AI. The UI always also offers the item's stored model when it is
  missing from the catalog.

### `providers.TextOps` mixin

`polish`, `_polish_rejected`, `to_prompt`, `translate`, `edit`, `_prompt_lang`,
`_classify_lang`, `_stt_prompt`, `_with_vocab`, `_vocab_rule` move unchanged into a mixin that
relies on `self._chat`, `self._chat_raw`, `self.vocab`, `self.vocab_extra`, `self.last_chat`.
`Client(TextOps)` — existing behavior and tests are untouched.

### `chains.FeatureClient(TextOps)` — new module

Same public surface `App.process` uses (`transcribe`, `polish`, `to_prompt`, `translate`,
`edit`, `engine`, `vocab`, `vocab_extra`), plus `stt_local: bool` and `ai_ok: bool`.

- `transcribe` starts a new operation: it resets `last_stt_model`, `last_stt_name`,
  `stt_local`, `last_chat`, and `ai_ok = False`. `_chat`/`_chat_raw` reset `last_chat` per call
  but **never clear `ai_ok`**: `ai_ok` means "at least one AI call of this operation produced
  output" (so `to_prompt` keeping its first answer after a failed language retry still counts).
- `transcribe(wav, lang)`: walks `stt` in order. Before each provider attempt the item's client
  receives the current `vocab` and `vocab_extra` (cached clients too). `local` →
  `offline.transcribe` when a pack is installed, else an error is recorded. A provider without
  a key pool records an error without building a client. Any exception moves to the next item.
  When all fail: raise the first `NetworkError` recorded, else the last error. A list whose
  first item is `local` never builds a provider client before the local attempt.
- `_chat`/`_chat_raw`: walk `ai` with strict clients' `_chat_raw`; the first non-None output
  wins, sets `last_chat` and `ai_ok = True`. All fail or empty list → `_chat` returns the input,
  `_chat_raw` returns `None`.
- Client cache key: `(pid, model, chat_model, tuple(keys))`.

### `core.App`

- `App.client(mode)` caches one FeatureClient per mode, keyed by
  `(mode, json.dumps(feature, sort_keys=True), tuple(sorted((pid, tuple(keys)) for pid, keys in pools.items())))`.
  `Api.key_add` / `key_remove` / `save_settings` call `engine.reset_client()`.
- `process`: the `offline_mode` branches and `_offline_handoff` are removed. **The AI list runs
  whatever served the transcription** — `local` first in the list is a choice (privacy, speed),
  not "no internet". `stt_local` only changes the history engine label.
  **Raw** = `not CFG["polish"]` **or** the feature's `ai` list is empty; raw skips
  `should_bypass`, `light_clean`, `polish` and `fix_mixed` (snippet expansion still runs, as
  today with polish off). Prompt/translate with `ai_ok == False` after the call (no AI item
  produced output — offline, keys exhausted…): the raw text is still typed and the final state
  message says so (`"done"` with `"مقدرتش أحوّله — اتكتب الكلام زي ما اتقال"`); history records
  the mode with the raw text as result.
- `_process_edit`: when `edit()` returns `None` (no AI item produced output) keep today's
  refusal ("معرفتش أعدّل النص"); when the instruction transcription itself fails, report it.
- Hotkey settings saved while `recording` or `busy` are applied when the operation ends
  (`_hotkey_restart_pending`, applied in the `process`/`cancel` exit path), never mid-press —
  replacing the logic mid-`hold` would lose the release that ends the recording.

## Hotkeys

### Representation (pure, `smart.py`)

`Hotkey(mods: frozenset[int], trigger: int)`; `hotkey_from_vks(vks)`;
`vk_label(vk, lang)`; `MODIFIER_VKS`. One matcher used by both the filter and the logic:

`HotkeyMatcher(hotkeys: dict[mode, Hotkey]).match(trigger, held_mods) -> mode | None` — the
mode whose hotkey has this trigger and `mods == held_mods - {trigger}` exactly. F7 and Ctrl+F7
can belong to two different modes.

### Engine — `core.start_hotkey`

pynput `keyboard.Listener(win32_event_filter=filter)`; pynput's `on_press/on_release` are not
used. The filter:

1. ignores our injected events (`dwExtraInfo == EMLAA_TAG`) and the fake Left Ctrl Windows
   sends with AltGr (`vkCode == 0xA2` and `scanCode & 0x200`) — `return False`;
2. updates the held-key set and decides suppression with the matcher **once per physical
   press**: the decision taken at the first keydown of a vk is latched until its keyup, so
   auto-repeat keydowns and the keyup reuse it (suppress the press of a matched non-modifier
   trigger and its repeats and release, even if the modifier was let go first). The held set
   starts from Windows' state (`GetAsyncKeyState` for the **side-specific** modifier vks —
   the hook never releases the generic 0x10–0x12) when the listener starts or resumes, so a
   Ctrl already held is known; before each new press, modifiers Windows no longer reports as
   down are dropped (a release lost on the secure desktop). Enqueues
   `(generation, vk, is_press, time, held_mods)` to the dispatcher;
3. raises `listener.suppress_event()` when suppressing, else `return False`.

`HotkeyDispatcher`: one daemon thread per generation; `stop()` enqueues a sentinel and bumps
the generation so stale events are dropped. Actions run through the same `guard` as today (log
the error, reset `recording`/`_active_key`, report `err`) and the thread survives exceptions.
`restart_hotkey`, `pause_hotkey`, and app shutdown stop listener and dispatcher together.
Caps/Scroll Lock as a suppressed trigger never toggles, so the lock-restore code is removed;
a press that matches a hotkey whose trigger or modifier is Alt or Win sends one `VK_MASK`
press, so the app never sees a bare Alt/Win tap (menu bar / Start menu).

### Capture — `Api.capture_hotkey(feature, count)`

- `App.try_begin_capture() -> bool` reserves the capture **under `_state_lock`**: refused when
  `recording`, `busy` or `capturing`; otherwise sets `capturing = True`. `App.begin` checks
  `capturing` inside the same locked section that reserves `recording`, so a hotkey and a
  capture can never both win. The window's record button goes through `begin` too.
- Then: pause the hotkey listener, run `core.capture_keys(count)`, resume the listener and
  clear `capturing` in `finally`.
- `core.capture_keys` uses `smart.CaptureSession(count, initially_down)`, where
  `initially_down` = keys Windows reports down at the start (`GetAsyncKeyState`). Those keys,
  including their auto-repeat keydowns and their keyup, are never ours and pass through. Only
  keys **pressed during the session** are recorded and suppressed. `count=1` → the result is the
  first captured key released; `count=2` → a modifier plus a non-modifier held together, result
  `[mod, key]`; two non-modifiers or two modifiers → error
  `"لازم زرار منهم يبقى Ctrl أو Alt أو Shift أو Win"`; Esc alone cancels; 10 s timeout →
  "the key didn't reach Windows — on a laptop try Fn + the key".
- **Every exit** (result, error, cancel, timeout) keeps the capture listener running until
  every captured key has been released (cap 3 s), so no suppressed keydown is left without its
  suppressed keyup when the listeners switch.
- Returns `{ok, feature, keys, label}`; the UI writes the result into the `feature` echoed back.

## UI (`source/ui`)

Settings page: tab bar (4 features) → panel: hotkey row (label + "record one key" / "record two
keys" + clear), STT list, AI list. Rows: provider select, model select, ↑ ↓ ✕, "+ add".
Providers with no key → disabled "(no key)"; `local` without a pack → disabled "(not
installed)"; STT-only providers absent from AI selects. During capture all tabs and capture
buttons are disabled. The home page's hotkey chips (`renderKeys`) read `features[*].hotkey`
labels and show the edit feature when it has a hotkey. Keys section: one key-pool block per provider. General: recording mode
(toggle/hold), open-Emlaa shortcut, typing group, offline download group (no mode select),
app group. Every new Arabic string has an `EN` entry.

## Classic UI (`emlaa.py`)

Hotkey selects show legacy names plus, when the stored hotkey is not a legacy single key, an
extra option carrying the stored vk list unchanged. On save the classic dialog builds the full
`features` dict (all four hotkeys at once), validates it with `smart.validate_features`, and
saves once; when any hotkey differs from the stored one it sets `features_custom = True` (so a
later provider change does not recompute and erase it). Its readiness checks use `core.can_run()`. Provider change recomputes features when
`features_custom` is false.

## Testing

Unit (no network/keys/mic/real hook/real clipboard): matcher (F7 vs Ctrl+F7 in two modes, extra
modifiers), filter suppression, dispatcher order/generation/exception survival, capture state
machine (pre-held keys, AltGr, combo shapes, full-release), migration matrix with
`validate_features(default_features(...))` for every case, `load_config` writes nothing,
FeatureClient fallback + state reset between operations, raw definition through `App.process`,
prompt/translate AI failure message, cache invalidation on key change, readiness gates, capture
refusal while recording, classic save of a combo and a swap.
Live: hotkey capture and suppression of F7 / Ctrl+F7 / Right Alt on the user's keyboard; one
dictation per tab.

## Out of scope

Per-feature typing settings, per-tab keys, capture for the open-Emlaa shortcut, Store (MSIX)
changes, new providers.
