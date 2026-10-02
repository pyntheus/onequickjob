# Codex review

Codex reviews run through the official Codex plugin for Claude Code, via
`scripts/codex-review.sh`: an adversarial, read-only review of your branch against
`main`, in the foreground. The plugin's slash command can't be invoked by the model,
so always use the script.

## Two rules

- The review only sees COMMITTED work: it compares your branch's last commit with
  `main`. The script refuses to run while anything is uncommitted, so commit first,
  every time, including before a re-check.
- Codex reviews read-only and doesn't run tests. Run them yourself and put the results
  in the focus text.

## When and how

1. Finish the work. Run `make lint` and `make test`. Commit everything.
2. Run the review from your worktree:

       scripts/codex-review.sh "<focus text>"

   Reviews can take several minutes. If one might exceed the Bash tool's timeout, run it
   in the background, writing to `/tmp/codex-review-<session>.out`, and check back.
3. Triage using the plugin's own severities:
   - critical or high: must fix;
   - medium: fix unless you have a clear reason not to, and give the reason;
   - low: your judgement.
4. Commit the fixes, then run one re-check, with focus text listing exactly what you
   changed. A third review only if a critical or high finding is still open.
5. Report: the verdict (approve or needs-attention), what you fixed, and which findings
   you declined and why. Findings are inputs, not vetoes. Never merge: Hasan merges.

## Focus text

Start with this, filled in:

    Review this branch for session <F | L1 | L2 | L3 | I> as described in
    docs/design/build-pack.md, against CLAUDE.md and docs/spec/decisions.md.
    Test results: <one line, e.g. "pytest 118 passed; vitest 42 passed; ruff and
    eslint clean">. Check: (1) the session's scope and acceptance steps are met;
    (2) money is integer pence, fees come only from api/app/core/money.py, rounding is
    half-up, and the pricing golden tests are unchanged and still pass exactly;
    (3) agency wording and commission disclosure match the prototype, and nothing
    promises a guarantee; (4) no real messages are sent (outbox only) and DEMO_MODE
    features disappear when it is off; (5) only Caddy publishes ports, everything else
    binds to 127.0.0.1, and no secrets or live keys are in the repo; (6) no edits to
    files another lane owns (docs/spec/lanes.md); (7) bugs, missing error handling,
    weak tests.

Then add the session's extra line:

- F: "Also check: the contracts let L1, L2 and L3 work without editing each other's
  files; every endpoint has typed request and response models; make seed is idempotent."
- L1: "Also check: questions render generically from each category's intake schema;
  first acceptance is atomic; the demo simulator uses the real endpoints and disappears
  when DEMO_MODE is off."
- L2: "Also check: the benefit answer is never stored; ledger, mileage and tax-pack
  figures are correct; provider-area font sizes and tap targets meet the rules."
- L3: "Also check: the provider is the settlement merchant; fees, the £1 minimum and
  refunds are exact to the penny; webhooks verify signatures and are idempotent; one
  admin cannot both draft and approve a pricing version."
- I: "Also check: the end-to-end scripts cover the agreed journeys; the production-style
  run serves only through Caddy with basic auth; backups run and are kept 14 days."
