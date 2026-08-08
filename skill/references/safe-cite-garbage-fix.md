# `_safe_cite()` Must Reject, Not Dress Up Garbage

## The bug

The APA 7 formatter (`_apa7_cite()`) raises `ValueError` when a source has no authors, no year, no organization — missing critical APA metadata. This happens frequently with bare PMC URLs from DDG and with student thesis repositories.

The original `_safe_cite()` wrapped this in a try/except and fell back to:
```python
f"{title}. {url}"
```

This produced `(n.d.). *Title fragment*. URL` — which looks like a valid citation but is garbage. The source has no author, no date, no journal, no publication context. This is how the fear-of-intimacy v1 article ended up with citations like:
```
* (n.d.). (PDF) fear of intimacy - academia.edu... https://www.academia.edu/93894471/Fear_of_intimacy
* (n.d.). Parental bonding, adult romantic attachment... https://digital.library.unt.edu/ark:/67531/metadc3902/
```

## The fix

`_safe_cite()` is now a direct pass-through to `_apa7_cite()` — no try/except:
```python
def _safe_cite(source: dict) -> str:
    return _apa7_cite(source)
```

All call sites in `_format_research_packet` wrap in try/except ValueError and `continue` (skip that source). A source that cannot produce valid APA metadata is silently dropped from the citation list.

## Guard rule

When adding new calls to `_safe_cite()` in `_format_research_packet`, ALWAYS wrap in try/except ValueError. Search `_safe_cite(` in the function and guard every call. An unguarded `_safe_cite()` on an unhydrated PMC URL crashes the entire brief at packet assembly.

## Related

- Student repo blocklist: `references/student-repo-blocklist.md`
- Safe-cite from the earlier session: `references/safe-cite-fix-20260729.md` (original fix, now outdated by this stricter approach)
