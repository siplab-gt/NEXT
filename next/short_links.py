"""Short study links: https://<host>/s/<link_name> -> the experiment's query page.

An experiment gets one with `link_name: rank4` in its YAML (ARankB). Names live in
the MongoDB collection `short_links` (app_data), one document per name:
  {_id: <name>, exp_uid, created, history: [{exp_uid, until}]}

One name, one experiment: launching with a name that is already taken FAILS - a
relaunch must never silently move a link that a live Prolific study is using. To
move a name on purpose (e.g. relaunch after a bug, before publishing the study):

    local/relink.sh <name> <EXP_UID>        # = python -m next.short_links move ...

The redirect keeps the query string (?participant=<PROLIFIC_ID>), honours the
experiment's protocol, and is a 302 so browsers don't cache a link that may move.
"""
import os
import re
import sys

from flask import Blueprint, redirect, request

import next.utils as utils
import next.site_links as site_links
from next.api.resource_manager import ResourceManager
from next.database_client.DatabaseAPI import DatabaseAPI

BUCKET = 'short_links'
NAME_RE = re.compile(r'^[a-z0-9](?:[a-z0-9-]{0,48}[a-z0-9])?$')
NAME_RULE = 'lowercase letters, digits and "-", 1-50 characters, not starting or ending with "-"'

db = DatabaseAPI()
resource_manager = ResourceManager()


def _links():
    return db._bucket(BUCKET)


def _experiment(exp_uid):
    # ResourceManager.get_experiment raises (AttributeError) for an unknown uid
    try:
        return resource_manager.get_experiment(exp_uid)
    except Exception:
        return None


def validate(name):
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise ValueError('link_name {!r} is not allowed: use {}'.format(name, NAME_RULE))


def lookup(name):
    return _links().find_one({'_id': name})


def name_for(exp_uid):
    doc = _links().find_one({'exp_uid': exp_uid})
    return doc['_id'] if doc else None


def check_available(name):
    """Raise ValueError if experiments can't be launched with this link_name."""
    validate(name)
    doc = lookup(name)
    if doc:
        raise ValueError(
            'link_name {!r} already points to experiment {} (since {}). Pick another '
            'name, or move it on purpose: local/relink.sh {} <EXP_UID>'.format(
                name, doc['exp_uid'], doc.get('created', '?'), name))


def claim(name, exp_uid):
    """Give a free name to a new experiment. Atomic: _id is the name."""
    validate(name)
    _links().insert_one({'_id': name, 'exp_uid': exp_uid,
                         'created': utils.datetimeNow('string'), 'history': []})


def move(name, exp_uid):
    """Point an existing (or new) name at another experiment; returns the old one."""
    validate(name)
    if _experiment(exp_uid) is None:
        raise ValueError('no experiment {}'.format(exp_uid))
    old = lookup(name)
    now = utils.datetimeNow('string')
    if old is None:
        claim(name, exp_uid)
        return None
    _links().update_one({'_id': name}, {
        '$set': {'exp_uid': exp_uid, 'created': now},
        '$push': {'history': {'exp_uid': old['exp_uid'], 'until': now}}})
    return old['exp_uid']


short_links = Blueprint('short_links', __name__)


@short_links.route('/<name>')
def follow(name):
    doc = lookup(name.lower()) if NAME_RE.match(name.lower()) else None
    experiment = _experiment(doc['exp_uid']) if doc else None
    if experiment is None:
        return ('<html><body style="font-family:sans-serif;text-align:center;margin-top:80px">'
                '<h2>Study not found</h2><p>Please check the link you were given.</p>'
                '</body></html>'), 404
    path = site_links.QUERY_PATH.format(exp_uid=doc['exp_uid'])
    query_string = request.query_string.decode('utf-8')
    if site_links.protocol_of(experiment) == 'https' and site_links.https_host():
        target = site_links.https_redirect_target(path, query_string)
    else:
        # relative: stays on the scheme and host the visitor used
        target = path + ('?' + query_string if query_string else '')
    return redirect(target, 302)


def _main(argv):
    usage = ('usage: python -m next.short_links move <name> <EXP_UID>\n'
             '       python -m next.short_links list')
    if len(argv) == 3 and argv[0] == 'move':
        old = move(argv[1], argv[2])
        print('{}: {} -> {}'.format(argv[1], old or '(new)', argv[2]))
        return 0
    if argv == ['list']:
        for doc in _links().find().sort('_id', 1):
            print('{:20s} {}  since {}'.format(doc['_id'], doc['exp_uid'], doc.get('created', '?')))
        return 0
    print(usage)
    return 2


if __name__ == '__main__':
    try:
        code = _main(sys.argv[1:])
    except Exception as e:
        print('error: {}'.format(e))
        code = 1
    sys.stdout.flush()
    # os._exit, not sys.exit: DatabaseAPI.__del__ closes its MongoClient during
    # interpreter shutdown, where pymongo can no longer start threads and the
    # process hangs. Every write above is already acknowledged (w=1).
    os._exit(code)
