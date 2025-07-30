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
        n = experiment['args']['n'] # all entries in the targetset
        
        setTrap = experiment['args']['setTrap']
        isTrap = False
        target_indices = []
        num_trap_questions = experiment['args']['num_trap_questions']
        num_targets = n - num_trap_questions
        # num_queries = (experiment['args']['iteration'] + experiment['args']['burn_in']) * num_targets
        num_queries = experiment['args']['num_tries']
        total_queries = num_queries
        
        if setTrap:
            trapRatio = experiment['args']['trapRatio']
            
            # Calculate total number of queries including trap questions
            trap_count = int(trapRatio * num_queries) if trapRatio > 0 else num_trap_questions
            total_queries = num_queries + trap_count
            
            # Calculate interval between trap questions
            trap_interval = num_queries // trap_count + 1
            
            # Check if current query should be a trap
            if query_id % trap_interval == 0:
                if trapRatio > 0:
                    # Random trap question
                    target_indices = [random.randint(num_targets, n)]
                else:
                    # Evenly spaced trap question
                    trap_index = (query_id // trap_interval - 1) + num_targets
                    target_indices = [trap_index]
                isTrap = True
        
        butler.participants.increment(uid=participant_uid, key='query_id')
        # if isTrap is true, alg will return an empty list; else, alg will return a list of target indices
        target_indices.extend(alg({'participant_uid': participant_uid, 'isTrap': isTrap}))
        target_items = []
        for i in range(len(target_indices)):
            cur = self.TargetManager.get_target_item(exp_uid, target_indices[i])
            cur['label'] = 'position_' + str(i)
            target_items.append(cur)
        
        return {'target_items': target_items, 'A': experiment['args']['A'], 'B': experiment['args']['B'], 
                                                'participant_uid': participant_uid, 'isTrap': isTrap, 
                                                'query_id': query_id, 'total_queries': total_queries}

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
        if not butler.participants.exists(uid=participant_uid, key='participant_failed'):
            butler.participants.set(uid=participant_uid, key='participant_failed', value=False)
        if not butler.participants.exists(uid=participant_uid, key='num_trapped'):
            butler.participants.set(uid=participant_uid, key='num_trapped', value=0)
        if trapped:
            butler.participants.increment(uid=participant_uid, key='num_trapped')
            num_trapped = butler.participants.get(uid=participant_uid, key='num_trapped')
            if num_trapped >= experiment['args']['tolerance'] * experiment['args']['num_trap_questions']:
                butler.participants.set(uid=participant_uid, key='participant_failed', value=True)
        
        n = experiment['args']['n']
        num_tries = experiment['args']['num_tries']
        if num_reported_answers % ((n+4)/4) == 0:
            butler.job('getModel', json.dumps({'exp_uid': butler.exp_uid, 'args': {
                       'alg_label': query['alg_label'], 'logging': True}}))
        participant_failed = butler.participants.get(uid=participant_uid, key='participant_failed')
        if num_reported_answers >= num_tries and participant_failed:
            raise ValueError("Participant {} failed".format(participant_uid))
        alg({'target_winner': target_winner, 'participant_uid': participant_uid, 
             'disregard_candidate': participant_failed})
        return {'target_winner': target_winner, 'targets': targets, 'participant_failed': participant_failed}

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
