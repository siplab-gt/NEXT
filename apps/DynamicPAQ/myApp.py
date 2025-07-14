import json
import random
import next.utils as utils
import next.apps.SimpleTargetManager


class MyApp:
    def __init__(self, db):
        self.app_id = 'DynamicPAQ'
        self.TargetManager = next.apps.SimpleTargetManager.SimpleTargetManager(
            db)

    def initExp(self, butler, init_algs, args):
        exp_uid = butler.exp_uid
        if 'targetset' in list(args['targets'].keys()):
            n = len(args['targets']['targetset'])
            self.TargetManager.set_targetset(
                exp_uid, args['targets']['targetset'])
        else:
            n = args['targets']['n']
        args['n'] = n
        del args['targets']

        alg_data = {}
        algorithm_keys = ['startItems', 'referenceItems', 'endItems', 
                          'tickFlag', 'tickNum', 'queryType']
        for key in algorithm_keys:
            if key in args:
                alg_data[key] = args[key]

        init_algs(alg_data)
        return args

    def getQuery(self, butler, alg, args):
        participant_uid = args.get('participant_uid', butler.exp_uid)
        if not butler.participants.exists(uid = participant_uid, key='query_id'):
            butler.participants.set(uid=participant_uid, key='query_id', value=0)
        query_id = butler.participants.get(uid=participant_uid, key='query_id')
        exp_uid = butler.exp_uid
        experiment = butler.experiment.get()
        n = experiment['args']['n']
        startIdx, endIdx, refIdx = self.get_dynamic_items(n)
        start = self.TargetManager.get_target_item(exp_uid, startIdx)['alt_description'] 
        end = self.TargetManager.get_target_item(exp_uid, endIdx)['alt_description'] 
        ref = self.TargetManager.get_target_item(exp_uid, refIdx)['alt_description'] 
        alg_response = alg({'ref': ref, 'start': start, 'end': end,
                            'query_id': query_id})
        butler.participants.increment(uid=participant_uid, key='query_id')
        return alg_response

    def processAnswer(self, butler, alg, args):
        query = butler.queries.get(uid=args['query_uid'])
        experiment = butler.experiment.get()
        num_reported_answers = butler.experiment.increment(
            key='num_reported_answers_for_' + query['alg_label'])

        alg({'answer': args['answer']})
        return {'answer': args['answer']}

    def getModel(self, butler, alg, args):
        return alg()

    def format_responses(self, responses):
        return [responses]

    # Custom function to get dynamic items
    def get_dynamic_items(self, n):
        return random.randint(0, n-1), random.randint(0, n-1), random.randint(0, n-1)
