# Job-hunt agent

A daily agent that finds Dubai jobs, throws out the junk, scores what is left, drafts outreach,
and sends you a short list. It runs every morning until you tell it to stop.

## What it does each day

1. Searches Indeed UAE, Bayt, GulfTalent (partly), company career pages, and your job-alert emails.
2. Drops duplicates, stale posts (older than 21 days), fresher/entry/junior roles, wrong-language roles,
   part-time/freelance roles, pay under your floor, and scam patterns.
3. Scores what is left out of 100 and sorts it into pay tiers.
4. Writes a gap analysis and outreach drafts for the strong ones (score 75 or more, at most 5 a day).
5. Saves a tracker and a report in a private Google Drive folder, and sends a digest to your Slack DM.

## What it never does

- It never applies, submits a form, logs in, or uploads your CV.
- It never sends an email. It only saves drafts in Gmail.
- It never scrapes LinkedIn. LinkedIn comes only from your own job-alert emails.
- It never puts your details in this public repo.
- It never decides a job is good enough. You do.

## How the pieces fit

```
Routine (daily, 07:47 Dubai)  ->  PLAYBOOK.md  ->  sources  ->  jobhunt package  ->  Drive + Gmail drafts + Slack
                                   (the model)      (pages)       (the decisions)
```

The model reads pages and writes the prose. The `jobhunt` package makes every decision that has to be exact:
pay parsing, dates, de-duplication, filters, scoring and the tracker. It is plain Python with no installs,
and it is tested.

| File | Job |
|---|---|
| `PLAYBOOK.md` | the step-by-step runbook the daily session follows |
| `jobhunt/salary.py` | turns "AED 5K - AED 11K/mo" into a monthly range |
| `jobhunt/dates.py` | reads "16 days ago", "21 Sep", "Posted on: October 02, 2026" |
| `jobhunt/normalize.py` | makes the same job on two boards one row |
| `jobhunt/score.py` | filters and scoring |
| `jobhunt/tracker.py` | the memory between days |
| `jobhunt/report.py` | the Slack digest and the report |
| `jobhunt/cli.py` | the commands the playbook calls |
| `profile.example.json` | a generic example of the settings |

## Pay tiers

Pay is read as monthly AED. A range is judged by its middle.

| Tier | Monthly pay | Meaning |
|---|---|---|
| A | 8,000 or more | target |
| B | 5,000 to 7,999 | acceptable |
| C | 4,000 to 4,999 | fallback; check the scope carefully |
| U | not listed | kept and flagged; open the post to find out |
| X | top of range under 4,000 | dropped |

Many roles near AED 4–5k are labelled Entry level or Fresher and bundle several jobs into one. Those are dropped
or marked down. The digest always says where a pay figure came from.

## Score (0 to 100)

| Part | Max | What it measures |
|---|---|---|
| Title | 30 | how close the title is to what you are hunting |
| Skills | 25 | how many of your tools the post names |
| Seniority | 15 | whether the years asked suit you |
| Pay | 20 | tier A 20, B 14, C 8, unlisted 8 |
| Freshness | 5 | newer is better |
| Adjustment | -20 to +5 | scope bloat, free-email apply, hidden employer, watchlist company |

Score 60 or more is shortlisted. Score 75 or more is strong and gets outreach drafts.

## The tracker

Drive's connector cannot overwrite a file, so each run saves a new dated Sheet
(`Job Hunt Tracker <date>-<time>`) and the next run reads the newest one. The last 3 are kept.
Open the newest one and edit the **Status** and **Notes** columns. The agent keeps what you type.

Statuses you can type: `Shortlisted`, `Applied`, `Interview`, `Offer`, `Accepted`, `Rejected`, `Dead`.
Common words work too (`skip`, `not interested`, `hired`, `interviewing`). A job you reject or apply to never comes back.
Rows you have not touched are removed after 45 days without being seen.

## Stop, pause, change

- **Stop:** tell Claude "stop the job hunt". It disables the Routine. Or set any row to `Accepted` and the agent stops itself.
- **Pause:** tell Claude "pause the job hunt for two weeks".
- **Change targets, pay floor, languages, queries:** tell Claude. These live in the private Routine prompt, not in git.
- **Day 14, 28, …:** the digest asks if you are still hunting.

## Run the tests

From this folder:

```bash
python3 -m unittest discover -s tests -t . -v
```

Try the pipeline on the real listings captured on 2026-10-05:

```bash
python3 -m jobhunt run --candidates tests/fixtures/candidates_2026-10-05.json --out /tmp/demo --today 2026-10-05
python3 -m jobhunt report --out /tmp/demo
cat /tmp/demo/digest_1.txt
```

## Honest limits

- Coverage is Indeed UAE and Bayt, plus GulfTalent in part. LinkedIn is the biggest UAE source and appears only
  if you create daily job alerts for your titles in Dubai.
- Indeed's connector shows no pay. The agent opens each plausible job to find it, up to 25 a day.
- A daily run driven by a model is not perfectly repeatable. The package and the health line limit the damage.
  A failed source shows up as a warning in the digest instead of a silent gap.
- Pay data on these boards is thin and the boards disagree. Treat pay figures as signals, not facts.
- The fixtures mix real listing details with a few invented fields. `tests/fixtures/candidates_2026-10-05.json` says which.

## Costs

Per run, at most: 10 Indeed searches, 25 job-detail calls, 12 Tiny Fish fetches, 3 Tiny Fish automation runs,
12 Firecrawl calls, 5 deep dives. Tiny Fish search and fetch are free. Automation and Firecrawl use credits.
