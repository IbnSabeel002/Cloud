---
name: loop-engineering
description: Pick the right work loop before starting any task that takes more than one step - turn-based (explore or decide, you own the check), goal-based (a stop condition you can prove), time-based (re-run on a timer or schedule), or proactive (a trigger feeds a fix-review-PR pipeline that a human merges). Routes to verify-work, goal-loop, time-loop or proactive-loop.
when_to_use: Use at the start of any multi-step task, whenever the user says "keep going until", "check every", "watch", "babysit", "monitor", "every morning", "until it passes", "loop", "/goal", "/loop", "/schedule", or asks for recurring or unattended work. Also use when unsure whether a task is done.
---

# Loop engineering

Every agent task is a loop. The only real choice is **what you hand off**: the check, the stop
condition, the trigger, or the whole prompt. Pick the loop first, then do the work.

## Pick the loop

| Loop | What the user hands off | Use it when | Reach for |
| :- | :- | :- | :- |
| Turn-based | the check | Exploring or deciding. "Done" is a judgment call. | `verify-work` skill |
| Goal-based | the stop condition | You know what done looks like and a command can prove it. | `goal-loop` skill, `/goal` |
| Time-based | the trigger | The work happens outside the project, on a timer (CI, deploys, inboxes, PRs). | `time-loop` skill, `/loop`, `/schedule` |
| Proactive | the prompt | The work is recurring and well defined, and should run with no one watching. | `proactive-loop` skill (combines all of the above) |

## Decide in this order

Ask these questions in order. Stop at the first "yes".

1. **Is the work recurring, well defined, and meant to run with no one watching** (laptop closed,
   every day, on every new bug report)? -> **Proactive**. Load `proactive-loop`.
2. **Does the next step depend on something outside this session changing over time** (CI finishing,
   a reviewer commenting, a deploy, new email)? -> **Time-based**. Load `time-loop`.
3. **Can a command or a visible result prove the task is done** (tests exit 0, score >= 90, queue
   empty, file under N lines)? -> **Goal-based**. Load `goal-loop`.
4. Otherwise -> **Turn-based**. Load `verify-work` and end every turn with it.

Loops nest. A proactive loop runs a goal loop inside each run. A time loop's iteration ends with
`verify-work`. Turn-based verification is the floor under every other loop, never skipped.

## Rules that apply to every loop

- **Every loop needs an exit.** Name it before starting: a condition, a try limit, a time limit,
  or "the user stops it". A loop with no exit is a bug.
- **Every loop needs a budget.** Attempts, turns, or wall time. When it runs out, stop and report
  what was tried and what is still failing. Never quietly keep going.
- **Evidence, not belief.** "Done" means a check ran and its output is in the transcript. "Should
  work" is not done.
- **Don't fake the exit.** Never weaken a test, skip a check, lower a threshold, or edit the
  condition to make a loop end. If the bar is wrong, stop and ask.
- **Quiet when nothing changed.** A timed or proactive iteration with nothing to do says so in one
  line, or nothing at all, and does not ping the user.
- **Pick the cheapest trigger that works.** Waiting on a background task the harness tracks needs
  no loop at all: it wakes you when done. Polling is for things nothing will tell you about.

## Tell the user which loop you picked

In one line, before starting: the loop, its exit, and its budget. Example:
"Goal loop: stop when `npm test` exits 0 and lint is clean, max 6 attempts."

See [reference.md](reference.md) for the exact behavior and limits of `/goal`, `/loop` and `/schedule`.
