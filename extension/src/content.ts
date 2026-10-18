export interface VideoState {
  supported: boolean;
  videoId?: string;
  url?: string;
  title?: string;
  channel?: string;
  currentTime?: number;
  duration?: number;
  paused?: boolean;
}

const textFrom = (selector: string): string | undefined => {
  const value = document.querySelector(selector)?.textContent?.trim();
  return value || undefined;
};

const getVideoState = (): VideoState => {
  const url = new URL(window.location.href);
  const videoId = url.searchParams.get("v");
  const video = document.querySelector<HTMLVideoElement>("video.html5-main-video, video");
  if (
    !["youtube.com", "www.youtube.com"].includes(url.hostname) ||
    url.pathname !== "/watch" ||
    !videoId ||
    !video
  ) {
    return { supported: false };
  }
  const canonicalUrl = `https://www.youtube.com/watch?v=${encodeURIComponent(videoId)}`;
  const title =
    document.querySelector<HTMLMetaElement>('meta[name="title"]')?.content ||
    textFrom("ytd-watch-metadata h1 yt-formatted-string") ||
    document.title.replace(/\s*-\s*YouTube$/, "");
  const channel =
    textFrom("ytd-watch-metadata ytd-channel-name a") ||
    textFrom("#owner ytd-channel-name a") ||
    "Unknown channel";
  return {
    supported: true,
    videoId,
    url: canonicalUrl,
    title,
    channel,
    currentTime: Number.isFinite(video.currentTime) ? video.currentTime : 0,
    duration: Number.isFinite(video.duration) ? video.duration : 0,
    paused: video.paused
  };
};

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "GET_VIDEO_STATE") {
    sendResponse(getVideoState());
  }
});

