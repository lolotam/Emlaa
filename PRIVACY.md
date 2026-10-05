# Privacy Policy — Emlaa (إملاء)

_Last updated: October 4, 2026_

Emlaa is a Windows dictation app developed by **Walid Mohamed** ([walidmohamed.com](https://walidmohamed.com)). This policy explains what the app does with your data. Short version: **we don't collect anything.** There are no accounts, no analytics, no tracking and no servers of ours in the loop.

## What stays on your device

The following are stored **only on your computer** and are never sent to us:

- **API keys** you enter for your chosen transcription provider.
- **Settings** (hotkeys, language, theme, chosen models).
- **History** of your dictations (by default, only the last 10 are kept).
- **Audio of your last 10 recordings**, stored as MP3 files in a `recordings` folder in the app's data folder (next to `Emlaa.exe` for the portable version, `%LOCALAPPDATA%\Emlaa` for the Microsoft Store version), for replay and download. They stay on your device and are deleted when you delete their history entry, when you clear the history, or when newer recordings push them out.
- **Clipboard history**, if you turn it on. Content that password managers mark as private is never saved. You can turn this feature off and delete entries at any time.
- **Your dictionary** of custom words.
- An **error log**, used only for troubleshooting.

In the Microsoft Store version these files are kept in `%LOCALAPPDATA%\Emlaa`. In the standalone version they are kept next to `Emlaa.exe`. Uninstalling the app, or deleting these files, removes them.

## Microphone and audio

Emlaa records audio **only while you are dictating**, after you press your hotkey or the record button. The recording is sent **directly from your computer to the transcription provider you selected**, using **your own API key**, and the temporary audio file is deleted right after transcription. A copy of your **last 10 recordings** is kept on your device as MP3 files (in a `recordings` folder in the app's data folder (next to `Emlaa.exe` for the portable version, `%LOCALAPPDATA%\Emlaa` for the Microsoft Store version)) for replay and download; these are deleted when you delete their history entry, when you clear the history, or when newer recordings push them out. The audio never passes through any server operated by us.

## Third-party providers

Depending on the provider you choose, your audio, and for text cleanup, prompt and translate features the transcribed text, is processed by that provider under its own privacy policy:

| Provider | Privacy policy |
|---|---|
| Groq | https://groq.com/privacy-policy/ |
| OpenAI | https://openai.com/policies/privacy-policy/ |
| Google Gemini | https://policies.google.com/privacy |
| Deepgram | https://deepgram.com/privacy |

You choose the provider and can switch or remove it at any time in Settings.

## Update checks

- **Microsoft Store version:** updates come from the Microsoft Store. The app does not check for updates itself.
- **Standalone version:** the app asks GitHub (`api.github.com`) for the latest release number. No personal data, keys or content are sent. You can turn this off in Settings.

## Children

Emlaa is not directed at children and does not knowingly collect any personal information.

## Changes

If this policy changes, the updated version will be published at this address with a new date.

## Contact

Walid Mohamed — [walidmohamed.com](https://walidmohamed.com) · [github.com/lolotam/Emlaa/issues](https://github.com/lolotam/Emlaa/issues)
