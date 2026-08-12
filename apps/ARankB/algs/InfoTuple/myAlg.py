import time
import numpy as np
from apps.ARankB.algs.InfoTuple import utilsInfoTuple
import next.utils as utils
from itertools import permutations
from cblearn.embedding import SOE
from sklearn.utils import check_random_state

# When False (default) the one-step-ahead precompute skips any prediction that
# crosses an anchor-cycle wrap (head n-1 -> 0), because the participant
# embedding is updated at the wrap and a precomputed tuple would use the stale
# embedding. Flip to True to precompute across wraps with the stale embedding
# (max speedup, slight approximation).
PRECOMPUTE_ACROSS_WRAP = False


class MyAlg:
    def initExp(self, butler, A, B, n, d 
                ,random_seed, failure_probability
                ,iteration, burn_in, down_sample, mu, debug,
                setTrap, expel, tolerance, trapRatio, num_trap_questions):
        #For InfoTuple
        butler.algorithms.set(key='debug_flag', value=debug)
        butler.algorithms.set(key='mu', value=mu)
        butler.algorithms.set(key='down_sample', value=down_sample)
        butler.algorithms.set(key='burn_in', value=burn_in)
        butler.algorithms.set(key='iteration', value=iteration)
        butler.algorithms.set(key='responses', value=list()) #store all responses in list
       
        rng = check_random_state(random_seed)
        rng_state = rng.get_state()
        serializable_rng_state = (rng_state[0], rng_state[1].tolist(), *rng_state[2:])
        butler.algorithms.set(key='rng_state', value=serializable_rng_state)
        butler.algorithms.set(key='seed', value=random_seed)
        
    
        #Set parameters A, B in bulter.algo
        butler.algorithms.set(key='A', value=A) #query length
        butler.algorithms.set(key='B', value=B) #answer length
        butler.algorithms.set(key='delta', value=failure_probability)
        butler.algorithms.set(key='num_reported_answers', value=0)
        # Store the number of regular targets (A) separately from total targets (n)
        butler.algorithms.set(key='num_regular_targets', value=A)
        butler.algorithms.set(key='total_targets', value=n)
        # Create embedding matrix only for regular targets (0 to A-1)
        X = rng.rand(n - num_trap_questions, d)
        butler.algorithms.set(key='X', value=X)

        # To keep track of bad participants
        butler.algorithms.set(key='bad_participants', value=list())
        butler.algorithms.set(key='expel', value=expel)
        return True

    def _restore_rng(self, butler):
        rng = np.random.RandomState()
        retrieved_state = butler.algorithms.get(key='rng_state')
        restored_rng_state = (retrieved_state[0], np.array(retrieved_state[1]), *retrieved_state[2:])
        rng.set_state(restored_rng_state)
        return rng

    def _save_rng(self, butler, rng):
        rng_state = rng.get_state()
        serializable_rng_state = (rng_state[0], rng_state[1].tolist(), *rng_state[2:])
        butler.algorithms.set(key='rng_state', value=serializable_rng_state)

    def _select_infotuple(self, butler, participant_uid, h):
        """InfoTuple selection for anchor h from the participant's current
        embedding. Consumes and persists one global rng_state advance. This is
        the expensive step; it runs inline in getQuery or in a background
        precompute_next_query job."""
        A = butler.algorithms.get(key='A')
        mu = butler.algorithms.get(key='mu')
        down_sample = butler.algorithms.get(key='down_sample')
        X_part = np.array(butler.participants.get(uid=participant_uid, key='embedding'))
        n, d = X_part.shape

        rng = self._restore_rng(butler)
        candidates = permutations(filter(lambda x: x is not h, range(n)), A)
        tuples = map(lambda x: [h] + list(x), candidates)
        selected_tuple, _, _ = utilsInfoTuple.primal_body_selector(X_part, tuples, rng, mu, down_sample)
        selected_tuple = list(map(lambda x: int(x), selected_tuple))
        self._save_rng(butler, rng)
        return selected_tuple

    def _consume_precomputed(self, butler, participant_uid, h, curr_iteration, n):
        """Peek-then-take the precomputed tuple for the participant's current
        state (token = curr_iteration * n + head). A doc for a FUTURE state
        (page refresh re-serving the current query) is kept in place; a doc
        for a PAST state is discarded. Returns the tuple on a hit, else None."""
        pc = butler.participants.get(uid=participant_uid, key='precomputed_query')
        if not pc:
            return None
        t_doc = pc.get('curr_iteration', -1) * n + pc.get('head', -1)
        t_cur = curr_iteration * n + h
        if t_doc == t_cur:
            pc = butler.participants.get_and_delete(uid=participant_uid, key='precomputed_query')
            if pc and pc.get('curr_iteration', -1) * n + pc.get('head', -1) == t_cur:
                utils.debug_print('PRECOMPUTE HIT participant={} head={} iter={}'.format(
                    participant_uid, h, curr_iteration))
                return [int(x) for x in pc['tuple']]
            utils.debug_print('PRECOMPUTE RACED participant={} head={} iter={}'.format(
                participant_uid, h, curr_iteration))
            return None
        if t_doc < t_cur:
            butler.participants.get_and_delete(uid=participant_uid, key='precomputed_query')
            utils.debug_print('PRECOMPUTE STALE participant={} doc=({},{}) cur=({},{})'.format(
                participant_uid, pc.get('head'), pc.get('curr_iteration'), h, curr_iteration))
            return None
        utils.debug_print('PRECOMPUTE FUTURE kept participant={} doc=({},{}) cur=({},{})'.format(
            participant_uid, pc.get('head'), pc.get('curr_iteration'), h, curr_iteration))
        return None

    def _schedule_precompute(self, butler, participant_uid, h, curr_iteration, n, burn_in, next_steps):
        """Submit a background job computing the tuple for the state next_steps
        answers ahead of (h, curr_iteration). Skips burn-in states (instant to
        serve inline) and, unless PRECOMPUTE_ACROSS_WRAP, any prediction that
        crosses the anchor-cycle wrap (the embedding updates at the wrap)."""
        h2, c2, wrapped = h, curr_iteration, False
        for _ in range(next_steps):
            if h2 == n - 1:
                h2, c2, wrapped = 0, c2 + 1, True
            else:
                h2 += 1
        if c2 < burn_in:
            return
        if wrapped and not PRECOMPUTE_ACROSS_WRAP:
            utils.debug_print('PRECOMPUTE SKIP-WRAP participant={} cur=({},{})'.format(
                participant_uid, h, curr_iteration))
            return
        pc = butler.participants.get(uid=participant_uid, key='precomputed_query')
        if pc and pc.get('curr_iteration', -1) * n + pc.get('head', -1) == c2 * n + h2:
            # a kept FUTURE doc already covers the target state; don't duplicate
            return
        butler.db.submit_job(butler.app_id, butler.exp_uid,
                             'precompute_next_query',
                             {'participant_uid': participant_uid,
                              'head': h2, 'curr_iteration': c2},
                             namespace=butler.exp_uid + '_' + participant_uid,
                             ignore_result=True, time_limit=60,
                             alg_id=butler.alg_id, alg_label=butler.alg_label)
        utils.debug_print('PRECOMPUTE SCHEDULED participant={} target=({},{})'.format(
            participant_uid, h2, c2))

    def precompute_next_query(self, butler, args):
        """Background job (per-participant namespace): compute and store the
        tuple for the target state, unless the participant already reached it
        (then the serving path computed it inline and this job is waste)."""
        participant_uid = args['participant_uid']
        h = int(args['head'])
        c = int(args['curr_iteration'])
        X = np.array(butler.algorithms.get(key='X'))
        n, d = X.shape
        cur_h = butler.participants.get(uid=participant_uid, key='head')
        cur_c = butler.participants.get(uid=participant_uid, key='curr_iteration')
        if cur_h is None or cur_c is None:
            return True
        if cur_c * n + cur_h >= c * n + h:
            utils.debug_print('PRECOMPUTE ABANDONED participant={} target=({},{}) cur=({},{})'.format(
                participant_uid, h, c, cur_h, cur_c))
            return True
        selected_tuple = self._select_infotuple(butler, participant_uid, h)
        butler.participants.set(uid=participant_uid, key='precomputed_query',
                                value={'head': h, 'curr_iteration': c,
                                       'tuple': selected_tuple,
                                       'computed_at': str(utils.datetimeNow())})
        utils.debug_print('PRECOMPUTE DONE participant={} target=({},{})'.format(
            participant_uid, h, c))
        return True

    def getQuery(self, butler, participant_uid, isTrap=False, precompute=False, next_steps=0):
        # For trap questions, return empty list since trap targets are handled separately
        if isTrap:
            return []
        #Gather necessary parameters for getQuery
        A = butler.algorithms.get(key='A')
        X = np.array(butler.algorithms.get(key='X'))
        burn_in = butler.algorithms.get(key='burn_in')
        n, d = X.shape

        if not butler.participants.exists(uid = participant_uid, key='embedding'):
            # participant init draws from the global rng stream, as before
            rng = self._restore_rng(butler)
            X_part = rng.rand(n, d)
            butler.participants.set(uid=participant_uid, key='embedding', value=X_part)
            butler.participants.set(uid=participant_uid, key='head', value=0)
            butler.participants.set(uid=participant_uid, key='responses', value=list()) #store all personal responses
            butler.participants.set(uid=participant_uid, key='curr_iteration', value=0)
            self._save_rng(butler, rng)

        selected_tuple = None
        h = butler.participants.get(uid=participant_uid, key='head')
        curr_iteration = butler.participants.get(uid=participant_uid, key='curr_iteration')

        if precompute:
            selected_tuple = self._consume_precomputed(butler, participant_uid, h, curr_iteration, n)

        if selected_tuple is None:
            if curr_iteration < burn_in:
                rng = self._restore_rng(butler)
                selected_tuple = [h]+list(rng.choice([i for i in range(n) if i != h], size=A, replace=False))
                selected_tuple = list(map(lambda x: int(x), selected_tuple))
                self._save_rng(butler, rng)
            else:
                selected_tuple = self._select_infotuple(butler, participant_uid, h)

        if precompute and next_steps > 0:
            self._schedule_precompute(butler, participant_uid, h, curr_iteration, n, burn_in, next_steps)

        return selected_tuple


    def processAnswer(self, butler, target_winner, participant_uid, disregard_candidate):
        # Check if the participant is a bad participant
        if disregard_candidate:
            if participant_uid not in butler.algorithms.get(key='bad_participants'):
                butler.algorithms.append(key='bad_participants', value=participant_uid) 
            if butler.algorithms.get(key='expel'):
                raise ValueError("Bad participant {} is expelled".format(participant_uid))
            return True
       
        X = np.array(butler.algorithms.get(key='X'))
        n, d = X.shape
        h = butler.participants.get(uid=participant_uid, key='head')
        iteration = butler.algorithms.get(key='iteration')
        curr_iteration = butler.participants.get(uid=participant_uid, key='curr_iteration')
        B = butler.algorithms.get(key='B')
       
        # target_winner consists of head, B ranked targets and A - B unranked targets
        head_element = int(target_winner[0])
        # Form explicit pairwise comparisons
        explicit_targets = np.array(target_winner[1:B+1], dtype=int)
        i, j = np.triu_indices(len(explicit_targets), k=1)
        explicit_comparison = list(zip(explicit_targets[i], explicit_targets[j]))
        explicit_comparison = [(head_element, int(i), int(j)) for i, j in explicit_comparison]
        # Form implicit pairwise comparisons
        implicit_targets = np.array(target_winner[B+1:], dtype=int)
        X, Y = np.meshgrid(explicit_targets, implicit_targets, indexing='ij')
        implicit_comparison = list(zip(X.flatten(), Y.flatten()))
        implicit_comparison = [(head_element, int(i), int(j)) for i, j in implicit_comparison]
        # Update participant responses
        current_responses = butler.participants.get(uid=participant_uid, key='responses')
        participant_responses = current_responses + explicit_comparison + implicit_comparison
        butler.participants.set(uid=participant_uid, key='responses', value=participant_responses)
        # Update algorithm responses
        current_responses = butler.algorithms.get(key='responses')
        algorithm_responses = current_responses + explicit_comparison + implicit_comparison 
        butler.algorithms.set(key='responses', value=algorithm_responses)
        
        num_reported_answers = butler.algorithms.increment(
            key='num_reported_answers')
        
        #Update participant parameters
        if h == n - 1:
            if curr_iteration == iteration - 1:
                if (butler.algorithms.get(key='debug_flag')):
                    self.full_embedding_update(butler, args=None)
                else:
                    butler.job('full_embedding_update', {}, time_limit=30)
            
            self.incremental_embedding_update(butler, participant_uid)

            #Set head back to 0 and perform next iteration
            butler.participants.set(uid=participant_uid, key='head', value=0)
            butler.participants.increment(uid=participant_uid, key='curr_iteration')
        else:
            butler.participants.increment(uid=participant_uid, key='head')
            
        return True

    def getModel(self, butler):
        return butler.algorithms.get(key=['X', 'num_reported_answers'])

    def incremental_embedding_update(self, butler, participant_uid):
        responses = butler.participants.get(uid=participant_uid, key='responses')
        seed = butler.algorithms.get(key='seed')
        X = np.array(butler.participants.get(uid=participant_uid, key='embedding'))
        n, d = X.shape
        embedder = SOE(n_components=d, random_state=seed, n_init=10, backend='scipy', max_iter=20, margin=5) # Embedding algorithm to get the embeddings
        # set maximum time allowed to update embedding
        # t_max = 1.0
        # take a single gradient step
        #t_start = time.time()
        #while (time.time()-t_start < 0.5*t_max):
        try:
            X = embedder.fit_transform(responses, n_objects=n, init=X)
            butler.participants.set(uid=participant_uid, key='embedding', value=X.tolist())
        except Exception as e:
            # Log the error but don't fail the entire process
            print(f"Warning: Embedding update failed for participant {participant_uid}: {e}")
            return

    def full_embedding_update(self, butler, args):
        X = np.array(butler.algorithms.get(key='X'))
        n, d = X.shape
        
        responses = butler.algorithms.get(key='responses')
        
        # Check if there are any responses to process
        if not responses:
            return  # Skip embedding update if no responses available
        
        seed = butler.algorithms.get(key='seed')
        try:
            embedder = SOE(n_components=d, random_state=seed, n_init=10, backend='scipy', max_iter=20, margin=5)
            X = embedder.fit_transform(responses, n_objects=n, init=X)
        except Exception as e:
            raise ValueError("SOE embedding exception {}".format(e))
       
        butler.algorithms.set(key='X', value=X.tolist())
        