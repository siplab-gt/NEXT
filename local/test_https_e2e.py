#!/usr/bin/env python3
"""
test_https_e2e.py — real Chrome against the live domain: HTTPS, short links,
per-experiment protocol, images over HTTPS (HTTPS_PLAN.md, "Test plan").

Needs the disposable Selenium grid (host-only port) and two throwaway experiments:
    docker run -d --name selenium-https --shm-size=2g -p 127.0.0.1:4444:4444 selenium/standalone-chrome
    #  A: protocol: https, link_name: <name>, some targets '/media/cats/catNN.png' (primary_type image)
    #  B: protocol: http,  link_name: <name>
    ./local-venv/bin/python test_https_e2e.py --https-link=demo-img --http-link=demo-http
    docker rm -f selenium-https

  1  https experiment, entered as http://<IP>/s/<name>?participant=..  -> lands on
     https://<host>/query/...?participant=.. , jQuery loaded, ID pre-filled, full run to
     the success debrief, every image on every question loaded, no browser errors,
     export has query ids 1..N exactly once
  2  http experiment opened over https://<host>/s/<name> -> served over HTTPS (no
     downgrade), 3 questions answered, no browser errors
"""
import sys, time
from random import shuffle, uniform
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

opts = dict(a[2:].split('=', 1) for a in sys.argv[1:] if a.startswith('--') and '=' in a)
HOST = opts.get('host', 'siplab-next.xyz')
IP = opts.get('ip', '52.2.236.217')
HTTPS_LINK = opts.get('https-link', 'demo-img')
HTTP_LINK = opts.get('http-link', 'demo-http')
GRID = opts.get('grid', 'http://127.0.0.1:4444/wd/hub')
API = opts.get('api', 'http://127.0.0.1:8000')     # backend directly, from this host
TAG = time.strftime('%H%M%S')
RESULTS = {}


def report(name, ok, detail=''):
    RESULTS[name] = ok
    print('%s %s %s' % ('PASS' if ok else 'FAIL', name, detail), flush=True)


def make_driver():
    o = Options()
    o.add_argument('--headless'); o.add_argument('--no-sandbox'); o.add_argument('--disable-dev-shm-usage')
    o.add_argument('--window-size=1280,900')
    o.set_capability('goog:loggingPrefs', {'browser': 'ALL'})
    d = webdriver.Remote(command_executor=GRID, options=o)
    d.set_page_load_timeout(60)
    return d


def browser_errors(d):
    return [e['message'] for e in d.get_log('browser') if e['level'] == 'SEVERE']


def shown(d, el_id):
    try: return d.find_element(By.ID, el_id).is_displayed()
    except Exception: return False


def progress(d):
    try: return d.find_element(By.ID, 'progress-text').text.strip()
    except Exception: return ''


def wait_query(d, old_sig, timeout=120):
    def ready(x):
        if shown(x, 'debrief'): return 'debrief'
        if shown(x, 'technical_modal'): return 'technical'
        sig = progress(x)
        if sig and sig != old_sig and x.find_elements(By.CSS_SELECTOR, '#targets-container .target-container'):
            return 'query'
        return False
    return WebDriverWait(d, timeout, poll_frequency=0.3).until(ready)


def images_state(d):
    """(#images on the page, #not loaded) - waits briefly for loading."""
    js = ("var im=[].slice.call(document.querySelectorAll('img'));"
          "return [im.length, im.filter(function(i){return !(i.complete && i.naturalWidth>0);}).length];")
    end = time.time() + 10
    n, bad = d.execute_script(js)
    while bad and time.time() < end:
        time.sleep(0.3); n, bad = d.execute_script(js)
    return n, bad


def answer(d):
    is_trap = len(d.find_elements(By.ID, 'target-trap')) > 0
    cards = d.find_elements(By.CSS_SELECTOR, '#targets-container .target-container')
    if is_trap:
        correct = (d.execute_script("var c=document.querySelector('#targets-container .target-container');"
                                    "return c?c.getAttribute('data-correct-answer'):'';") or '').strip()
        chosen = next((c for c in cards if c.find_element(By.CSS_SELECTOR, '.target-text').text.strip() == correct), cards[0])
        d.execute_script('arguments[0].click();', chosen)
    else:
        shuffle(cards)
        for c in cards:
            d.execute_script('arguments[0].click();', c); time.sleep(uniform(0.05, 0.15))
    d.execute_script("document.getElementById('submit').click();")


def start(d, url):
    d.get(url)
    WebDriverWait(d, 30).until(lambda x: x.find_element(By.ID, 'prolific_start_btn').is_displayed())
    d.execute_script("document.getElementById('prolific_start_btn').click();")


def exp_of_link(name):
    r = requests.get('https://%s/s/%s' % (HOST, name), allow_redirects=False, timeout=20)
    return r.headers['Location'].split('?')[0].rstrip('/').split('/')[-1]


def scenario_1():
    pid = 'E2EHTTPS' + TAG
    d = make_driver()
    try:
        start(d, 'http://%s/s/%s?participant=%s' % (IP, HTTPS_LINK, pid))
        url = d.current_url
        report('1a lands on https host, ID kept',
               url.startswith('https://%s/query/query_page/query_page/' % HOST) and ('participant=' + pid) in url, url)
        report('1b jQuery loaded (no mixed-content block)', d.execute_script('return typeof jQuery') == 'function')
        sig, n_q, img_total, img_bad, state = '', 0, 0, 0, None
        while True:
            state = wait_query(d, sig)
            if state != 'query':
                break
            n, bad = images_state(d)
            img_total += n; img_bad += bad
            sig = progress(d); answer(d); n_q += 1
        report('1c full run ends on the success debrief', state == 'debrief', '%d questions' % n_q)
        report('1d every image loaded over https', img_total > 0 and img_bad == 0,
               '%d images shown, %d failed' % (img_total, img_bad))
        errs = browser_errors(d)
        report('1e no browser errors', not errs, '; '.join(errs)[:300])
        exp = exp_of_link(HTTPS_LINK)
        rows = requests.get(API + '/api/experiment/%s/participants' % exp, timeout=60).json()
        ids = sorted(q['query_id'] for q in rows.get('participant_responses', {}).get(exp + '_' + pid, [])
                     if 'target_winner' in q)
        report('1f export: every question exactly once', ids == list(range(1, n_q + 1)), 'ids 1..%d' % (ids[-1] if ids else 0))
    finally:
        d.quit()


def scenario_2():
    pid = 'E2EHTTP' + TAG
    d = make_driver()
    try:
        start(d, 'https://%s/s/%s?participant=%s' % (HOST, HTTP_LINK, pid))
        url = d.current_url
        report('2a http experiment over https: no downgrade', url.startswith('https://%s/' % HOST), url)
        sig = ''
        for _ in range(3):
            if wait_query(d, sig) != 'query':
                break
            sig = progress(d); answer(d)
        report('2b answers accepted', wait_query(d, sig) in ('query', 'debrief'))
        errs = browser_errors(d)
        report('2c no browser errors', not errs, '; '.join(errs)[:300])
    finally:
        d.quit()


scenario_1()
scenario_2()
bad = [k for k, v in RESULTS.items() if not v]
print('RESULT:', 'all passed' if not bad else 'FAILED: ' + ', '.join(bad))
sys.exit(1 if bad else 0)
