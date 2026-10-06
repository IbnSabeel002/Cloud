# Job-hunt agent

A daily agent that finds Dubai jobs, throws out the junk, scores what is left, drafts outreach,
and sends you a short list. It runs every morning until you tell it to stop.

## What it does each day

1. Searches Indeed UAE, Bayt, GulfTalent (partly), company career pages, and your job-alert emails
   (LinkedIn alerts are read by a script that takes the title, company and place from each email).
2. Drops duplicates, stale posts (older than 21 days), fresher/entry/junior roles, wrong-language roles,
   part-time/freelance roles, pay under your floor, and scam patterns.
3. Scores what is left out of 100 and sorts it into pay tiers.
4. Writes a gap analysis and outreach drafts for the strong ones (score 75 or more, at most 5 a day).
5. Saves new jobs to your private tracker page, writes a full report to a private Google Drive folder,
   and sends a digest to your own Slack DM (when Slack is on).

## What it never does

- It never applies, submits a form, logs in, or uploads your CV.
- It never sends an email. It only saves drafts in Gmail.
- It never scrapes LinkedIn. LinkedIn comes only from your own job-alert emails.
- It never puts your details in this public repo.
- It never decides a job is good enough. You do.

## How the pieces fit

```
Routine (daily, 07:47 Dubai)
   -> dispatcher session (does nothing except start one worker)
        -> a NEW worker subagent every day (empty memory)
             -> clones this repo, reads PLAYBOOK.md through the gate
             -> sources -> jobhunt package -> tracker page + Drive report + Gmail drafts + Slack
```

The model reads pages and writes the prose. The `jobhunt` package makes every decision that has to be exact:
pay parsing, dates, de-duplication, filters, scoring and which database writes are needed. It is plain Python
with no installs, and it is tested.

### Why a dispatcher and a new worker every day

The first design woke one long-lived session each morning. That session drifted: after the first run it worked from
its memory of that run, skipped the playbook, and its context grew by about 190k tokens a run. So now:

- The routine wakes a **dispatcher** that has one job: start a **fresh worker subagent** with the run prompt, then pass
  its digest on unchanged. It does not search, fetch, read or decide anything. A message that does not start with
  `DAILY RUN DISPATCH` is not a wake-up and is ignored.
- The worker has no memory of earlier days. It clones this repo into a new folder and reads the playbook from that
  clone, not from any copy lying around.
- State that has to survive between days lives in the private tracker database, never in a session.

### The playbook gate

"Read the playbook first" is a rule a model can skip, so it is also a check the code makes:

- `python3 -m jobhunt playbook --chunk N` prints the playbook in numbered chunks of about 7,500 characters. Each
  chunk ends with where it is and what comes next. Reading chunk 1 starts a new receipt.
- `prefilter`, `run` and `report` **refuse to run** (exit code 2) until every chunk of the current playbook has been read
  in the last 12 hours. A playbook that changed after it was read does not count.
- The digest carries a line such as `Playbook @abc1234 sha:1f2e3d4c read 5/5` and the run record stores it. The
  dispatcher adds a warning to the digest if that line is missing.
- `playbook --section N` re-prints one section for a quick check without touching the receipt.
- Tests set `JOBHUNT_SKIP_PLAYBOOK_GATE=1`. Never set it in a routine.

### Untrusted text in the digest

Job titles, company names, reasons and links come from web pages and emails, so the digest treats them as data:
URLs and email addresses are stripped from text fields, markup characters are removed, lengths are capped, and a
link is shown only if it is a plain `https` address. A source that never reported (`Settings`, `Indeed connector`,
`Tiny Fish pages`, `Gmail alerts`, `Tracker write`) marks the run as degraded and shows as a warning instead of staying
silent. LinkedIn alert emails are read only by `parse-alert`: each job it makes carries a mark, and `prefilter` and `run`
refuse a `linkedin_alert` entry without it, so one typed by hand is dropped and the digest says so.

| File | Job |
|---|---|
| `PLAYBOOK.md` | the step-by-step runbook the daily worker follows |
| `jobhunt/salary.py` | turns "AED 5K - AED 11K/mo" into a monthly range |
| `jobhunt/dates.py` | reads "16 days ago", "21 Sep", "Posted on: October 02, 2026" |
| `jobhunt/normalize.py` | makes the same job on two boards one row |
| `jobhunt/score.py` | filters and scoring |
| `jobhunt/profile.py` | the settings and their checks |
| `jobhunt/alerts.py` | reads LinkedIn alert emails (exact sender check, tracking links removed) |
| `jobhunt/indeed_links.py` | matches each result-page card to its own job link |
| `jobhunt/availability.py` | turns the notice end date into the right sentence for today |
| `jobhunt/tracker.py` | the merge rules: what to keep, add, update and prune |
| `jobhunt/store.py` | turns those rules into the exact database writes |
| `jobhunt/report.py` | the Slack digest and the report |
| `jobhunt/playbook_gate.py` | serves the playbook in chunks and keeps the receipt |
| `jobhunt/watchdog.py` | fills the watchdog prompt template (`WATCHDOG.md`) with your private values |
| `jobhunt/cli.py` | the commands the playbook calls |
| `profile.example.json` | a generic example of the settings |

## The watchdog

A second, separate routine runs at 09:17 Dubai time and checks that the 07:47 hunt really happened. It sends one short
message to your phone and email. It reads only; it never changes anything.

- **It checks:** the daily routine is switched on and started today; and today's run left a record in the tracker that shows
  the whole playbook was read, has a report link, names every required check, and shows at least one source worked.
- **What you see:** one `OK` line on a healthy day; `⚠️ Job hunt ALERT` with plain reasons when something is wrong;
  `⚠️ Watchdog could not check` when it could not look something up (the hunt itself may be fine); `STOPPED` when the daily
  routine is switched off, so a stopped hunt is never reported as healthy.
- **What it cannot see:** whether the Slack message arrived (an organisation setting stops a routine from being given the
  Slack connector, so the OK line says `Slack not checked`), whether the jobs are good, or whether data was typed by hand or a
  source was skipped (the digest warns about those). If both routines stop at once (a connector expiry, a paused plan),
  nothing arrives.
- **Where it lives:** `WATCHDOG.md` holds the prompt, the setup and the test plan. `python3 -m jobhunt watchdog-prompt`
  fills in your private values (none of them are in git). If you finish your search, switch this routine off as well.

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
| Seniority | 15 | how far the years asked sit above your own |
| Pay | 20 | tier A 20, B 14, C 8, unlisted 8 |
| Freshness | 5 | newer is better |
| Adjustment | -20 to +5 | engineering title, scope bloat, free-email apply, hidden employer, watchlist company |

Score 60 or more is shortlisted. Score 75 or more is strong and gets outreach drafts.

## The tracker

The tracker is a private page with its own small database: one document per job. Open the page to see every
shortlisted role, its score, pay and flags, and the last run's health. Change a job's **status** or type a **note**
and the agent keeps it.

Statuses: `Shortlisted`, `Applied`, `Interview`, `Offer`, `Accepted`, `Rejected`, `Dead`.
A job you reject or apply to never comes back. Jobs you have not touched are removed 30 days after they were
first seen (a job that old would be screened out as stale anyway). `Applied`, `Interview`, `Offer` and `Accepted`
are never removed.

The agent writes only what changed: new jobs, and a job whose pay or score changed. Seeing the same job again
writes nothing, so it can never overwrite an edit you just made.

## Stop, pause, change

- **Stop:** tell Claude "stop the job hunt". It disables the Routine. Or set any job to `Accepted` on the tracker page and the agent stops itself.
- **Pause:** tell Claude "pause the job hunt for two weeks".
- **Change targets, pay floor, languages, visa, availability, portfolio link:** tell Claude. The changes are saved in
  the private tracker database (document `config/candidate`) and take effect on the next run. A Routine's own prompt
  cannot be edited after it is created, which is why the settings are not kept there. None of it is in git.
- **What the agent knows about you** comes from your CV plus what you told it: English only (a post that *requires*
  Arabic is dropped; "Arabic is a plus" is kept); you hold a UAE visa with an NOC, so you need no visa sponsorship
  ("visa not stated" is never raised and "no visa provided" is never a reason to drop a post) but the new employer must
  issue a labour card (a post that wants you to bring your own labour card is flagged); your notice period ends by a
  date you gave (`notice_ends_by`), and a small script turns it into the right sentence for today ("ends by Friday
  9 October", later "available to join immediately") so a draft never states a stale date; and your portfolio link goes
  into outreach drafts.
- **Slack:** on, to your own DM only (`slack_user_id` in the same settings document). The workspace is a work account
  whose admins may read DMs. To turn it off, tell Claude; the digest then arrives only as the run's final message.
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
- LinkedIn alerts carry only a title, a company and a place: no pay, no description, no date. Those jobs are judged at a
  lower bar (50, not 60) and the digest says so. They are leads for you to open, not verified matches. The agent never
  opens LinkedIn itself. Jobs outside the UAE are dropped; other emirates are flagged.
- A results page shows only a few bullets per job. Those are judged like a listing with no description, and a job
  is only ever linked by its own address, never by the search page it was found on.
- Indeed's connector shows no pay. The agent opens each plausible job to find it, up to 25 a day.
- A daily run driven by a model is not perfectly repeatable. The package and the health line limit the damage.
  A failed source shows up as a warning in the digest instead of a silent gap.
- Pay data on these boards is thin and the boards disagree. Treat pay figures as signals, not facts.
- Gmail has to stay connected for alerts and drafts. If the connection expires, the digest says
  "Gmail needs re-authorization" and everything else keeps running.
- The tracker is a database because Google Drive could not hold it: the connector cannot overwrite a file, and
  reading a Sheet back drops rows past about 115 and shortens cells to `...`. This was measured, not assumed.
- The fixtures mix real listing details with a few invented fields. `tests/fixtures/candidates_2026-10-05.json` says which.

## Costs

Per run, at most: 10 Indeed searches, 25 job-detail calls, 12 Tiny Fish fetches, 3 Tiny Fish automation runs,
12 Firecrawl calls, 5 deep dives. Tiny Fish search and fetch are free. Automation and Firecrawl use credits.
