"""Participant and dashboard links, and the per-experiment protocol.

An experiment's YAML chooses `protocol: http` (default) or `protocol: https`.
nginx serves both all the time; the query page and the short links enforce the
choice (HTTPS_PLAN.md, "Choosing HTTP or HTTPS per experiment"):
  - an https experiment opened over HTTP is redirected to https://NEXT_HTTPS_HOST
  - an http experiment opened over HTTPS is served as it is (no downgrade)
"""
import requests

import next.constants as constants

QUERY_PATH = '/query/query_page/query_page/{exp_uid}'


def https_host():
    return constants.NEXT_HTTPS_HOST or ''


def public_host():
    """The name participants use: the HTTPS hostname when this server has one
    (it serves plain HTTP too), else the backend's global host (the IP)."""
    return https_host() or constants.NEXT_BACKEND_GLOBAL_HOST


def protocol_of(experiment):
    return ((experiment or {}).get('args') or {}).get('protocol') or 'http'


def base_url(protocol):
    if protocol == 'https' and https_host():
        return 'https://' + https_host()
    return 'http://' + public_host()


def participant_url(exp_uid, protocol):
    return base_url(protocol) + QUERY_PATH.format(exp_uid=exp_uid)


def short_url(name, protocol):
    return base_url(protocol) + '/s/' + name


def dashboard_url(exp_uid, app_id):
    path = '/dashboard/experiment_dashboard/{}/{}'.format(exp_uid, app_id)
    if https_host():
        return 'https://' + https_host() + path
    return 'http://' + public_host() + path


def https_redirect_target(path, query_string):
    """Where to send a visitor of an https experiment who came in over HTTP."""
    target = 'https://' + https_host() + path
    if query_string:
        target += '?' + query_string
    return target


def https_problem():
    """None when experiments on this server can use protocol: https, else the
    reason they can't - checked at launch so nobody hands out a dead link."""
    host = https_host()
    if not host:
        return ('this server has no HTTPS hostname '
                '(set NEXT_HTTPS_HOST in local/site.local.conf)')
    try:
        # certificate is verified: an expired or wrong certificate fails here
        requests.get('https://{}/favicon.ico'.format(host), timeout=10)
    except Exception as e:
        return 'https://{} is not reachable with a valid certificate ({})'.format(
            host, type(e).__name__)
    return None
