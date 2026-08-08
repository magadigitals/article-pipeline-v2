# Student Repository Blocklist

The `.edu` domain filter in `_is_trusted_web_source()` was too broad — it accepted every `.edu` URL including:
- Student honors theses
- Institutional repository uploads (undergrad papers)
- Search result pages (academia.edu/Documents/in/)
- University libraries hosting theses/dissertations

## Blocked URL patterns (STUDENT_REPO_PATTERNS)

The following patterns cause `_is_trusted_web_source()` to return False:

| Pattern | Example URLs |
|---------|-------------|
| `honorstheses` | `stars.library.ucf.edu/honorstheses/...` |
| `bitstreams` | `jewlscholar.mtsu.edu/.../bitstreams/...` |
| `scholarworks` | `scholarworks.sjsu.edu/...` |
| `stars\.library` | `stars.library.ucf.edu/...` |
| `mcnair` | `scholarworks.sjsu.edu/mcnair/...` |
| `jewlscholar` | `jewlscholar.mtsu.edu/...` |
| `/theses/` | Any path containing `/theses/` |
| `/dissertations/` | Any path containing `/dissertations/` |
| `academia\.edu` | `academia.edu/...` (entire domain) |
| `academia\.edu/Documents/in/` | Search result pages on academia.edu |
| `digital\.library` | `digital.library.unt.edu/...` |
| `/ark:/` | UNT digital library URLs with ARK identifiers |

## Why this matters

Student theses and repository uploads are not peer-reviewed clinical evidence. An undergrad honors thesis about parental bonding does not belong in a patient-facing mental health article. The old `.edu` filter accepted these because it only checked the domain suffix — now it also checks the URL path.

## Known limitation

`.edu` pages that are legitimate (NIH-funded research projects hosted on a university site, university medical centers, etc.) could theoretically match these patterns. In practice, the patterns are specific enough to catch only repository infrastructure paths. Broad University websites like `brown.edu`, `stanford.edu`, or `harvard.edu` are unaffected.
