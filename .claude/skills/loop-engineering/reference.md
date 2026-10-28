# Loop commands: what they really do

Checked against the Claude Code docs (code.claude.com/docs/en/goal, /scheduled-tasks, /routines,
/commands) on 2026-10-28. If behavior looks different, re-read those pages; they change often.

## `/goal [condition | clear]` - goal-based

- A **built-in command**. Only the user can type it. Claude cannot start it with the Skill tool.
  When a goal loop fits, give the user the exact `/goal ...` line to paste, or run the loop yourself
  (see `goal-loop`).
- After every turn, a **separate small fast model** checks the condition. Verdicts: not yet met
  (keep working, reason is fed back), met (goal clears), impossible (goal clears as failed).
- The evaluator **does not run commands or read files**. It only sees what is in the
  conversation. So the condition must name a check whose output Claude prints, e.g.
  "`npm test` exits 0".
- Bound it inside the condition: "... or stop after 20 turns". Condition max 4,000 characters.
- One goal per session. `/goal` with no argument shows status. `/goal clear` (or stop, off, reset,
  none, cancel) removes it. `/clear` also removes it. It survives `--resume`.
- Run it in auto mode for unattended turns. Works with `claude -p "/goal ..."`.
- Unavailable when hooks are disabled (`disableAllHooks`, `allowManagedHooksOnly`) or the folder
  is untrusted. It is a session-scoped prompt-based Stop hook underneath.
- If Claude makes no tool calls for several turns in a row, the loop stops with the goal still set.

## `/loop [interval] [prompt]` - time-based, in session

- A **bundled skill**. Claude can invoke it. Alias: `/proactive`.
- `/loop 5m <prompt>`: fixed interval (units s, m, h, d; seconds round up to 1 minute; odd values
  like 7m are rounded). `/loop <prompt>`: Claude picks a 1 min - 1 h delay each time
  (self-paced). `/loop` alone: built-in maintenance prompt, or `.claude/loop.md` if present.
- Can run a skill each time: `/loop 20m /some-skill args`. Skills with
  `disable-model-invocation: true` arrive as plain text instead.
- **Only fires while the session is open and idle.** No catch-up for missed fires.
- Recurring tasks **expire after 7 days**. Up to 50 scheduled tasks per session.
- Stop: self-paced -> `Esc`, or Claude stops it when done. Fixed interval -> ask Claude to cancel
  it (`CronDelete`); `Esc` does not stop it.
- Underlying tools: `CronCreate`, `CronList`, `CronDelete`, `ScheduleWakeup`.
- If a Monitor tool is available, streaming a background script beats polling.

## `/schedule [description]` - time-based or proactive, in the cloud

- Creates cloud scheduled tasks (formerly "routines"). Alias `/routines`.
- Runs in the cloud: **laptop can be closed**. Each run gets a **fresh clone** (no local files).
- **Minimum interval is 1 hour.** A "every 5 minutes" job cannot be a cloud task; use `/loop`.
- Can also fire from an API call or GitHub events. Auto mode by default. Connectors are set per task.
- In a Claude Code cloud session the same thing is reachable through the remote tools
  (`create_trigger`, `send_later`, `list_triggers`, `update_trigger`, `delete_trigger`).

## Desktop scheduled tasks

- Run on the user's machine (machine must be on, no session needed), with local files.
  Minimum 1 minute when Claude sets it.

## Which one, quickly

| Need | Use |
| :- | :- |
| Keep working until a provable condition holds | `/goal` |
| Poll something every few minutes while I'm here | `/loop` |
| Run every day even when my laptop is closed | `/schedule` (cloud) |
| Run on a schedule and needs my local files | Desktop scheduled task |
| React to a CI failure the moment it happens | Event subscription or channel, not polling |
| Custom stop logic for every session | A Stop hook in settings |
