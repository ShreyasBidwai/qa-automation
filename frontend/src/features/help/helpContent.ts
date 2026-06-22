/**
 * Help center content — structured data, NOT prose-in-markup. Everything the
 * reader sees lives here as plain objects so (a) content is easy to edit without
 * touching React, and (b) the search index (helpSearch.ts) can read every word
 * from the same source the renderer (HelpBlocks.tsx) draws from. One source of
 * truth: change a sentence here and both the page and search follow.
 *
 * Tone (per the brief): beginner-proof. Plain language, short sentences, and a
 * concrete example in every section. We assume the reader has never used a QA
 * tool, so terms are introduced before they are used.
 */

/** A trust mark: the symbol + colour + meaning that says how much to believe a test. */
export interface TrustMark {
  /** Drives the rendered glyph shape (see HelpBlocks → TrustGlyph). */
  variant: "solid" | "hollow" | "ring";
  /** The literal symbol, kept for the search index and as a text fallback. */
  symbol: string;
  /** The colour word — colour is never the only signal, the name carries it too. */
  color: string;
  /** The short name shown as the badge label. */
  name: string;
  /** One word for how strong the signal is. */
  strength: string;
  /** The full plain-language explanation. */
  meaning: string;
}

/** One node on the cross-layer blast path (page → endpoint → model → table). */
export interface BlastNode {
  tier: string;
  label: string;
}

/** One numbered step in the loop. */
export interface Step {
  label: string;
  detail: string;
}

/** A term and its one-line plain definition (modes, history, triage, glossary…). */
export interface Definition {
  term: string;
  definition: string;
}

/**
 * A renderable block. The renderer switches on `kind`; the indexer pulls text
 * out of each kind (see blockText in helpSearch.ts). Adding a kind means
 * updating both — they are intentionally kept in lockstep.
 */
export type HelpBlock =
  | { kind: "text"; text: string }
  | { kind: "list"; items: string[] }
  | { kind: "steps"; items: Step[] }
  | { kind: "example"; text: string }
  | { kind: "trustMarks"; items: TrustMark[] }
  | { kind: "blastPath"; nodes: BlastNode[]; failingIndex: number; caption: string }
  | { kind: "definitions"; items: Definition[] };

export interface HelpSection {
  /** Stable slug — the anchor id and the jump target. Never reuse one. */
  id: string;
  title: string;
  /** One line under the title and in the section list. */
  summary: string;
  /** Extra search terms (symbols, synonyms) that may not appear in the prose. */
  keywords?: string[];
  body: HelpBlock[];
}

export const HELP_SECTIONS: HelpSection[] = [
  {
    id: "what-is-polaris",
    title: "What is Polaris?",
    summary:
      "An automated QA tool that reads your code, writes and runs tests, then ranks the problems it finds.",
    keywords: ["qa", "quality assurance", "automated", "intro", "overview"],
    body: [
      {
        kind: "text",
        text: "Polaris is an automated QA tool. QA means quality assurance — making sure software works the way it should. Normally a person writes test cases by hand and reads through the results. Polaris does that work for you.",
      },
      {
        kind: "text",
        text: "It reads your app’s code, builds an understanding of how the app fits together, writes tests, runs them, and then shows you a ranked list of problems. Each problem is called a finding.",
      },
      {
        kind: "text",
        text: "“Testing with Polaris” means you stop hand-writing test cases. Polaris generates and runs them, then tells you two things: what’s broken, and how much to trust each result.",
      },
      {
        kind: "example",
        text: "Say you run an online store. Instead of writing a test that signs in, adds an item, and checks out, you point Polaris at the store. It works out the checkout flow on its own, tries it, and reports back: “Orders can be placed without signing in” — a real problem, ranked at the top.",
      },
    ],
  },
  {
    id: "how-it-works",
    title: "How it works — the loop",
    summary: "The five-step loop: understand, generate, run, review, triage.",
    keywords: ["loop", "process", "steps", "pipeline", "how"],
    body: [
      {
        kind: "text",
        text: "Polaris works in a loop. Every run moves through five steps, in order.",
      },
      {
        kind: "steps",
        items: [
          {
            label: "Understand",
            detail:
              "Polaris reads your code and builds a model of the app — its pages, its endpoints, its data.",
          },
          {
            label: "Generate",
            detail:
              "It writes tests from that model — the checks a careful tester would run.",
          },
          {
            label: "Run",
            detail: "It executes those tests against your running app.",
          },
          {
            label: "Review",
            detail: "It turns the raw results into ranked findings, worst first.",
          },
          {
            label: "Triage",
            detail: "You decide what to do with each finding.",
          },
        ],
      },
      {
        kind: "text",
        text: "The first four steps are automatic. The last step, triage, is where you come in.",
      },
      {
        kind: "example",
        text: "On a store app: Understand maps the checkout page to its order endpoint and the orders table. Generate writes a test that places an order. Run carries it out. Review ranks “orders accepted without signing in” as the top finding. Triage is you deciding to fix it.",
      },
    ],
  },
  {
    id: "modes",
    title: "The 3 ways to ask for tests",
    summary: "Three modes: describe it, autonomous, or authoring.",
    keywords: [
      "mode",
      "modes",
      "describe it",
      "autonomous",
      "authoring",
      "natural language",
    ],
    body: [
      {
        kind: "text",
        text: "You ask Polaris for tests in one of three ways. These are called modes. Pick whichever fits what you want to do.",
      },
      {
        kind: "definitions",
        items: [
          {
            term: "Describe it",
            definition:
              "Write what to test in plain English, like “test checkout”. Polaris turns your sentence into tests. Best when you know the area you care about but don’t want to spell out every step.",
          },
          {
            term: "Autonomous",
            definition:
              "Let Polaris decide what to test. Aim it at everything, or at only what changed since the last run. Best for broad coverage with little effort.",
          },
          {
            term: "Authoring",
            definition:
              "Write specific test cases yourself when you need exact, repeatable checks. Best when one particular behaviour must be pinned down precisely.",
          },
        ],
      },
      {
        kind: "example",
        text: "Want to check one flow? Use Describe it and type “test checkout”. Want a full sweep after a big change? Use Autonomous and choose “test only what changed”. Need to lock down one exact rule? Use Authoring.",
      },
    ],
  },
  {
    id: "findings",
    title: "Findings",
    summary: "A finding is a ranked problem — not a raw test log.",
    keywords: ["finding", "findings", "problem", "ranked", "result"],
    body: [
      {
        kind: "text",
        text: "A finding is a single problem Polaris found, written in plain language. It is not a raw test log — Polaris does the reading for you and hands you the conclusion.",
      },
      {
        kind: "text",
        text: "Every finding carries four labels so you can judge it at a glance:",
      },
      {
        kind: "definitions",
        items: [
          { term: "Severity", definition: "How bad the problem is." },
          { term: "Confidence", definition: "How sure Polaris is that it’s real." },
          { term: "Layer", definition: "Where it lives — api, ui, or db." },
          {
            term: "Status",
            definition:
              "Where it is in your workflow — for example new, or already resolved.",
          },
        ],
      },
      {
        kind: "example",
        text: "A finding might read: “Orders accepted without authentication” — severity critical, high confidence, layer api, status new. One line tells you it’s serious, it’s almost certainly real, it’s in the API, and you haven’t seen it before.",
      },
    ],
  },
  {
    id: "trust-marks",
    title: "Trust marks",
    summary:
      "The symbols that say how much to believe a test: rule-derived, characterization, spec-grounded.",
    keywords: [
      "trust mark",
      "trust marks",
      "oracle",
      "rule-derived",
      "characterization",
      "spec-grounded",
      "●",
      "◌",
      "◉",
      "emerald",
      "amber",
      "blue",
    ],
    body: [
      {
        kind: "text",
        text: "Trust marks are the most important symbols in Polaris. Behind every test is an oracle — the thing that decides pass or fail. The trust mark tells you how trustworthy that oracle is. In one question: how much should you believe this test?",
      },
      {
        kind: "trustMarks",
        items: [
          {
            variant: "solid",
            symbol: "●",
            color: "emerald",
            name: "Rule-derived",
            strength: "strong",
            meaning:
              "The check follows from a real rule, so a failure is almost certainly a real bug. Trust it.",
          },
          {
            variant: "hollow",
            symbol: "◌",
            color: "amber",
            name: "Characterization",
            strength: "weak",
            meaning:
              "The check only pins down how the app behaves right now. A failure means behaviour changed — which might be a bug, or might be on purpose. Look before you act.",
          },
          {
            variant: "ring",
            symbol: "◉",
            color: "blue",
            name: "Spec-grounded",
            strength: "anchored",
            meaning:
              "The check is tied to a documented contract or spec — something written down. A failure means the app broke a promise it made.",
          },
        ],
      },
      {
        kind: "text",
        text: "Why it matters: a test you can’t trust is just noise. Polaris is honest about which of its own tests are strong and which are weak. That honesty is what makes it different from a tool that reports every check as equally certain.",
      },
      {
        kind: "example",
        text: "Two findings both say “failed”. The one with a solid emerald mark follows a real rule (“orders must require sign-in”) — believe it and fix it. The one with a hollow amber mark only noticed today’s behaviour differs from yesterday’s — worth a look, but it may just be an intended change.",
      },
    ],
  },
  {
    id: "severity-confidence",
    title: "Severity & confidence",
    summary:
      "Severity is how bad; confidence is how sure. They are separate on purpose.",
    keywords: [
      "severity",
      "confidence",
      "critical",
      "major",
      "minor",
      "blast radius",
      "failure shape",
    ],
    body: [
      {
        kind: "text",
        text: "Severity and confidence answer two different questions. Polaris keeps them apart on purpose, because a problem can be very bad but uncertain, or very certain but minor.",
      },
      {
        kind: "definitions",
        items: [
          {
            term: "Severity — how bad",
            definition:
              "Polaris combines blast radius (how much of the app it touches) with failure shape (how it breaks) into one of three levels: critical, major, or minor.",
          },
          {
            term: "Confidence — how sure",
            definition:
              "How certain Polaris is that this is a real problem and not a false alarm.",
          },
        ],
      },
      {
        kind: "text",
        text: "Read them together. Critical and high confidence is a drop-everything bug. Critical but low confidence is worth a look yet might be a false alarm. Minor but high confidence is real, and can wait.",
      },
      {
        kind: "example",
        text: "“Payment data stored unencrypted” could be critical severity but only medium confidence — Polaris isn’t certain the field holds card numbers. “Button label misspelled” is high confidence but minor severity. Different problems, sorted differently.",
      },
    ],
  },
  {
    id: "blast-path",
    title: "Cross-layer blast path",
    summary:
      "The chain page → endpoint → model → table that shows how far a problem reaches.",
    keywords: [
      "blast path",
      "cross-layer",
      "cross layer",
      "page",
      "endpoint",
      "model",
      "table",
      "reach",
    ],
    body: [
      {
        kind: "text",
        text: "The blast path shows how far a problem reaches across your app. It is a chain: the page a user sees → the endpoint it calls → the model that handles the data → the table underneath. The node where things break is lit up.",
      },
      {
        kind: "text",
        text: "It answers “where did it break, and what does it touch?” in a single glance.",
      },
      {
        kind: "blastPath",
        nodes: [
          { tier: "Page", label: "/checkout" },
          { tier: "Endpoint", label: "POST /api/orders" },
          { tier: "Model", label: "Order" },
          { tier: "Table", label: "orders" },
        ],
        failingIndex: 1,
        caption: "The checkout page calls the orders endpoint, which fails here.",
      },
      {
        kind: "text",
        text: "In this checkout example, the page /checkout calls POST /api/orders. That endpoint is lit — it accepted an order it should have rejected. The problem starts there and flows down to the Order model and the orders table, where a bad row gets written.",
      },
      {
        kind: "example",
        text: "Seeing the whole chain tells you the fix belongs at the endpoint, not the page. The page did its job; the endpoint failed to check the rules.",
      },
    ],
  },
  {
    id: "history",
    title: "History",
    summary: "Is this finding new, known, a regression, or flaky?",
    keywords: [
      "history",
      "new",
      "known",
      "regression",
      "flaky",
      "intermittent",
      "seen before",
    ],
    body: [
      {
        kind: "text",
        text: "History tells you whether you have seen this finding before. It is one of four labels.",
      },
      {
        kind: "definitions",
        items: [
          { term: "New", definition: "Polaris is reporting this for the first time." },
          {
            term: "Known",
            definition: "Seen in earlier runs too — nothing about it has changed.",
          },
          {
            term: "Regression",
            definition:
              "It was fixed before, and now it is back. Worth attention — something undid the fix.",
          },
          {
            term: "Flaky",
            definition:
              "It comes and goes between runs. The test passes sometimes and fails others, so the result is unreliable.",
          },
        ],
      },
      {
        kind: "example",
        text: "A finding tagged regression on the checkout flow means: you fixed “orders without sign-in” last week, and this run it failed again. Something reopened the hole.",
      },
    ],
  },
  {
    id: "triage",
    title: "Triage",
    summary:
      "What you do with a finding: acknowledge, resolve, won’t fix, or false positive.",
    keywords: [
      "triage",
      "acknowledge",
      "resolve",
      "won't fix",
      "wont fix",
      "false positive",
      "disposition",
    ],
    body: [
      {
        kind: "text",
        text: "Triage is the step where you decide what to do with a finding. There are four choices, and your choice is called a disposition.",
      },
      {
        kind: "definitions",
        items: [
          {
            term: "Acknowledge",
            definition:
              "You have seen it and you are aware. It stays open while you work on it.",
          },
          { term: "Resolve", definition: "It is fixed. Mark it resolved." },
          {
            term: "Won’t fix",
            definition:
              "It is real, but you have decided to leave it. Maybe it is not worth the effort.",
          },
          {
            term: "False positive",
            definition: "It is not actually a problem — Polaris got this one wrong.",
          },
        ],
      },
      {
        kind: "text",
        text: "A disposition sticks to the issue across future runs. That means a “won’t fix” will not keep resurfacing run after run, and you never have to re-decide the same thing twice.",
      },
      {
        kind: "example",
        text: "You mark “button label misspelled” as won’t fix before a launch. Next week’s run sees it again, remembers your decision, and keeps it quiet instead of flagging it as fresh.",
      },
    ],
  },
  {
    id: "run-scope",
    title: "Run scope",
    summary: "Which layers a run covers: API, UI, or Full.",
    keywords: ["scope", "run scope", "api", "ui", "full", "layers"],
    body: [
      {
        kind: "text",
        text: "Scope is how much of your app a single run covers. Polaris works it out from what your project actually has — it never tests something that isn’t there.",
      },
      {
        kind: "definitions",
        items: [
          {
            term: "API",
            definition:
              "Tests the backend endpoints only — the parts that handle data behind the scenes.",
          },
          {
            term: "UI",
            definition:
              "Tests the user interface only — the pages and buttons a person clicks.",
          },
          {
            term: "Full",
            definition: "Tests both, plus how they connect — the complete picture.",
          },
        ],
      },
      {
        kind: "example",
        text: "A project that is only a backend service gets API scope. Add a website on top and connect it, and Polaris offers Full — so one run can follow a click on the page all the way down to the database.",
      },
    ],
  },
  {
    id: "glossary",
    title: "Glossary",
    summary: "Plain one-line definitions of every Polaris term and symbol.",
    keywords: ["glossary", "definitions", "terms", "the brain", "crawl", "oracle"],
    body: [
      { kind: "text", text: "Every term and symbol in Polaris, one line each." },
      {
        kind: "definitions",
        items: [
          {
            term: "Finding",
            definition: "A single ranked problem Polaris found, in plain language.",
          },
          {
            term: "Oracle",
            definition: "The thing that decides whether a test passed or failed.",
          },
          {
            term: "Trust mark",
            definition:
              "A symbol (● ◌ ◉) showing how much to believe a test, based on its oracle.",
          },
          {
            term: "Blast path",
            definition:
              "The page → endpoint → model → table chain showing how far a problem reaches.",
          },
          {
            term: "Mode",
            definition:
              "One of the three ways to ask for tests: describe it, autonomous, or authoring.",
          },
          { term: "Scope", definition: "Which layers a run covers: API, UI, or Full." },
          {
            term: "The Brain",
            definition:
              "Polaris’s internal model of your app — what it learned by reading the code.",
          },
          {
            term: "Crawl",
            definition:
              "When Polaris explores your running app to discover its pages and flows.",
          },
          {
            term: "Run",
            definition: "One pass through the loop: understand, generate, run, review.",
          },
          {
            term: "Severity",
            definition: "How bad a finding is: critical, major, or minor.",
          },
          {
            term: "Confidence",
            definition: "How sure Polaris is that a finding is real.",
          },
          {
            term: "Triage",
            definition:
              "Deciding what to do with a finding: acknowledge, resolve, won’t fix, or false positive.",
          },
        ],
      },
      {
        kind: "example",
        text: "Stuck on a symbol like ◉? The glossary says: spec-grounded trust mark — the test is anchored to a documented contract.",
      },
    ],
  },
];
