import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  CompanionError,
  bootstrapNotion,
  cancelJob,
  createJob,
  getHealth,
  getJob,
  getSettings,
  getStoredToken,
  pair,
  retryJob,
  testDeepgram,
  testNotion
} from "./api";
import { formatTime, parseTime } from "./time";
import type { Health, Job, VideoState } from "./types";

const terminalStages = new Set(["complete", "failed", "cancelled"]);

const getActiveVideo = async (): Promise<VideoState> => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) return { supported: false };
  try {
    return (await chrome.tabs.sendMessage(tab.id, {
      type: "GET_VIDEO_STATE"
    })) as VideoState;
  } catch {
    return { supported: false };
  }
};

const friendlyStage = (job: Job): string => {
  const labels: Record<string, string> = {
    queued: "Queued",
    validating: "Validating video",
    metadata: "Reading video metadata",
    downloading: "Downloading selected section",
    extracting: "Extracting frames and audio",
    transcribing: "Transcribing speech",
    creating_notion_page: "Creating Notion entry",
    uploading_frames: "Uploading frames",
    finalizing: "Finalizing",
    complete: "Saved to Notion",
    failed: "Capture failed",
    cancelled: "Capture cancelled"
  };
  return labels[job.stage] ?? job.stage;
};

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [companionOffline, setCompanionOffline] = useState(false);
  const [paired, setPaired] = useState(false);
  const [pairCode, setPairCode] = useState("");
  const [pairError, setPairError] = useState("");
  const [video, setVideo] = useState<VideoState>({ supported: false });
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [title, setTitle] = useState("");
  const [tags, setTags] = useState("");
  const [notes, setNotes] = useState("");
  const [job, setJob] = useState<Job | null>(null);
  const [formError, setFormError] = useState("");
  const [setupMessage, setSetupMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const previousVideoId = useRef<string | undefined>(undefined);

  const refreshHealth = useCallback(async () => {
    try {
      const current = await getHealth();
      setHealth(current);
      setCompanionOffline(false);
      const token = await getStoredToken();
      if (!token) {
        setPaired(false);
        return;
      }
      try {
        await getSettings();
        setPaired(true);
      } catch (error) {
        if (error instanceof CompanionError && error.status === 401) {
          await chrome.storage.local.remove("pairToken");
          setPaired(false);
        }
      }
    } catch {
      setCompanionOffline(true);
      setHealth(null);
      setPaired(false);
    }
  }, []);

  useEffect(() => {
    void refreshHealth();
    const timer = window.setInterval(() => void refreshHealth(), 3000);
    return () => window.clearInterval(timer);
  }, [refreshHealth]);

  useEffect(() => {
    const refreshVideo = async () => {
      const current = await getActiveVideo();
      setVideo(current);
      if (current.supported && current.videoId !== previousVideoId.current) {
        const currentTime = current.currentTime ?? 0;
        const duration = current.duration ?? currentTime + 10;
        setStart(formatTime(currentTime));
        setEnd(formatTime(Math.min(duration, currentTime + 10)));
        setTitle("");
        setTags("");
        setNotes("");
        setJob(null);
        setFormError("");
        previousVideoId.current = current.videoId;
      }
    };
    void refreshVideo();
    const timer = window.setInterval(() => void refreshVideo(), 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!job || terminalStages.has(job.stage)) return;
    const timer = window.setInterval(async () => {
      try {
        setJob(await getJob(job.id));
      } catch (error) {
        setFormError(error instanceof Error ? error.message : "Could not read job progress.");
      }
    }, 750);
    return () => window.clearInterval(timer);
  }, [job?.id, job?.stage]);

  const validation = useMemo(() => {
    const startSeconds = parseTime(start);
    const endSeconds = parseTime(end);
    if (startSeconds === null || endSeconds === null) {
      return { error: "Use seconds, M:SS, or H:MM:SS.", startSeconds, endSeconds };
    }
    if (endSeconds <= startSeconds) {
      return { error: "End time must be after start time.", startSeconds, endSeconds };
    }
    if (endSeconds - startSeconds < 0.5) {
      return { error: "Select at least half a second.", startSeconds, endSeconds };
    }
    if (video.duration && endSeconds > video.duration + 0.25) {
      return { error: "End time is beyond this video.", startSeconds, endSeconds };
    }
    return { error: "", startSeconds, endSeconds };
  }, [start, end, video.duration]);

  const submitPairing = async () => {
    setBusy(true);
    setPairError("");
    try {
      await pair(pairCode.trim());
      setPaired(true);
      setPairCode("");
      await refreshHealth();
    } catch (error) {
      setPairError(error instanceof Error ? error.message : "Pairing failed.");
    } finally {
      setBusy(false);
    }
  };

  const runSetupAction = async (action: "deepgram" | "notion" | "bootstrap") => {
    setBusy(true);
    setSetupMessage("");
    try {
      if (action === "deepgram") {
        await testDeepgram();
        setSetupMessage("Deepgram connection works.");
      } else if (action === "notion") {
        await testNotion();
        setSetupMessage("Notion connection works.");
      } else {
        const result = await bootstrapNotion();
        setSetupMessage("Motion Graphic Library is ready in Notion.");
        if (result.database_url) window.open(result.database_url, "_blank");
      }
      await refreshHealth();
    } catch (error) {
      setSetupMessage(error instanceof Error ? error.message : "Setup check failed.");
    } finally {
      setBusy(false);
    }
  };

  const submitCapture = async () => {
    setFormError("");
    if (!video.supported || !video.url) {
      setFormError("Open a normal YouTube video first.");
      return;
    }
    if (validation.error || validation.startSeconds === null || validation.endSeconds === null) {
      setFormError(validation.error || "Check the selected times.");
      return;
    }
    setBusy(true);
    try {
      const created = await createJob({
        youtube_url: video.url,
        start_seconds: validation.startSeconds,
        end_seconds: validation.endSeconds,
        custom_title: title.trim(),
        tags: tags
          .split(",")
          .map((tag) => tag.trim())
          .filter(Boolean),
        notes: notes.trim(),
        language: "auto"
      });
      setJob(created);
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "Could not start capture.");
    } finally {
      setBusy(false);
    }
  };

  if (companionOffline) {
    return (
      <Shell>
        <StatusCard tone="warning" eyebrow="Companion offline" title="Start the local service">
          <p>The extension needs the local companion to run yt-dlp, FFmpeg, Deepgram, and Notion.</p>
          <code>cd companion &amp;&amp; uv run snatcher serve</code>
          <button className="secondary" onClick={() => void refreshHealth()}>
            Check again
          </button>
        </StatusCard>
      </Shell>
    );
  }

  if (!health) {
    return (
      <Shell>
        <div className="loading">Checking local companion…</div>
      </Shell>
    );
  }

  if (!paired) {
    return (
      <Shell>
        <StatusCard tone="accent" eyebrow="First-time setup" title="Pair this extension">
          <p>Enter the eight-character code printed by <code>snatcher serve</code>.</p>
          <label>
            Pairing code
            <input
              value={pairCode}
              onChange={(event) => setPairCode(event.target.value)}
              placeholder="e.g. a1b2c3d4"
              autoFocus
            />
          </label>
          {pairError && <div className="inline-error">{pairError}</div>}
          <button disabled={busy || pairCode.trim().length < 6} onClick={() => void submitPairing()}>
            {busy ? "Pairing…" : "Pair extension"}
          </button>
        </StatusCard>
      </Shell>
    );
  }

  if (!health.deepgram_configured || !health.notion_configured || !health.notion_database_configured) {
    return (
      <Shell>
        <StatusCard tone="neutral" eyebrow="One-time setup" title="Connect the pipeline">
          <SetupRow
            label="FFmpeg & FFprobe"
            ready={health.ffmpeg && health.ffprobe}
            detail={health.ffmpeg && health.ffprobe ? "Ready" : "Install with Homebrew"}
          />
          <SetupRow label="yt-dlp" ready={health.yt_dlp} detail={health.yt_dlp ? "Ready" : "Missing"} />
          <SetupRow
            label="Deepgram"
            ready={health.deepgram_configured}
            detail={health.deepgram_configured ? "Configured" : "Run snatcher configure"}
          />
          <SetupRow
            label="Notion connection"
            ready={health.notion_configured}
            detail={health.notion_configured ? "Configured" : "Run snatcher configure"}
          />
          <SetupRow
            label="Notion library"
            ready={health.notion_database_configured}
            detail={health.notion_database_configured ? "Ready" : "Needs creation"}
          />
          <code>cd companion &amp;&amp; uv run snatcher configure</code>
          <div className="button-grid">
            <button
              className="secondary"
              disabled={busy || !health.deepgram_configured}
              onClick={() => void runSetupAction("deepgram")}
            >
              Test Deepgram
            </button>
            <button
              className="secondary"
              disabled={busy || !health.notion_configured}
              onClick={() => void runSetupAction("notion")}
            >
              Test Notion
            </button>
          </div>
          <button
            disabled={busy || !health.notion_configured}
            onClick={() => void runSetupAction("bootstrap")}
          >
            {busy ? "Working…" : "Create Notion library"}
          </button>
          {setupMessage && <div className="setup-message">{setupMessage}</div>}
        </StatusCard>
      </Shell>
    );
  }

  if (job && job.stage === "complete") {
    return (
      <Shell>
        <StatusCard tone="success" eyebrow="Capture complete" title="Saved to Notion">
          <div className="success-stat">
            <strong>{job.frame_count}</strong>
            <span>timestamped frames</span>
          </div>
          <p>{job.transcript_status || "Transcript saved"}.</p>
          {job.notion_url && (
            <button onClick={() => window.open(job.notion_url, "_blank")}>Open in Notion</button>
          )}
          <button className="secondary" onClick={() => setJob(null)}>
            Capture another section
          </button>
        </StatusCard>
      </Shell>
    );
  }

  if (job) {
    const failed = job.stage === "failed";
    const cancelled = job.stage === "cancelled";
    return (
      <Shell>
        <StatusCard
          tone={failed ? "danger" : cancelled ? "neutral" : "accent"}
          eyebrow={failed ? "Needs attention" : "Capture in progress"}
          title={friendlyStage(job)}
        >
          {!failed && !cancelled && (
            <>
              <div className="progress-track">
                <div className="progress-fill" style={{ width: `${Math.round(job.progress * 100)}%` }} />
              </div>
              <div className="progress-meta">
                <span>{job.message}</span>
                <span>{Math.round(job.progress * 100)}%</span>
              </div>
              <button className="secondary danger-text" onClick={() => void cancelJob(job.id)}>
                Cancel
              </button>
            </>
          )}
          {failed && (
            <>
              <p className="error-copy">{job.error_message || "The capture failed."}</p>
              <div className="button-grid">
                {job.retryable && (
                  <button
                    onClick={async () => {
                      setJob(await retryJob(job.id));
                    }}
                  >
                    Retry
                  </button>
                )}
                <button className="secondary" onClick={() => setJob(null)}>
                  Back
                </button>
              </div>
            </>
          )}
          {cancelled && (
            <button className="secondary" onClick={() => setJob(null)}>
              Back to capture
            </button>
          )}
        </StatusCard>
      </Shell>
    );
  }

  return (
    <Shell>
      {!video.supported ? (
        <StatusCard tone="neutral" eyebrow="Waiting for a video" title="Open a YouTube watch page">
          <p>Normal prerecorded videos are supported. Shorts and livestreams are not included yet.</p>
        </StatusCard>
      ) : (
        <main className="capture-form">
          <div className="video-card">
            <div className="video-kicker">Current video</div>
            <h2>{video.title}</h2>
            <p>{video.channel}</p>
            <span>{formatTime(video.duration ?? 0)} total</span>
          </div>

          <section>
            <div className="section-heading">
              <div>
                <span>01</span>
                <h3>Select the moment</h3>
              </div>
              {validation.startSeconds !== null && validation.endSeconds !== null && !validation.error && (
                <small>{formatTime(validation.endSeconds - validation.startSeconds)} selected</small>
              )}
            </div>
            <div className="time-grid">
              <label>
                Start
                <input value={start} onChange={(event) => setStart(event.target.value)} />
                <button
                  className="text-button"
                  onClick={() => setStart(formatTime(video.currentTime ?? 0))}
                >
                  Use current time
                </button>
              </label>
              <label>
                End
                <input value={end} onChange={(event) => setEnd(event.target.value)} />
                <button
                  className="text-button"
                  onClick={() => setEnd(formatTime(video.currentTime ?? 0))}
                >
                  Use current time
                </button>
              </label>
            </div>
            {validation.error && <div className="inline-error">{validation.error}</div>}
          </section>

          <section>
            <div className="section-heading">
              <div>
                <span>02</span>
                <h3>Describe the reference</h3>
              </div>
            </div>
            <label>
              Reference title <em>optional</em>
              <input
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder="e.g. Type assembles into a logo"
                maxLength={200}
              />
            </label>
            <label>
              Tags <em>comma separated</em>
              <input
                value={tags}
                onChange={(event) => setTags(event.target.value)}
                placeholder="kinetic type, logo reveal, dark"
              />
            </label>
            <label>
              Notes <em>optional</em>
              <textarea
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
                placeholder="What is useful about this animation?"
                rows={4}
                maxLength={2000}
              />
            </label>
          </section>

          {formError && <div className="form-error">{formError}</div>}
          <button
            className="capture-button"
            disabled={busy || Boolean(validation.error)}
            onClick={() => void submitCapture()}
          >
            <span>{busy ? "Starting…" : "Capture to Notion"}</span>
            <span aria-hidden>→</span>
          </button>
          <p className="privacy-note">Temporary media is deleted after the Notion entry is saved.</p>
        </main>
      )}
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="app-shell">
      <header>
        <div className="brand-mark">
          <span />
          <span />
          <span />
        </div>
        <div>
          <h1>Graphic Snatcher</h1>
          <p>YouTube → Notion</p>
        </div>
      </header>
      {children}
      <footer>
        <span className="status-dot" />
        Local-only media processing
      </footer>
    </div>
  );
}

function StatusCard({
  tone,
  eyebrow,
  title,
  children
}: {
  tone: "warning" | "accent" | "neutral" | "success" | "danger";
  eyebrow: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <main className={`status-card ${tone}`}>
      <div className="status-icon">{tone === "success" ? "✓" : tone === "danger" ? "!" : "◆"}</div>
      <span className="eyebrow">{eyebrow}</span>
      <h2>{title}</h2>
      {children}
    </main>
  );
}

function SetupRow({ label, ready, detail }: { label: string; ready: boolean; detail: string }) {
  return (
    <div className="setup-row">
      <span className={ready ? "ready" : "pending"}>{ready ? "✓" : "·"}</span>
      <div>
        <strong>{label}</strong>
        <small>{detail}</small>
      </div>
    </div>
  );
}

