# Working rules for Claude in this repo

## Loop engineering (always on)

Before any task that takes more than one step, pick the loop with the `loop-engineering` skill and
say in one line which loop, its exit and its budget. Then:

- **Exploring or deciding** -> turn-based: finish with `verify-work`.
- **Done is provable by a command** -> `goal-loop`.
- **Waiting on something outside the session, or on a timer** -> `time-loop`.
- **Recurring, well-defined work that should run unattended** -> `proactive-loop`.

`verify-work` runs before every claim that something is done, fixed or working, before every
commit or push, and at the end of every loop iteration. No exceptions.

## Repo

- `jobhunt/`: the daily job-hunt agent. Read `jobhunt/README.md` first. Tests:
  `cd jobhunt && python3 -m unittest discover -s tests -t .`.
- `.claude/skills/`: the loop-engineering skills. Check them with `python3 scripts/check_skills.py`
  and `python3 -m unittest discover -s tests`.
