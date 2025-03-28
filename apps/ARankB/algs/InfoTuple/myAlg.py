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
        
        # X = np.random.rand(n,  d)
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
            # X_part = np.random.rand(n,  d)
            X_part = rng.rand(n, d)
            butler.participants.set(uid=participant_uid, key='embedding', value=X_part)
            butler.participants.set(uid=participant_uid, key='head', value=0)
            butler.participants.set(uid=participant_uid, key='responses', value=list()) #store all personal responses
            butler.participants.set(uid=participant_uid, key='curr_iteration', value=0)
            # For testing participant embedding
            # butler.algorithms.set(key=f'{participant_uid}_embedding', value=[])
        
        

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
        # Test tuples are a list of tuples selected by a trial in the original infotuple repo
        # test_init_tuples = [(0, 0, 5), (1, 1, 5), (2, 5, 4), (3, 1, 2), (4, 4, 7), (5, 1, 7), (6, 9, 5), (7, 8, 3), (8, 8, 1), (9, 9, 4)]
        # test_tuples = [[0, 5, 6], [1, 2, 7], [2, 5, 0], [3, 7, 8], [4, 0, 7], [5, 8, 3], [6, 2, 7], [7, 1, 3], [8, 9, 3], [9, 5, 4], [0, 7, 4], [1, 7, 4], [2, 0, 8], [3, 1, 0],
        #             [4, 0, 1], [5, 9, 0], [6, 5, 3], [7, 9, 1], [8, 9, 6], [9, 0, 8], [0, 8, 2], [1, 4, 7], [2, 1, 6], [3, 8, 4], [4, 7, 9], 
        #             [5, 6, 8], [6, 2, 3], [7, 2, 8], [8, 3, 1], [9, 4, 5], [0, 3, 5], [1, 3, 8], [2, 0, 1], [3, 9, 1], [4, 3, 0], [5, 9, 1], [6, 5, 9], [7, 3, 5],
        #             [8, 9, 5], [9, 4, 2], [0, 8, 3], [1, 9, 8], [2, 3, 1], [3, 8, 2], [4, 6, 9], [5, 6, 7], [6, 7, 5], [7, 8, 2], [8, 3, 1], 
        #             [9, 4, 6], [0, 2, 6], [1, 0, 4], [2, 0, 5], [3, 4, 8], [4, 3, 9], [5, 8, 0], [6, 0, 1], [7, 8, 4], [8, 1, 4], [9, 1, 3], [0, 8, 4], 
        #             [1, 2, 5], [2, 5, 6], [3, 8, 5], [4, 1, 2], [5, 7, 6], [6, 0, 2], [7, 8, 5], [8, 4, 5], [9, 7, 6], [0, 5, 9], [1, 8, 5], [2, 9, 0], [3, 7, 1], 
        #             [4, 0, 8], [5, 8, 6], [6, 0, 1], [7, 6, 1], [8, 2, 3], [9, 7, 5], [0, 2, 9], [1, 0, 9], [2, 5, 0], [3, 7, 8], [4, 6, 8], [5, 8, 4], [6, 5, 0], 
        #             [7, 6, 5], [8, 7, 6], [9, 8, 0], [0, 3, 8], [1, 0, 5], [2, 3, 6], [3, 9, 1], [4, 2, 5], [5, 6, 0], [6, 1, 2], [7, 0, 6], [8, 7, 5], [9, 7, 8]]
        # if curr_iteration < burn_in:
        #     idx = n * curr_iteration + h
        #     selected_tuple = test_init_tuples[idx]
        # else: 
        #     idx = n * (curr_iteration - burn_in) + h
        #     selected_tuple = test_tuples[idx]
        # return list(selected_tuple)

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
            
            
        # Temporarily updating full embedding every n time
        # if h == n - 1:
        #     butler.job('full_embedding_update', {}, time_limit=30)
        #     butler.participants.set(uid=participant_uid, key='head', value=0)
        #     butler.participants.increment(uid=participant_uid, key='curr_iteration')
        # else:
        #     butler.participants.increment(uid=participant_uid, key='head')
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
        # For testing participant embedding
        # butler.algorithms.append(key=f'{participant_uid}_embedding', value=X.tolist())

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
        