import os

# The playbook gate (jobhunt/playbook_gate.py) makes prefilter, run and report refuse to work until the playbook has
# been read in full. Every test except test_playbook_gate.py runs with it off.
os.environ.setdefault("JOBHUNT_SKIP_PLAYBOOK_GATE", "1")
