# Agent setup guide

Instructions for an AI coding agent asked to set up this project from its GitHub link. Do the automatable steps yourself; hand the user the steps that need a browser, an account, or a secret. Never ask the user to paste API keys into chat, and never write keys to files.

Read [README.md](README.md) for full detail. This file is the short path.

## Requirements

macOS only (secrets are stored in macOS Keychain). Chrome 116+.

## 1. Do these yourself

```sh
git clone https://github.com/matt-j-penny/youtube-motion-graphic-snatcher.git
cd youtube-motion-graphic-snatcher
```

Install anything missing (check with `make doctor`), using Homebrew:

- Node.js 22+: `brew install node`
- Python 3.12+ and uv: `brew install uv` (uv fetches Python if needed)
- FFmpeg/FFprobe: `brew install ffmpeg`

Then:

```sh
make install
make build
make test
```

`extension/dist` now holds the unpacked extension. Tell the user its absolute path.

## 2. The user does these (give them the steps)

**Notion** (where captures are saved):
1. Create an internal integration at https://www.notion.so/profile/integrations with Read, Insert and Update content.
2. Copy the integration token.
3. Create an empty Notion page, then page menu → **Add connections** → add the integration.
4. Copy the page URL.

**Deepgram** (transcription):
1. Create an API key at https://console.deepgram.com/ on a project with credit.

**Save credentials.** The user runs this in their own terminal (it prompts for the keys without echoing them):

```sh
make configure
```

## 3. Start the companion

Run in the background (it must stay running while the extension is used):

```sh
make companion
```

It prints an eight-character pairing code. Pass that code to the user.

## 4. The user loads the extension

1. Open `chrome://extensions` and turn on **Developer mode**.
2. Click **Load unpacked** and choose the `extension/dist` folder path you gave them.
3. Open any normal `youtube.com/watch` video and click the extension icon to open the side panel.
4. Enter the pairing code.
5. In the setup screen click **Test Deepgram**, **Test Notion**, then **Create Notion library**. That creates the `Motion Graphic Library` database in the Notion page; nothing needs to be designed by hand.

## Done

Setup is finished when both tests pass and the library exists. Later, the user only needs `make companion` running to use the extension. If credentials change, run `make configure` again and restart the companion.
