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
                ,iteration, burn_in, down_sample, mu
                , debug):
        #Algo Specific
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
        X = rng.rand(n, d)
        butler.algorithms.set(key='X', value=X)
       
        return True

    def getQuery(self, butler, participant_uid):
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
    

    def processAnswer(self, butler, target_winner, participant_uid):
        #Gather necessary parameters for processAnswer
        X = np.array(butler.algorithms.get(key='X'))
        n, d = X.shape
        h = butler.participants.get(uid=participant_uid, key='head')
        iteration = butler.algorithms.get(key='iteration')
        curr_iteration = butler.participants.get(uid=participant_uid, key='curr_iteration')
        
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
        seed = butler.algorithms.get(key='random_seed')
        X = np.array(butler.participants.get(uid=participant_uid, key='embedding'))
        n, d = X.shape
        embedder = SOE(n_components=d, random_state=seed, n_init=10, backend='scipy', max_iter=20, margin=5) # Embedding algorithm to get the embeddings
        # set maximum time allowed to update embedding
        # t_max = 1.0
        # take a single gradient step
        #t_start = time.time()
        #while (time.time()-t_start < 0.5*t_max):
        X = embedder.fit_transform(responses, n_objects=n, init=X)
        butler.participants.set(uid=participant_uid, key='embedding', value=X.tolist())

    def full_embedding_update(self, butler, args):
        X = np.array(butler.algorithms.get(key='X'))
        n, d = X.shape
        
        responses = butler.algorithms.get(key='responses')
        seed = butler.algorithms.get(key='random_seed')
        try:
            embedder = SOE(n_components=d, random_state=seed, n_init=10, backend='scipy', max_iter=20, margin=5)
            X = embedder.fit_transform(responses, n_objects=n, init=X)
        except Exception as e:
            raise ValueError("SOE embedding exception {}".format(e))
       
        butler.algorithms.set(key='X', value=X.tolist())
        