from next.api.resources.targets import Targets
from next.api.resources.participants import Participants
from next.api.resources.logs import Logs
from next.api.resources.process_answer import processAnswer
from next.api.resources.get_query import getQuery
from next.api.app_handler import AppHandler
from next.api.resources.experiment import Experiment
from flask import Blueprint
from next.api import api_util

# Initialize flask.Flask application and restful.api objects
api = Blueprint('api',
                __name__,
                template_folder='templates',
                static_folder='static')
api_interface = api_util.NextBackendApi(api)

# Format: Resource Class, get url, post url (when applicable)
api_interface.add_resource(Experiment,
                           '/experiment',
                           '/experiment/<string:exp_uid>')

api_interface.add_resource(AppHandler,
                           '/experiment/<string:exp_uid>/custom/function_name',
                           '/experiment/custom/<string:function_name>')

api_interface.add_resource(getQuery,
                           '/experiment/<string:exp_uid>/getQuery',
                           '/experiment/getQuery')

api_interface.add_resource(processAnswer, '/experiment/processAnswer')

api_interface.add_resource(Logs,
                           '/experiment/<string:exp_uid>/logs',
                           '/experiment/<string:exp_uid>/logs/<log_type>')

api_interface.add_resource(Participants,
                           '/experiment/<string:exp_uid>/participants')

api_interface.add_resource(Targets,
                           '/experiment/<string:exp_uid>/targets')
