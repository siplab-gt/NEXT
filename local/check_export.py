#!/usr/bin/env python3
"""
check_export.py — integrity check of an ARankB experiment's participant export.

    ./local-venv/bin/python check_export.py EXP_UID [--base=http://127.0.0.1:8000]
        [--tolerance=0.3] [--prefix=sim]   (only participants whose id starts with prefix)

For every participant it verifies, from /api/experiment/<EXP>/participants:
  * answered queries have contiguous, duplicate-free query_id 1..k
    (a duplicate means an answer was recorded twice - the retry hazard)
  * every served query is a trap exactly when query_id % trap_interval == 0
  * num_trapped == number of answered traps flagged wrong
  * participant_failed == (num_trapped >= ceil(tolerance * num_trap_questions))
  * an expelled participant's last answered query is the one that tripped the limit
Exit status 0 when every participant passes, 1 otherwise.
"""
import math, sys
import requests

args = [a for a in sys.argv[1:] if not a.startswith('--')]
opts = dict(a[2:].split('=', 1) for a in sys.argv[1:] if a.startswith('--') and '=' in a)
if not args:
    sys.exit(__doc__)
EXP = args[0]
BASE = opts.get('base', 'http://127.0.0.1:8000')
PREFIX = opts.get('prefix', '')

exp = requests.get(BASE + '/api/experiment/' + EXP, timeout=60).json()
a = exp.get('args', exp)
num_tries = int(a['num_tries']); num_traps = int(a.get('num_trap_questions', 0) or 0)
set_trap = bool(a.get('setTrap', False)); trap_ratio = float(a.get('trapRatio', 0) or 0)
tolerance = float(opts.get('tolerance', a.get('tolerance', 0.3)))
if set_trap:
    trap_count = int(trap_ratio * num_tries) if trap_ratio > 0 else num_traps
    trap_interval = num_tries // trap_count + 1 if trap_count > 0 else 0
else:
    trap_count, trap_interval = 0, 0
fail_at = math.ceil(tolerance * trap_count) if trap_count else None
print("experiment %s: num_tries=%d traps=%d interval=%s fail_at=%s" % (EXP, num_tries, trap_count, trap_interval, fail_at))

data = requests.get(BASE + '/api/experiment/' + EXP + '/participants', timeout=120).json()
responses = data['participant_responses']; summaries = data.get('participant_summaries', {})
problems = 0; checked = 0
for pid, docs in sorted(responses.items()):
    short = pid.replace(EXP + '_', '')
    if PREFIX and not short.startswith(PREFIX):
        continue
    checked += 1
    errs = []
    answered = [q for q in docs if 'target_winner' in q]
    ids = sorted(int(q['query_id']) for q in answered)
    if ids != list(range(1, len(ids) + 1)):
        dup = sorted(set(i for i in ids if ids.count(i) > 1))
        errs.append("query_id sequence not contiguous/unique: %s%s" % (ids[:12], (" DUPLICATES %s" % dup) if dup else ""))
    for q in docs:
        qid = int(q['query_id']); is_trap = bool(q.get('isTrap'))
        expect = (trap_interval > 0 and qid % trap_interval == 0)
        if is_trap != expect:
            errs.append("query %d isTrap=%s expected %s" % (qid, is_trap, expect))
    wrong = sum(1 for q in answered if q.get('isTrap') and q.get('trapped'))
    summ = summaries.get(pid, {})
    failed = bool(summ.get('participant_failed', False)) if summ else any(q.get('participant_failed') for q in answered)
    num_trapped = summ.get('num_trapped', wrong) if summ else wrong
    note = ''
    if failed and fail_at is not None:
        # The answer that trips the limit is counted on the participant record but
        # the app raises before that query doc is written, so the docs hold one
        # wrong trap fewer than num_trapped. Anything beyond that means answers
        # kept being accepted after expulsion.
        if num_trapped == fail_at and wrong == fail_at - 1:
            note = '  (expelled at trap %d; expelling answer not stored - expected)' % fail_at
        else:
            errs.append("expelled but num_trapped=%s, wrong traps in docs=%d (expected %d and %d)" % (num_trapped, wrong, fail_at, fail_at - 1))
    else:
        if num_trapped != wrong:
            errs.append("summary num_trapped=%s but %d wrong traps in docs" % (num_trapped, wrong))
        if fail_at is not None and wrong >= fail_at:
            errs.append("%d wrong traps (>= fail_at %d) but participant not failed" % (wrong, fail_at))
    status = "OK " if not errs else "BAD"
    print("%s %-28s answered=%-3d wrong_traps=%d failed=%s%s%s" % (status, short, len(ids), wrong, failed, note, ("  " + "; ".join(errs)) if errs else ""))
    problems += bool(errs)
print("\n%d participants checked, %d with problems" % (checked, problems))
sys.exit(1 if problems else 0)
