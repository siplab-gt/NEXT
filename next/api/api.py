import logging
import json
import sys
from next.api import api_blueprint
from next.dashboard.dashboard import dashboard
from next.assistant.assistant_blueprint import assistant
from next.home import home
from next.query_page import query_page
import next.constants as constants

from flask import Flask

# from logging.config import dictConfig

# dictConfig({
#     'version': 1,
#     'formatters': {'default': {
#         'format': '[%(asctime)s] %(levelname)s in %(module)s: %(message)s',
#     }},
#     'handlers': {'wsgi': {
#         'class': 'logging.StreamHandler',
#         'stream': 'ext://flask.logging.wsgi_errors_stream',
#         'formatter': 'default'
#     }},
#     'root': {
#         'level': 'INFO',
#         'handlers': ['wsgi']
#     }
# })

app = Flask(__name__)
app.register_blueprint(api_blueprint.api, url_prefix='/api')
app.register_blueprint(assistant, url_prefix='/assistant')
app.register_blueprint(home, url_prefix='/home')
if constants.SITE_KEY:
    dashboard_prefix = '/dashboard/{}'.format(constants.SITE_KEY)
else:
    dashboard_prefix = '/dashboard'
app.register_blueprint(dashboard, url_prefix=dashboard_prefix)
app.register_blueprint(query_page, url_prefix='/query')


@app.context_processor
def inject_global_templatevars():
    return dict(next_git_hash=constants.GIT_HASH,
                next_version=constants.VERSION)


# Log to standard out. Remember to turn off in production
app.logger.addHandler(logging.StreamHandler(sys.stdout))
app.logger.setLevel(logging.DEBUG)

# Handle internal errors using a custom error message


@app.errorhandler(404)
def internal_system_error(error):
    response = {
        'meta': {
            'status': 'FAIL',
            'code': 404,
            'message': 'Resource not found'
        }
    }
    return json.dumps(response), 404
