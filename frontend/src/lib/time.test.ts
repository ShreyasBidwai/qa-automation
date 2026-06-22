import { describe, expect, it } from "vitest";

import { relativeTime } from "./time";

const NOW = Date.parse("2026-06-22T12:00:00Z");

describe("relativeTime", () => {
  it("formats recent timestamps relative to now", () => {
    expect(relativeTime("2026-06-22T11:59:30Z", NOW)).toBe("just now");
    expect(relativeTime("2026-06-22T11:45:00Z", NOW)).toBe("15 min ago");
    expect(relativeTime("2026-06-22T09:00:00Z", NOW)).toBe("3 hr ago");
    expect(relativeTime("2026-06-21T12:00:00Z", NOW)).toBe("1 day ago");
    expect(relativeTime("2026-06-19T12:00:00Z", NOW)).toBe("3 days ago");
  });

  it("falls back to a locale date for anything older than ~a month", () => {
    const iso = "2026-01-01T12:00:00Z";
    expect(relativeTime(iso, NOW)).toBe(new Date(iso).toLocaleDateString());
  });

  it("returns an empty string for an unparseable date", () => {
    expect(relativeTime("not-a-date", NOW)).toBe("");
  });
});
