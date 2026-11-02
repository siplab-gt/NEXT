# Serving the query page over HTTPS — plan

Status: **plan only, nothing implemented yet** (branch `feature/https`, 2026-11-02).

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
- The instance only has an IP (Elastic IP 52.2.236.217) and AWS's default name.
  Let's Encrypt refuses `*.amazonaws.com` names, so we need our own hostname.

## Decision: hostname (open)

Everything below works with any hostname; switching later only means re-issuing the
certificate and updating the Prolific/Qualtrics links (media paths are relative, so
configs don't change).

| Option | Cost | Time | Trade-off |
|---|---|---|---|
| **DuckDNS** (`<name>.duckdns.org`) | free | minutes | Good for building and testing now. Dynamic-DNS domains are sometimes flagged by corporate/school web filters and security tools, and look less trustworthy to participants. |
| **Bought domain** (Cloudflare Registrar, Porkbun, Namecheap) | ~$10–15/yr | under an hour | Clean reputation, lab controls it. Someone must keep the renewal paid. |
| **Georgia Tech subdomain** (`*.gatech.edu`) | usually free | days–weeks | Most trustworthy to participants; depends on GT's process for a server hosted on AWS — ask the advisors / OIT. |

Leaning: DuckDNS now to build and test, then a bought or GT domain before the next
real collection. Whichever is used, it gets an A record pointing at 52.2.236.217 (the
Elastic IP is stable, so no dynamic-update cron is needed). Keep any DuckDNS or
registrar token in a gitignored local file, never in the repo (the repo is public).

## Steps

1. **Hostname** — set up the chosen name (see above), point it at 52.2.236.217, confirm with
   `dig +short <hostname>`.
2. **Security group** — allow inbound TCP 443 (AWS console; the AWS CLI is not
   installed on the instance).
3. **Fix mixed content** — `http://code.jquery.com` → `https://code.jquery.com` in the
   three query-page templates. Works on plain HTTP too, so it can ship first; live
   after `docker restart local_nextbackenddocker_1`.
4. **Certificate** — install certbot on the host; use the webroot method: nginx
   serves `/.well-known/acme-challenge/` from a host folder on port 80.
5. **nginx + compose** (one change, then recreate only nginx):
   - `local/nginx.conf`: new `server { listen 443 ssl; http2 on; ... }` with the
     certificate and the same `location` blocks as today (incl. the 330 s timeouts);
     port 80 keeps the ACME location and otherwise `return 308 https://$host$request_uri;`
     (308, not 301, so an in-flight `processAnswer` POST stays a POST).
   - `local/docker-compose.yml.pre`: publish `443:443`; mount `/etc/letsencrypt`
     (read-only) and the ACME webroot into the nginx container.
   - Apply: `docker rm -f reverse_proxy`, then `docker-compose up -d nginx`
     (stateless container; a few seconds of downtime). The user runs compose.
6. **Renewal** — certbot's systemd timer renews automatically; add a deploy hook
   `docker exec reverse_proxy nginx -s reload`.
7. **Media paths (rule for all future configs)** — image/video/audio targets are
   written as **relative paths** to files in `local/media/`, e.g.
   `primary_description: '/media/cats/cat01.png'`, never `http://<ip>/...`.
   Fix the example comment in `ARankB-InfoTuple-cog_rank4_precompute.yaml` (and the
   other configs) to show this form, document the rule in README, and change
   `next/assistant/s3.py` to build `https://` URLs. Test with the `cats/` images over
   HTTPS before any image study. Details in "Images, video and audio" below.
8. **Links and docs** — Prolific study URL, Qualtrics end-of-survey redirect, CLAUDE.md
   URLs, README. Then a manual click-through and a short load test.

## Images, video and audio (planned for future studies)

HTTPS does **not** get in the way of media, as long as the media URLs are not
`http://`. The ARankB widget (`apps/ARankB/widgets/getQuery_widget.html`) puts each
target's `primary_description` straight into `<img src>`, `<video><source src>` or
`<audio><source src>`, so whatever URL is in the YAML is what the browser loads.

- **Recommended: host media on this server, use relative URLs.** Put files in
  `local/media/` (already served by nginx at `/media/`, e.g. `local/media/cats/`)
  and write targets as `primary_description: '/media/cats/cat01.png'`. A relative URL
  inherits the page's scheme and hostname, so the same config works on HTTP today
  and HTTPS later, and survives a hostname change.
- **Don't** write `http://52.2.236.217/media/...` or `http://<ip>/...` in configs
  (the example comment in the rank-4 YAML does this — update it). Browsers try to
  upgrade such image/video/audio URLs to HTTPS, and the IP has no certificate,
  so they would fail to load.
- **S3, if ever used:** `next/assistant/s3.py` builds `http://<bucket>.s3.amazonaws.com/...`;
  change to `https://`. S3 serves HTTPS out of the box.
- **Performance:** the 443 server block enables HTTP/2, which loads many images in
  parallel over one connection. Consider adding `expires 7d;` to the `/media/`
  location so repeated targets are cached by the browser (the current
  `proxy_cache` lines there do nothing for `alias`). For large video, keep files
  small (re-encode to H.264, modest bitrate) — bandwidth, not TLS, is the limit.

## Cutover timing and caveats

- Switch over only **between collections**: participants mid-study on the old
  `http://` page would otherwise go through the redirect for every answer.
- `local/healthcheck.sh` probes `http://127.0.0.1/...` and keeps working (port 80
  still answers locally). Dashboard links to `:8000` stay HTTP — admin only.
- HTTPS does not close the other published ports: MongoDB 27017, Redis 6379,
  RabbitMQ 5672/15672, backend 8000, cAdvisor 8888. Check the security group allows
  none of them from the internet; an open MongoDB is a larger risk than plain HTTP.
