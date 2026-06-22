import { describe, expect, it } from "vitest";

import { historyViz, severityViz } from "./findingViz";

describe("severityViz", () => {
  it("labels and colours each severity, passing unknowns through", () => {
    expect(severityViz("critical").label).toBe("Critical");
    expect(severityViz("critical").dot).toBe("bg-severity-critical-dot");
    expect(severityViz("major").label).toBe("Major");
    expect(severityViz("minor").label).toBe("Minor");
    expect(severityViz("weird").label).toBe("weird");
  });
});

describe("historyViz", () => {
  it("labels and colours each history class, passing unknowns through", () => {
    expect(historyViz("new").label).toBe("New");
    expect(historyViz("new").dot).toBe("bg-history-new-fg");
    expect(historyViz("regression").label).toBe("Regression");
    expect(historyViz("known").label).toBe("Known");
    expect(historyViz("flaky").label).toBe("Flaky");
    expect(historyViz("weird").label).toBe("weird");
  });
});
