import json
import random
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
                          'mu', 'iteration', 'debug', 'setTrap', 'expel', 
                          'tolerance', 'trapRatio', 'num_trap_questions']
        for key in algorithm_keys:
            if key in args:
                alg_data[key] = args[key]

        init_algs(alg_data)
        return args

    def getQuery(self, butler, alg, args):
        exp_uid = butler.exp_uid
        participant_uid = args.get('participant_uid', butler.exp_uid)
        
        # Set query_id for individual participants
        if not butler.participants.exists(uid=participant_uid, key='query_id'):
            butler.participants.set(uid=participant_uid, key='query_id', value=1)
        query_id = butler.participants.get(uid=participant_uid, key='query_id')
        # Decide if the query shoud be a trap question
        
        experiment = butler.experiment.get()
        A = experiment['args']['A']
        B = experiment['args']['B']
        setTrap = experiment['args']['setTrap']
        isTrap = False
        target_indices = []
        if setTrap:
            num_trap_questions = experiment['args']['num_trap_questions']
            num_queries = (experiment['args']['iteration'] + experiment['args']['burn_in']) * A
            trapRatio = experiment['args']['trapRatio']
            # if trapRatio > 0.0, then randomly choose a trap question when its turn for trap
            if trapRatio > 0.0 and query_id % ((int)(trapRatio * num_queries)) == 0:
                target_indices = [random.randint(0, num_trap_questions - 1) + A]
                isTrap = True
            # if trapRatio == 0.0, then evenly space out the trap questions
            elif trapRatio == 0.0 and query_id % ((int)(num_trap_questions / num_queries)) == 0:
                target_indices = [query_id / ((int)(num_trap_questions / num_queries)) - 1 + A]
                isTrap = True
        
        butler.participants.increment(uid=participant_uid, key='query_id')
        target_indices.extend(alg({'participant_uid': participant_uid, 'isTrap': isTrap}))
        target_items = []
        for i in range(len(target_indices)):
            cur = self.TargetManager.get_target_item(exp_uid, target_indices[i])
            cur['label'] = 'position_' + str(i)
            target_items.append(cur)
        
        return {'target_items': target_items, 'A': A, 'B': B, 
                'participant_uid': participant_uid, 'isTrap': isTrap}

    def processAnswer(self, butler, alg, args):
        query = butler.queries.get(uid=args['query_uid'])
        targets = query['target_items']
        target_winner = args['target_winner']
        participant_uid = args['participant_uid']
        trapped = args['trapped']
        experiment = butler.experiment.get()
        num_reported_answers = butler.experiment.increment(
            key='num_reported_answers_for_' + query['alg_label'])
        # Handle trapped questions
        disregard_candidate = False
        if not butler.participants.exists(uid=participant_uid, key='num_trapped'):
            butler.participants.set(uid=participant_uid, key='num_trapped', value=0)
        if trapped:
            butler.participants.increment(uid=participant_uid, key='num_trapped')
            num_trapped = butler.participants.get(uid=participant_uid, key='num_trapped')
            if num_trapped >= experiment['args']['tolerance'] * experiment['args']['num_trap_questions']:
                disregard_candidate = True
        
        n = experiment['args']['n']
        if num_reported_answers % ((n+4)/4) == 0:
            butler.job('getModel', json.dumps({'exp_uid': butler.exp_uid, 'args': {
                       'alg_label': query['alg_label'], 'logging': True}}))
       
        alg({'target_winner': target_winner, 'participant_uid': participant_uid, 
             'disregard_candidate': disregard_candidate})
        return {'target_winner': target_winner, 'targets': targets}

    def getModel(self, butler, alg, args):
        return alg()

    def format_responses(self, responses):
        formatted = []
        for response in responses:
            if 'target_winner' not in response:
                continue
            targets = {'target_' + target['label']: target['primary_description']
                       for target in response['target_items']}
            ids = {target['label'] + '_id': target['target_id']
                   for target in response['target_items']}
            winner = {t['target_id'] == response['target_winner']: (t['primary_description'], t['target_id'])
                      for t in response['target_items']}
            response.update(
                {'target_winner': winner[True][0], 'winner_id': winner[True][1]})

            for key in ['q', '_id', 'target_items']:
                if key in response:
                    del response[key]
            response.update(targets)
            response.update(ids)
            formatted += [response]

        return formatted
