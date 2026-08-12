#!/usr/bin/env python3
"""Threaded Selenium load test for the ARankB query page (prolific-id flow).

Simulates N participants answering simultaneously, each in its own headless
Chrome session and thread: enter the (pre-filled) Prolific ID, answer normal
queries by ranking all option cards, answer trap questions via the flexible
rule (move one card; wrong-trap drivers pick a wrong card), and record the
participant-experienced latency from pressing Submit to the next query being
on screen.

Browser runtime (disposable, NOT part of the NEXT compose stack):

    docker run -d --name selenium-load --shm-size=2g -p 4444:4444 \
        -e SE_NODE_MAX_SESSIONS=32 -e SE_NODE_OVERRIDE_MAX_SESSIONS=true \
        selenium/standalone-chrome
    # ... run the test ...
    docker rm -f selenium-load

Usage:

    ./local-venv/bin/python stress_test.py EXP_UID \
        [--drivers=30] [--wrong-trap-drivers=2] [--min-wait=10] [--max-wait=20] \
        [--base=http://172.17.0.1] [--grid=http://127.0.0.1:4444/wd/hub] \
        [--max-queries=200] [--tag=run1]

Note --base must be reachable FROM INSIDE the selenium container: use the
docker bridge address (default 172.17.0.1) or the instance's Elastic IP, not
127.0.0.1. Participant IDs are alphanumeric (the ID modal enforces
/^[A-Za-z0-9]+$/): <tag>d00, <tag>d01, ...

Output: per-answer CSV (stress_<tag>_latencies.csv) and a summary with p50/p95
latency per driver group. Failures are recorded, never "fixed" mid-run.
"""
import csv
import statistics
import sys
import threading
import time
from random import shuffle, uniform

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

args = [a for a in sys.argv[1:] if not a.startswith('--')]
opts = dict(o.lstrip('-').split('=', 1)
            for o in sys.argv[1:] if o.startswith('--') and '=' in o)
if not args:
    sys.exit(__doc__)
EXP_UID = args[0]
N_DRIVERS = int(opts.get('drivers', 30))
WRONG_TRAP_DRIVERS = int(opts.get('wrong-trap-drivers', 2))
MIN_WAIT = float(opts.get('min-wait', 10))
MAX_WAIT = float(opts.get('max-wait', 20))
BASE = opts.get('base', 'http://172.17.0.1')
GRID = opts.get('grid', 'http://127.0.0.1:4444/wd/hub')
MAX_QUERIES = int(opts.get('max-queries', 200))
TAG = opts.get('tag', 'run')

QUERY_URL = BASE + '/query/query_page/query_page/' + EXP_UID
QUERY_READY_TIMEOUT = 120   # generous: worst case is an inline InfoTuple compute under load
results = []                # rows: driver, query_num, is_trap, latency_s, outcome
results_lock = threading.Lock()
events = []                 # driver-level lifecycle notes
events_lock = threading.Lock()


def note(driver_id, msg):
    line = '[%s] driver %s: %s' % (time.strftime('%H:%M:%S'), driver_id, msg)
    print(line, flush=True)
    with events_lock:
        events.append(line)


def make_driver():
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.set_capability('unhandledPromptBehavior', 'dismiss')
    return webdriver.Remote(command_executor=GRID, options=chrome_options)


def debrief_shown(driver):
    try:
        el = driver.find_element(By.ID, 'debrief')
        return el.is_displayed()
    except Exception:
        return False


def query_signature(driver):
    """Progress text ('3 / 32') identifies the current query; '' if absent."""
    try:
        return driver.find_element(By.ID, 'progress-text').text.strip()
    except Exception:
        return ''


def wait_for_query_or_debrief(driver, old_signature, timeout=QUERY_READY_TIMEOUT):
    """Return 'query' when a new query is rendered, 'debrief' when the end/fail
    modal is up. A new query means the progress text changed from
    old_signature and option cards are present."""
    def ready(d):
        if debrief_shown(d):
            return 'debrief'
        sig = query_signature(d)
        if sig and sig != old_signature and \
                len(d.find_elements(By.CSS_SELECTOR, '#targets-container .target-container')) > 0:
            return 'query'
        return False
    return WebDriverWait(driver, timeout, poll_frequency=0.2).until(ready)


def answer_current_query(driver, driver_id, wrong_traps):
    """Click cards for the current query. Returns ('trap'|'normal', n_cards)."""
    is_trap = len(driver.find_elements(By.ID, 'target-trap')) > 0
    cards = driver.find_elements(By.CSS_SELECTOR, '#targets-container .target-container')
    if is_trap:
        correct = driver.execute_script(
            "var c=document.querySelector('#targets-container .target-container');"
            "return c ? c.getAttribute('data-correct-answer') : '';") or ''
        correct = correct.strip()
        chosen = None
        for card in cards:
            text = card.find_element(By.CSS_SELECTOR, '.target-text').text.strip()
            if (text == correct) != wrong_traps:
                chosen = card
                break
        if chosen is None:  # wrong_traps but only the correct card left, or vice versa
            chosen = cards[0]
        driver.execute_script('arguments[0].click();', chosen)
        return 'trap', 1
    # normal query: rank every card, random order (widget requires exactly B)
    shuffle(cards)
    for card in cards:
        driver.execute_script('arguments[0].click();', card)
        time.sleep(uniform(0.05, 0.2))
    return 'normal', len(cards)


def run_participant(idx):
    driver_id = '%sd%02d' % (TAG, idx)
    wrong_traps = idx < WRONG_TRAP_DRIVERS
    driver = None
    try:
        driver = make_driver()
        driver.set_page_load_timeout(60)
        driver.get(QUERY_URL + '?participant=' + driver_id)
        WebDriverWait(driver, 30).until(
            lambda d: d.find_element(By.ID, 'prolific_start_btn').is_displayed())
        driver.execute_script("document.getElementById('prolific_start_btn').click();")
        note(driver_id, 'started (wrong_traps=%s)' % wrong_traps)

        outcome = 'incomplete'
        state = wait_for_query_or_debrief(driver, '', timeout=QUERY_READY_TIMEOUT)
        for q in range(1, MAX_QUERIES + 1):
            if state == 'debrief':
                text = ''
                try:
                    text = driver.find_element(By.ID, 'debrief_text').text.strip()
                except Exception:
                    pass
                outcome = 'debrief:' + text[:40]
                break
            sig = query_signature(driver)
            time.sleep(uniform(MIN_WAIT, MAX_WAIT))          # think time
            kind, _ = answer_current_query(driver, driver_id, wrong_traps)
            t0 = time.time()
            driver.execute_script("document.getElementById('submit').click();")
            try:
                state = wait_for_query_or_debrief(driver, sig)
                latency = time.time() - t0
                with results_lock:
                    results.append((driver_id, q, kind, round(latency, 3), state))
            except TimeoutException:
                note(driver_id, 'TIMEOUT waiting after query %d (sig=%s)' % (q, sig))
                outcome = 'timeout_q%d' % q
                break
        note(driver_id, 'finished: %s' % outcome)
    except Exception as e:
        note(driver_id, 'ERROR: %r' % e)
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


def main():
    print('Load test: %d drivers (%d answering traps wrongly) against %s' %
          (N_DRIVERS, WRONG_TRAP_DRIVERS, QUERY_URL), flush=True)
    threads = []
    for i in range(N_DRIVERS):
        t = threading.Thread(target=run_participant, args=(i,), daemon=True)
        t.start()
        threads.append(t)
        time.sleep(1.0)      # stagger session creation
    for t in threads:
        t.join()

    out = 'stress_%s_latencies.csv' % TAG
    with open(out, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['driver', 'query_num', 'kind', 'latency_s', 'next_state'])
        w.writerows(sorted(results))
    lat = [r[3] for r in results]
    print('\n=== %d answers recorded -> %s ===' % (len(lat), out), flush=True)
    if lat:
        lat_sorted = sorted(lat)
        p = lambda q: lat_sorted[min(len(lat_sorted) - 1, int(q * len(lat_sorted)))]
        print('submit->next-query latency: p50=%.2fs p95=%.2fs max=%.2fs mean=%.2fs' %
              (p(0.50), p(0.95), lat_sorted[-1], statistics.mean(lat)), flush=True)
    with open('stress_%s_events.log' % TAG, 'w') as f:
        f.write('\n'.join(events) + '\n')


if __name__ == '__main__':
    main()
