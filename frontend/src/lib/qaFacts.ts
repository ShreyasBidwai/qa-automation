/**
 * QA / testing facts shown one at a time under a loading indicator (see
 * {@link LoadingFact}). Static + zero-weight by design: a hardcoded list, no
 * fetch, no API call, no dependency — so it adds no perceptible load time.
 *
 * Curated in Polaris's honest, anti-vanity voice: the oracle problem, why
 * coverage isn't correctness, characterization-test traps, flakiness, trust in
 * tests, and what good testing actually verifies. Each is one short sentence a
 * working tester would nod at — not trivia, not dates, not "did you know" filler.
 */
export const QA_FACTS: readonly string[] = [
  "Code coverage tells you which lines ran, not whether anything checked the result.",
  "The hard part of testing is the oracle problem — knowing the right answer, not producing one.",
  "A test with no meaningful assertion only proves the code didn't crash.",
  "Characterization tests pin current behaviour, bugs and all, so they resist the very fixes you want.",
  "A green suite means nothing broke the checks you wrote — not that the software is correct.",
  "Flaky tests cost twice: the run they waste, and the trust they drain from every other test.",
  "Full coverage with weak assertions is a number that looks like safety and isn't.",
  "A test that can never fail is documentation, not verification.",
  "Re-running a passing test proves nothing new; re-running a flaky one only proves it's flaky.",
  "Automated tests assert what the code does — deciding what it should do is the real work.",
  "Snapshot tests catch change, not correctness, and will happily freeze a broken output.",
  "If a test passes whether or not the feature works, the feature was never really tested.",
  "Mocks verify how you assume a dependency behaves, not how it actually behaves.",
  "Deleting a flaky test removes the noise and the signal in the same stroke.",
  "A suite you don't trust is slower than no suite, because you re-check it by hand anyway.",
  "A passing test proves a bug absent only for the single case it actually exercises.",
  "Asserting on timestamps or ordering the spec never promised is how you author your own flakiness.",
  "The expensive tests aren't the slow ones — they're the ones that stay green while the product breaks.",
];

/** One fact at random — chosen once on mount by the caller; never re-fetched. */
export function randomQaFact(): string {
  return QA_FACTS[Math.floor(Math.random() * QA_FACTS.length)];
}
