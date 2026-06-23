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
    id: "getting-around",
    title: "Getting around",
    summary: "Where things live: Projects, Findings, Runs, and your account.",
    keywords: [
      "navigation",
      "navigate",
      "sidebar",
      "screens",
      "projects",
      "runs",
      "findings",
      "dashboard",
      "inbox",
      "account",
      "getting around",
    ],
    body: [
      {
        kind: "text",
        text: "Polaris keeps a sidebar on the left with three places, plus your account at the bottom. Here is what each one is for.",
      },
      {
        kind: "definitions",
        items: [
          {
            term: "Projects",
            definition:
              "Every codebase you have connected. Open one to see its health, recent runs, and settings — or to start a run.",
          },
          {
            term: "Runs",
            definition:
              "The test runs for a project, newest first. Open a run to see its dashboard.",
          },
          {
            term: "Findings",
            definition:
              "One inbox of every open problem across all your projects, worst first — what is broken right now.",
          },
          {
            term: "Account",
            definition:
              "Your profile and password, and your team. It sits at the bottom of the sidebar, behind your initials.",
          },
        ],
      },
      {
        kind: "text",
        text: "A run’s dashboard is a master–detail view: the ranked list of findings on the left, and the finding you click open on the right — its blast path, evidence, and history. The findings inbox uses the same left-list, right-detail layout.",
      },
      {
        kind: "example",
        text: "Want the single most urgent thing across everything? Open Findings. Want to dig into one test run? Open Runs, pick a run, and click through its findings on the dashboard.",
      },
    ],
  },
  {
    id: "modes",
    title: "The 2 ways to ask for tests",
    summary: "Two ways: describe it in plain English, or let Polaris run autonomously.",
    keywords: [
      "mode",
      "modes",
      "describe it",
      "autonomous",
      "natural language",
      "full sweep",
      "what changed",
    ],
    body: [
      {
        kind: "text",
        text: "You ask Polaris for tests in one of two ways. These are called modes. Pick whichever fits what you want to do.",
      },
      {
        kind: "definitions",
        items: [
          {
            term: "Describe it",
            definition:
              "Say what to test in plain English, like “orders require authentication”. Polaris turns your sentence into tests. Best when you know the area you care about but don’t want to spell out every step.",
          },
          {
            term: "Autonomous",
            definition:
              "Let Polaris decide what to test. Choose “Test everything” for a full sweep, or “Test only what changed” to focus on the files you just touched. Best for broad coverage with little effort.",
          },
        ],
      },
      {
        kind: "example",
        text: "Want to check one flow? Use Describe it and type “orders require authentication”. Pushed a big change and want a full sweep? Use Autonomous → Test everything. Touched only a couple of files? Use Autonomous → Test only what changed.",
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
        text: "Every finding carries a few labels so you can judge it at a glance:",
      },
      {
        kind: "definitions",
        items: [
          {
            term: "Severity",
            definition: "How bad the problem is — critical, major, or minor.",
          },
          {
            term: "Confidence",
            definition:
              "How much to believe it. This is shown as the finding’s trust mark, not a separate score — the detail panel labels the field Confidence. See Trust marks.",
          },
          { term: "Layer", definition: "Where it lives — api, ui, or db." },
          {
            term: "History",
            definition:
              "Whether you’ve seen it before — new, known, regression, or flaky. See History.",
          },
          {
            term: "Status",
            definition:
              "What you’ve decided about it — open until you triage it, then acknowledged, resolved, won’t fix, or false positive. See Triage.",
          },
        ],
      },
      {
        kind: "example",
        text: "A finding might read: “Orders accepted without authentication” — severity critical, a strong (rule-derived) trust mark, layer api, history new, status open. One line tells you it’s serious, the check follows a real rule, it’s in the API, you haven’t seen it before, and you haven’t triaged it yet.",
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
    title: "Severity & trust",
    summary:
      "Severity is how bad; the trust mark is how much to believe it. They are separate on purpose.",
    keywords: [
      "severity",
      "confidence",
      "trust",
      "critical",
      "major",
      "minor",
      "blast radius",
      "failure shape",
    ],
    body: [
      {
        kind: "text",
        text: "Severity and trust answer two different questions. Polaris keeps them apart on purpose, because a problem can be very bad but only loosely confirmed, or rock-solid but minor.",
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
            term: "Trust — how much to believe it",
            definition:
              "This is the finding’s trust mark — how strong the check behind it is. The detail panel labels this field Confidence, but it shows the mark, not a how-sure score. A strong mark means the check follows a real rule; a weak one only pins down today’s behaviour. See Trust marks.",
          },
        ],
      },
      {
        kind: "text",
        text: "Read them together. Critical with a strong trust mark is a drop-everything bug. Critical with a weak mark is worth a look but might be an intended change. Minor with a strong mark is real, and can wait.",
      },
      {
        kind: "example",
        text: "“Payment data stored unencrypted” might be critical severity but carry a weak trust mark — the check only noticed a behaviour change, so confirm it before acting. “Button label misspelled” carries a strong mark but minor severity. Different problems, sorted differently.",
      },
    ],
  },
  {
    id: "blast-path",
    title: "Cross-layer blast path",
    summary: "The chain page → endpoint → table that shows how far a problem reaches.",
    keywords: [
      "blast path",
      "cross-layer",
      "cross layer",
      "page",
      "endpoint",
      "table",
      "ui",
      "api",
      "db",
      "reach",
    ],
    body: [
      {
        kind: "text",
        text: "The blast path shows how far a problem reaches across your app. It is a chain across the layers Polaris can see: the page a user sees (UI) → the endpoint it calls (API) → the table underneath (DB). The node where things break is lit up.",
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
          { tier: "Table", label: "orders" },
        ],
        failingIndex: 1,
        caption: "The checkout page calls the orders endpoint, which fails here.",
      },
      {
        kind: "text",
        text: "In this checkout example, the page /checkout calls POST /api/orders. That endpoint is lit — it accepted an order it should have rejected. The problem starts there and flows down to the orders table, where a bad row gets written. When Polaris can’t resolve the whole chain, it shows just the node that failed.",
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
    summary:
      "In autonomous mode, what a run covers: test everything, or only what changed.",
    keywords: [
      "scope",
      "run scope",
      "full sweep",
      "change impact",
      "what changed",
      "everything",
      "autonomous",
      "changed files",
    ],
    body: [
      {
        kind: "text",
        text: "When you run in Autonomous mode, Polaris asks how much to cover. On the Start-a-run screen this choice is labelled Scope, and there are two options.",
      },
      {
        kind: "definitions",
        items: [
          {
            term: "Test everything",
            definition:
              "A full sweep across every testable target in your project. Best after a big change, or when you want broad coverage.",
          },
          {
            term: "Test only what changed",
            definition:
              "Change-impact selection: you give Polaris the list of files you changed (one path per line) and it tests just what those touch. Best for a quick, focused check.",
          },
        ],
      },
      {
        kind: "text",
        text: "Either way, Polaris only tests the layers your project actually has — it never tests something that isn’t there. A backend-only service is checked at the API; add a website and connect it, and a run can follow a click on the page down through the endpoint to the database (that chain is the blast path).",
      },
      {
        kind: "example",
        text: "Pushed a big refactor? Use Test everything. Touched two files in checkout? Use Test only what changed and paste those paths — Polaris focuses there instead of re-running the whole app.",
      },
    ],
  },
  {
    id: "db-state-testing",
    title: "Database-state testing",
    summary:
      "Let Polaris check your data layer directly — and the tier that controls how far it can go.",
    keywords: [
      "db-state",
      "database state",
      "data layer",
      "tier",
      "off",
      "read only",
      "read_only",
      "full",
      "write",
      "select",
      "sql",
      "production",
      "safety",
    ],
    body: [
      {
        kind: "text",
        text: "Most checks watch your app from the outside — a page, an endpoint, a response. Database-state testing goes one level deeper: it asserts directly on the rows in your target’s database, so Polaris can confirm what actually got written, not just what the app reported. You turn it on per project, in Project settings, and choose how far it may go.",
      },
      {
        kind: "definitions",
        items: [
          {
            term: "Off",
            definition:
              "No database-state testing. This is the default — runs never touch the database directly.",
          },
          {
            term: "Read-only",
            definition:
              "Polaris may read the database to make assertions (SELECT only). It never writes, so it is safe against any target.",
          },
          {
            term: "Full (write-capable)",
            definition:
              "Polaris may also write to the database as part of a test — for example, to set up a row and check what happens. Powerful, but safe only against a throwaway environment.",
          },
        ],
      },
      {
        kind: "text",
        text: "Safety first: Full writes to the target database. Point it only at a disposable, non-production environment — never your real production data. Polaris also refuses write-tests against a target it recognises as production, but the first line of defence is you: keep Full aimed at staging or a scratch database.",
      },
      {
        kind: "text",
        text: "Anyone on the team can see the tier; changing it needs permission to manage the project, so owners, admins, and members can, and viewers can’t. Changing the tier only records your choice — it never writes anything by itself.",
      },
      {
        kind: "example",
        text: "Testing checkout against a staging copy you can wipe? Full lets Polaris insert an order and confirm the row landed correctly. Running against anything you can’t afford to change? Keep it on Read-only or Off.",
      },
    ],
  },
  {
    id: "team",
    title: "Your team",
    summary: "Invite people, and what each role can do.",
    keywords: [
      "team",
      "members",
      "member",
      "invite",
      "role",
      "roles",
      "owner",
      "admin",
      "viewer",
      "permissions",
      "pending invite",
      "organization",
    ],
    body: [
      {
        kind: "text",
        text: "Open Account → Team to see who is on your team and to invite more people. Everyone has a role, and the role decides what they can do.",
      },
      {
        kind: "definitions",
        items: [
          {
            term: "Owner",
            definition:
              "Full control, including managing other owners. Every team keeps at least one owner.",
          },
          {
            term: "Admin",
            definition: "Can invite people and change roles, but cannot manage owners.",
          },
          {
            term: "Member",
            definition: "Can use Polaris and see findings, but cannot manage the team.",
          },
          {
            term: "Viewer",
            definition: "Read-only access to the team’s work.",
          },
        ],
      },
      {
        kind: "text",
        text: "To invite someone, type their email, pick a role, and send. They appear in the members list marked “Invite pending” until they accept. Inviting or removing people and changing roles is limited to owners and admins — if you do not see those controls, your role does not allow them, and Polaris enforces this on the server too.",
      },
      {
        kind: "example",
        text: "An admin can invite a new member and later promote them, but only an owner can add or remove another owner — and Polaris will not let the last owner be removed.",
      },
    ],
  },
  {
    id: "account-security",
    title: "Sign-in limits & passwords",
    summary:
      "Why a sign-in can be paused for a moment, and what makes a valid password.",
    keywords: [
      "rate limit",
      "rate-limited",
      "too many attempts",
      "locked out",
      "lockout",
      "retry",
      "password",
      "password policy",
      "8 characters",
      "weak password",
      "sign in",
      "login",
      "security",
    ],
    body: [
      {
        kind: "text",
        text: "Two safeguards on the sign-in and password screens can stop you, and both are on purpose.",
      },
      {
        kind: "definitions",
        items: [
          {
            term: "Too many attempts",
            definition:
              "If you try to sign in (or repeat another sensitive action) too many times too quickly, Polaris pauses you with “Too many attempts. Please try again in N seconds.” It is a guard against password guessing — wait the few seconds it names and try again. Nothing is wrong with your account.",
          },
          {
            term: "Password rules",
            definition:
              "A new password must be at least 8 characters, cannot be all numbers, and cannot be a common, easily-guessed password. If yours is rejected, the message says which rule it missed.",
          },
        ],
      },
      {
        kind: "text",
        text: "These apply when you sign up, sign in, or change your password. The exact reason always comes back on the field itself, so you never have to guess what to fix.",
      },
      {
        kind: "example",
        text: "Choose “12345678”? It is long enough, but all numbers — Polaris asks you to add letters or a symbol. Choose something short or obvious? It asks for something longer and less guessable.",
      },
    ],
  },
  {
    id: "glossary",
    title: "Glossary",
    summary: "Plain one-line definitions of every Polaris term and symbol.",
    keywords: ["glossary", "definitions", "terms", "oracle", "model", "the brain"],
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
            term: "Confidence",
            definition:
              "How much to believe a finding — shown as its trust mark (oracle tier), not a separate score. The detail panel labels this field Confidence.",
          },
          {
            term: "Blast path",
            definition:
              "The page → endpoint → table chain showing how far a problem reaches across the UI, API, and DB layers.",
          },
          {
            term: "Mode",
            definition:
              "One of the two ways to ask for tests: describe it, or autonomous.",
          },
          {
            term: "Scope",
            definition:
              "In autonomous mode, what a run covers: test everything, or test only what changed.",
          },
          {
            term: "Model",
            definition:
              "Polaris’s internal picture of your app — what it learned by reading the code. You build it from the project page. (Internally it’s called the Brain.)",
          },
          {
            term: "Run",
            definition:
              "One pass through the loop: understand, generate, run, review, triage.",
          },
          {
            term: "Severity",
            definition: "How bad a finding is: critical, major, or minor.",
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
