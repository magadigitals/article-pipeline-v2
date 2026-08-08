# V2 Versioning — Always alongside, never replace

## Rule

When the user asks for a v2 of an article, brief, or any deliverable, save the new version as `{slug}-v2.md` (or `{slug}-v2.docx`, etc.) **alongside** the original file. Never overwrite.

## Examples

| Request | Correct | Wrong |
|---------|---------|-------|
| "do a v2 of fear-of-intimacy" | Create `fear-of-intimacy-v2.md`, keep `fear-of-intimacy.md` | Overwrite `fear-of-intimacy.md` |
| "re-write passively suicidal" | Create `passively-suicidal-v2.md` | Replace `passively-suicidal.md` |
| "run v2 research brief" | Save as `{slug}_Research_Brief_Dumbed-v2.md` | Overwrite original brief |

## Why

1. The user compares versions side by side to evaluate quality.
2. They explicitly chose "v2" language — that means versioning, not replacement.
3. Overwriting destroys the ability to roll back or reference the original.

## What to do if you already overwrote

Immediately recover the original from `runs/{slug}/` (check `article.raw.md`, `article.compiled.md`, or any checkpoint). Copy it back to the GWF path, then create the new version as `-v2`.
