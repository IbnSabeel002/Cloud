---
name: goal-loop
description: Goal-based loop - turn a task into a verifiable stop condition (one measurable end state, the command that proves it, what must not change, and a try limit), then iterate until it holds or the limit is hit. Writes a ready-to-paste /goal line, or runs the loop in-session with an attempt log when /goal is not available.
when_to_use: Use when the user knows what done looks like - "until tests pass", "get the score to 90", "make the build green", "fix all lint errors", "under 300 lines", "empty the queue", "stop after N tries", or mentions /goal. Also use when a task has verifiable exit criteria and would otherwise take many back-and-forth turns.
argument-hint: "[what done looks like]"
---

# Goal loop

The user defines what done looks like. You iterate until it is reached or the limit is hit.
Pattern: **work on the task -> evaluator checks the condition -> not met, back to work -> loop
ends when the goal is met or the turn limit is reached.**

## 1. Write the stop condition

Turn the request ($ARGUMENTS, or the user's last message) into a condition with four parts:

1. **One measurable end state.** A number, an exit code, a count, an empty list.
2. **The check that proves it.** An exact command whose output will appear in the transcript.
3. **Constraints.** What must not change on the way there.
4. **A limit.** Max attempts, turns, or minutes.

Template:

```
<end state>, proven by `<command>` showing <expected output>.
Do not <constraint>. Stop after <N> attempts and report what is still failing.
```

Example: `homepage Lighthouse performance score >= 90, proven by
"npx lighthouse http://localhost:3000 --only-categories=performance --output=json --quiet"
printing the score. Do not remove page content or features. Stop after 5 attempts.`

**Reject vague conditions.** "Make it faster", "clean up the code", "make it good" have no exit.
Propose a measurable version and confirm it with the user before looping. If no command can
prove the condition, this is not a goal loop: use `verify-work` (turn-based) instead.

Run the check **once before changing anything** to record the baseline. If it already passes,
stop and say so.

## 2. Pick how to run the loop

**Option A: `/goal` (best when the user is at the terminal).** `/goal` is a built-in command, so
only the user can start it. Give them one line to paste:

```
/goal <the condition from step 1>
```

Remind them: the evaluator only reads the conversation, so you will print the check output every
turn; run it in auto mode to avoid permission prompts; `/goal clear` stops it.

**Option B: run it yourself, in this session (default when /goal is not possible:
cloud sessions, scheduled runs, subagents, or the user asked you to just do it).**

For each attempt, 1 to N:

1. Form one hypothesis about the biggest gap between now and the goal.
2. Make one focused change for it.
3. Run the check command. Read the full output.
4. Log the attempt (see below).
5. Condition met -> go to step 3 of this skill. Not met -> use what the output says to choose the
   next hypothesis. Never repeat a change that already failed.

Keep the attempt log in the scratchpad (or a temp file), not the repo:

```
| # | Hypothesis | Change | Check result | Kept? |
```

Revert changes that made the result worse unless the next attempt builds on them.

**Option C: independent evaluator.** For long or high-stakes goals where you might talk yourself
into "done", have a fresh subagent (no shared context) run the check and judge the condition,
returning only "met / not met / impossible" and a reason. Only use when the user asked for
subagents or the stakes justify the cost.

## 3. Exit

The loop ends in exactly one of three ways. Report which:

- **Met.** Show the final check output and the baseline beside it. Then run `verify-work`
  (the goal condition is necessary, not sufficient: also check you broke nothing else).
- **Limit reached.** Show the attempt log, the best result reached, what is still failing, and
  the most likely next step. Do not keep going past the limit without the user's say-so.
- **Impossible.** If the evidence shows the condition cannot be met (e.g. the target needs
  something outside the repo), stop early and explain why with evidence.

## Never

- Change the condition, the check, or the threshold to make the loop end.
- Game the metric (skip tests, delete content, special-case the checker, hard-code outputs).
- Claim "met" from memory. The check output from the final attempt must be on screen.
