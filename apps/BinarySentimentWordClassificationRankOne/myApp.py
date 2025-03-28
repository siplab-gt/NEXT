import json
import next.utils as utils
import next.apps.SimpleTargetManager


class MyApp:
    def __init__(self, db):
        self.app_id = 'BinarySentimentWordClassificationRankOne'
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
        algorithm_keys = ['n', 'd', 'failure_probability']
        for key in algorithm_keys:
            if key in args:
                alg_data[key] = args[key]

        init_algs(alg_data)
        return args

    def getQuery(self, butler, alg, args):
        alg()
        participant_uid = args.get('participant_uid', butler.exp_uid)
        if not butler.participants.exists(uid = participant_uid, key='query_id'):
            butler.participants.set(uid=participant_uid, key='query_id', value=0)
        query_id = butler.participants.get(uid=participant_uid, key='query_id')
        exp_uid = butler.exp_uid
        query = self.TargetManager.get_target_item(exp_uid, query_id)
        butler.participants.increment(uid=participant_uid, key='query_id')
        return {'text_query': query}

    def processAnswer(self, butler, alg, args):
        alg()
        query = butler.queries.get(uid=args['query_uid'])
        experiment = butler.experiment.get()
        num_reported_answers = butler.experiment.increment(
            key='num_reported_answers_for_' + query['alg_label'])
        return args

    def getModel(self, butler, alg, args):
        return alg()

    def format_responses(self, responses):
        formatted = []
        for response in responses:
            req_fields = ['participant_uid','reading_time', 'decision_time',  
                          'word_selected', 'label'] 
            query = response['text_query']['primary_description']
            query_id, query_order = query.split(' ')[0], query.split(' ')[1:]
            words_not_selected = [word for word in query_order if word != response['word_selected']]
            N = len(query_order)
            response = [(k, v) for k, v in response.items() if k in req_fields]
            new_field = {'N': N, 'query_id': query_id, 'query_order': query_order, 
                         'words_not_selected': words_not_selected}
            response.update(new_field)
            formatted += [response]

        return formatted
