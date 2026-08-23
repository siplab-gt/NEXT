"""
next_backend Answer Resource 
author: Christopher Fernandez, Lalit Jain
Ansewr resource for restful answering of experiment queries in next_backend. 
"""
'''
example usage:

answer a tripletMDS query:
curl -H "Content-Type: application/json" \
-d '{"exp_uid": "DFPDISJFSA", "app_id": "PoolBasedTripletMDS", "args": {"alg_uid": "33f6d2c3f898cc5b4c528002bfe1351f", "target_indices": [{"index": 6, "flag": 0, "label": "center"}, {"index": 8, "flag": 0, "label": "left"}, {"index": 5, "flag": 0, "label": "right"}], "index_winner": 8, "timestamp_query_generated": "2015-02-11 14:59:20.494993"} }' \
-X POST http://localhost:8001/experiment/answer
'''


from flask import Flask
from flask_restful import Resource, reqparse
from next.api.api_util import *
from next.api.api_util import APIArgument
import json
import re
import next.utils
import next.utils as utils
import next.broker.broker
from next.api.resource_manager import ResourceManager
resource_manager = ResourceManager()
broker = next.broker.broker.JobBroker()

# Request parser. Checks that necessary dictionary keys are available in a given resource.
# We rely on learningLib functions to ensure that all necessary arguments are available and parsed.
post_parser = reqparse.RequestParser(argument_class=APIArgument)

# Custom errors for GET and POST verbs on experiment resource
custom_errors = {
    'ReportAnswerError': {
        'message': "Failed to report answer to the specified experiment. Please verify that you have specified the correct application specific query parameters.",
        'code': 400,
        'status': 'FAIL',
    },
}

meta_success = {
    'code': 200,
    'status': 'OK'
}

# An app signals a genuine attention-check expulsion by raising from
# processAnswer (apps/ARankB/myApp.py: "Participant <uid> failed";
# apps/ARankB/algs/InfoTuple/myAlg.py: "Bad participant <uid> is expelled").
# That used to surface as a generic HTML 500 - indistinguishable from an outage -
# so the query page could only guess. It is now returned as a structured 200
# with meta.expelled=True, which the page maps to the attention-check fail exit.
EXPULSION_RE = re.compile(r"(Participant .* failed|Bad participant .* is expelled)")

# Answer resource class


class processAnswer(Resource):
    def post(self):
        post_parser.add_argument('exp_uid', type=str, required=True)
        post_parser.add_argument('args', type=dict, required=True)

        # Validate args with post_parser
        args_data = post_parser.parse_args()
        # Pull app_id and exp_uid from parsed args
        exp_uid = args_data["exp_uid"]

        args_data['args']['response_time'] = float(
            args_data['args']['response_time'])

        # Fetch app_id data from resource manager
        app_id = resource_manager.get_app_id(exp_uid)
        # Parse out a target_winner. If the argument doesn't exist, return a meta dictionary error.
        args_json = json.dumps(args_data)
        # Execute processAnswer
        try:
            response_json, didSucceed, message = broker.applyAsync(app_id,
                                                                   exp_uid,
                                                                   'processAnswer',
                                                                   args_json)
        except Exception as e:
            if EXPULSION_RE.search(str(e)):
                meta = dict(meta_success, participant_failed=True, expelled=True,
                            message=str(e)[:200])
                return attach_meta({}, meta), 200
            raise

        # Per-request copy: meta_success is module-level and must not be mutated
        # (concurrent requests would leak each other's flags).
        meta = dict(meta_success)
        meta['participant_failed'] = args_data['args'].get('participant_failed', False)

        if didSucceed:
            return attach_meta(eval(response_json), meta), 200
        else:
            print("Failed to processAnswer", message)
            return attach_meta({}, custom_errors['ReportAnswerError'], backend_error=message)
