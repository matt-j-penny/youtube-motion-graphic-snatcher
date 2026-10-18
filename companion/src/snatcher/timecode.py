from __future__ import annotations


def format_timecode(seconds: float, *, milliseconds: bool = False) -> str:
    seconds = max(0, seconds)
    whole = int(seconds)
    hours, remainder = divmod(whole, 3600)
    minutes, secs = divmod(remainder, 60)
    suffix = f".{int(round((seconds - whole) * 1000)):03d}" if milliseconds else ""
    if suffix == ".1000":
        whole += 1
        hours, remainder = divmod(whole, 3600)
        minutes, secs = divmod(remainder, 60)
        suffix = ".000"
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}{suffix}"
    return f"{minutes:02d}:{secs:02d}{suffix}"


def sample_timestamps(start: float, end: float, count: int = 10) -> list[float]:
    duration = end - start
    if duration <= 0:
        raise ValueError("End must be after start.")
    if count <= 0:
        raise ValueError("Count must be positive.")
    return [start + ((index + 0.5) / count) * duration for index in range(count)]
