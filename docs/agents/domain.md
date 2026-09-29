# Domain docs

Single-context repo.

## Before exploring, read these

- **`CONTEXT.md`** — the domain glossary. Use its terms in issue titles, code, test names and proposals; don't drift to synonyms it lists under *Avoid*.
- **`docs/ARCHITECTURE.md`** — the decisions from the design session: stack, principles, safety model, roadmap, open items. Treat its decision table as the ADR log.
- **`docs/adr/`** — new architectural decisions made after the design session, one file each (`NNNN-slug.md`). Create the directory lazily when the first one is written.

If `docs/adr/` doesn't exist, proceed silently.

## Flag conflicts

If your output contradicts a decision in `docs/ARCHITECTURE.md` or an ADR, say so explicitly instead of silently overriding it:

> _Contradicts the "state lives in Cloudflare" decision in docs/ARCHITECTURE.md — but worth reopening because…_

If a term you need is missing from `CONTEXT.md`, that is either invented language (reconsider) or a real gap (add it to `CONTEXT.md` in the same change).
