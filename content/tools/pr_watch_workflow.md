# PR watch — CI and review comments in one snapshot

Use `pr_watch` (MCP) or `hw-native-sys-pr-watch` (CLI) when you need to watch a
pull request rather than make a one-off query. One call returns the PR state,
the CI rollup, unresolved review threads, review summaries, conversation
comments, and a cursor for the next poll. The tool is read-only and never posts.

## When to use

- Watching a PR through CI and review rounds (Codex, CodeRabbit, Copilot, human).
- Replacing a loop that only runs `gh pr checks`: that misses review bodies and
  reviews whose findings are not posted as inline threads.
- Feeding a status note or a handoff; pass the cursor back to get only new items.

Do not use it as a merge gate. CI conclusions and AI review cleanliness are
inputs, not substitutes for the repository's required checks.

## Tool contract

MCP: `pr_watch(repo, number, since="", seen_ids=[], include_resolved=False)`.

CLI:

```bash
hw-native-sys-pr-watch --repo pypto --pr 3248 --format summary
hw-native-sys-pr-watch --repo pypto --branch feat/x \
  --state-file ~/.local/state/hw-native-sys/pr-watch/pypto-3248.json \
  --update-state --format json
```

- `since` is the previous `cursor.next_since`; `seen_ids` is the previous
  `cursor.seen_ids`. Empty on the first call.
- The CLI's `--state-file` persists those values, plus body hashes and the last
  CI/review/merge state, and writes atomically only when the snapshot is
  complete. `posted_ids` is reserved for replies the user approved.
- Exit codes: `0` success, `2` usage, `3` gh/transport/GraphQL error, `4`
  incomplete snapshot (no cursor is returned).
- `gh` must be installed and authenticated. The MCP server does not read a
  token; it inherits `gh auth`.

## Surfaces

| Surface | Query field | Resolvable | Used for |
|---|---|---|---|
| A — inline findings | `reviewThreads` + nested `comments` | yes | actionable review findings |
| B — review summaries | `reviews` | no | Codex/CodeRabbit/Copilot summaries, human verdicts |
| C — conversation | `comments` | no | bot summaries, rebase requests, discussion |

Threads are the source of truth for findings. A summary that merely enumerates
inline comments is not recounted as a finding.

## AI classification

| Reviewer | Detection | Finding treatment |
|---|---|---|
| Codex | `chatgpt-codex-connector`; or `github-actions` with `<!-- pypto-codex-review -->` / `## Codex Review` | Surface A threads are actionable. B/C summaries are `codex_summary` noise. Markers such as `Reported code location` or `Existing review thread` set `attention_required=true` but not `actionable`. |
| CodeRabbit | `coderabbitai` | Threads actionable. Walkthroughs and `Actionable comments posted: 0` / `Review skipped` are noise. |
| Copilot | `isCopilotCodeReview` or `copilot-pull-request-reviewer` / `github-copilot` / `copilot` | Threads actionable; summaries informational. |
| Generic bot | `__typename == "Bot"` or a `[bot]` login | Status-only echoes are `ci_status_echo` noise; otherwise informational. |
| Human | fallback | Any non-empty body is actionable, including “please rebase”. |

Reviews are summaries by default. A human `CHANGES_REQUESTED` is an actionable
review-decision item. `is_outdated=true` threads stay actionable but must be
re-validated against the current `head_sha`.

## CI

`statusCheckRollup` is normalized across `CheckRun` and `StatusContext`.

- CheckRun: `SUCCESS` → pass; `FAILURE|ERROR|TIMED_OUT|ACTION_REQUIRED|STARTUP_FAILURE`
  → fail; not completed → pending; `SKIPPED|NEUTRAL|CANCELLED|STALE` → skipped.
- StatusContext: `SUCCESS` → pass; `FAILURE|ERROR` → fail; `PENDING|EXPECTED` →
  pending.
- Overall: any fail → fail; else any pending → pending; else pass.
- Exact case-insensitive name collisions keep the CheckRun and mark the
  StatusContext `duplicate_of`; a CodeRabbit SUCCESS status can never mask a
  failing CheckRun.
- `isRequired` is best-effort; a schema/permission failure retries without it
  and warns.

## Delta and cursor

- `is_new`: ID not in `seen_ids` (and the timestamp is at/after `since` when
  provided). `is_updated`: ID was seen and its timestamp is at/after `since`.
- A thread is returned when it is new, updated, or has a new reply
  (`has_new_comments`); resolved threads are omitted unless
  `include_resolved=true`, but their IDs stay in `seen_ids` so a reopen is not
  misreported as new.
- Every item carries `body_hash`; bots edit comments in place, so compare the
  hash when timestamps are unreliable.
- `next_since` is 60 s behind the fetch start (clock-skew overlap); `seen_ids`
  is the primary dedup key.
- A failed or truncated page returns `complete=false` and **no cursor**. Never
  advance state on an incomplete snapshot.

## Acting on findings

1. Re-validate against the current `head_sha` (force-pushes make threads
   `is_outdated` and summaries stale).
2. Reproduce, fix in the sibling repo on the PR branch, and verify (sim Docker
   for pypto UTs/STs).
3. Draft the reply. Surface A: reply on the comment `database_id`. Surfaces
   B/C: PR conversation comment.
4. Reply or resolve only after the user explicitly asks, per the notes
   `AGENTS.md`. Resolve only surface A, after the fix is pushed and verified.
   Record approved replies in `posted_ids`.

## Gotchas

- Pagination: the tool follows cursors for contexts, threads, thread comments,
  reviews and comments; repeated cursors or the page cap make the snapshot
  incomplete.
- Rate limits: one query per PR per poll; the CLI backs off only on transient
  transport failures, never on rate limit or auth. Keep the poll at 120 s or
  slower.
- CI status contexts and check runs can describe the same job under the same
  name; only exact-name duplicates are merged. Do not fuzzy-match.
- `mergeable`/`mergeStateStatus` may be `UNKNOWN` while GitHub computes; treat
  it as pending, not an error.
- pypto PRs not targeting `main` do not get a Codex review; do not wait for one.

## Related

- `tools/gate_pr_workflow` — pre-push gate (tests, pre-commit, squash).
- Notes skill `watch-pr` — the 2-minute loop, reporting policy, triage.
- `pr_plans/00-branch-and-pr-standards.md` § Automated PR review — repository
  policy for AI review findings.
