# YouTube Motion Graphic Snatcher — Implementation Plan

Status: Approved direction, ready for implementation  
Target: Personal-use desktop Chrome extension on macOS  
Last updated: 2026-07-26

## 1. Product summary

The product captures a visual reference from a normal, prerecorded YouTube video. The user selects a start and end time from a Chrome side panel. The system then:

1. Downloads only the requested section with `yt-dlp`.
2. Extracts 10 clean, evenly distributed video frames with FFmpeg.
3. Extracts a temporary MP3 from the same section.
4. Transcribes the MP3 with Deepgram.
5. Creates a Notion database entry containing the source metadata, notes, tags, transcript, and 10 timestamped images.
6. Deletes all temporary video, audio, image, and transcript files after the Notion save succeeds.

The MVP supports normal `youtube.com/watch` videos only. Shorts, livestreams, embeds, playlists, members-only videos, and AI visual analysis are outside the first release.

## 2. Confirmed product decisions

- Notion is the permanent library and source of truth.
- Deepgram is the transcription provider.
- `yt-dlp` and FFmpeg perform media acquisition and processing.
- Exactly 10 frames are sampled at 5%, 15%, 25%, ..., 95% of the selected range.
- The system stores:
  - Video title
  - Channel
  - YouTube URL and video ID
  - Start and end timestamps
  - Capture date
  - Custom title
  - Tags
  - Notes
  - A full transcript
  - Timestamped transcript utterances
  - 10 timestamped images
- The extension is personal-only and will initially be installed as an unpacked extension.
- There is no ZIP or local-library export in the MVP.
- There is no AI analysis of animation style in the MVP.

## 3. Architecture

### 3.1 Components

#### Chrome extension

A Manifest V3 extension provides:

- A persistent Chrome side panel.
- Detection of the current supported YouTube video.
- Start/end timestamp inputs.
- “Use current time” buttons.
- Custom title, tags, and notes fields.
- Capture progress, cancellation, errors, and completion state.
- A link to the resulting Notion page.
- A settings/setup screen for checking the companion service.

The extension does not store Deepgram or Notion credentials and does not execute media tools.

#### Local companion service

A Python service bound only to `127.0.0.1` provides:

- Input validation and URL allowlisting.
- Job creation, progress, cancellation, and recovery.
- YouTube metadata extraction through `yt-dlp`.
- Selected-section media download.
- FFmpeg frame and MP3 extraction.
- Deepgram transcription.
- Notion database bootstrapping and page creation.
- Temporary-file lifecycle management.
- Credential storage through macOS Keychain.

The local service is necessary because Chrome extensions cannot directly execute `yt-dlp` or FFmpeg.

#### External services

- YouTube supplies the source media.
- Deepgram transcribes the temporary MP3.
- Notion stores the final library entry and uploaded frames.

### 3.2 Technology stack

#### Extension

- TypeScript
- React
- Vite
- Manifest V3
- Chrome Side Panel API
- Vitest for unit tests
- Playwright or a small manual harness for extension smoke tests

#### Companion

- Python 3.12+
- FastAPI and Uvicorn
- Pydantic
- `yt-dlp` Python package
- FFmpeg and FFprobe executables
- `httpx` for Deepgram and Notion REST calls
- `keyring` for macOS Keychain
- `pytest`
- `uv` for Python dependency and environment management

Direct REST calls are preferred for Notion so the implementation can explicitly use the current API version and File Upload endpoints.

### 3.3 End-to-end flow

1. The content script reads:
   - Canonical video URL
   - Video ID
   - Current playback time
   - Video duration
2. The side panel validates start/end values locally.
3. The extension submits a job to the companion:
   - YouTube URL
   - Start and end seconds
   - Custom title
   - Tags
   - Notes
   - Language setting, defaulting to automatic detection
4. The companion validates that the URL is an ordinary YouTube watch URL.
5. `yt-dlp` retrieves video metadata without downloading media.
6. The companion rejects unsupported content, invalid ranges, or ranges beyond the configured maximum.
7. `yt-dlp` downloads the requested section into a unique temporary job directory.
8. FFprobe verifies the resulting file and establishes its actual duration and stream information.
9. FFmpeg extracts:
   - 10 JPEG frames
   - One mono, 16 kHz, 64 kbps MP3
10. The MP3 is sent to Deepgram.
11. Deepgram word and utterance times are shifted from clip-relative time to original-video time.
12. The companion creates or updates the Notion database entry.
13. The 10 JPEGs are uploaded with the Notion File Upload API and attached as image blocks.
14. The transcript and other blocks are added.
15. The Notion entry status changes to `Saved`.
16. The extension displays success and links to the Notion page.
17. The companion deletes all local job artifacts.

## 4. Capture behavior

### 4.1 Timestamp parsing

The side panel accepts:

- Seconds: `75`
- Minutes and seconds: `1:15`
- Hours, minutes, and seconds: `1:02:15`

Values are normalized to seconds internally. Millisecond values may be displayed in frame captions but are not required as user input in the MVP.

### 4.2 Validation rules

- Start must be zero or greater.
- End must be greater than start.
- End must not exceed the video duration.
- Minimum selection: 0.5 seconds.
- Default maximum selection: 15 minutes.
- The maximum is configurable in the local companion settings.
- The URL must match a single normal YouTube watch video.
- Live or upcoming streams are rejected.
- Playlist parameters are ignored; only the current video is processed.

### 4.3 Frame sampling

For a start time `S` and end time `E`, frame `i` is sampled at:

`S + ((i + 0.5) / 10) × (E - S)`, for `i = 0...9`.

This produces samples at 5%, 15%, ..., 95% and avoids boundary frames that may belong to the preceding or following shot.

Frame output:

- JPEG
- Maximum width: 1920 px while preserving aspect ratio
- Quality target: approximately 90
- Rotation metadata applied
- No subtitles, browser UI, playback controls, or overlays
- File names include sequence and original-video timestamp

If two requested timestamps resolve to the same source frame in an extremely short or low-frame-rate selection, the capture still completes with 10 files and logs the duplication.

### 4.4 Media acquisition

The companion will invoke `yt-dlp` through its Python API or a safely constructed argument array. It must:

- Use `--ignore-config` behavior so machine-wide settings cannot silently change the job.
- Use `--no-playlist`.
- Download only the selected time range.
- Prefer a video stream no larger than 1080p plus the best compatible audio stream.
- Merge to a format FFmpeg can process reliably.
- Never use `shell=True`.
- Never interpolate the title or user notes into a shell command.
- Avoid browser-cookie access in the MVP.

For accurate boundaries, the implementation will download with a small safety margin where necessary, then use FFmpeg for the precise requested cut. The frame timestamps and transcript timestamps always refer to the original requested range, not the safety margin.

## 5. Transcription design

### 5.1 Audio preparation

FFmpeg creates a temporary MP3 with:

- Mono channel
- 16 kHz sample rate
- 64 kbps bitrate
- No embedded artwork or unrelated metadata

The MP3 is sent directly from the local companion to Deepgram and is never uploaded to Notion.

### 5.2 Deepgram request

Initial request configuration:

- Model: `nova-3-general`
- `smart_format=true`
- `utterances=true`
- Automatic language detection by default
- Punctuation enabled through smart formatting
- No summarization
- No sentiment analysis
- No diarization in the MVP

The full Deepgram response is retained only in the job directory until the Notion save succeeds. The saved Notion page contains the readable transcript, timestamped utterances, detected language, overall confidence when available, and Deepgram request ID for troubleshooting.

### 5.3 Timestamp mapping

Deepgram timestamps begin at zero for the extracted clip. Each timestamp is converted back to YouTube time:

`youtube_time = selected_start + deepgram_time`

The Notion page shows utterances in this form:

`[01:24.320–01:28.910] Transcript text`

The source link uses the selected start timestamp so the user can jump back to the clip.

### 5.4 Transcript edge cases

- No speech: save the frames and mark the transcript as “No speech detected.”
- Low confidence: save the transcript and include a warning.
- Unsupported/detection failure: permit one retry with English before failing transcription.
- Deepgram failure: keep processed local artifacts temporarily and allow retry without re-downloading.
- Transcription should not create a partially complete `Saved` entry.

## 6. Notion design

### 6.1 Runtime authorization

The app uses a dedicated Notion internal integration. The user will:

1. Create an internal integration in the desired Notion workspace.
2. Grant read content, insert content, and update content capabilities.
3. Create or choose a parent Notion page.
4. Add the integration to that page through `Add connections`.
5. Enter the integration token and parent-page URL into the local companion setup UI.

The token is stored in macOS Keychain, never in extension storage, source control, logs, or Notion itself.

### 6.2 Database bootstrap

On first successful Notion connection, the companion creates a database named `Motion Graphic Library` under the shared parent page. If a database ID is already configured, it validates the schema instead.

Proposed properties:

| Property | Type | Purpose |
| --- | --- | --- |
| Name | Title | Custom title or generated reference title |
| Status | Status/Select | Processing, Saved, Failed |
| YouTube URL | URL | Canonical source |
| Video ID | Rich text | Stable YouTube ID |
| Video Title | Rich text | Original title |
| Channel | Rich text | Channel/uploader |
| Start Seconds | Number | Machine-readable start |
| End Seconds | Number | Machine-readable end |
| Start Time | Rich text | Human-readable timestamp |
| End Time | Rich text | Human-readable timestamp |
| Clip Duration | Number | Selected duration in seconds |
| Tags | Multi-select | User-entered categories |
| Notes | Rich text | Short notes for database views |
| Language | Select/Rich text | Deepgram detected language |
| Confidence | Number | Transcript confidence when available |
| Captured At | Date | Capture completion time |

The full transcript belongs in the page body rather than a database property to avoid rich-text property length limits.

### 6.3 Page body

Each entry contains:

1. Source summary with video title, channel, start/end, and a timestamped YouTube link.
2. User notes.
3. Tags.
4. A `Frames` heading.
5. Ten uploaded image blocks, each captioned with its sequence and source timestamp.
6. A `Transcript` heading.
7. A readable transcript paragraph or paragraphs.
8. A `Timestamped transcript` toggle containing utterances with source times.
9. A small processing-details section containing model, detected language, confidence, and request ID.

The images are uploaded directly to Notion. No permanent public hosting service is required.

### 6.4 Notion failure and retry policy

- Respect Notion’s rate limits and `Retry-After` header.
- Limit upload concurrency.
- Create the page only after local media processing and transcription succeed.
- Mark the page `Processing` while images and body blocks are being attached.
- Persist the page ID in the local job record immediately after creation.
- On retry, update the existing page rather than creating a duplicate.
- Change status to `Saved` only after all 10 images and transcript blocks exist.
- If a job remains incomplete, surface a `Retry Notion save` action.

## 7. Local companion API

All endpoints are versioned under `/v1`.

### Setup and diagnostics

- `GET /v1/health`
  - Service version
  - FFmpeg availability
  - `yt-dlp` availability
  - Whether Notion and Deepgram credentials are configured
- `POST /v1/setup/deepgram/test`
- `POST /v1/setup/notion/test`
- `POST /v1/setup/notion/bootstrap`

### Jobs

- `POST /v1/jobs`
  - Create a capture job
- `GET /v1/jobs/{job_id}`
  - Return state, stage, progress, messages, errors, and Notion URL
- `POST /v1/jobs/{job_id}/cancel`
- `POST /v1/jobs/{job_id}/retry`
- `GET /v1/jobs/recent`
  - Return a small local history for recovery, not a permanent media library

### Job state machine

`queued → validating → metadata → downloading → extracting → transcribing → creating_notion_page → uploading_frames → finalizing → complete`

Terminal alternatives:

- `failed`
- `cancelled`

Retryable failures include network interruption, Deepgram 429/5xx, Notion 429/5xx, and expired file uploads. Invalid URL, unsupported content, invalid credentials, insufficient Deepgram credit, and missing Notion access are non-retryable until the user changes configuration.

## 8. Security and privacy

- Bind the companion only to `127.0.0.1`.
- Use a random pairing token between the extension and companion.
- Restrict CORS to the installed extension origin.
- Require the pairing token on every non-health endpoint.
- Store credentials only in macOS Keychain.
- Redact authorization headers, tokens, and signed media URLs from logs.
- Validate and canonicalize YouTube URLs.
- Build process arguments as arrays and never invoke a shell.
- Create one random temporary directory per job.
- Delete temporary files on success, cancellation, and handled failure.
- Sweep abandoned directories older than a configured retention period on startup.
- Retain failed-job files for no more than one hour by default to permit retry.
- Do not access Chrome cookies in the MVP.
- Make it explicit that the tool is for personal reference material and that the user is responsible for using material they are entitled to capture.

## 9. User interface

### 9.1 Capture screen

- Supported-video status
- Video title and channel preview
- Start input
- `Use current time` button
- End input
- `Use current time` button
- Selected duration
- Custom reference title
- Comma-separated or chip-based tags
- Notes
- `Capture to Notion` button

### 9.2 Progress screen

Display the active stage rather than an artificial timer:

- Validating video
- Downloading selected section
- Extracting 10 frames
- Preparing audio
- Transcribing speech
- Uploading to Notion
- Finalizing

Include progress when `yt-dlp` provides it, a cancel action, and concise diagnostic details on failure.

### 9.3 Completion screen

- Confirmation that 10 frames were saved
- Transcript status
- Notion page title
- `Open in Notion`
- `Capture another section`

### 9.4 Setup screen

- Companion detected/not detected
- Install/start instructions
- FFmpeg and `yt-dlp` status
- Deepgram configured/tested status
- Notion configured/tested status
- Selected Notion database link
- Maximum clip duration setting

Secrets are entered into a localhost setup page owned by the companion, not into the Chrome extension.

## 10. Implementation phases

### Phase 0 — Environment and contracts

Estimated effort: 0.5–1 day

- Create extension and companion directories.
- Define shared request/response schemas.
- Add formatter, linter, type checking, and test commands.
- Add a safe `.gitignore` for secrets and generated media.
- Add environment diagnostics for Python, FFmpeg, and Chrome.
- Document local development startup.

Exit criteria:

- Extension loads unpacked.
- Companion health endpoint runs locally.
- Side panel shows the companion health state.

### Phase 1 — YouTube side panel

Estimated effort: 1–1.5 days

- Add Manifest V3 configuration and minimum permissions.
- Enable the side panel only on supported YouTube watch pages.
- Detect SPA navigation between YouTube videos.
- Read video metadata, duration, and current time from the page.
- Implement time parsing and range validation.
- Implement title, tags, and notes fields.
- Add capture job submission and polling.

Exit criteria:

- The panel accurately reflects the active ordinary YouTube video.
- Current-time buttons and validation work.
- A valid request reaches the companion.

### Phase 2 — Media pipeline

Estimated effort: 2–3 days

- Retrieve and normalize metadata with `yt-dlp`.
- Reject unsupported video types.
- Download only the selected section.
- Verify media with FFprobe.
- Extract precise 5%–95% frames.
- Create the temporary MP3.
- Add progress hooks and cancellation.
- Add deterministic cleanup.

Exit criteria:

- A valid job produces exactly 10 correctly ordered images and one playable MP3.
- Images have no YouTube or browser controls.
- Temporary directories are removed on completion and cancellation.

### Phase 3 — Deepgram transcription

Estimated effort: 1–1.5 days

- Add Keychain-backed credential configuration.
- Implement credential testing.
- Submit local MP3s to the prerecorded transcription endpoint.
- Enable Nova-3, smart formatting, utterances, and language detection.
- Normalize transcript, utterance, word timing, confidence, and request metadata.
- Shift timestamps to the YouTube timeline.
- Add retry and error classification.

Exit criteria:

- Spoken content is transcribed and timestamped against the original video.
- No-speech and failed-transcription cases are clearly represented.

### Phase 4 — Notion integration

Estimated effort: 2–3 days

- Add Notion Keychain configuration and access testing.
- Validate the shared parent page.
- Bootstrap or validate the Motion Graphic Library database.
- Create database entries.
- Implement single-part image uploads.
- Attach image blocks with captions.
- Append transcript and processing blocks.
- Add rate limiting, backoff, and idempotent retries.
- Return the final Notion URL to the extension.

Exit criteria:

- A job produces one Notion entry with all metadata, 10 viewable images, notes, tags, and transcript.
- Retrying a partial save does not create a duplicate.

### Phase 5 — UX, recovery, and packaging

Estimated effort: 1.5–2 days

- Build stage-specific progress.
- Add cancellation and retry actions.
- Add actionable setup and failure guidance.
- Add recent-job recovery.
- Add startup cleanup of abandoned files.
- Create a one-command development launcher.
- Document unpacked extension installation.
- Optionally package the companion as a small macOS app after the script-based MVP works.

Exit criteria:

- A nontechnical repeat capture can be performed from Chrome after one-time setup.
- Failures identify the next corrective action.

### Phase 6 — Verification

Estimated effort: 1.5–2 days

- Unit tests for time parsing, sampling, validation, timestamp shifting, state transitions, and Notion mapping.
- Mocked integration tests for Deepgram and Notion.
- Media fixture tests for FFmpeg extraction.
- Manual end-to-end tests against several public normal-length YouTube videos.
- Verify cleanup and secret redaction.
- Verify Chrome reload and YouTube SPA navigation.
- Run a final acceptance checklist.

Exit criteria:

- All acceptance criteria pass.
- No credentials or media artifacts appear in source control.
- The setup and use instructions work from a clean local checkout.

Total estimated implementation effort: 10–14 focused developer days.

## 11. Acceptance criteria

### Capture

- The extension works on normal prerecorded `youtube.com/watch` pages.
- Start and end may be typed or taken from the player’s current time.
- Invalid and unsupported ranges are rejected before download.
- Exactly 10 frames are produced at the defined 5%–95% sample points.
- Frames contain only source video imagery.
- Each frame is captioned with its original-video timestamp in Notion.

### Transcript

- The selected section is converted to MP3 and sent to Deepgram.
- The Notion page contains a readable transcript.
- Timestamped utterances refer to the original YouTube timeline.
- No-speech, low-confidence, and API failure states are clear.

### Notion

- One database entry is created per successful job.
- All confirmed metadata fields are populated.
- All 10 images are viewable directly in the page.
- Tags and notes are preserved.
- The returned page can be opened from the extension.
- A retry cannot create duplicate entries for the same job.

### Reliability and security

- The extension never receives Notion or Deepgram credentials.
- Secrets are stored in macOS Keychain and redacted from logs.
- Temporary media is deleted after success.
- Cancellation stops processing and cleans up.
- Retryable external failures use bounded backoff.
- The companion is reachable only on loopback and requires pairing authorization.

## 12. Test matrix

Test at least:

- 5-second, 30-second, and 5-minute selections
- Selection beginning at zero
- Selection ending near the video duration
- Theater mode and normal mode
- YouTube SPA navigation without refreshing
- Video with speech throughout
- Video with music and no speech
- Video with multiple speakers
- Non-English video
- Slow YouTube download
- Deepgram invalid key, insufficient credit, 429, and 5xx
- Notion unshared page, invalid token, 429, partial upload, and expired upload
- Companion stopped while the panel is open
- Cancellation during download, transcription, and Notion upload
- Duplicate job retry
- Free Notion workspace file-size limit

## 13. Known risks and mitigations

### YouTube/`yt-dlp` compatibility

Risk: YouTube regularly changes delivery behavior and may temporarily break extraction.

Mitigation:

- Pin a known-good `yt-dlp` version.
- Show the installed version in diagnostics.
- Make upgrades isolated and testable.
- Classify extractor errors clearly.
- Avoid logged-in/private content in the MVP.

### Terms and copyright

Risk: Downloading YouTube media may be restricted by YouTube’s terms or the rights attached to a video.

Mitigation:

- Personal-use scope only.
- Download the selected temporary section rather than retaining the full video.
- Delete local media after processing.
- Include a clear responsible-use notice.

### Accurate section boundaries

Risk: Video keyframes can make direct partial downloads begin slightly before the requested time.

Mitigation:

- Download with a small margin.
- Use FFmpeg for the final precise trim and frame timestamps.
- Verify output duration with FFprobe.

### Notion API partial completion

Risk: Image upload or block insertion can fail after the page has been created.

Mitigation:

- Persist the Notion page ID immediately.
- Use explicit processing status.
- Make every finalization step idempotent.
- Retry the same page rather than creating another.

### Credential exposure

Risk: Extension storage, logs, or source control could expose API keys.

Mitigation:

- Keep all secrets in the local companion.
- Store them in Keychain.
- Redact logs.
- Add automated secret-pattern checks.

### Temporary storage accumulation

Risk: Crashes may leave media files behind.

Mitigation:

- Use per-job temporary directories.
- Cleanup in `finally` handlers.
- Run an age-based startup sweeper.
- Display disk usage in diagnostics if cleanup fails.

## 14. Required inputs from the user

No secrets should be pasted into chat or committed to this repository. During setup, the user will need:

1. A Deepgram account with available transcription credit.
2. A dedicated Deepgram API key entered into the local setup page.
3. A Notion internal integration with:
   - Read content
   - Insert content
   - Update content
4. A Notion parent page shared with that integration.
5. The parent page URL entered into the local setup page.
6. FFmpeg installed on the Mac.

The implementation can create the Motion Graphic Library database automatically. The user does not need to design it manually.

## 15. Deferred work

- Shorts, livestreams, embeds, playlists, and restricted videos
- Browser-cookie import
- Chrome Web Store publishing
- Cloud-hosted companion service
- Multi-user authentication
- AI animation/style analysis
- Similarity search and duplicate detection
- OCR of on-screen text
- Video clip storage
- ZIP or filesystem export
- Notion-to-local synchronization
- Automatic title/tag generation

## 16. Definition of done

The MVP is done when a clean installation can take a normal YouTube URL and selected time range, produce 10 clean source frames, transcribe the selected audio through Deepgram, save a complete and correctly structured Notion entry, return its URL to the Chrome side panel, and remove all temporary local media without exposing credentials.
