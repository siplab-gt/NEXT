# The ONLY paths a participant needs - open without a password, on port 80 and
# 443. Everything else on the site is admin and needs the password (HTTPS only).
# A new participant-facing endpoint must be added here, or it stays locked.
# Keep in sync with HTTPS_PLAN.md ("Admin password").

# query page + its JS/CSS (/query/static/...)
location /query/ {
  include /etc/nginx/conf.d/snippets/proxy_backend.inc;
}
# the two calls the query page makes (next/query_page/static/js/next_widget.js)
location = /api/experiment/getQuery {
  include /etc/nginx/conf.d/snippets/proxy_backend.inc;
}
location = /api/experiment/processAnswer {
  include /etc/nginx/conf.d/snippets/proxy_backend.inc;
}
# short study links: /s/<link_name> -> redirect to the query page
location /s/ {
  include /etc/nginx/conf.d/snippets/proxy_backend.inc;
}
# browsers fetch this on every page; answer here so it never hits the password
location = /favicon.ico {
  access_log off;
  log_not_found off;
  return 204;
}
