import json
import next.utils as utils
import next.apps.SimpleTargetManager


class MyApp:
    def __init__(self, db):
        self.app_id = 'ArankB'
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
        algorithm_keys = ['A', 'B', 'n', 'd', 'failure_probability', 
                          'random_seed', 'burn_in', 'down_sample', 
                          'mu', 'iteration', 'debug']
        for key in algorithm_keys:
            if key in args:
                alg_data[key] = args[key]

        init_algs(alg_data)
        return args

    def getQuery(self, butler, alg, args):
        participant_uid = args.get('participant_uid', butler.exp_uid)
        alg_response = alg({'participant_uid': participant_uid})
        exp_uid = butler.exp_uid
        target_indices = []
        for i in range(len(alg_response)):
            cur = self.TargetManager.get_target_item(exp_uid, alg_response[i])
            cur['label'] = 'position_' + str(i)
            target_indices.append(cur)
        experiment = butler.experiment.get()
        A = experiment['args']['A']
        B = experiment['args']['B']
        return {'target_indices': target_indices, 'A': A, 'B': B, 'participant_uid': participant_uid}

    def processAnswer(self, butler, alg, args):
        query = butler.queries.get(uid=args['query_uid'])
        targets = query['target_indices']
        target_winner = args['target_winner']
        participant_uid = args['participant_uid']
    
        experiment = butler.experiment.get()
        num_reported_answers = butler.experiment.increment(
            key='num_reported_answers_for_' + query['alg_label'])

        n = experiment['args']['n']
        if num_reported_answers % ((n+4)/4) == 0:
            butler.job('getModel', json.dumps({'exp_uid': butler.exp_uid, 'args': {
                       'alg_label': query['alg_label'], 'logging': True}}))
       
        alg({'target_winner': target_winner, 'participant_uid': participant_uid})
        return {'target_winner': target_winner, 'targets': targets}

    def getModel(self, butler, alg, args):
        return alg()

    def format_responses(self, responses):
        formatted = []
        for response in responses:
            if 'target_winner' not in response:
                continue
            targets = {'target_' + target['label']: target['primary_description']
                       for target in response['target_indices']}
            ids = {target['label'] + '_id': target['target_id']
                   for target in response['target_indices']}
            winner = {t['target_id'] == response['target_winner']: (t['primary_description'], t['target_id'])
                      for t in response['target_indices']}
            response.update(
                {'target_winner': winner[True][0], 'winner_id': winner[True][1]})

            for key in ['q', '_id', 'target_indices']:
                if key in response:
                    del response[key]
            response.update(targets)
            response.update(ids)
            formatted += [response]

        return formatted
