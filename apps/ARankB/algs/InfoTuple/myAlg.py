import time
import numpy as np
from apps.ARankB.algs.InfoTuple import utilsInfoTuple
import next.utils as utils
from itertools import permutations
from cblearn.embedding import SOE
from sklearn.utils import check_random_state


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
        X = rng.rand(A, d)
        butler.algorithms.set(key='X', value=X)

        # To keep track of bad participants
        butler.algorithms.set(key='bad_participants', value=list())
        butler.algorithms.set(key='expel', value=expel)
        return True

    def getQuery(self, butler, participant_uid, isTrap=False):
        # For trap questions, return empty list since trap targets are handled separately
            
        if isTrap:
            return []
        #Gather necessary parameters for getQuery
        A = butler.algorithms.get(key='A')
        X = np.array(butler.algorithms.get(key='X'))
        burn_in = butler.algorithms.get(key='burn_in')
        n, d = X.shape
        
        rng = np.random.RandomState()
        retrieved_state = butler.algorithms.get(key='rng_state')
        restored_rng_state = (retrieved_state[0], np.array(retrieved_state[1]), *retrieved_state[2:])
        rng.set_state(restored_rng_state)
        
        if not butler.participants.exists(uid = participant_uid, key='embedding'):
            X_part = rng.rand(n, d)
            butler.participants.set(uid=participant_uid, key='embedding', value=X_part)
            butler.participants.set(uid=participant_uid, key='head', value=0)
            butler.participants.set(uid=participant_uid, key='responses', value=list()) #store all personal responses
            butler.participants.set(uid=participant_uid, key='curr_iteration', value=0)

        selected_tuple = None
        h = butler.participants.get(uid=participant_uid, key='head')
        curr_iteration = butler.participants.get(uid=participant_uid, key='curr_iteration')
        if curr_iteration < burn_in:
            selected_tuple = [h]+list(rng.choice(n, A, replace=False))
        else: 
            candidates = permutations(filter(lambda x: x is not h, range(n)), A)
            tuples = map(lambda x: [h] + list(x), candidates)
            mu = butler.algorithms.get(key='mu')
            down_sample = butler.algorithms.get(key='down_sample')
            
            X_part = np.array(butler.participants.get(uid=participant_uid, key='embedding'))
            selected_tuple, _, _ = utilsInfoTuple.primal_body_selector(X_part, tuples, rng, mu, down_sample)
        selected_tuple = list(map(lambda x: int(x), selected_tuple))
        # Set rng state
        rng_state = rng.get_state()
        serializable_rng_state = (rng_state[0], rng_state[1].tolist(), *rng_state[2:])
        butler.algorithms.set(key='rng_state', value=serializable_rng_state)
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
        
        # Check if target_winner has enough elements for pairwise comparisons
        if len(target_winner) >= 3:
            for i in range(len(target_winner)-2):
                pairwise_comparison = (int(target_winner[0]),int(target_winner[i+1]), int(target_winner[i+2]))
                butler.participants.append(uid=participant_uid, key='responses', value=pairwise_comparison)
                butler.algorithms.append(key='responses', value=pairwise_comparison)
        
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
        
        # Check if there are any responses to process
        if not responses:
            return  # Skip embedding update if no responses available
        
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
        