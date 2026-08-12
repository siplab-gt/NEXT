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

    @staticmethod
    def _trap_schedule(experiment_args):
        """Return (trap_count, trap_interval, total_queries).

        trap_count == 0 means no traps (setTrap off, num_trap_questions == 0,
        or a trapRatio too small to yield a single trap). Serving and
        next-slot prediction both derive from this so they can never disagree.
        """
        num_queries = experiment_args['num_tries']
        if not experiment_args['setTrap']:
            return 0, 0, num_queries
        trapRatio = experiment_args['trapRatio']
        num_trap_questions = experiment_args['num_trap_questions']
        trap_count = int(trapRatio * num_queries) if trapRatio > 0 else num_trap_questions
        if trap_count <= 0:
            return 0, 0, num_queries
        trap_interval = num_queries // trap_count + 1
        return trap_count, trap_interval, num_queries + trap_count

    @staticmethod
    def _is_trap_slot(query_id, trap_count, trap_interval):
        return trap_count > 0 and query_id % trap_interval == 0

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

        isTrap = False
        target_indices = []
        num_trap_questions = experiment['args']['num_trap_questions']
        num_targets = n - num_trap_questions
        # num_queries = (experiment['args']['iteration'] + experiment['args']['burn_in']) * num_targets
        trap_count, trap_interval, total_queries = self._trap_schedule(experiment['args'])

        if self._is_trap_slot(query_id, trap_count, trap_interval):
            if experiment['args']['trapRatio'] > 0:
                # Random trap question
                target_indices = [random.randint(num_targets, n)]
            else:
                # Evenly spaced trap question
                trap_index = (query_id // trap_interval - 1) + num_targets
                target_indices = [trap_index]
            isTrap = True

        # if isTrap is true, alg will return an empty list; else, alg will return a list of target indices
        alg_args = {'participant_uid': participant_uid, 'isTrap': isTrap}
        if experiment['args'].get('precompute', False):
            # One-step-ahead precompute: tell the alg how many answers ahead
            # the next InfoTuple selection is. Trap slots consume an answer
            # without needing a computed tuple, so the target is the next
            # NON-trap query id. next_steps == 0 disables precompute for this
            # serve (participant about to finish, or already failed).
            target_qid = query_id + 1
            while (self._is_trap_slot(target_qid, trap_count, trap_interval)
                   and target_qid <= total_queries):
                target_qid += 1
            next_steps = target_qid - query_id
            if target_qid > total_queries:
                next_steps = 0
            elif (butler.participants.exists(uid=participant_uid, key='participant_failed')
                  and butler.participants.get(uid=participant_uid, key='participant_failed')):
                # a failed-but-not-expelled participant's head no longer
                # advances, so predictions would never match
                next_steps = 0
            alg_args.update({'precompute': True, 'next_steps': next_steps})
        target_indices.extend(alg(alg_args))
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
        # query_id counts answered queries: a served-but-unanswered query (page
        # refresh) does not consume the slot and gets re-served on the next getQuery
        butler.participants.increment(uid=participant_uid, key='query_id')
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
        if trapped:
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
        # trapped / num_trapped_so_far are persisted onto the query doc so the
        # per-trap outcome survives into the JSON/CSV exports
        return {'target_winner': target_winner, 'targets': targets, 'participant_failed': participant_failed,
                'trapped': trapped, 'num_trapped_so_far': num_trapped}

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
            # target_winner is [anchor, ranked..., unranked...]; ids arrive as
            # floats from the widget and ints from API clients, and trap
            # questions store the sentinel [0] rather than a target_id
            descriptions = {int(t['target_id']): t['primary_description']
                            for t in response['target_items']}
            winner_ids = response['target_winner']
            if not isinstance(winner_ids, list):
                winner_ids = [winner_ids]
            winner_ids = [int(float(w)) for w in winner_ids]

            ranking = {}
            if not response.get('isTrap', False) and winner_ids:
                num_ranked = int(response.get('B', len(winner_ids) - 1))
                ranking['anchor_id'] = winner_ids[0]
                ranking['anchor'] = descriptions.get(winner_ids[0], '')
                for k, wid in enumerate(winner_ids[1:1 + num_ranked]):
                    ranking['rank_{}_id'.format(k + 1)] = wid
                    ranking['rank_{}'.format(k + 1)] = descriptions.get(wid, '')

            row = {key: value for key, value in response.items()
                   if key not in ('q', '_id', 'target_items', 'targets')}
            row['target_winner'] = winner_ids
            row.update(targets)
            row.update(ids)
            row.update(ranking)
            formatted += [row]

        return formatted
