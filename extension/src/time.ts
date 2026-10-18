export const parseTime = (input: string): number | null => {
  const trimmed = input.trim();
  if (!trimmed) return null;
  const parts = trimmed.split(":");
  if (parts.length > 3 || parts.some((part) => part === "" || !/^\d+(\.\d+)?$/.test(part))) {
    return null;
  }
  const values = parts.map(Number);
  if (values.some((value) => !Number.isFinite(value) || value < 0)) return null;
  if (parts.length > 1 && values.slice(1).some((value) => value >= 60)) return null;
  return values.reduce((total, value) => total * 60 + value, 0);
};

export const formatTime = (seconds: number): string => {
  const value = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  const secs = value % 60;
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`
    : `${minutes}:${String(secs).padStart(2, "0")}`;
};

