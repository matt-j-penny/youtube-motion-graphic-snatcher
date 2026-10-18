const isSupportedUrl = (url?: string): boolean => {
  if (!url) return false;
  try {
    const parsed = new URL(url);
    return (
      ["youtube.com", "www.youtube.com"].includes(parsed.hostname) &&
      parsed.pathname === "/watch" &&
      Boolean(parsed.searchParams.get("v"))
    );
  } catch {
    return false;
  }
};

chrome.runtime.onInstalled.addListener(() => {
  void chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });
});

chrome.runtime.onStartup.addListener(() => {
  void chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  const url = changeInfo.url ?? tab.url;
  if (!url) return;
  void chrome.sidePanel.setOptions({
    tabId,
    path: "sidepanel.html",
    enabled: isSupportedUrl(url)
  });
});

