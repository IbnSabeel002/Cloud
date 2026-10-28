# Cloud

- `jobhunt/`: a daily job-hunt agent. See [jobhunt/README.md](jobhunt/README.md).
- `.claude/skills/`: loop-engineering skills for Claude Code (below).

## Loop-engineering skills

Every agent task is a loop. These skills make Claude pick the right one, state its exit and
budget, and prove the result before calling it done. `CLAUDE.md` tells Claude to use them on
every multi-step task in this repo.

| Skill | Loop | You hand off | Use it when |
| :- | :- | :- | :- |
| `loop-engineering` | Router | - | Start of any multi-step task: picks one of the four below |
| `verify-work` | Turn-based | the check | Exploring or deciding; and before every "done", commit or push |
| `goal-loop` | Goal-based | the stop condition | A command can prove it's done ("tests pass", "score >= 90, max 5 tries") |
| `time-loop` | Time-based | the trigger | Work outside the project on a timer: PRs, CI, deploys, inboxes |
| `proactive-loop` | Proactive | the prompt | Recurring, well-defined work that runs unattended and opens PRs |

Limits worth knowing (checked against the Claude Code docs, Oct 2026; details in
`.claude/skills/loop-engineering/reference.md`):

- `/goal` is a built-in command: only you can type it. Its evaluator reads only the conversation,
  so the condition must name a check whose output Claude prints.
- `/loop` runs only while the session is open (1 minute minimum, 7-day expiry).
- `/schedule` cloud tasks run with the laptop closed but no more often than **hourly**.

### Use them in every project

These load automatically in this repo. To have them in every project on your machine:

```bash
scripts/install_loop_skills.sh          # copies to ~/.claude/skills, skips ones you already have
scripts/install_loop_skills.sh --force  # replace existing copies
```

Then add the "Loop engineering" section of `CLAUDE.md` to `~/.claude/CLAUDE.md` so Claude
reaches for them everywhere, not only when a request happens to match a skill description.

### Check them

```bash
python3 scripts/check_skills.py            # frontmatter, name, length, links
python3 -m unittest discover -s tests      # validator, content and installer tests
```
