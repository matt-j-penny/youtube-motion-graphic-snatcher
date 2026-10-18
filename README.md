# YouTube Motion Graphic Snatcher

> **Setting up with an AI agent?** Give it this repo's link and ask it to follow [AGENTS.md](AGENTS.md).

A personal Chrome extension that turns a selected section of a normal YouTube video into a structured Notion reference:

- 10 clean, timestamped source frames
- A Deepgram transcript of the selected audio
- Video title, channel, URL, start/end times, tags, and notes

Media processing happens locally on the Mac. Temporary video, MP3, and image files are removed after the Notion entry is saved.

## How it works

The project has two parts:

- `extension/` — a Manifest V3 Chrome side panel.
- `companion/` — a loopback-only Python service that runs `yt-dlp`, FFmpeg, Deepgram, and Notion requests.

The extension never receives the Notion or Deepgram keys. They are stored in macOS Keychain by the companion.

## Requirements

- macOS
- Chrome 116 or newer
- Node.js 22+
- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/)
- FFmpeg and FFprobe
- A Deepgram account with transcription credit
- A Notion workspace where you can create an internal integration

Check the local toolchain:

```sh
make doctor
```

If FFmpeg is missing:

```sh
brew install ffmpeg
```

## 1. Install and build

From the repository root:

```sh
make install
make build
```

The unpacked extension is generated at:

```text
extension/dist
```

## 2. Create the Notion integration

1. Open [Notion integrations](https://www.notion.so/profile/integrations) and create an internal integration for the target workspace.
2. Enable these content capabilities:
   - Read content
   - Insert content
   - Update content
3. Copy the integration token somewhere secure.
4. Create an empty Notion page that will contain the library.
5. Open the page menu, choose **Add connections**, and add the new integration.
6. Copy the page URL.

The companion will create the `Motion Graphic Library` database inside that page. You do not need to design the database manually.

## 3. Create a Deepgram key

Create a dedicated API key in the [Deepgram console](https://console.deepgram.com/). A project with available transcription credit is required.

## 4. Save credentials in Keychain

Run:

```sh
make configure
```

The command prompts for:

- Deepgram API key
- Notion integration token
- Notion parent-page URL
- Maximum allowed clip length

The prompts do not echo the tokens. Credentials are stored in macOS Keychain, while non-secret settings are stored under:

```text
~/Library/Application Support/VideoGraphicSnatcher
```

Do not paste credentials into source files or commit them.

## 5. Start the companion

Run:

```sh
make companion
```

Keep this terminal open. It prints an eight-character extension pairing code and listens only on:

```text
http://127.0.0.1:43127
```

## 6. Load the extension

1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. Click **Load unpacked**.
4. Select the absolute `extension/dist` folder in this repository.
5. Pin **YouTube Motion Graphic Snatcher** if desired.
6. Open a normal YouTube watch video.
7. Click the extension icon to open the side panel.
8. Enter the pairing code printed by the companion.

Pairing is normally required only once. The extension stores a random companion access token in `chrome.storage.local`; it does not store external API keys.

## 7. Finish setup in the side panel

The setup screen reports the state of FFmpeg, `yt-dlp`, Deepgram, and Notion.

1. Click **Test Deepgram**.
2. Click **Test Notion**.
3. Click **Create Notion library**.

If credentials are changed with `make configure`, restart the companion so it reloads Keychain and configuration.

## Use

1. Open a normal prerecorded `youtube.com/watch` video.
2. Open the extension side panel.
3. Enter start and end times, or use the current-time buttons.
4. Add an optional reference title, comma-separated tags, and notes.
5. Click **Capture to Notion**.
6. Wait for the pipeline to download the selected section, extract frames, transcribe it, and upload the entry.
7. Click **Open in Notion**.

Time fields accept:

- `75`
- `1:15`
- `1:02:15`

Frames are sampled at 5%, 15%, ..., 95% of the selected range. The default maximum range is 15 minutes.

## Commands

```sh
make install      # Install Python and Node dependencies
make build        # Build extension/dist
make configure    # Save credentials and settings
make companion    # Start the local service
make status       # Show configuration state without revealing secrets
make lint         # Run Python lint/format checks and TypeScript checks
make test         # Run companion and extension tests
make doctor       # Check the required local toolchain
```

## Notion entry structure

The companion creates one database row per successful capture. Each row contains:

- Reference name and processing status
- Canonical YouTube URL and video ID
- Video title and channel
- Start, end, and duration values
- Tags, notes, language, confidence, and capture date
- 10 directly uploaded image blocks with timestamps
- Full readable transcript
- Timestamped transcript utterances
- Deepgram request ID for troubleshooting

Notion files are uploaded directly through its File Upload API. No public file host is used.

## Data and security

- The companion binds to loopback only.
- Extension requests require a persistent random pairing token.
- Notion and Deepgram secrets stay in macOS Keychain.
- Command arguments are passed without a shell.
- Browser cookies are not read.
- Logs do not intentionally contain authorization headers.
- Successful and cancelled jobs delete temporary media immediately.
- Failed-job media is retained for at most one hour to permit retry, then removed.

Job summaries are kept locally so interrupted or failed work can be diagnosed. They do not contain downloaded media or credentials.

## Supported scope

MVP support:

- Normal prerecorded `youtube.com/watch` videos
- Publicly accessible videos
- One selected range per capture
- Local personal use

Not currently supported:

- Shorts
- Livestreams and upcoming streams
- Embedded players
- Members-only or login-required videos
- Playlists as a batch
- Browser-cookie import
- Chrome Web Store publishing
- AI animation/style analysis

## Troubleshooting

### The extension says the companion is offline

Run:

```sh
make companion
```

Then click **Check again** in the side panel.

### Pairing stopped working after local data was removed

Restart the companion and pair again with the newly printed code.

### Notion says the page cannot be accessed

Open the chosen parent page in Notion and add the internal integration through **Add connections**. Then run:

```sh
make configure
```

Restart the companion and repeat the Notion tests.

### YouTube extraction fails

YouTube delivery changes periodically. Update the Python lock and installed `yt-dlp`:

```sh
cd companion
uv lock --upgrade-package yt-dlp
uv sync
```

### A failed job left temporary files

The companion removes expired failed-job directories on startup. Restart it, or wait for the configured one-hour retention window.

## Development

Run the extension in watch mode:

```sh
cd extension
npm run dev
```

After each rebuild, click **Reload** for the unpacked extension on `chrome://extensions`.

Run the companion directly:

```sh
cd companion
uv run snatcher serve
```

The full implementation plan is in [PLAN.md](./PLAN.md).

## Responsible use

This tool downloads a temporary selected section of a YouTube video. Use it only for material you are entitled to capture and for purposes permitted by applicable terms and copyright law.

