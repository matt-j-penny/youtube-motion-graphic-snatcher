import type { CaptureRequest, Health, Job } from "./types";

const BASE_URL = "http://127.0.0.1:43127/v1";

export class CompanionError extends Error {
  constructor(
    message: string,
    readonly code?: string,
    readonly status?: number
  ) {
    super(message);
  }
}

const readError = async (response: Response): Promise<CompanionError> => {
  try {
    const body = await response.json();
    const error = body.error ?? body;
    return new CompanionError(
      error.message ?? error.detail ?? "Companion request failed.",
      error.code,
      response.status
    );
  } catch {
    return new CompanionError(`Companion request failed (${response.status}).`, undefined, response.status);
  }
};

export const getStoredToken = async (): Promise<string | null> => {
  const value = await chrome.storage.local.get("pairToken");
  return typeof value.pairToken === "string" ? value.pairToken : null;
};

const request = async <T>(
  path: string,
  init: RequestInit = {},
  authenticated = true
): Promise<T> => {
  const token = authenticated ? await getStoredToken() : null;
  const response = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { "X-Snatcher-Token": token } : {}),
      ...(init.headers ?? {})
    }
  });
  if (!response.ok) throw await readError(response);
  return response.json() as Promise<T>;
};

export const getHealth = (): Promise<Health> => request("/health", {}, false);

export const pair = async (code: string): Promise<void> => {
  const value = await request<{ token: string }>(
    "/pair",
    { method: "POST", body: JSON.stringify({ code }) },
    false
  );
  await chrome.storage.local.set({ pairToken: value.token });
};

export const getSettings = (): Promise<Record<string, unknown>> => request("/settings");

export const testDeepgram = (): Promise<{ status: string }> =>
  request("/setup/deepgram/test", { method: "POST" });

export const testNotion = (): Promise<{ status: string }> =>
  request("/setup/notion/test", { method: "POST" });

export const bootstrapNotion = (): Promise<{ status: string; database_url?: string }> =>
  request("/setup/notion/bootstrap", { method: "POST" });

export const createJob = (payload: CaptureRequest): Promise<Job> =>
  request("/jobs", { method: "POST", body: JSON.stringify(payload) });

export const getJob = (jobId: string): Promise<Job> => request(`/jobs/${jobId}`);

export const cancelJob = (jobId: string): Promise<Job> =>
  request(`/jobs/${jobId}/cancel`, { method: "POST" });

export const retryJob = (jobId: string): Promise<Job> =>
  request(`/jobs/${jobId}/retry`, { method: "POST" });

