---
name: brain-ingest
description: Turn a new source (a web page, PDF, course document, chat answer or meeting note) into a templated research note in brain/inbox/ and log the run. Use when someone says "ingest this", "add this to the brain", or shares material to remember for the Financial Ledger project.
---

# brain-ingest

Adds one research note per source to the project's second brain (SK-2). It never edits existing notes: sorting, merging and linking are the job of `brain-refine`.

Background this skill relies on: [[double-entry-ledger]], [[sqlite-transactions-and-locking]] (examples of finished notes in `brain/resources/research/`).

## Inputs
- The source: a URL, a file path in the repo, or pasted text.
- Optional: the requirement IDs it relates to (FR-n, NFR-n, SK-n, TQ-n from SRS v1.1). If not given, infer them and say so.
- The author's GitHub username.

## Steps
1. **Read the source fully.** If it cannot be read (paywall, missing file), stop and say so. Never invent content.
2. **Pick a slug**: lowercase words joined by hyphens, 2–5 words, describing the topic (e.g. `idempotency-keys`). If `brain/inbox/<slug>.md` or any `brain/**/<slug>.md` already exists, add `-2`, `-3`… and mention the possible duplicate in your reply.
3. **Create `brain/inbox/<slug>.md`** from `brain/resources/templates/research.md`, filling every front-matter field:
   - `type: research`
   - `title`: a short human title
   - `tags`: 1–4 lowercase tags
   - `requirements`: list of SRS IDs, e.g. `[FR-2, FR-3]`
   - `sources`: the URL(s) or file path(s) actually read
   - `author`: the GitHub username
   - `created`: today's date, `YYYY-MM-DD`
4. **Write the body** in your own words:
   - `## Summary`: 3–5 sentences.
   - `## Key points`: 3–7 bullets of facts from the source.
   - `## How it applies to our project`: 1–4 bullets that name the requirement IDs or files it affects.
   - `## Related`: `[[FR-n]]` links for each requirement, plus links to existing notes on the same topic.
   Do not copy long passages; quote at most one short sentence.
5. **Append one row to `brain/log.md`**:
   `| YYYY-MM-DD | brain-ingest | <author> | Added inbox/<slug>.md from <source> | #<pr> |`
6. **Report**: the new file path, the requirement IDs, and any possible duplicates for `brain-refine` to merge.

## Rules
- One source → one note. Several sources on one topic → run the skill once per source.
- Only write inside `brain/inbox/` and the log. Never move, rename or delete notes.
- No secrets, API keys or personal data in notes.
- Front matter must be valid YAML; CI validates it (SK-1).

## Evaluation
See `evals/evals.md` for the test cases run before each stage (SK-8, TQ-7).
