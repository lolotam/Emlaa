# Feature Tabs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this
> plan task-by-task (inline, by the orchestrator). Steps use checkbox (`- [ ]`) syntax.

**Goal:** Settings get four feature tabs (normal, prompt, translate, edit); each has a hotkey
recorded from the keyboard and suppressed, an ordered transcription list and an ordered
AI-processing list; existing configs migrate automatically without behavior change.

**Architecture:** Pure hotkey/schema logic in `smart.py`; `providers.Client` gains a strict
single-model mode and its text operations move into a `TextOps` mixin; a new `chains.py`
`FeatureClient` walks a feature's lists; `core.App` builds one FeatureClient per mode and
dispatches hotkeys from a low-level event filter through an ordered queue; `app_web.py` and
`ui/` expose tabs, list editors and key capture.

**Tech Stack:** Python 3.12, pynput (win32 low-level hook), pywebview + vanilla JS UI, unittest.

**Spec:** `design/2026-10-09-feature-tabs-spec.md` (revision 3)

## Global Constraints

- Tests: `venv/Scripts/python -m unittest discover -s tests -p "unit_*.py"` — green after every
  task; CI runs the same on windows-latest, Python 3.12.
- Unit tests touch no network, no API keys, no microphone, no real clipboard, no real keyboard
  hook, and never write the real `config.json`/`.env` (fakes at the pynput / user32 / providers
  boundary; `load_config` never writes).
- `CFG["features"]` is the single source of truth for hotkeys and chains; schema exactly as in
  the spec (`hotkey`: `[]`, `[vk]`, or `[mod, non-mod vk]`; `stt`/`ai`: lists of
  `{"provider","model"}`).
- Feature ids are exactly `"normal"`, `"prompt"`, `"translate"`, `"edit"`; STT-only providers:
  `"deepgram"`, `"local"`.
- Inside a FeatureClient the user's list order is the only model fallback order (strict
  clients never walk `stt_alt`/`chat_alt`); key-pool rotation within one item is kept.
- Privacy invariant (spec): a password-field transcript never reaches an AI model, history,
  saved recordings, clipboard or toast.
- Every new Arabic UI string has an `EN` entry in `source/ui/i18n.js`.
- Comments follow the files' style (Egyptian Arabic, explaining *why*).
- No new third-party dependency.

---

## File map

| File | Responsibility | Change |
|---|---|---|
| `source/smart.py` | pure logic | vk tables, `Hotkey`, `HotkeyMatcher`, `vk_label`, combo-aware `HotkeyLogic`, `HotkeyFilter`, `CaptureSession`, `default_features`, `validate_features` |
| `source/providers.py` | provider calls | `TextOps` mixin (moved code), `strict`/`chat_model` on `Client`, `chat_models`, `stt_order`, `stt_catalog` |
| `source/chains.py` | **new** | `FeatureClient` |
| `source/core.py` | engine | computed migration in `load_config`, `can_run`, `App.client(mode)`, process/edit wiring, `HotkeyDispatcher`, `start/restart/pause/resume_hotkey`, `capture_keys`, `capturing` gate |
| `source/app_web.py` | JS bridge | readiness gates, `bootstrap` features + catalog, `save_settings` features, `capture_hotkey`, `reset_client` on key changes |
| `source/ui/*` | Settings page | tabs, list editors, capture buttons, keys per provider |
| `source/emlaa.py` | classic Tk UI | features-based hotkeys and readiness |
| `Emlaa.spec` | build | `hiddenimports` += `'chains'` |
| `README.md`, `ابدأ من هنا.txt` | docs | settings section |
| tests | | new: `unit_features.py`, `unit_chains.py`, `unit_hotkey_capture.py`; updated: see each task |

---

### Task 1: vk model, labels and the single matcher (`smart.py`)

**Files:** `source/smart.py` (after `TAP_MAX`, ~line 206). Test: `tests/unit_hotkey_capture.py` (new).

**Produces:**
- `MODIFIER_VKS = frozenset({0x10,0x11,0x12,0xA0,0xA1,0xA2,0xA3,0xA4,0xA5,0x5B,0x5C})`
- `LEGACY_HOTKEY_VKS = {"ctrl_r":0xA3,"alt_r":0xA5,"shift_r":0xA1,"caps_lock":0x14,"scroll_lock":0x91,"f6":0x75,"f7":0x76,"f8":0x77,"f9":0x78,"f10":0x79,"f11":0x7A,"f12":0x7B}`
- `Hotkey = namedtuple("Hotkey", "mods trigger")`; `hotkey_from_vks(vks) -> Hotkey | None`
  (`[]`→None, `[t]`→`Hotkey(frozenset(), t)`, `[m, t]`→`Hotkey(frozenset({m}), t)`)
- `hotkey_shape_ok(vks) -> bool` — `[]`, `[any]`, or `[mod, non-mod]` (not Esc anywhere)
- `HotkeyMatcher(hotkeys: dict[str, Hotkey])` with `match(trigger: int, held: frozenset) -> str | None`
  (mode whose trigger == `trigger` and `mods == (held & MODIFIER_VKS) - {trigger}`) and
  `triggers() -> set[int]`
- `vk_label(vk, lang="ar") -> str`, `hotkey_label(vks, lang="ar") -> str` (`" + "` joined)

- [ ] **Step 1: failing tests**

```python
F7, F8, LCTRL, RCTRL, RALT = 0x76, 0x77, 0xA2, 0xA3, 0xA5
class TestHotkeyModel(unittest.TestCase):
    def test_shapes(self):
        self.assertEqual(smart.hotkey_from_vks([F7]), smart.Hotkey(frozenset(), F7))
        self.assertEqual(smart.hotkey_from_vks([LCTRL, F7]), smart.Hotkey(frozenset({LCTRL}), F7))
        self.assertIsNone(smart.hotkey_from_vks([]))
        self.assertTrue(smart.hotkey_shape_ok([RCTRL]))
        self.assertFalse(smart.hotkey_shape_ok([0x41, 0x42]))      # two non-modifiers
        self.assertFalse(smart.hotkey_shape_ok([LCTRL, RALT]))     # two modifiers
        self.assertFalse(smart.hotkey_shape_ok([0x1B]))
    def test_labels(self):
        self.assertEqual(smart.hotkey_label([LCTRL, F7], "en"), "Left Ctrl + F7")
        self.assertEqual(smart.vk_label(RALT, "ar"), "Alt اليمين")
        self.assertEqual(smart.vk_label(0xB3, "en"), "Media Play/Pause")
        self.assertEqual(smart.vk_label(0xFE, "en"), "Key 0xFE")
class TestMatcher(unittest.TestCase):
    def setUp(self):
        self.m = smart.HotkeyMatcher({"normal": smart.Hotkey(frozenset(), F7),
                                      "prompt": smart.Hotkey(frozenset({LCTRL}), F7),
                                      "translate": smart.Hotkey(frozenset(), RCTRL)})
    def test_same_trigger_two_modes(self):
        self.assertEqual(self.m.match(F7, frozenset()), "normal")
        self.assertEqual(self.m.match(F7, frozenset({LCTRL})), "prompt")
    def test_extra_modifier_matches_nothing(self):
        self.assertIsNone(self.m.match(F7, frozenset({0xA0})))          # Shift+F7
        self.assertIsNone(self.m.match(F7, frozenset({LCTRL, 0xA0})))   # Ctrl+Shift+F7
    def test_modifier_trigger_ignores_itself_in_held(self):
        self.assertEqual(self.m.match(RCTRL, frozenset({RCTRL})), "translate")
```

- [ ] **Step 2:** run `venv/Scripts/python -m unittest discover -s tests -p "unit_hotkey_capture.py"`, expect `AttributeError`.
- [ ] **Step 3:** implement. `vk_label` table: L/R and generic Ctrl/Shift/Alt/Win (Arabic: `"Ctrl اليمين"`, `"Ctrl الشمال"`…; English: `"Right Ctrl"`, `"Left Ctrl"`…), F1–F24, A–Z, 0–9, Caps/Scroll/Num Lock, Space, Tab, Insert, Home, End, PgUp, PgDn, Pause, media `0xAD–0xB7` (Mute, Volume Down, Volume Up, Media Next, Media Prev, Media Stop, Media Play/Pause, Mail, Media Select), browser `0xA6–0xAC`; unknown → `"Key 0x%02X"`.
- [ ] **Step 4:** PASS. **Step 5:** commit `feat(hotkey): vk-based hotkey model, labels and matcher`.

---

### Task 2: combo-aware `HotkeyLogic` and `HotkeyFilter` (`smart.py`)

**Files:** `source/smart.py:209-` (`HotkeyLogic`). Tests: `tests/unit_hotkey.py` (existing — unchanged and passing), `tests/unit_hotkey_capture.py`.

**Consumes:** Task 1. **Produces:**
- `HotkeyLogic(matcher_or_key_map, mode_type, tap_max=TAP_MAX, alt_keys=(), cancel_keys=())` — accepts a `HotkeyMatcher` **or** the legacy `{key: mode}` dict (wrapped as single-key hotkeys) so `unit_hotkey.py` keeps working; `press(key, now, recording, busy, held=frozenset())`. The logic decides "is this a hotkey press" only through `matcher.match(key, held)`; keys tracked internally by `(key)` as today. A trigger pressed with non-matching modifiers behaves like any other key (spoils toggle taps; cancels a running hold recording).
- `HotkeyFilter(matcher, initially_down=frozenset())` with `event(vk, is_press, injected, fake_altgr_ctrl) -> tuple[bool, bool]` = `(dispatch, suppress)` and `held() -> frozenset[int]`:
  `down` starts as `initially_down` (core passes the modifier vks Windows reports down);
  injected or fake AltGr Ctrl → `(False, False)` and state untouched; otherwise `dispatch=True`.
  The suppress decision is **latched per physical press**: at the first keydown of a vk not in
  `down`, decide `suppress = matcher.match(vk, held_mods) is not None and vk ∉ MODIFIER_VKS`
  and store it in `latched[vk]`; auto-repeat keydowns (vk already in `down`) and the keyup
  return `latched.get(vk, False)`; the keyup then removes vk from `down` and `latched`.

- [ ] **Step 1: failing tests**

```python
class TestFilter(unittest.TestCase):
    def make(self):
        return smart.HotkeyFilter(smart.HotkeyMatcher({
            "normal": smart.Hotkey(frozenset(), F7),
            "prompt": smart.Hotkey(frozenset({LCTRL}), F8),
            "translate": smart.Hotkey(frozenset(), RALT)}))
    def test_single_trigger_suppressed_press_and_release(self):
        f = self.make()
        self.assertEqual(f.event(F7, True, False, False), (True, True))
        self.assertEqual(f.event(F7, False, False, False), (True, True))
    def test_unmatched_modifier_combination_is_not_suppressed(self):
        f = self.make()
        f.event(LCTRL, True, False, False)
        self.assertEqual(f.event(F7, True, False, False), (True, False))   # Ctrl+F7 stays the app's
    def test_combo_release_suppressed_after_modifier_released_first(self):
        f = self.make()
        f.event(LCTRL, True, False, False)
        self.assertEqual(f.event(F8, True, False, False), (True, True))
        f.event(LCTRL, False, False, False)
        self.assertEqual(f.event(F8, False, False, False), (True, True))
    def test_bare_modifier_trigger_never_suppressed(self):
        self.assertEqual(self.make().event(RALT, True, False, False), (True, False))
    def test_injected_and_fake_ctrl_ignored(self):
        f = self.make()
        self.assertEqual(f.event(F7, True, True, False), (False, False))
        self.assertEqual(f.event(LCTRL, True, False, True), (False, False))
        self.assertEqual(f.held(), frozenset())
    def test_decision_latched_across_repeats(self):
        f = self.make()
        self.assertEqual(f.event(F7, True, False, False), (True, True))
        f.event(LCTRL, True, False, False)                                   # Ctrl pressed mid-hold
        self.assertEqual(f.event(F7, True, False, False), (True, True))      # repeat still eaten
        self.assertEqual(f.event(F7, False, False, False), (True, True))
    def test_initially_held_ctrl_is_known(self):
        f = smart.HotkeyFilter(self.make()._matcher, initially_down=frozenset({LCTRL}))
        self.assertEqual(f.event(F7, True, False, False), (True, False))     # Ctrl+F7, not F7
class TestComboLogic(unittest.TestCase):
    def matcher(self):
        return smart.HotkeyMatcher({"normal": smart.Hotkey(frozenset(), F7),
                                    "prompt": smart.Hotkey(frozenset({LCTRL}), F7)})
    def test_toggle_same_trigger_two_modes(self):
        lg = smart.HotkeyLogic(self.matcher(), "toggle")
        lg.press(F7, 0.0, False, False, held=frozenset())
        self.assertEqual(lg.release(F7, 0.1, False, False), ["begin:normal"])
        lg.press(F7, 1.0, False, False, held=frozenset({LCTRL}))
        self.assertEqual(lg.release(F7, 1.1, False, False), ["begin:prompt"])
    def test_hold_extra_modifier_does_not_begin(self):
        lg = smart.HotkeyLogic(self.matcher(), "hold")
        self.assertEqual(lg.press(F7, 0.0, False, False, held=frozenset({0xA0})), [])
    def test_hold_combo_begin_end(self):
        lg = smart.HotkeyLogic(self.matcher(), "hold")
        self.assertEqual(lg.press(F7, 0.0, False, False, held=frozenset({LCTRL})), ["begin:prompt"])
        self.assertEqual(lg.release(F7, 0.4, True, False), ["end"])
```

- [ ] **Step 2:** fail. **Step 3:** implement (toggle remembers the mode matched at press time per held key; release fires that mode). **Step 4:** full suite green. **Step 5:** commit `feat(hotkey): combo-aware logic and suppression filter`.

---

### Task 3: `CaptureSession` (`smart.py`)

**Files:** `source/smart.py`; test `tests/unit_hotkey_capture.py`.

**Produces:** `CaptureSession(count, initially_down=frozenset())`; `event(vk, is_press, fake_altgr_ctrl) -> bool` (returns
whether this event belongs to the session and must be suppressed); `decided` (result, error or
cancel known), `finished` (decided **and** every captured key released), `cancelled`,
`error: str | None`, `result: list[int] | None`, `captured_down() -> frozenset`.
Rules: fake AltGr Ctrl → ignored (`False`). Keys in `initially_down` are never ours — their
auto-repeat keydowns and their keyup return `False` — until their keyup, after which a new
press of that key is ours. A release of a key not pressed during the session → `False`.
Esc press with nothing captured → `cancelled` (Esc itself is ours: suppressed). Auto-repeat of a
captured key → ours, no state change. `count=1`: decided on the first release of a captured
key, result `[vk]`. `count=2`: once two captured keys have been down together, decided on the
first release of either; result `[mod, key]`; a pair that is not one modifier + one
non-modifier → `error = "لازم زرار منهم يبقى Ctrl أو Alt أو Shift أو Win"`, `result = None`.
After `decided`, events of captured keys stay ours (suppressed) until `finished`.

- [ ] **Step 1: failing tests**

```python
class TestCapture(unittest.TestCase):
    def feed(self, s, events):
        return [s.event(vk, down, fake) for vk, down, fake in events]
    def test_altgr_records_right_alt(self):
        s = smart.CaptureSession(1)
        self.feed(s, [(LCTRL, True, True), (RALT, True, False), (LCTRL, False, True), (RALT, False, False)])
        self.assertEqual((s.finished, s.result), (True, [RALT]))
    def test_key_held_before_session_passes_through_including_repeats(self):
        s = smart.CaptureSession(1, initially_down=frozenset({LCTRL}))
        self.assertEqual(self.feed(s, [(LCTRL, True, False), (LCTRL, False, False)]), [False, False])
        self.assertFalse(s.decided)
    def test_two_keys_finished_only_after_full_release(self):
        s = smart.CaptureSession(2)
        self.feed(s, [(F7, True, False), (LCTRL, True, False), (F7, False, False)])
        self.assertTrue(s.decided)
        self.assertFalse(s.finished)
        self.assertTrue(s.event(LCTRL, False, False))     # still ours: suppressed
        self.assertTrue(s.finished)
        self.assertEqual(s.result, [LCTRL, F7])
    def test_single_key_waits_for_other_captured_keys(self):
        s = smart.CaptureSession(1)
        self.feed(s, [(F7, True, False), (F8, True, False), (F7, False, False)])
        self.assertEqual((s.decided, s.finished, s.result), (True, False, [F7]))
        s.event(F8, False, False)
        self.assertTrue(s.finished)
    def test_two_non_modifiers_rejected(self):
        s = smart.CaptureSession(2)
        self.feed(s, [(0x41, True, False), (0x42, True, False), (0x41, False, False), (0x42, False, False)])
        self.assertTrue(s.finished)
        self.assertIsNone(s.result)
        self.assertIsNotNone(s.error)
    def test_escape_cancels(self):
        s = smart.CaptureSession(1)
        s.event(0x1B, True, False)
        self.assertTrue(s.cancelled)
```

- [ ] **Steps 2–5:** fail → implement → pass → commit `feat(hotkey): capture state machine`.

---

### Task 4: `TextOps` mixin, strict `Client`, catalogs (`providers.py`)

Runs before the schema task because migration needs the catalogs.

**Files:** `source/providers.py`. Tests: all existing provider/prompt/edit/auto-language tests unchanged; new tests in `tests/unit_chains.py`.

**Produces:**
- `class TextOps:` — moved verbatim: `_stt_prompt`, `_with_vocab`, `_vocab_rule`, `polish`, `_polish_rejected`, `_prompt_lang`, `_classify_lang`, `to_prompt`, `translate`, `edit`. `class Client(TextOps)`.
- `Client.__init__(..., strict=False, chat_model=None)`; strict: `_stt_models()` → `[self.model]` (`RuntimeError("مفيش موديل تفريغ")` when None); `_oa_chat`/`_gemini_chat` candidates `[self.chat_model]`; `_chat`/`_chat_raw` ignore `helper` (strict chat on a provider without `chat` raises `RuntimeError`).
- `chat_models(pid) -> list[str]` (`chat` + `chat_alt`, `[]` for STT-only) — migration order **and** AI catalog.
- `stt_order(pid, chosen=None) -> list[str]` — today's `_stt_models()` order for that choice (migration only).
- `stt_catalog(pid) -> list[str]` — every id in `MODELS[pid]`, then any id of `stt_order(pid)` not already listed (UI only).

- [ ] **Step 1: failing tests**

```python
class TestStrictClient(unittest.TestCase):
    def test_strict_stt_only_chosen_model(self):
        cl = providers.Client("groq", "k", model="whisper-large-v3", strict=True)
        self.assertEqual(cl._stt_models(), ["whisper-large-v3"])
    def test_strict_chat_does_not_walk_chat_alt(self):
        cl = providers.Client("groq", "k", strict=True, chat_model="openai/gpt-oss-20b")
        seen = []
        def create(**kw):
            seen.append(kw["model"])
            raise RuntimeError("model_not_found")
        fake = mock.Mock()
        fake.with_options.return_value.chat.completions.create.side_effect = create
        with mock.patch.object(cl, "_openai", return_value=fake), mock.patch("core.log_error"):
            self.assertIsNone(cl._chat_raw("sys", "نص"))
        self.assertEqual(seen, ["openai/gpt-oss-20b"])
    def test_catalogs(self):
        self.assertEqual(providers.chat_models("deepgram"), [])
        self.assertEqual(providers.chat_models("groq")[0], providers.PROVIDERS["groq"]["chat"])
        self.assertEqual(providers.stt_order("groq", "whisper-large-v3")[0], "whisper-large-v3")
        self.assertEqual(providers.stt_catalog("openai")[:3],
                         ["gpt-4o-transcribe", "gpt-4o-mini-transcribe", "whisper-1"])
```

- [ ] **Step 2:** fail. **Step 3:** cut/paste the methods (no edits), add strict + catalogs. **Step 4:** full suite green with **zero** edits to existing tests. **Step 5:** commit `refactor(providers): TextOps mixin and strict single-model client`.

---

### Task 5: features schema — compute, validate, readiness

**Files:** `source/smart.py` (`FEATURES`, `default_features`, `validate_features`), `source/core.py` (`load_config` ~686, `can_run`, `feature`). Test `tests/unit_features.py` (new).

**Consumes:** Tasks 1, 4. **Produces:**
- `smart.FEATURES = ("normal", "prompt", "translate", "edit")`
- `smart.default_features(cfg, pools, local_model, stt_orders, chat_orders) -> dict` where `stt_orders = {pid: providers.stt_order(pid, cfg["models"].get(pid))}`, `chat_orders = {pid: providers.chat_models(pid)}` — rules exactly as the spec's Migration section. `cfg` is the **raw file dict before DEFAULTS are merged**; defaults fill only keys the file lacks *after* the legacy `hotkey` → `hotkey_normal` fallback.
- `smart.validate_features(features) -> str | None` — the spec's Validation section.
- `core.load_config()`: if the file has no `features` → `cfg["features"] = smart.default_features(...)` (pools from `providers.read_key_pools(ENV_PATH)`, `offline.installed()`), `cfg["features_custom"] = False`; **no `save_config` call**. Parse failure keeps today's behavior (defaults, nothing written).
- `core.can_run(cfg=None, pools=None, local=None) -> bool` — the spec's Readiness section.
- `core.feature(mode) -> dict`.

- [ ] **Step 1: failing tests**

```python
STT = {"groq": ["whisper-large-v3-turbo", "whisper-large-v3"], "deepgram": ["nova-3", "whisper-large"]}
CHAT = {"groq": ["qwen/qwen3.8-27b", "openai/gpt-oss-120b"], "gemini": ["g1", "g2"], "openai": ["o1"], "deepgram": []}
def mig(pools=None, local=None, **cfg):
    base = {"provider": "groq", "models": {}, "hotkey_normal": "ctrl_r", "hotkey_prompt": "alt_r",
            "hotkey_translate": "shift_r", "hotkey_edit": "", "offline_mode": "fallback"}
    base.update(cfg)
    return smart.default_features(base, pools if pools is not None else {"groq": ["k"]}, local, STT, CHAT)
CASES = [dict(), dict(local="base"), dict(local="base", offline_mode="always"),
         dict(provider="deepgram", pools={"deepgram": ["d"], "gemini": ["g"]}),
         dict(provider="deepgram", pools={"deepgram": ["d"]}), dict(pools={})]
class TestMigration(unittest.TestCase):
    def test_every_case_passes_validation(self):
        for c in CASES:
            self.assertIsNone(smart.validate_features(mig(**c)), c)
    def test_hotkeys_from_names(self):
        f = mig()
        self.assertEqual([f[m]["hotkey"] for m in smart.FEATURES], [[0xA3], [0xA5], [0xA1], []])
    def test_stt_keeps_todays_fallbacks_visible(self):
        self.assertEqual([i["model"] for i in mig()["normal"]["stt"]],
                         ["whisper-large-v3-turbo", "whisper-large-v3"])
    def test_offline_fallback_appends_local(self):
        self.assertEqual(mig(local="base")["normal"]["stt"][-1], {"provider": "local", "model": ""})
    def test_offline_always_is_local_only_everywhere(self):
        f = mig(local="base", offline_mode="always")
        self.assertTrue(all(f[m]["stt"] == [{"provider": "local", "model": ""}] for m in smart.FEATURES))
    def test_ai_mirrors_hidden_chat_fallbacks(self):
        self.assertEqual([i["model"] for i in mig()["prompt"]["ai"]], CHAT["groq"])
    def test_deepgram_borrows_first_chat_provider_with_key(self):
        f = mig(provider="deepgram", pools={"deepgram": ["d"], "gemini": ["g"]})
        self.assertEqual({i["provider"] for i in f["prompt"]["ai"]}, {"gemini"})
class TestValidate(unittest.TestCase):
    def bad(self, mutate):
        f = mig(); mutate(f)
        self.assertIsNotNone(smart.validate_features(f))
    def test_rules(self):
        self.bad(lambda f: f["prompt"].update(hotkey=[0xA3]))                        # duplicate
        self.bad(lambda f: f["prompt"].update(ai=[]))                                 # empty ai
        self.bad(lambda f: f["normal"].update(ai=[{"provider": "deepgram", "model": "x"}]))
        self.bad(lambda f: f["normal"].update(stt=[]))
        self.bad(lambda f: f["edit"].update(hotkey=[0x1B]))
        self.bad(lambda f: f["edit"].update(hotkey=[0x41, 0x42]))
        self.bad(lambda f: f["edit"].update(hotkey=[0xA3, 0x77]))   # Right Ctrl alone is normal's hotkey
        self.assertIsNone(smart.validate_features(mig()))
    def test_several_empty_hotkeys_allowed(self):
        f = mig()
        for m in smart.FEATURES:
            f[m]["hotkey"] = []
        self.assertIsNone(smart.validate_features(f))
class TestLoadConfig(unittest.TestCase):
    # patch core.CFG_PATH / ENV_PATH to temp files, offline.installed -> None
    def test_missing_features_computed_not_written(self): ...  # file bytes unchanged after load
    def test_existing_features_kept(self): ...
    def test_corrupt_file_not_overwritten(self): ...
    def test_legacy_hotkey_only_file_migrates_to_f8(self): ...   # file {"hotkey": "f8"} -> normal [0x77]
class TestCanRun(unittest.TestCase):
    def test_any_usable_stt_item(self): ...   # groq key → True; no keys, local installed in some list → True; neither → False
```

(The `...` tests are written in full in the step; each asserts the stated condition with temp files and `mock.patch.object(core.offline, "installed")`.)

- [ ] **Steps 2–5:** fail → implement → pass → commit `feat(settings): per-feature schema, computed migration, validation, readiness`.

---

### Task 6: `chains.FeatureClient`

**Files:** create `source/chains.py`; `Emlaa.spec` `hiddenimports` += `'chains'`. Test `tests/unit_chains.py`.

**Consumes:** Task 4. **Produces:** `FeatureClient(feature, pools, client_factory=None)` — spec behavior; attributes `vocab`, `vocab_extra`, `last_stt_model`, `last_stt_name`, `last_chat`, `stt_local`, `ai_ok`; `engine()`; default factory `providers.Client(pid, keys[0], model=model, keys=keys, strict=True, chat_model=chat_model)`, cached by `(pid, model, chat_model, tuple(keys))`. Before each STT attempt the item's client gets `vocab = list(self.vocab)` and `vocab_extra = list(self.vocab_extra)` (cached clients too). `ai_ok` is reset only by `transcribe` and set True by any AI success — a later failed call in the same operation never clears it. Test helpers: `_clients_for_test()` (cached clients in creation order) and `_ai_items_for_test()` (the live `ai` list).

- [ ] **Step 1: failing tests**

```python
class FakeProv:
    def __init__(self, pid, model, chat_model, fail=None):
        self.pid, self.model, self.chat_model, self.fail = pid, model, chat_model, fail
        self.vocab, self.vocab_extra, self.last_stt_model = [], [], None
        self.seen_vocab = None
    def transcribe(self, wav, lang):
        self.seen_vocab = (list(self.vocab), list(self.vocab_extra))
        if self.fail: raise self.fail
        self.last_stt_model = self.model
        return "نص:" + self.pid + ":" + self.model
    def _chat_raw(self, system, text, temperature=0.2):
        if self.fail: raise self.fail
        return "AI:" + self.pid + ":" + self.chat_model
def build(feature, fails=None, pools=None):
    # fails: {pid: exc} or {(pid, model): exc}
    fails, made = fails or {}, []
    pools = pools if pools is not None else {"groq": ["k"], "gemini": ["k"], "deepgram": ["k"]}
    def factory(pid, keys, model, chat_model):
        made.append(pid)
        return FakeProv(pid, model, chat_model, fails.get((pid, model or chat_model), fails.get(pid)))
    return chains.FeatureClient(feature, pools, client_factory=factory), made
FEAT = {"hotkey": [], "stt": [{"provider": "deepgram", "model": "nova-3"}, {"provider": "groq", "model": "w"}],
        "ai": [{"provider": "groq", "model": "q"}, {"provider": "gemini", "model": "g"}]}
class TestStt(unittest.TestCase):
    def test_first_item_serves(self):
        self.assertEqual(build(FEAT)[0].transcribe("w.wav", None), "نص:deepgram:nova-3")
    def test_next_item_on_any_error(self):
        fc, made = build(FEAT, fails={"deepgram": RuntimeError("HTTP 429")})
        self.assertEqual(fc.transcribe("w.wav", None), "نص:groq:w")
        self.assertEqual(made, ["deepgram", "groq"])
    def test_missing_key_skips_without_client(self):
        fc, made = build(FEAT, pools={"groq": ["k"]})
        self.assertEqual(fc.transcribe("w.wav", None), "نص:groq:w")
        self.assertEqual(made, ["groq"])
    def test_same_provider_two_models_in_order(self):
        feat = dict(FEAT, stt=[{"provider": "groq", "model": "a"}, {"provider": "groq", "model": "b"}],
                    ai=[{"provider": "groq", "model": "q1"}, {"provider": "groq", "model": "q2"}])
        fc, _ = build(feat, fails={("groq", "a"): RuntimeError("404"), ("groq", "q1"): RuntimeError("404")})
        self.assertEqual(fc.transcribe("w.wav", None), "نص:groq:b")
        self.assertEqual(fc._chat("sys", "نص"), "AI:groq:q2")
        self.assertEqual((fc.engine()["stt_model"], fc.engine()["chat_model"]), ("b", "q2"))
    def test_vocab_reaches_provider_client_every_operation(self):
        fc, _ = build(FEAT)
        fc.vocab, fc.vocab_extra = ["Next.js"], ["إيميلي"]
        fc.transcribe("w.wav", None)
        fc.vocab = ["Docker"]
        fc.transcribe("w.wav", None)
        self.assertEqual(fc._clients_for_test()[0].seen_vocab, (["Docker"], ["إيميلي"]))
    def test_network_error_preferred_when_all_fail(self):
        fc, _ = build(FEAT, fails={"deepgram": providers.NetworkError("dns"), "groq": RuntimeError("HTTP 401")})
        with self.assertRaises(providers.NetworkError):
            fc.transcribe("w.wav", None)
    def test_local_first_builds_no_provider_client(self):
        fc, made = build(dict(FEAT, stt=[{"provider": "local", "model": ""}, {"provider": "groq", "model": "w"}]))
        with mock.patch.object(chains.offline, "installed", return_value="base"), \
                mock.patch.object(chains.offline, "transcribe", return_value="محلي"):
            self.assertEqual(fc.transcribe("w.wav", None), "محلي")
        self.assertEqual((made, fc.stt_local), ([], True))
class TestAi(unittest.TestCase):
    def test_ai_order_and_ok_flag(self):
        fc, _ = build(FEAT, fails={"groq": RuntimeError("HTTP 429")})
        fc.transcribe("w.wav", None)
        self.assertEqual(fc._chat("sys", "نص"), "AI:gemini:g")
        self.assertTrue(fc.ai_ok)
    def test_ai_ok_survives_a_later_failed_call(self):
        # to_prompt keeps its first answer when the language retry fails — still an AI result
        fc, _ = build(FEAT)
        fc.transcribe("w.wav", None)
        fc._chat("sys", "نص")
        fc._ai_items_for_test().clear()
        self.assertIsNone(fc._chat_raw("sys", "نص"))
        self.assertTrue(fc.ai_ok)
    def test_all_fail(self):
        fc, _ = build(FEAT, fails={"groq": RuntimeError("x"), "gemini": RuntimeError("y")})
        self.assertEqual(fc._chat("sys", "نص"), "نص")
        self.assertIsNone(fc._chat_raw("sys", "نص"))
        self.assertFalse(fc.ai_ok)
    def test_state_reset_between_operations(self):
        fc, _ = build(FEAT)
        fc.transcribe("w.wav", None); fc._chat("sys", "نص")
        self.assertIsNotNone(fc.last_chat)
        fc.transcribe("w.wav", None)
        self.assertIsNone(fc.last_chat)
        self.assertFalse(fc.ai_ok)
```

- [ ] **Steps 2–5:** fail → implement → pass → commit `feat(engine): FeatureClient walks a feature's provider lists`.

---

### Task 7: `core.App` runs each mode's FeatureClient

**Files:** `source/core.py` (`App.client`, `reset_client`, `process`, `_process_edit`); `source/app_web.py` (`key_add`, `key_remove` call `engine.reset_client()`).

**Updated tests (explicitly):** every `app.client = lambda: fake` in `tests/unit_process.py`, `unit_inject.py`, `unit_snippets.py`, `unit_edit.py`, `unit_raw.py`, `unit_prompt_*.py` → `lambda *a, **k: fake`; `FakeClient` classes gain `stt_local = False`, `ai_ok = True`. `tests/unit_offline_wiring.py` is updated **as a whole file**: its `cfg()` fixture builds `features` (no `offline_mode`); the `always` tests use `stt=[local]` and assert the **provider factory** is never called; the network-fallback tests (`lambda: NetworkFailingClient()`, ~line 212) become a real `FeatureClient` with `stt=[groq, local]` whose groq client raises — and, per the new rule that any item failure moves to the next item, the old expectation "401 does not fall back to local" becomes "401 falls back to local"; prompt/translate after a local transcript now run the AI list (fake client) instead of handing off; bridge tests drop `offline_mode`.

**Produces:** `App.client(mode)` (cache key per spec); process changes per spec: the `offline_mode` branches and `_offline_handoff` are deleted — the AI list runs whatever served the transcription; `cl.stt_local` only affects the engine label; `raw = not CFG.get("polish", True) or not core.feature(mode)["ai"]` used where today's code checks `CFG.get("polish")` (bypass, light_clean, polish, fix_mixed); prompt/translate with `ai_ok False` → state `("done", "مقدرتش أحوّله — اتكتب الكلام زي ما اتقال")`; `_process_edit` keeps its `edit() is None` refusal (no `stt_local` special case). Hotkey settings saved while `recording` or `busy` set `App._hotkey_restart_pending`; `process` and `cancel` call `self._apply_pending_hotkeys()` on their exit path.

- [ ] **Step 1: new failing tests:** `test_each_mode_uses_its_client` (records the mode argument), `test_empty_ai_list_is_fully_raw` ("Yes." stays "Yes." and `fix_mixed` not applied with `polish=True`), `test_prompt_ai_failure_reports_it` (fake `ai_ok=False`), `test_local_transcript_still_runs_ai_list` (fake `stt_local=True`, prompt mode → `to_prompt` called, result typed), `test_hotkey_restart_deferred_until_operation_ends`, `test_cache_rebuilt_when_keys_change_same_provider` (pools `{"groq":["a"]}` → `{"groq":["a","b"]}` gives a new FeatureClient), `test_password_transcript_never_reaches_ai_history_clipboard` (secure focus; asserts no `polish/_chat` call, no `history_add`, no `recording_save`, no clipboard write, no `on_unplaced`).
- [ ] **Steps 2–5:** fail → implement + update listed tests → full suite green → commit `feat(engine): each mode runs its own feature chain`.

---

### Task 8: hotkey engine — filter → ordered dispatcher

**Files:** `source/core.py` (`HotkeyDispatcher`, `start_hotkey`, `restart_hotkey`, `pause_hotkey`, `resume_hotkey`, shutdown path), `source/winput.py` (`VK_LCONTROL = 0xA2`, `VK_ESCAPE = 0x1B`, `keys_down(vks) -> frozenset[int]` via `GetAsyncKeyState & 0x8000`, `frozenset()` on any error).

**Updated tests (explicitly):** `tests/unit_hotkey.py` hook-wiring tests (~lines 280–340: fake `Listener(on_press, on_release, win32_event_filter)`, `test_filter_ignores_only_our_tagged_events`, `test_lock_hotkey_restored_once_per_press_even_with_auto_repeat`) are rewritten for the new contract: the fake listener receives only `win32_event_filter`; tests drive the filter with fake `data` objects (`vkCode`, `scanCode`, `dwExtraInfo`) and drain the dispatcher synchronously; the lock-restore test becomes "a suppressed Scroll Lock trigger is suppressed on press and release and begins recording".

**Produces:**
- `HotkeyDispatcher(logic, app, generation)` — `put(vk, is_press, t, held)`, `stop()`, `drain()` (test helper: process queued events synchronously), thread `run()`; every action wrapped in the existing `guard` behavior; a stale generation's events are dropped.
- `App.start_hotkey()` builds `HotkeyMatcher` from `CFG["features"]`, `HotkeyFilter`, `HotkeyLogic(matcher, CFG["mode"], alt_keys={vk for triggers in (0xA4,0xA5,0x12)}, cancel_keys={0x1B})`, the dispatcher, and the pynput listener whose filter:
  `is_press = msg in (0x100, 0x104)`; `dispatch, suppress = filter.event(vk, is_press, data.dwExtraInfo == winput.EMLAA_TAG, vk == 0xA2 and bool(data.scanCode & 0x200))`; `if dispatch: dispatcher.put(vk, is_press, time.time(), filter.held())`; `if suppress: listener.suppress_event()`; `return False`.
- `restart_hotkey`/`pause_hotkey` stop listener **and** dispatcher; `resume_hotkey` = `start_hotkey`.
- The filter is created with `initially_down` = the modifier vks `GetAsyncKeyState` reports down (`winput.keys_down(MODIFIER_VKS)`), on every start/resume.
- `App.begin` checks `self.capturing` inside the `_state_lock` section that reserves `recording` and returns without starting when it is set.

- [ ] **Step 1: failing tests:** F7 toggle tap → `begin:normal` with press/release suppressed; Right Ctrl tap → begin, not suppressed; Ctrl+F8 hold → begin then end, F8 suppressed, Ctrl not; injected F7 → nothing queued, not suppressed; fake AltGr Ctrl ignored and Right Alt begins its mode; an action that raises → error state reported and the next event still processed; events queued under an old generation are dropped after `restart_hotkey`; a filter started while Left Ctrl is down treats F7 as Ctrl+F7.
- [ ] **Steps 2–5:** fail → implement + rewrite listed tests → full suite green → commit `feat(hotkey): ordered low-level dispatch with suppression`.

---

### Task 9: key capture over the bridge

**Files:** `source/core.py` (`capture_keys(count, timeout=10.0, listener_factory=None, clock=time.monotonic)`), `source/app_web.py` (`Api.capture_hotkey(feature, count)`). Tests `tests/unit_hotkey_capture.py` (`TestCaptureBridge`).

**Produces:**
- `core.capture_keys(...)` → `{"ok": True, "keys": [...], "label": smart.hotkey_label(keys, lang)}` or `{"ok": False, "err": ...}` (cancel `"اتلغى"`, timeout `"الزرار ماوصلش لويندوز — لو لابتوب جرّب Fn مع الزرار"`, shape error from `CaptureSession.error`). The capture listener's filter feeds `CaptureSession.event` and suppresses only events it reports as ours.
- `App.try_begin_capture() -> bool` (under `_state_lock`: refused when `recording`, `busy` or `capturing`; else sets `capturing = True`) and `App.end_capture()`.
- `Api.capture_hotkey(feature, count)`: `feature in smart.FEATURES`, `count in (1, 2)`; `engine.try_begin_capture()` else `{ok: False, err: "وقّف التسجيل الأول"}`; `engine.pause_hotkey()`, run capture, and in `finally` `engine.resume_hotkey()` + `engine.end_capture()`; returns the result plus `"feature": feature`. Without an engine: capture runs directly.
- `core.capture_keys` creates the session with `initially_down = winput.keys_down(<all vks 0x01–0xFE>)`, decides on `session.decided`, and keeps its listener until `session.finished` (cap 3 s) on **every** exit — result, error, Esc, timeout.

- [ ] **Step 1: failing tests** (fake listener factory that replays events through the filter; fake clock): single key; two keys after full release; pre-held Ctrl (keydown repeats + keyup) not suppressed; Esc cancel and timeout both wait for captured keys' release before returning; refused while recording; second concurrent capture refused; `resume_hotkey` called after an exception; a `begin` racing `try_begin_capture` (threads + barrier) never leaves both `recording` and `capturing` True.
- [ ] **Steps 2–5:** fail → implement → pass → commit `feat(hotkey): record hotkeys from the keyboard`.

---

### Task 10: bridge settings for features

**Files:** `source/app_web.py` (`run`/`after_start` gate ~507, `bootstrap` ~545–577, `save_settings` ~719–812). Tests `tests/unit_features.py::TestSaveSettings`, `tests/unit_app_web_keys.py` (unchanged, passing).

**Produces:**
- Engine start gate and `bootstrap.canRun` use `core.can_run()`.
- `bootstrap()["features"]` (each with `"label"`) and `bootstrap()["catalog"]` = `{pid: {"name", "sttModels": providers.stt_catalog(pid), "chatModels": providers.chat_models(pid), "hasKey", "sttOnly"}, "local": {"name": "محلي · Whisper", "installed": offline.installed() or None}}`; `hotkeys` and `hotkey_*` leave the `cfg` whitelist; `provider` stays (welcome).
- `save_settings(data)`: the "needs a key" check applies only to the welcome path (`provider` + `key` sent); `"features" in data` → `smart.validate_features` (error returned, nothing saved) else stored with `features_custom = True`; welcome path with `features_custom` false recomputes features after saving the key; hotkey listener restarts when any hotkey or `mode` changed (deferred via `_hotkey_restart_pending` while recording/busy); `offline_mode` no longer handled; `engine.reset_client()` always.
- `Api.key_remove`: the last-key guard computes the pools **after** removal and refuses only when `core.can_run(pools=after)` is False (message names that no feature could transcribe); removing the old `provider`'s last key is allowed when another usable STT item exists.

- [ ] **Step 1: failing tests:** invalid features rejected and file untouched; valid stored + `features_custom`; welcome recomputes non-custom features; customized features survive a welcome save; hotkey change restarts the listener (fake engine); `can_run` false → engine not started; `key_remove` of a provider no feature uses succeeds even if it is the old `provider`; removing the only usable STT key is refused.
- [ ] **Steps 2–5:** fail → implement → pass → commit `feat(settings): bridge per-feature settings`.

---

### Task 11: Settings UI

**Files:** `source/ui/index.html` (settings ~266–384), `source/ui/app.js` (`fillSettings` ~889, save ~1081, `applyBoot` ~1215), `source/ui/app.css`, `source/ui/i18n.js`.

**Produces (DOM ids):** `#featTabs` (buttons `data-feat`), `#featPanel` with `#hkLabel`, `#hkRec1`, `#hkRec2`, `#hkClear`, `#sttList`, `#aiList`, `.chain-row` (provider select, model select, ↑, ↓, ✕), `#sttAdd`, `#aiAdd`; `#keysSection` with one key-pool block per provider (`data-pid`), reusing today's key-pool JS per block. Removed ids: `#setProvider`, `#modelPick`, `#hkNormal`, `#hkPrompt`, `#hkTranslate`, `#hkEdit`, `#offlineMode` (search app.js for every reference and remove/replace). Also every reader of the removed `cfg` fields: `renderKeys` (home-page hotkey chips, `app.js:~151`) reads `boot.features[m].label` for all four features and shows edit when it has a hotkey. Model selects always include the item's stored model even when the catalog lacks it.
JS state `S.features` (deep copy), `S.feat`. Save payload adds `features`; drops `provider/model/hotkey_*/offline_mode`. Capture: `api().capture_hotkey(S.feat, n)`; while waiting all `[data-feat]` and capture buttons are disabled and the label shows `"دوس الزرار دلوقتي… (Esc للإلغاء)"`; the result is written into `S.features[r.feature]`.

- [ ] **Step 1:** implement markup/JS/CSS; add every new string to `EN`.
- [ ] **Step 2:** visual check in the built-in browser: open `source/ui/index.html`, inject a stub `window.pywebview.api` (fixture `bootstrap` with two keyed providers, local installed, migrated features; `capture_hotkey` resolves after 300 ms to `{ok:true, feature:<arg>, keys:[162,118], label:"Left Ctrl + F7"}`; `save_settings` records its argument), dispatch `pywebviewready`, open Settings; screenshot each tab in Arabic/English and light/dark; add/move/remove rows; switch tabs while a capture is pending and confirm the result lands in the originating tab; confirm the saved payload shape; after saving a combo and an edit hotkey, the home page shows four chips with the combo label.
- [ ] **Step 3:** suite green. **Step 4:** commit `feat(ui): feature tabs, chain editors and key capture`.

---

### Task 12: classic Tk UI

**Files:** `source/emlaa.py` (settings dialog ~1152–1379, welcome/readiness checks, `HOTKEYS`).

**Produces:** hotkey selects whose options carry vk lists (legacy names → `[vk]`, plus the stored value as an extra option when it is not a legacy single key); save builds the full `features` dict, validates once with `smart.validate_features`, saves once, and sets `features_custom = True` when any hotkey changed; readiness via `core.can_run()`; provider change recomputes features when `features_custom` is false.

- [ ] **Steps:** failing tests on the pure helper `emlaa.classic_hotkey_options(features, lang)` / `emlaa.apply_classic_hotkeys(features, picks) -> (features, err)`: a stored combo survives a save that doesn't touch it; swapping two modes' hotkeys in one save succeeds; a duplicate is refused; a hotkey changed in one save survives a provider change in the next save → implement → pass → commit `fix(classic): classic settings use feature hotkeys`.

---

### Task 13: docs

**Files:** `README.md` (features table, «الإعدادات» table, English summary), `ابدأ من هنا.txt` (usage section).
- Describe tabs, recording a key (one key or modifier + key, blocked from other apps), STT/AI lists with fallback order, keys section, local Whisper as a list item.
- Run `docs-guard`. Commit `docs: per-feature settings and hotkey recording`.

---

### Task 14: end-to-end verification

- Full suite + `python -m compileall -q source`; `clean-code-guard` (production diff), `test-guard` (test diff); fix findings.
- PyInstaller build (confirms `chains` bundled); launch `dist/Emlaa.exe` only when no user copy is running; window opens; no `emlaa-error.log`.
- Live from source: capture F7, Ctrl+F7 (two modes), Right Alt; F7 in a browser does not toggle caret browsing; one dictation per tab; config migrated from the user's real `config.json` (back it up first to `F:\Dev\Temp`).
- `superpowers:requesting-code-review` before the PR.

---

## Self-review

- Spec coverage: privacy wording (constraints, T7 test), schema/validation/migration/readiness (T5, T10), strict client/TextOps/catalogs (T4), FeatureClient + state reset + ai_ok (T6), core wiring + raw definition + cache (T7), matcher/filter/dispatcher lifecycle (T1, T2, T8), capture rules (T3, T9), UI (T11), classic (T12), docs (T13), live (T14).
- Names consistent across tasks: `Hotkey`, `HotkeyMatcher.match`, `HotkeyFilter.event/held`, `CaptureSession`, `FeatureClient(feature, pools, client_factory)`, `App.client(mode)`, `core.can_run`, `core.capture_keys`, `Api.capture_hotkey(feature, count)`.

---

## Debate round 1 — verdicts (Codex `gpt-6.1-sol`, effort high, read-only)

| # | Finding | Sev | Verdict | Reason |
|---|---|---|---|---|
| 1 | Two hotkeys sharing a trigger overwrite each other | P1 | accept | `HotkeyMatcher` matches full identity (T1); logic and filter both use it (T2) |
| 2 | Filter suppresses keys the logic won't fire | P1 | accept | one `match()` for both; test for Ctrl+F7 with single F7 configured (T2) |
| 3 | Engine start/save gates still use old provider | P1 | accept | `core.can_run()` at every gate (spec Readiness; T5, T10, T12) |
| 4 | Dispatcher lifecycle undefined | P1 | accept | generations, stop sentinel, guard, stop on restart/pause/shutdown (T8) |
| 5 | Capture during a recording leaves the mic running | P1 | accept | capture refused while recording/busy; `capturing` blocks `begin` (T8, T9) |
| 6 | Password invariant overstated | P1 | partial | audio to STT is an existing documented decision (lolotam/Emlaa#2); invariant reworded to AI/history/recordings/clipboard/toast and tested (spec, T7) |
| 7 | "Always offline" migration fails edit validation | P1 | accept | rule removed; every migration case validated (T5) |
| 8 | Temporary migration persisted; import-time writes | P1 | accept | migration computed, never written at load; catalogs task moved before schema (T4→T5) |
| 9 | Migration could overwrite an unreadable config | P1 | accept | resolved by never writing at load (T5 test) |
| 10 | Two non-modifier keys can be captured but never fire | P2 | accept | shape rule: modifier + non-modifier only, at capture and save (T1, T3, T5) |
| 11 | Single modifier hotkey vs combo starting with it | P2 | accept | refused by validation (T5) |
| 12 | Capture unbalances key events across listener switch | P2 | accept | only session keys suppressed; combo returns after full release (T3, T9) |
| 13 | Failed prompt/translation reported as success | P2 | partial | raw text still typed as today; `ai_ok` drives an explicit status message (T6, T7) |
| 14 | Empty normal AI list isn't fully raw | P2 | accept | raw definition covers bypass/light_clean/polish/fix_mixed (T7 test) |
| 15 | Client cache misses key changes | P2 | accept | signature includes keys; key add/remove reset (T7) |
| 16 | Model metadata leaks across operations | P2 | accept | reset at transcribe and each chat call (T6 test) |
| 17 | Capture result written to the wrong tab | P2 | accept | `feature` pinned in API and echoed; tabs disabled; one capture at a time (T9, T11) |
| 18 | Classic save loses combos and blocks swaps | P2 | accept | full-dict build + one validation (T12 tests) |
| 19 | Existing hook/offline tests silently broken | P2 | accept | affected tests named with their new contract (T7, T8) |
| 20 | Migration drops today's STT fallbacks | P2 | accept | migration expands today's STT order into visible items (T5 test) |

## Debate round 2 — verdicts (Codex `gpt-6.1-sol`, effort high, read-only)

| # | Finding | Sev | Verdict | Reason |
|---|---|---|---|---|
| 1 | AI lists after a `local` transcript are valid but never run | P1 | accept | the AI list runs whatever served STT; `_offline_handoff` and the `stt_local` special cases are deleted (spec core.App; T7) |
| 2 | Capture/begin race | P1 | accept | `try_begin_capture` under `_state_lock`; `begin` checks `capturing` in the same section; barrier test (T8, T9) |
| 3 | Restarting hotkeys mid-`hold` loses the release | P1 | accept | `_hotkey_restart_pending` applied when the operation ends (spec; T7, T10) |
| 4 | Not every capture exit waits for releases | P2 | accept | `decided` vs `finished`; every exit waits for captured keys' release, cap 3 s (T3, T9) |
| 5 | Pre-held keys captured through auto-repeat | P2 | accept | `initially_down` snapshot ignored until keyup (T3, T9) |
| 6 | Suppression decision changes within one press | P2 | accept | decision latched per physical press (T2) |
| 7 | Modifier state at listener start undefined | P2 | accept | `initially_down` from `GetAsyncKeyState` on start/resume (T2, T8) |
| 8 | `ai_ok` false after `to_prompt` keeps its first answer | P2 | accept | `ai_ok` reset only per operation, set by any success (spec; T6 test) |
| 9 | Dictionary hints not passed to inner STT clients | P2 | accept | synced before each STT attempt, cached clients too (T6 test) |
| 10 | UI catalog drops available models | P2 | accept | `stt_order` (migration) vs `stt_catalog` (UI); stored model always offered (T4, T10, T11) |
| 11 | Legacy `hotkey` hidden by DEFAULTS | P2 | accept | migration reads the raw file dict before DEFAULTS (T5 test) |
| 12 | `ai=[]` migration changes Deepgram-without-helper output | P2 | partial | empty AI list = raw is the user-facing rule chosen in design; the change is documented in the spec and covered by a test rather than hidden |
| 13 | Last-key removal tied to old provider | P2 | accept | guard uses `can_run(pools=after)` (spec Readiness; T10 tests) |
| 14 | Classic save doesn't mark features custom | P2 | accept | `features_custom = True` on hotkey change; two-save test (T12) |
| 15 | Home page hotkey chips read removed fields | P2 | accept | `renderKeys` reads `features` labels (T11) |
| 16 | Offline wiring tests only partly planned | P2 | accept | whole-file update with the new any-error fallback rule spelled out (T7) |
| 17 | Chain tests can't detect wrong model use | P2 | accept | same-provider two-model test asserting attempts and `engine()` (T6) |
| 18 | Duplicate rule blocks several empty hotkeys | P2 | accept | duplicates checked among non-empty hotkeys only; test (T5) |
