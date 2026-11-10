#!/bin/sh
# certbot deploy hook: after a certificate is renewed, make nginx load it.
# Installed as /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh (README §3.6):
#   sudo install -m 755 local/certbot-deploy-hook.sh /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
# certbot's systemd timer (certbot.timer) runs the renewal twice a day; this only
# fires when a certificate actually changed.
docker exec reverse_proxy nginx -t && docker exec reverse_proxy nginx -s reload
