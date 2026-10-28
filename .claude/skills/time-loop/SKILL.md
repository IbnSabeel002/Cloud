---
name: time-loop
description: Time-based loop - run a prompt repeatedly on a timer or schedule for recurring work or anything that changes outside the project (PR reviews, CI, deploys, inboxes, feeds). Chooses between /loop (in session, 1 minute and up), cloud /schedule (laptop closed, 1 hour and up) and desktop tasks, and writes an iteration prompt that is safe to re-run.
when_to_use: Use when the user says "every 5 minutes", "check back", "keep an eye on", "watch", "babysit my PR", "poll", "every morning", "daily", "remind me", or mentions /loop or /schedule; or when the next step depends on something outside the session changing over time.
argument-hint: "[interval] [what to do each time]"
---

# Time loop

Claude runs a prompt repeatedly on a schedule: **timer fires -> Claude runs the routine ->
repeats until stopped.** The user hands off the trigger.

## 1. Do you need a timer at all?

- Waiting on a background shell or subagent you started? **No loop.** The harness wakes you when
  it finishes.
- A PR event subscription, a webhook, a channel or a Monitor tool can push the change to you?
  **Prefer that.** Polling is for things nothing will tell you about.
- Need to keep working until a condition holds, not on a clock? Use `goal-loop` instead.

## 2. Pick the scheduler

| Situation | Use | Limits |
| :- | :- | :- |
| Session stays open; poll every few minutes | `/loop <interval> <prompt>` | 1 min minimum; dies with the session; 7-day expiry |
| Unsure how often; check more while busy, less when quiet | `/loop <prompt>` (self-paced) | Claude picks 1 min - 1 h each time |
| Must run with the laptop closed, daily/hourly | `/schedule` (cloud scheduled task) | **1 hour minimum**; fresh clone, no local files; set connectors per task |
| Must run on a schedule and needs local files | Desktop scheduled task | Machine must be on |
| One reminder later in this session | Ask in plain words ("in 45 minutes, check X") | One-shot |

`/loop` is a skill you can invoke. `/schedule` walks the user through setup. In a Claude Code
cloud session, use the remote tools instead: `ScheduleWakeup` (self-paced `/loop`), `send_later`
(one check-in), `create_trigger` / `update_trigger` / `delete_trigger` (cloud scheduled tasks).

Catch this mismatch: **"every 5 minutes" + "while my laptop is closed" is impossible** with these
tools (cloud minimum is 1 hour). Say so and offer either `/loop 5m` with the session open, or an
hourly cloud task, or an event trigger.

Pick the slowest interval that still meets the need. Every iteration costs tokens. A PR waiting
on human review does not need checking every minute.

## 3. Write the iteration prompt

The prompt runs many times with no memory beyond the session (or none at all, in the cloud). It
must be safe to run again and again. Include:

1. **Target**: exactly what to look at (PR number and repo, URL, inbox query, branch).
2. **Actions**: what to do for each kind of change, in order. E.g. "red CI -> read the failing
   job log, fix the root cause, run the tests locally, push. New review comment -> address it,
   reply, resolve the thread."
3. **Idempotence**: how to tell what is already handled (comment already replied to, item already
   in the tracker) so nothing is done twice.
4. **Quiet path**: "if nothing changed, say so in one line and do nothing else."
5. **Exit**: when the loop should stop itself (PR merged or closed, deploy finished, N runs).
6. **Guardrails**: what it must never do (force-push, merge, send email, delete).
7. **Verification**: end each iteration with `verify-work` for anything it changed.

Example: `/loop 5m check PR #123: if CI is red, fix the root cause, run tests, push; address any
new review comments and resolve them; if nothing changed, say "no change" in one line; stop the
loop when the PR is merged or closed. Never force-push or merge.`

## 4. Start it and tell the user

One line: the scheduler, the interval, what each run does, how it stops, and how they can stop it
(`Esc` for self-paced `/loop`; "cancel the X loop" for fixed `/loop`; `/schedule` to edit or delete
a cloud task).

## 5. Each iteration

Do the actions. Verify what you changed. If nothing changed, stay quiet. If the exit is reached,
cancel the schedule yourself (`CronDelete`, `ScheduleWakeup` with stop, `delete_trigger`) and say
so once. If the same failure repeats three runs in a row with no progress, stop fixing and report
it instead of burning more runs.
