import type { VideoState } from "./content";

export type { VideoState };

export interface Health {
  status: string;
  version: string;
  ffmpeg: boolean;
  ffprobe: boolean;
  yt_dlp: boolean;
  deepgram_configured: boolean;
  notion_configured: boolean;
  notion_database_configured: boolean;
  pairing_required: boolean;
}

export type JobStage =
  | "queued"
  | "validating"
  | "metadata"
  | "downloading"
  | "extracting"
  | "transcribing"
  | "creating_notion_page"
  | "uploading_frames"
  | "finalizing"
  | "complete"
  | "failed"
  | "cancelled";

export interface CaptureRequest {
  youtube_url: string;
  start_seconds: number;
  end_seconds: number;
  custom_title: string;
  tags: string[];
  notes: string;
  language: string;
}

export interface Job {
  id: string;
  stage: JobStage;
  progress: number;
  message: string;
  frame_count: number;
  transcript_status?: string;
  notion_url?: string;
  error_code?: string;
  error_message?: string;
  retryable: boolean;
}

