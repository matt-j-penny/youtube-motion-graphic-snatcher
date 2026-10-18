import { describe, expect, it } from "vitest";

import { formatTime, parseTime } from "./time";

describe("parseTime", () => {
  it("parses seconds and colon formats", () => {
    expect(parseTime("75")).toBe(75);
    expect(parseTime("1:15")).toBe(75);
    expect(parseTime("1:02:15")).toBe(3735);
    expect(parseTime("0:01.5")).toBe(1.5);
  });

  it("rejects malformed or overflowing values", () => {
    expect(parseTime("")).toBeNull();
    expect(parseTime("1:75")).toBeNull();
    expect(parseTime("a:b")).toBeNull();
    expect(parseTime("-1")).toBeNull();
  });
});

describe("formatTime", () => {
  it("formats short and long values", () => {
    expect(formatTime(75)).toBe("1:15");
    expect(formatTime(3735)).toBe("1:02:15");
  });
});

