#!/usr/bin/env python3
"""
repro_duplicate_answer.py — reproduce the "skipped query" bug: the same answer
(same query_uid, same body) POSTed to processAnswer twice, as a browser does when it
re-sends a request after a dropped connection.

Each scenario uses a fresh participant ID on an existing ARankB experiment (launch the
32-query demo, local/ARankB-InfoTuple-cog_rank4_sample_base.yaml, which has a trap
every 4th query, tolerance 0.3 x 8 traps -> expelled at the 3rd wrong trap).

  A  sequential duplicate: answer q1, send the identical POST again, then getQuery.
     Correct: next query_id is 2.             Bug: 3 (query 2 skipped).
  B  concurrent duplicate: the two identical POSTs in parallel.
     Correct: 2.                               Bug: 3.
  C  duplicated wrong trap: answer q1-q3, answer trap q4 WRONG and send it twice,
     answer q5-q7, answer trap q8 wrong once.
     Correct: 2 wrong traps -> NOT expelled.   Bug: counted as 3 -> expelled at q8.
  C0 control for C without any duplicate: must NOT be expelled.
  D  3 wrong traps, the 3rd (expelling) one sent twice at the same time.
     Correct: BOTH copies report the expulsion (the page must show the fail exit
     even when the original's response is the one lost).

Usage (from this box, through nginx like real participants):
  ./local-venv/bin/python repro_duplicate_answer.py --exp <EXP_UID>
Exit code 0 = all scenarios behave correctly, 1 = bug reproduced.
"""
import argparse, json, random, sys, threading, time
import requests

p = argparse.ArgumentParser()
p.add_argument("--exp", required=True)
p.add_argument("--base", default="http://127.0.0.1")
p.add_argument("--host-header", default="52.2.236.217")
p.add_argument("--tag", default=time.strftime("%H%M%S"))
a = p.parse_args()

S = requests.Session()
S.headers["Host"] = a.host_header


def post(kind, args):
    r = S.post(a.base + "/api/experiment/" + kind, json={"exp_uid": a.exp, "args": args}, timeout=180)
    try:
        body = r.json()
    except ValueError:
        body = {"_text": r.text[:200]}
    return r.status_code, body


def expelled(status, body):
    meta = body.get("meta", {}) if isinstance(body, dict) else {}
    return bool(meta.get("expelled")) or "expelled" in json.dumps(body) or "failed" in str(meta.get("backend_error", ""))


def get_query(pid):
    st, q = post("getQuery", {"participant_uid": pid, "widget": False})
    assert st == 200 and "query_uid" in q, (st, q)
    return q


def answer_args(q, wrong_trap=False):
    if q.get("isTrap"):
        winner, trapped = [0], bool(wrong_trap)
    else:
        ids = [t["target_id"] for t in q["target_items"]]
        rest = ids[1:]
        random.shuffle(rest)
        winner, trapped = [ids[0]] + rest, False
    return {"query_uid": q["query_uid"], "target_winner": winner,
            "participant_uid": q["participant_uid"], "trapped": trapped, "response_time": 1.0}


def answer(q, wrong_trap=False, duplicate=None):
    """duplicate: None | 'seq' | 'par'. Returns list of (status, body)."""
    body = answer_args(q, wrong_trap)
    if duplicate == "par":
        out = [None, None]
        def go(i): out[i] = post("processAnswer", body)
        ts = [threading.Thread(target=go, args=(i,)) for i in range(2)]
        [t.start() for t in ts]; [t.join() for t in ts]
        return out
    out = [post("processAnswer", body)]
    if duplicate == "seq":
        out.append(post("processAnswer", body))
    return out


def pid(name):
    return "dup{}{}".format(name, a.tag)


results = {}

# A / B: duplicate answer -> next query id
for name, mode in (("A", "seq"), ("B", "par")):
    q1 = get_query(pid(name))
    assert q1["query_id"] == 1, q1["query_id"]
    resp = answer(q1, duplicate=mode)
    q_next = get_query(pid(name))
    ok = q_next["query_id"] == 2
    results[name] = ok
    print("{} {:10s} statuses={} next query_id={} -> {}".format(
        name, "sequential" if mode == "seq" else "concurrent",
        [s for s, _ in resp], q_next["query_id"], "OK" if ok else "BUG (query skipped)"))

# C / C0: wrong trap counted twice -> premature expulsion
for name, dup in (("C", True), ("C0", False)):
    participant = pid(name)
    was_expelled, last_qid = False, 0
    for _ in range(8):
        q = get_query(participant)
        last_qid = q["query_id"]
        if q["query_id"] > 8:
            break
        is_first_trap = q.get("isTrap") and q["query_id"] == 4
        resp = answer(q, wrong_trap=bool(q.get("isTrap")),
                      duplicate=("seq" if (dup and is_first_trap) else None))
        if any(expelled(s, b) for s, b in resp):
            was_expelled = True
            break
    ok = not was_expelled
    results[name] = ok
    print("{:2s} {:10s} 2 wrong traps{} -> expelled={} at query {} -> {}".format(
        name, "", " (1st sent twice)" if dup else "", was_expelled, last_qid,
        "OK" if ok else "BUG (expelled early)"))

# D: the expelling answer itself arrives twice (at the same time) -> BOTH copies must
# report the expulsion, so the page shows the fail exit even if the original's
# response was the one lost on the network.
participant = pid("D")
copies = None
for _ in range(12):
    q = get_query(participant)
    if q["query_id"] > 12:
        break
    third_trap = q.get("isTrap") and q["query_id"] == 12
    resp = answer(q, wrong_trap=bool(q.get("isTrap")), duplicate=("par" if third_trap else None))
    if third_trap:
        copies = [expelled(s, b) for s, b in resp]
        break
    if any(expelled(s, b) for s, b in resp):
        copies = ["expelled early at %d" % q["query_id"]]
        break
ok = copies == [True, True]
results["D"] = ok
print("D  {:10s} 3rd wrong trap sent twice -> expelled per copy={} -> {}".format(
    "concurrent", copies, "OK" if ok else "BUG"))

bad = [k for k, v in results.items() if not v]
print("RESULT:", "all correct" if not bad else "bug reproduced in " + ", ".join(bad))
sys.exit(1 if bad else 0)
