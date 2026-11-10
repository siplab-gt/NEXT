# Serving the query page over HTTPS — plan

Status: **implemented and live on 2026-11-10** (branch `feature/https-impl`), domain
**`siplab-next.xyz`** (written `<domain>` below). User guide: README §3.6. What was built,
how it differs from this plan, and the test results: "Implementation" at the end.
2026-11-02: first plan. 2026-11-10: admin password, closed ports, short links added; built.

## Where things stand today

- All participant traffic enters through the `reverse_proxy` nginx container, which
  listens on **port 80 only** (`local/nginx.conf`, `local/docker-compose.yml.pre`).
  Nothing serves port 443.
- The production query page (`next/query_page/templates/query_page.html`) calls
  `next_widget.setUrl("")`, so `getQuery` / `processAnswer` use **relative URLs** and
  will follow the page onto HTTPS with no code change.
- **One blocker:** the page loads jQuery from `http://code.jquery.com/...` (line 8).
  On an HTTPS page browsers block that script ("mixed content") and the query page
  stops working. Same line in `query_page_popup.html` and `queries_unlimited.html`.
  (`queries_unlimited.html` and `captioncontest.html` also build `http://<host>:8000`
  API URLs; production doesn't use them — fix only if someone does.)
- **The dashboard and the data downloads have no password.** `SITE_KEY` is unset and
  nginx has no access control, so anyone who finds the address can list experiments,
  download participant data (incl. Prolific IDs), retire experiments, or create new
  ones. This is already true on the bare IP; a domain makes it urgent, because
  issuing a certificate publishes the name in public Certificate Transparency logs,
  which scanners watch.
- **Internal services are published on all interfaces** (`0.0.0.0` in
  `docker-compose.yml.pre`): backend 8000, MongoDB 27017/28017, RabbitMQ 5672/15672,
  Redis 6379, cAdvisor 8888. Port 8000 is the Flask app itself, so a password in
  nginx can be bypassed on `:8000` unless that port is closed. Whether the AWS
  security group already blocks these is unknown — check it (step 2).

## Hostname

The lab has a domain. One name serves every study on this server: studies are
separated by the experiment ID in the path (or by a short link name, see below),
the query page keeps no cookies or browser storage, and exported participant IDs are
prefixed with the experiment ID — so concurrent studies on one domain do not interact.
Subdomain-per-study is not needed (it would need a wildcard certificate via the
registrar's DNS API, or a re-issued certificate per study, for no gain). A second
server, if there ever is one, gets its own subdomain (e.g. `next2.<domain>`).

What all studies on the server *do* share is CPU: the measured capacity
(`CAPACITY_REPORT.md`) is for the total number of simultaneous participants across
every live study.

Keep any registrar token in a gitignored local file, never in the repo (the repo is
public).

## Steps

Order matters: the admin password (step 6) goes live together with HTTPS, before the
domain is given to anyone.

1. **DNS** — A record `<domain>` → 52.2.236.217 (Elastic IP, stable, no dynamic
   update needed). Confirm with `dig +short <domain>`.
2. **Security group** (AWS console; the AWS CLI is not installed on the instance) —
   inbound should be exactly: TCP 80 and 443 from anywhere, TCP 22 (ideally only from
   the lab's / your IPs). Remove any rule for 8000, 8888, 27017, 28017, 5672, 15672,
   6379. Screenshot the before/after for the record.
3. **Fix mixed content** — `http://code.jquery.com` → `https://code.jquery.com` in the
   three query-page templates. Works on plain HTTP too, so it can ship first; live
   after `docker restart local_nextbackenddocker_1`.
4. **Certificate** — install certbot on the host; webroot method: nginx serves
   `/.well-known/acme-challenge/` from a host folder on port 80.
5. **nginx + compose for HTTPS** (applied together with step 6, one nginx recreate):
   - `local/nginx.conf`: new `server { listen 443 ssl; http2 on; server_name <domain>; ... }`
     with the certificate and the same `location` blocks as today (incl. the 330 s
     timeouts) — move the shared proxy settings into an `include` snippet so the two
     server blocks can't drift. Port 80 keeps serving participant pages as today,
     plus the ACME location. **No global HTTP→HTTPS redirect and no HSTS header** —
     the choice is made per experiment (step 10).
   - `local/docker-compose.yml.pre`: publish `443:443`; mount `/etc/letsencrypt`
     (read-only), the ACME webroot, and the password file (step 6) into nginx.
   - Apply: `docker rm -f reverse_proxy`, then `docker-compose up -d nginx`
     (stateless container; a few seconds of downtime). The user runs compose.
6. **Admin password + close direct ports** — see "Admin password" below.
7. **Renewal** — certbot's systemd timer renews automatically; add a deploy hook
   `docker exec reverse_proxy nginx -s reload`.
8. **Media paths (rule for all future configs)** — image/video/audio targets are
   **relative paths** to files in `local/media/`, e.g.
   `primary_description: '/media/cats/cat01.png'`, never `http://<ip>/...`.
   The example comment in every `local/*.yaml` still shows
   `http://44.223.248.38/media/video01.mp4` (an old IP) — change it to the relative
   form, document the rule in README, and change `next/assistant/s3.py` to build
   `https://` URLs. Details in "Images, video and audio" below.
9. **Short study links** — see "Short study links" below.
10. **Per-experiment `protocol` setting** — see "Choosing HTTP or HTTPS per experiment".
11. **Links, docs, test** — Prolific study URL, Qualtrics end-of-survey redirect,
    CLAUDE.md URLs (dashboard links become `https://<domain>/dashboard/...`), README.
    Then the test list at the end, a manual click-through and a short load test.

## Admin password

Goal: participants reach the study with no login; everything else needs a password.

**Mechanism: nginx HTTP basic auth, allow-list style.** Every path requires the
password *except* the few a participant needs. New endpoints added later are
protected by default.

Open (no password) — exactly what the query page uses:

| Path | Why |
|---|---|
| `/query/` | the query page and its JS (`/query/static/...`) |
| `= /api/experiment/getQuery` | next question (POST from `next_widget.js`) |
| `= /api/experiment/processAnswer` | submit answer (POST) |
| `/s/` | short study links |
| `/media/` | study images / video / audio |
| `/.well-known/acme-challenge/` | certificate renewal |

Password-protected — everything else, notably `/dashboard/...` (experiment list,
dashboards, stats, retire, database backup/restore), `/api/experiment/<uid>/participants`
(data download), `/api/experiment/<uid>/logs`, `/api/experiment` (GET/POST),
`/assistant/...` (creating experiments), `/home`, `/cadvisor/`.

Details:
- **Password file:** `local/admin.htpasswd`, gitignored, mounted read-only into nginx.
  One line per person (`openssl passwd -6` hash), so access can be removed per person
  by deleting a line and reloading nginx (`nginx -s reload`, no restart).
- **Only over HTTPS.** Basic auth sends the password with every request, so on port 80
  the protected paths **redirect to `https://<domain>/...`** instead of asking for it.
  This redirect is per-path (admin paths only); participant paths on port 80 are
  untouched, so `http` experiments keep working.
- **Close the bypass on port 8000 — without touching MongoDB.**
  - Security group (step 2) is the main control.
  - Second layer: bind the **stateless** containers' ports to localhost in
    `docker-compose.yml.pre` — backend `127.0.0.1:8000:8000`, cAdvisor
    `127.0.0.1:8888:8080`. They are recreated on every deploy anyway.
  - **Do not change the ports of `local_mongodb_1`** (or RabbitMQ/Redis) now:
    changing them means recreating the container, and the compose recreate bug's
    workaround (`docker rm`) is forbidden for MongoDB because it orphans the data
    volume. Instead add host firewall rules in the `DOCKER-USER` iptables chain that
    drop outside traffic to 27017, 28017, 5672, 15672, 6379 (Docker bypasses ufw;
    `DOCKER-USER` is the supported place), persisted with `iptables-persistent`.
    Rebinding MongoDB to localhost can wait for a planned migration with a fresh backup.
  - Anything that used those ports from outside (e.g. MongoDB Compass on a laptop)
    switches to an SSH tunnel: `ssh -L 27017:127.0.0.1:27017 ubuntu@<domain>`.
- **Things that call protected paths and need updating:**
  - `local/healthcheck.sh` probes `http://127.0.0.1/dashboard/get_stats` → give it its
    own `healthcheck` user, credentials in the gitignored `local/alert.local.conf`
    (`HEALTH_AUTH=user:pass`), passed with `curl -u`, and probe over HTTPS
    (`--resolve <domain>:443:127.0.0.1`). Without this it alerts every 5 minutes.
  - `launch.py` talks to `localhost:8000` directly — still works after the localhost
    binding. Change the URLs it *prints* to `https://<domain>/dashboard/...`.
  - Data exports by script: `curl -u <user> 'https://<domain>/api/experiment/<EXP_UID>/participants?csv=1&zip=1'`.
- `SITE_KEY` stays unset: it only hides the dashboard under a secret path, which leaks
  through browser history and links. The password is the control.

## Short study links

Goal: `https://<domain>/s/rank4` instead of
`https://<domain>/query/query_page/query_page/8674955c...`.

- **YAML:** optional `args.link_name: rank4` (lowercase letters, digits, `-`; declared
  in `apps/ARankB/myApp.yaml` like `precompute`, so a malformed name is rejected at
  launch). Experiments without it keep only the long link.
- **Storage:** a small MongoDB collection `short_links` (`name → exp_uid`, created
  date) rather than searching every experiment's args — so a name can be moved
  explicitly without editing an experiment.
- **One name, one experiment.** At launch, if the name already points to another
  experiment, the launch **fails** with "rank4 already points to <uid> (launched
  <date>)". A relaunch must never silently move a link a live Prolific study is
  using. To move it on purpose (e.g. relaunch after a bug, before publishing the
  Prolific study): a small host script, `./local-venv/bin/python relink.py rank4 <new_uid>`,
  which prints the old and new target.
- **Route:** Flask `/s/<name>` → `302` redirect to the full query-page URL, **keeping
  the query string** so `?participant=<PROLIFIC_ID>` survives. It honours the
  experiment's `protocol` (an `https` experiment reached over HTTP is sent straight to
  `https://<domain>/query/...` in one hop). `302`, not `301`, so browsers don't cache
  a link that may be moved. Unknown name → a plain "study not found" page.
- **Shown where you need it:** `launch.py` and the experiment dashboard print the short
  link next to the long one.
- **Caveat:** short names are guessable, so a stranger could open a study. Today that
  is prevented only by the long random ID. In practice data is already filtered to
  Prolific's approved participants; pick names that aren't obvious if this matters
  (e.g. `rank4-k7q`).

## Choosing HTTP or HTTPS per experiment

Requirement: each experiment's YAML decides whether participants use HTTP or HTTPS,
because some studies may need one or the other, and the server may have only one
HTTPS hostname (or none, e.g. on a second machine).

**Idea:** nginx serves both ports all the time; the query page enforces the choice.

- **YAML:** new key `args.protocol: http | https`, default `http` — experiments
  launched before this change (no key) keep working exactly as today. Declared in
  `apps/ARankB/myApp.yaml` (same pattern as `precompute`) so a typo is rejected at
  launch.
- **Server setting, not YAML:** the HTTPS hostname belongs to the server, so it is
  one env var, `NEXT_HTTPS_HOST=<domain>`, set by `docker_up.sh` next to
  `NEXT_BACKEND_GLOBAL_HOST`. Every `https` experiment on this server shares it.
- **Query page** (`next/query_page/query_page.py`): reads `experiment['args']['protocol']`
  and the scheme the visitor came in on (`X-Forwarded-Proto`, already set by nginx).
  - `https` experiment visited over HTTP → redirect to
    `https://$NEXT_HTTPS_HOST/query/...` keeping the query string (so
    `?participant=<PROLIFIC_ID>` survives).
  - `http` experiment visited over HTTPS → **served as-is, no downgrade redirect.**
    Browsers (Chrome's automatic HTTPS upgrade) would fight a redirect to HTTP and
    can loop; serving it is harmless. In practice "http" means "HTTP allowed".
  - API calls and media are relative, so they follow whatever scheme the page is on.
- **Launch check:** `launch.py` refuses `protocol: https` when the server has no
  `NEXT_HTTPS_HOST` (or its certificate is missing/expired), instead of handing out
  a link that won't work.
- **Links:** `launch.py` and the experiment dashboard print the participant link with
  the right scheme and host (and the short link, if any), so the link pasted into
  Prolific/Qualtrics is always the correct one.
- **Never enable HSTS** on the domain: it would make browsers refuse HTTP on that name
  for months, breaking `http` experiments linked through it.

## Images, video and audio (planned for future studies)

HTTPS does **not** get in the way of media, as long as the media URLs are not
`http://`. The ARankB widget (`apps/ARankB/widgets/getQuery_widget.html`) puts each
target's `primary_description` straight into `<img src>`, `<video><source src>` or
`<audio><source src>`, so whatever URL is in the YAML is what the browser loads.

- **Recommended: host media on this server, use relative URLs.** Put files in
  `local/media/` (already served by nginx at `/media/`, e.g. `local/media/cats/`)
  and write targets as `primary_description: '/media/cats/cat01.png'`. A relative URL
  inherits the page's scheme and hostname, so the same config works on HTTP and
  HTTPS and survives a hostname change.
- **Don't** write `http://52.2.236.217/media/...` or `http://<ip>/...` in configs.
  Browsers try to upgrade such image/video/audio URLs to HTTPS, and the IP has no
  certificate, so they would fail to load.
- **S3, if ever used:** `next/assistant/s3.py` builds `http://<bucket>.s3.amazonaws.com/...`;
  change to `https://`. S3 serves HTTPS out of the box.
- **Performance:** the 443 server block enables HTTP/2, which loads many images in
  parallel over one connection. Consider adding `expires 7d;` to the `/media/`
  location so repeated targets are cached by the browser (the current
  `proxy_cache` lines there do nothing for `alias`). For large video, keep files
  small (re-encode to H.264, modest bitrate) — bandwidth, not TLS, is the limit.

## Test plan

Run from **outside** the server (a laptop), not from the instance itself.

- **Participant side, no password:** launch the 32-query demo twice
  (`protocol: http` + `link_name: demo-http`, `protocol: https` + `link_name: demo-https`).
  Open each via long link and short link, over both schemes: redirects as designed,
  `?participant=` pre-fill survives every redirect, full run-through with answers
  recorded, image demo (`/media/cats/`) loads over HTTPS.
- **Short links:** relaunching with an existing `link_name` fails; `relink.py` moves it;
  unknown name shows "not found".
- **Admin side:** `/dashboard/experiment_list`, a dashboard, the participants download,
  `/api/experiment/<uid>/logs`, `POST /assistant/init/experiment` → 401 without the
  password over HTTPS, redirect to HTTPS over HTTP, work with the password.
- **Bypass closed:** `curl http://<domain>:8000/dashboard/experiment_list` and
  `nc -zv <domain> 27017 6379 5672 15672 8888` → refused / timed out.
- **Stack:** `local/healthcheck.sh` logs OK; `launch.py` still launches; a short load
  test at the usual participant count shows no change in wait times.

## Cutover timing and caveats

- No forced cutover: existing and running experiments default to `http` and are
  untouched. Still, apply steps 5–6 between collections — recreating nginx drops
  connections for a few seconds, and the password changes how you reach the dashboard.
- Dashboard links on `:8000` stop working from outside (step 6) — use
  `https://<domain>/dashboard/...`.

## Implementation (2026-11-10)

Built on `feature/https-impl` (from `fix/duplicate-answer`), one commit per step.

| Step | Where |
|---|---|
| DNS `@` + `www` → 52.2.236.217 (Porkbun); security group 80/443 open, 22 from one IP, everything else closed (verified by probing the public IP) | done by the user |
| jQuery over `https://` in the three query-page templates | `next/query_page/templates/` |
| nginx config as a folder mounted as `conf.d/` (`local/nginx/next.conf` + `snippets/*.inc`); domain names; ACME webroot; 443 published | `local/nginx/`, `docker-compose.yml.pre` |
| Certificate (Let's Encrypt, `siplab-next.xyz` + `www`, expires 2027-02-08), renewal by `certbot.timer`, deploy hook reloads nginx (dry run OK) | host; `local/certbot-deploy-hook.sh` |
| 443 server (HTTP/2, TLS 1.2/1.3, no HSTS) + admin password (allow-list `snippets/participant.inc`; admin paths redirect HTTP→HTTPS) | `local/nginx/` |
| Health check: probe over HTTPS as user `healthcheck`, certificate-expiry warning | `local/healthcheck.sh` |
| `protocol` + `link_name` YAML keys; redirect in the query page; `/s/<name>`; launch checks; links printed and on the dashboard; `relink.sh` | `next/site_links.py`, `next/short_links.py`, `apps/ARankB/myApp.yaml`, `next/assistant/assistant_blueprint.py`, `local/launch.py`, `local/relink.sh` |
| Relative `/media/` paths in config examples; S3 URLs over `https://` | `local/*.yaml`, `next/assistant/s3.py` |

**Different from the plan**
- The old single-file mount of `nginx.conf` went stale when an editor replaced the file
  (the container kept the old version), and the image's `default.conf` answered every
  hostname except the IP — the domain got 404s. Mounting the whole folder fixes both.
- `NEXT_HTTPS_HOST` is read from the environment **or** `local/site.local.conf`, so the
  backend picks it up without a redeploy; `launch.py` gets the links from the server.
- Launch checks run on the server (experiment creation), not in `launch.py`, so every
  way of creating an experiment is covered. HTTPS readiness is tested by fetching
  `https://<domain>/favicon.ico` with certificate verification.
- Short-link names are stored with `_id` = name (atomic claim); moving one keeps a history.
- No `DOCKER-USER` iptables layer: the security group was verified to block MongoDB,
  Redis and RabbitMQ from outside, and iptables rules that survive reboots next to
  Docker's own are fragile. Revisit if the security group ever changes.
- Let's Encrypt stopped sending expiry emails in 2025 — the health check's
  `cert_days` warning replaces them.

**Still to apply at the next full deploy** (`docker rm -f local_nextbackenddocker_1
local_minionworker_1 local_cadvisor_1`, then `./docker_up.sh 52.2.236.217`): the
backend's port 8000 and cAdvisor's 8888 bound to `127.0.0.1` (today they are published
on all interfaces but blocked by the security group).

**Tests (all passed)**
- From the public address: participant paths 200 on HTTP and HTTPS; 10 admin paths
  401 without / with a wrong password, 200 with it; admin paths on HTTP → 301 to HTTPS;
  certificate valid for both names, HTTP/2, no HSTS header.
- Redirect matrix for an `https` and an `http` experiment, by IP / domain / short link,
  `?participant=` kept on every hop; unknown or dangling short link → "Study not found".
- Launch refusals: taken `link_name`, malformed `link_name`, `protocol: htps`; HTTPS
  readiness check fails with no hostname and with an expired certificate.
- `load_sim.py` full runs over HTTPS on both experiments + `check_export.py`: 0 server
  errors, 0 export problems; `repro_duplicate_answer.py` over HTTPS: all correct.
- Real Chrome (`local/test_https_e2e.py`): from `http://52.2.236.217/s/demo-img?participant=…`
  to the HTTPS page with the ID kept, jQuery loaded, a full 32-question run to the
  success debrief, all 6 cat images loaded over HTTP/2, no browser errors, export ids
  1..32 exactly once; an `http` experiment over HTTPS served without a downgrade.

Demo experiments from the tests: `demo-https` 2fd93031…, `demo-http` 18c281c9…,
`demo-img` 6b5c3f54… (short links stay taken; they're harmless).
