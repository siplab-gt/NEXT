#!/usr/bin/env python3
"""
test_query_page_retry.py — browser-level tests for the query page's server-error
handling (retry banner, recovery, technical-problem exit, genuine expulsion, resume).

Needs the disposable Selenium grid (see stress_test.py) and a throwaway experiment:

    docker run -d --name selenium-load --shm-size=2g -p 4444:4444 selenium/standalone-chrome
    ./local-venv/bin/python test_query_page_retry.py EXP_UID [--base=http://172.17.0.1:8000] [--only=A,B]

Scenarios (each prints PASS/FAIL):
  A  normal flow: two queries answered, progress advances, no JS errors
  B  transient failure + recovery: worker paused while an answer is submitted ->
     retry banner -> worker unpaused -> next query rendered; export has no duplicates
  C  retries exhausted: worker paused throughout -> "Technical problem" modal with
     debrief_link_error; after unpausing, a refresh resumes at the same query
  D  genuine expulsion: every trap answered wrong -> the attention-check fail exit
     (debrief modal with debrief_link_fail), not the technical one
  E  refresh mid-query resumes at the same query
The worker is paused/unpaused with `docker pause/unpause local_minionworker_1`.
"""
import json, subprocess, sys, time
from random import shuffle, uniform
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

args = [a for a in sys.argv[1:] if not a.startswith('--')]
opts = dict(a[2:].split('=', 1) for a in sys.argv[1:] if a.startswith('--') and '=' in a)
if not args:
    sys.exit(__doc__)
EXP = args[0]
BASE = opts.get('base', 'http://172.17.0.1:8000')        # as seen from the grid container
API = opts.get('api', 'http://127.0.0.1:8000')            # as seen from this host
GRID = opts.get('grid', 'http://127.0.0.1:4444/wd/hub')
ONLY = opts.get('only', 'A,B,C,D,E').split(',')
WORKER = 'local_minionworker_1'
URL = BASE + '/query/query_page/query_page/' + EXP
RESULTS = {}

def docker(*cmd):
    subprocess.run(['docker'] + list(cmd), check=True, capture_output=True)

def make_driver():
    o = Options()
    o.add_argument('--headless'); o.add_argument('--no-sandbox'); o.add_argument('--disable-dev-shm-usage')
    o.set_capability('goog:loggingPrefs', {'browser': 'ALL'})
    d = webdriver.Remote(command_executor=GRID, options=o)
    d.set_page_load_timeout(60)
    return d

def js_errors(d):
    return [e['message'] for e in d.get_log('browser') if e['level'] == 'SEVERE' and 'favicon' not in e['message']]

def start(d, pid):
    d.get(URL + '?participant=' + pid)
    WebDriverWait(d, 30).until(lambda x: x.find_element(By.ID, 'prolific_start_btn').is_displayed())
    d.execute_script("document.getElementById('prolific_start_btn').click();")

def progress(d):
    try: return d.find_element(By.ID, 'progress-text').text.strip()
    except Exception: return ''

def shown(d, el_id):
    try: return d.find_element(By.ID, el_id).is_displayed()
    except Exception: return False

def wait_query(d, old_sig, timeout=120):
    def ready(x):
        if shown(x, 'debrief'): return 'debrief'
        if shown(x, 'technical_modal'): return 'technical'
        sig = progress(x)
        if sig and sig != old_sig and x.find_elements(By.CSS_SELECTOR, '#targets-container .target-container'):
            return 'query'
        return False
    return WebDriverWait(d, timeout, poll_frequency=0.3).until(ready)

def answer(d, wrong_traps=False):
    is_trap = len(d.find_elements(By.ID, 'target-trap')) > 0
    cards = d.find_elements(By.CSS_SELECTOR, '#targets-container .target-container')
    if is_trap:
        correct = (d.execute_script("var c=document.querySelector('#targets-container .target-container');return c?c.getAttribute('data-correct-answer'):'';") or '').strip()
        chosen = None
        for c in cards:
            if (c.find_element(By.CSS_SELECTOR, '.target-text').text.strip() == correct) != wrong_traps:
                chosen = c; break
        d.execute_script('arguments[0].click();', chosen or cards[0])
    else:
        shuffle(cards)
        for c in cards:
            d.execute_script('arguments[0].click();', c); time.sleep(uniform(0.05, 0.15))
    d.execute_script("document.getElementById('submit').click();")
    return 'trap' if is_trap else 'normal'

def export_rows(pid):
    r = requests.get(API + '/api/experiment/' + EXP + '/participants', timeout=60).json()
    full = EXP + '_' + pid
    return r.get('participant_responses', {}).get(full, [])

def answered_ids(pid):
    return sorted(q['query_id'] for q in export_rows(pid) if 'target_winner' in q)

def report(name, ok, detail=''):
    RESULTS[name] = ok
    print('%s %s %s' % ('PASS' if ok else 'FAIL', name, detail), flush=True)

# ---------------------------------------------------------------- scenarios
def scenario_A():
    d = make_driver()
    try:
        pid = 'rtA%d' % int(time.time())
        start(d, pid); wait_query(d, '')
        p0 = progress(d); answer(d); wait_query(d, p0); p1 = progress(d); answer(d); wait_query(d, p1); p2 = progress(d)
        errs = js_errors(d)
        report('A normal flow', p0 != p1 != p2 and not errs, 'progress %s -> %s -> %s; js errors: %s' % (p0, p1, p2, errs))
    finally:
        d.quit()

def scenario_B():
    d = make_driver()
    try:
        pid = 'rtB%d' % int(time.time())
        start(d, pid); wait_query(d, '')
        p0 = progress(d); answer(d); wait_query(d, p0)          # one real answer first
        d.execute_script('next_widget.setOptions({timeout: 20000});')  # must exceed one query's compute time (~8 s here)
        docker('pause', WORKER)
        try:
            sig = progress(d); answer(d)                            # submit while the worker is frozen
            banner = WebDriverWait(d, 30).until(lambda x: 'Connection problem' in x.find_element(By.ID, 'wrapper').text)
            att = d.execute_script('return retry.attempt;')
            time.sleep(6)                                           # let the first retry also fail
        finally:
            docker('unpause', WORKER)
        state = wait_query(d, sig, timeout=180)                     # recovery: the retry getQuery succeeds
        time.sleep(3)
        ids = answered_ids(pid)
        contiguous = ids == list(range(1, len(ids) + 1))
        report('B transient failure + recovery', banner and att >= 1 and state == 'query' and contiguous,
               'banner=%s attempt=%s state=%s answered=%s js errors=%s' % (banner, att, state, ids, js_errors(d)))
    finally:
        d.quit()

def scenario_C():
    d = make_driver()
    try:
        pid = 'rtC%d' % int(time.time())
        start(d, pid); wait_query(d, '')
        p0 = progress(d); answer(d); wait_query(d, p0); p1 = progress(d)
        d.execute_script('next_widget.setOptions({timeout: 4000}); retry.max = 2; retry.delaysMs = [3000, 3000];')
        docker('pause', WORKER)
        try:
            answer(d)
            WebDriverWait(d, 90).until(lambda x: shown(x, 'technical_modal'))
            href = d.find_element(By.ID, 'technical_link').get_attribute('href')
            text = d.find_element(By.ID, 'technical_text').text
            fail_shown = shown(d, 'debrief')
        finally:
            docker('unpause', WORKER)
        time.sleep(5)
        # resume: reload the page, same participant -> same query count continues
        start(d, pid); wait_query(d, '')
        p_after = progress(d)
        report('C retries exhausted -> technical exit, then resume',
               'TECH123' in href and 'technical problem' in text.lower() and not fail_shown and p_after != '',
               'href=%s fail_modal=%s progress before=%s after=%s' % (href, fail_shown, p1, p_after))
    finally:
        d.quit()

def scenario_D():
    d = make_driver()
    try:
        pid = 'rtD%d' % int(time.time())
        start(d, pid); state = wait_query(d, ''); n = 0
        while state == 'query' and n < 40:
            sig = progress(d); answer(d, wrong_traps=True); n += 1
            state = wait_query(d, sig, timeout=150)
        link = d.find_element(By.ID, 'debrief_link').get_attribute('href') if state == 'debrief' else ''
        text = d.find_element(By.ID, 'debrief_text').text if state == 'debrief' else ''
        report('D genuine expulsion -> fail exit', state == 'debrief' and 'YOUR_FAILURE_CODE' in link and 'attention' in text.lower(),
               'state=%s after %d answers; link=%s; text=%s' % (state, n, link, text[:60]))
    finally:
        d.quit()

def scenario_E():
    d = make_driver()
    try:
        pid = 'rtE%d' % int(time.time())
        start(d, pid); wait_query(d, ''); p0 = progress(d); answer(d); wait_query(d, p0); p1 = progress(d)
        start(d, pid); wait_query(d, ''); p2 = progress(d)
        report('E refresh mid-query resumes', p1 == p2, 'before refresh %s, after %s' % (p1, p2))
    finally:
        d.quit()

for s in ONLY:
    try:
        globals()['scenario_' + s.strip()]()
    except Exception as e:
        report(s, False, 'exception: %r' % e)
        subprocess.run(['docker', 'unpause', WORKER], capture_output=True)
print('\nSUMMARY:', ', '.join('%s=%s' % (k.split()[0], 'PASS' if v else 'FAIL') for k, v in RESULTS.items()))
sys.exit(0 if all(RESULTS.values()) else 1)
