# Proxy a request to the NEXT backend (gunicorn). Included by every location
# that reaches the backend, in both the port-80 and the port-443 server.
# No URI after "http://backend": the request URI is passed on unchanged, which
# exact-match locations (location = /api/...) rely on.
proxy_pass http://backend;
# The backend waits up to 320 s for a celery result (RESULT_GET_TIMEOUT in
# next/broker/broker.py) and celery's hard task limit is 360 s. With nginx's
# 60 s default the proxy returned 504 while the backend was still finishing
# the request - the browser saw an error for an answer that was then recorded
# anyway. Keep nginx patient enough that the backend always answers first.
proxy_connect_timeout 10s;
proxy_send_timeout    330s;
proxy_read_timeout    330s;
proxy_set_header    Host                $http_host;
proxy_set_header    X-Real-IP           $remote_addr;
proxy_set_header    X-Forwarded-For     $proxy_add_x_forwarded_for;
proxy_set_header    X-Forwarded-Proto   $scheme;
