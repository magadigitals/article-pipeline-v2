# Editorial Karpathy Pairs — 32 BEFORE/AFTER editing rules

Applied by edit_article.sh as the final polishing pass after gate scripts.

Current count: 32 pairs (was 30 — pairs #31 and #32 added 2026-07-30).

## New pairs added this session

| # | Domain | What it catches |
|---|--------|-----------------|
| 31 | **Bullet list lead-ins** | Before each bullet list, check if the preceding sentence sets up what the list will deliver. If the list feels abrupt, add a lead-in ending with a colon. Vary the phrasing — never start two in a row with the same formula. Avoid "Here are some..." — embed the setup in the paragraph flow. |
| 32 | **Source-attribution anchor text** | The link anchor should be the claim itself, not a wrapper attributing it to evidence. WRONG: "[evidence supports therapy](url) as the primary treatment" — removing the link leaves a dangling "evidence supports." RIGHT: "[Therapy is the primary treatment](url)" — the link can be removed and the sentence still stands. If removing the link leaves a dangling attribution, the anchor text is wrong. |

## Coverage

| Domain | Pairs | What it catches |
|---|---|---|
| Intensifiers | 3 | "actually", "quite", "rather", "really", "in fact", "just", "of course" |
| Passive voice | 2 | "was taken by" → "took" |
| Throat-clearing | 4 | "It is worth noting that...", "There is/There are..." |
| Contrast templates | 5 | "The question is not X. It is Y" → direct Y |
| Clinical register | 2 | "is a known driver" → "can drive" |
| Source signaling | 5 | "One trial linked it to...", "Researchers most consistently cite...", "A 2023 study found..." |
| Abstract → concrete | 2 | "resulted in improved outcomes" → "80% completed the program" |
| Nominalization | 2 | "cessation of the habit" → "people stopped the habit" |
| Weak verbs | 2 | "has findings that are important" → "found results that change" |
| Sentence rhythm | 1 | Long rambling → short verdicts |
| Repeated openers | 1 | "Supplements... Supplements... Supplements..." |
| Em dashes | 1 | "X — Y — Z" → "X: Y. Z." |
| Banned phrases | 3 | "delve into the landscape of", "tapestry", "steady approach" |
| Attribution framing | 2 | "We know that..." → state directly |
| Reader assumptions | 2 | "You sense that..." → "Some people sense" |
| Bridge to care | 2 | Institutional → human |
| Endings | 1 | Summary → action/imagery |
| Native speaker friction | 2 | "bottles are something that can be set aside" → "bottles can be set aside" |
| **Bullet list lead-ins (new #31)** | 1 | Before each bullet list, check lead-in with colon; vary phrasing |
| **Source-attribution anchor text (new #32)** | 1 | Link anchor must be the claim, not an attribution wrapper |

## Known gaps to watch for (model-specific blind spots)

- "Navigation housekeeping" like "The sections below are organized by symptom" — not caught by current pairs
- "One [trial/study/paper] linked/found/suggested..." — the current pair covers this but the exact wording "One trial linked it to" was missed on the test run because the model classifying "One" as different from "A 2023"
- "For some people" as throat-clearing — sometimes missed when it blends into the following clause
- "None of this is meant to scare" — defensive/denial opener, not explicitly targeted by current pairs
- Importance puffery ("are real and meaningful", "well established", "well documented") — partially covered by other rules but not always caught

## Path

`/Users/mac/Documents/Codex/2026-07-14/ca/local_worker/editorial_karpathy.md`

Calling script: `~/.hermes/scripts/edit_article.sh`
