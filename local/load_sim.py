#!/usr/bin/env python3
"""
load_sim.py — simulated ARankB participants over plain HTTP (no browser needed).

Each simulated participant runs in its own thread and behaves like the real query
page: POST getQuery -> think -> POST processAnswer -> repeat, until the server says the
study is complete.  Traps are answered correctly, or deliberately wrong for a chosen
fraction of participants (to exercise expulsion).  Every request is logged to a CSV
with latency, HTTP status and an outcome classification; a summary is printed at the
end.

Error handling mirrors the (new) query page logic so the same tool can validate it:
  * a genuine expulsion (HTTP 500 whose backend_error says "Participant ... failed" /
    "is expelled", or a 200 with meta.expelled) ends the participant -> outcome=expelled
  * anything else (timeout, 5xx, 404, 200-with-FAIL-meta) is "transient": the answer
    is NEVER re-POSTed; the participant waits and re-asks for the query (the server
    re-serves an unanswered query, or the next one if the answer did land)
  * when the retry budget is exhausted -> outcome=technical_exit, participant stops

Usage (from this box, through nginx like real participants):
  ./local-venv/bin/python load_sim.py --base http://52.2.236.217 --exp <EXP_UID> \
      --participants 5 --think 2,4 --max-queries 10 --tag repro1

From a laptop, same command with the public IP.  Use --base http://HOST:8000 to
bypass nginx.  Output: loadsim_<tag>.csv (gitignored).
"""
import argparse, csv, json, random, re, statistics, sys, threading, time
from collections import Counter, defaultdict

try:
    import requests
except ImportError:
    sys.exit("pip install requests (or run with local/local-venv/bin/python)")

EXPELLED_RE = re.compile(r"(Participant .* failed|Bad participant .* is expelled)")

def parse_pair(s, cast=float):
    a, b = s.split(",")
    return cast(a), cast(b)

class Stats:
    def __init__(self):
        self.lock = threading.Lock()
        self.in_flight = 0
        self.peak_in_flight = 0
        self.rows = []
        self.outcomes = Counter()
        self.statuses = Counter()
        self.latencies = defaultdict(list)
        self.completed = 0
        self.expelled = 0
        self.technical = 0
    def enter(self):
        with self.lock:
            self.in_flight += 1
            self.peak_in_flight = max(self.peak_in_flight, self.in_flight)
    def leave(self):
        with self.lock:
            self.in_flight -= 1
    def record(self, row):
        with self.lock:
            self.rows.append(row)
            self.outcomes[row["outcome"]] += 1
            self.statuses[row["http_status"]] += 1
            if row["outcome"] == "ok":
                self.latencies[row["kind"]].append(row["latency_ms"])

def classify(kind, status, body_text, exc):
    """Return (outcome, snippet, parsed_json_or_None)."""
    if exc is not None:
        return "transient", type(exc).__name__ + ": " + str(exc)[:80], None
    data = None
    try:
        data = json.loads(body_text) if body_text else None
    except ValueError:
        data = None
    meta = (data or {}).get("meta", {}) if isinstance(data, dict) else {}
    if status == 200:
        if isinstance(meta, dict) and meta.get("expelled"):
            return "expelled", "meta.expelled", data
        if isinstance(meta, dict) and meta.get("status") == "FAIL":
            return "app_fail", str(meta.get("message", ""))[:80], data
        if kind == "getQuery" and (not isinstance(data, dict) or "query_uid" not in data):
            return "app_fail", "no query_uid in 200 body", data
        return "ok", "", data
    if status == 500 and isinstance(meta, dict):
        be = str(meta.get("backend_error", ""))
        if EXPELLED_RE.search(be):
            return "expelled", EXPELLED_RE.search(be).group(0)[:80], data
        return "transient", "500: " + (be.strip().splitlines() or [""])[-1][:80], data
    return "transient", "HTTP %s %s" % (status, (body_text or "")[:60].replace("\n", " ")), data

class Participant(threading.Thread):
    def __init__(self, idx, pid, args, stats, log):
        super().__init__(daemon=True)
        self.idx, self.pid, self.args, self.stats, self.log = idx, pid, args, stats, log
        self.wrong_traps = (idx < int(round(args.participants * args.wrong_trap_fraction)))
        self.session = requests.Session()
        self.req_counter = 0
        self.answered = 0
        self.final = "unknown"

    def post(self, kind, payload):
        url = self.args.base.rstrip("/") + "/api/experiment/" + kind
        self.req_counter += 1
        if self.args.fault_every and self.req_counter % self.args.fault_every == 0:
            url += "X"   # deliberate 404 to exercise transient handling
        t0 = time.time()
        status, text, exc = 0, "", None
        self.stats.enter()
        try:
            r = self.session.post(url, json=payload, timeout=self.args.timeout)
            status, text = r.status_code, r.text
        except Exception as e:   # timeout, connection error, ...
            exc = e
        finally:
            self.stats.leave()
        latency_ms = int((time.time() - t0) * 1000)
        outcome, snippet, data = classify(kind, status, text, exc)
        qid = (data or {}).get("query_id", "") if isinstance(data, dict) else ""
        is_trap = (data or {}).get("isTrap", "") if isinstance(data, dict) else ""
        row = dict(ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), pid=self.pid,
                   query_id=qid, kind=kind, isTrap=is_trap, latency_ms=latency_ms,
                   http_status=status, outcome=outcome, error=snippet)
        self.stats.record(row)
        self.log(row)
        return outcome, data

    def run(self):
        a = self.args
        attempt = 0
        while True:
            # ---- get a query (with retry budget) ----
            outcome, q = self.post("getQuery", {"exp_uid": a.exp,
                                                "args": {"participant_uid": self.pid, "widget": False}})
            if outcome == "expelled":
                self.final = "expelled"; self.stats.expelled += 1; return
            if outcome != "ok":
                if a.no_retry or attempt >= a.retries:
                    self.final = "technical_exit"; self.stats.technical += 1; return
                delay = a.retry_delays[min(attempt, len(a.retry_delays) - 1)]
                attempt += 1
                time.sleep(delay)
                continue
            attempt = 0
            if q.get("query_id", 0) > q.get("total_queries", 10**9):
                self.final = "completed"; self.stats.completed += 1; return
            if a.max_queries and self.answered >= a.max_queries:
                self.final = "max_queries"; return
            # ---- think ----
            think = random.uniform(*a.think)
            time.sleep(think)
            # ---- build the answer ----
            if q.get("isTrap"):
                target_winner, trapped = [0], bool(self.wrong_traps)
            else:
                ids = [t["target_id"] for t in q["target_items"]]
                rest = ids[1:]
                random.shuffle(rest)
                target_winner, trapped = [ids[0]] + rest, False
            outcome, _ = self.post("processAnswer", {"exp_uid": a.exp, "args": {
                "query_uid": q["query_uid"], "target_winner": target_winner,
                "participant_uid": q["participant_uid"], "trapped": trapped,
                "response_time": round(think, 3)}})
            if outcome == "ok":
                self.answered += 1
                attempt = 0
            elif outcome == "expelled":
                self.final = "expelled"; self.stats.expelled += 1; return
            else:
                # transient: never re-POST; fall through to getQuery which re-serves
                # the unanswered query (or the next one if the answer did land).
                if a.no_retry or attempt >= a.retries:
                    self.final = "technical_exit"; self.stats.technical += 1; return
                delay = a.retry_delays[min(attempt, len(a.retry_delays) - 1)]
                attempt += 1
                time.sleep(delay)

def pct(xs, p):
    if not xs: return 0
    xs = sorted(xs); k = max(0, min(len(xs) - 1, int(round(p / 100.0 * len(xs) + 0.5)) - 1))
    return xs[k]

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True, help="e.g. http://52.2.236.217 (nginx) or http://HOST:8000")
    ap.add_argument("--exp", required=True, help="experiment uid")
    ap.add_argument("--participants", type=int, default=5)
    ap.add_argument("--think", default="8,15", help="uniform think time range in seconds, e.g. 2,4")
    ap.add_argument("--wrong-trap-fraction", type=float, default=0.0, help="fraction of participants that answer every trap wrong")
    ap.add_argument("--max-queries", type=int, default=0, help="answers per participant (0 = until the study completes)")
    ap.add_argument("--timeout", type=float, default=120.0, help="per-request timeout seconds")
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--retry-delays", default="5,15,30")
    ap.add_argument("--no-retry", action="store_true")
    ap.add_argument("--stagger", type=float, default=0.5, help="seconds between participant starts")
    ap.add_argument("--pid-prefix", default="sim")
    ap.add_argument("--tag", default="run")
    ap.add_argument("--fault", default="none", help="none | bad-url:K (every K-th request hits a wrong URL)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    args.think = parse_pair(args.think)
    args.retry_delays = [float(x) for x in args.retry_delays.split(",")]
    args.fault_every = int(args.fault.split(":")[1]) if args.fault.startswith("bad-url:") else 0

    stats = Stats()
    csv_path = "loadsim_%s.csv" % args.tag
    f = open(csv_path, "w", newline="")
    w = csv.DictWriter(f, fieldnames=["ts", "pid", "query_id", "kind", "isTrap", "latency_ms", "http_status", "outcome", "error"])
    w.writeheader()
    wlock = threading.Lock()
    def log(row):
        with wlock:
            w.writerow(row); f.flush()
        if not args.quiet and row["outcome"] != "ok":
            print("  [%s] %s %s q=%s -> %s %s" % (row["pid"], row["kind"], row["http_status"], row["query_id"], row["outcome"], row["error"]), flush=True)

    print("load_sim: %d participants -> %s exp=%s think=%s retries=%d tag=%s" % (
        args.participants, args.base, args.exp, args.think, args.retries, args.tag), flush=True)
    t_start = time.time()
    threads = []
    for i in range(args.participants):
        pid = "%s%s%02d" % (args.pid_prefix, args.tag, i)
        p = Participant(i, pid, args, stats, log)
        threads.append(p); p.start()
        time.sleep(args.stagger)
    try:
        last = 0
        while any(t.is_alive() for t in threads):
            time.sleep(5)
            if not args.quiet and time.time() - last > 30:
                last = time.time()
                alive = sum(t.is_alive() for t in threads)
                print("  ... %ds elapsed, %d alive, in_flight=%d, done=%d expelled=%d technical=%d" % (
                    time.time() - t_start, alive, stats.in_flight, stats.completed, stats.expelled, stats.technical), flush=True)
    except KeyboardInterrupt:
        print("interrupted", flush=True)
    f.close()
    dur = time.time() - t_start
    print("\n=== load_sim summary (%s) ===" % args.tag)
    print("duration %.0fs  participants %d  requests %d  peak_in_flight %d" % (dur, args.participants, len(stats.rows), stats.peak_in_flight))
    for kind in ("getQuery", "processAnswer"):
        xs = stats.latencies.get(kind, [])
        if xs:
            print("%-14s n=%-5d p50=%5dms p95=%5dms p99=%5dms max=%5dms" % (kind, len(xs), pct(xs, 50), pct(xs, 95), pct(xs, 99), max(xs)))
    print("http statuses:", dict(sorted(stats.statuses.items(), key=lambda kv: str(kv[0]))))
    print("outcomes:     ", dict(stats.outcomes))
    finals = Counter(t.final for t in threads)
    print("participants: ", dict(finals))
    n5xx = sum(v for k, v in stats.statuses.items() if isinstance(k, int) and 500 <= k < 600)
    print("5xx total: %d   technical exits: %d   expelled: %d   completed: %d" % (n5xx, stats.technical, stats.expelled, stats.completed))
    print("csv:", csv_path)

if __name__ == "__main__":
    main()
