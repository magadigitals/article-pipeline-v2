# Source-Attribution Anchor Text (Karpathy Pair #32)

## The pattern

The link anchor text should be the claim itself, not a wrapper that attributes the claim to evidence.

**WRONG — attribution wrapper:**
- `Clinical evidence supports these [coping strategies](url), and therapists commonly teach them.`
  → Remove the link and "Clinical evidence supports these" dangles. The sentence makes no claim of its own.
- `The [evidence supports therapy](url) as the primary treatment for BPD hallucinations.`
  → "Evidence supports" is a verb attributing authority to an unnamed source.
- `[Research shows](url) that DBT reduces distress.`
  → "Research shows" is weasel attribution, same as "studies show."

**RIGHT — the link IS the claim:**
- `Therapists commonly teach these [coping strategies](url) in BPD treatment.`
  → Remove the link and the sentence still stands as a complete claim.
- `[Therapy is the primary treatment](url) for BPD hallucinations.`
  → The link anchor is the claim itself, not a wrapper around it.
- `[DBT reduces distress](url) in people with this condition.`

## The test

If you remove the link text from the sentence (replace the `[anchor](url)` with just `anchor`), does the sentence still make a complete claim?
- "Clinical evidence supports these coping strategies, and therapists commonly teach them." — makes a claim ✓
- "Clinical evidence supports these, and therapists commonly teach them." — dangles without the link ✗

The second sentence is the problem — the link anchor IS the concept, and without the link, the attribution "Clinical evidence supports these" has nothing to attach to.

## Where this appears

- Karpathy pair #32 in `editorial_karpathy.md`
- No-AI-Slop skill: "Source-attribution anchor text" pattern in Patterns to cut
