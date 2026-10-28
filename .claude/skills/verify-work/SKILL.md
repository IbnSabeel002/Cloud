---
name: verify-work
description: The turn-based loop - gather context, take action, verify the work, then respond. Use before saying a task is done, fixed, working or complete, before committing or pushing, and at the end of any exploring or deciding turn. Proves the result with evidence (commands run, output read, diff re-read) instead of assuming it.
when_to_use: Use whenever about to claim success, report results, commit, push, open a PR, or hand back to the user; when the user asks "does it work", "is it done", "check your work", "verify"; and as the final step of every goal, time or proactive loop iteration.
---

# Verify the work (turn-based loop)

Turn-based loop: **gather context -> take action -> verify the work -> respond**.
You decide when the task is complete, so the check is yours. The loop only exits to a response
when verification passes, or when you need context only the user has.

## 1. Gather context (before acting)

- Restate the ask in one line. If two readings are possible and they lead to different work,
  ask; otherwise pick the obvious one and say so.
- Read the code, data or docs the change touches. Find how this repo checks itself: test command,
  linter, type checker, build, CI config (`.github/workflows`, `Makefile`, `package.json`,
  `pyproject.toml`, README).
- Decide now what "verified" will mean for this task (see table below).

## 2. Take action

Make the smallest change that does the job. Match the surrounding code.

## 3. Verify the work

Pick every row that applies. Run it. Read the output. Don't summarize output you didn't read.

| Kind of work | Proof |
| :- | :- |
| Code change | Repo's tests for the touched area pass; lint/format/typecheck clean; new behavior has a test that fails without the change |
| Bug fix | Reproduce the bug first, then show the same steps passing |
| UI / page | Load it (Playwright or the `run` skill), screenshot it, look at the screenshot |
| Script / CLI | Run it on a real input and on one bad input |
| Data / numbers | Recompute one value by a second route; check totals and row counts |
| Docs / config | Every command, flag, path and link it names actually exists |
| Research / facts | Each claim traced to a source you opened; numbers cross-checked in a second source |
| Decision / recommendation | The strongest counter-argument stated and answered; costs and risks named |

Then, every time:

- **Re-read your own diff as a hostile reviewer.** What breaks? What did you leave half done?
  Debug prints, TODOs, unrelated edits, secrets?
- **Check the ask again.** Did you do what was asked, all of it, and nothing extra?

If any check fails, go back to step 1 with what you learned. Don't respond yet.

## 4. Respond

- Lead with the outcome. Then the evidence: which checks ran and what they showed.
- Say plainly what was **not** verified and why (no network, no credentials, no test exists).
- Never write "should work", "probably fixed" or "done" without a check behind it.

## Budget

If the same check fails three times in a row with no new information, stop looping. Report what
you tried, the exact failing output, and your best guess at the cause. That is a valid response;
an endless loop is not.

## Never

- Weaken, skip, or delete a test or check to make it pass.
- Claim a check passed that you did not run.
- Hide a failure inside a long summary.
