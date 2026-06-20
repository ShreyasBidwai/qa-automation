import { describe, expect, it } from "vitest";

import { modeLabel } from "./modeLabel";

describe("modeLabel", () => {
  it("maps the persisted Run.mode values from the list endpoint", () => {
    expect(modeLabel("B")).toBe("Autonomous (Mode B)");
    expect(modeLabel("C")).toBe("Natural language (Mode C)");
  });

  it("maps the create-form mode values", () => {
    expect(modeLabel("mode_b")).toBe("Autonomous (Mode B)");
    expect(modeLabel("mode_c")).toBe("Natural language (Mode C)");
  });

  it("passes through an unknown value unchanged", () => {
    expect(modeLabel("whatever")).toBe("whatever");
  });
});
