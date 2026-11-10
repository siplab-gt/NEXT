# Admin area (everything that is not in participant.inc): HTTP basic auth.
# Included in the port-443 server only - the port-80 server redirects admin
# paths to HTTPS instead, so a password never travels unencrypted.
# Users: local/nginx/admin.htpasswd (gitignored), one line per person; add one with
#   printf '%s:%s\n' NAME "$(openssl passwd -6)" >> local/nginx/admin.htpasswd
# and remove a person by deleting their line. No reload needed (read per request).
auth_basic           "NEXT admin";
auth_basic_user_file /etc/nginx/conf.d/admin.htpasswd;
