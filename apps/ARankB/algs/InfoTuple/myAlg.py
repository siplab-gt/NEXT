import time
import numpy as np
from apps.ARankB.algs.InfoTuple import utilsInfoTuple
import next.utils as utils
from itertools import permutations
from cblearn.embedding import SOE
from sklearn.utils import check_random_state

class MyAlg:
    def initExp(self, butler, A, B, n, d, failure_probability, iteration,
                burn_in_period, down_sample_rate, mu):
        #Algo Specific
        butler.algorithms.set(key='mu', value=mu)
        butler.algorithms.set(key='down_sample_rate', value=down_sample_rate)
        seed = np.random.RandomState(42)
        butler.algorithms.set(key='seed', value=seed)
        embedder = SOE(n_components=d, random_state=seed, n_init=10, backend='torch', max_iter=20, margin=5) # Embedding algorithm to get the embeddings
        butler.algorithms.set(key='embedder', value=embedder)
        butler.algorithms.set(key='responses', value=list()) #store all responses in list
        
    
        #Set parameters A, B in bulter.algo
        butler.algorithms.set(key='A', value=A) #query length
        butler.algorithms.set(key='B', value=B) #answer length
        butler.algorithms.set(key='delta', value=failure_probability)
        butler.algorithms.set(key='num_reported_answers', value=0)
        butler.algorithms.set(key='burn_in', value=burn_in_period)
        butler.algorithms.set(key='iteration', value=iteration)
        X = np.random.rand(n,  d)
        butler.algorithms.set(key='X', value=X)
       
        return True


    def getQuery(self, butler, participant_uid):
        #Gather necessary parameters for getQuery
        A = butler.algorithms.get(key='A')
        X = np.array(butler.participants.get(key='X'))
        burn_in = butler.algorithms.get(key='burn_in')
        seed = butler.algorithms.get(key='seed')
        rng = check_random_state(seed)

        n, d = X.shape
        
        if not butler.participants.exists(key=participant_uid+'_embedding'):
            X_part = np.random.rand(n,  d)
            butler.participants.set(key=participant_uid+'_embedding', value=X_part)
            butler.participants.set(key=participant_uid+'_head', value=0)
            butler.participants.set(key=participant_uid+'_responses', value=list()) #store all personal responses
            butler.participants.set(key=participant_uid+'_curr_iteration', value=0)
        
        #Check burn_in
        selected_tuple = None
        h = butler.participants.get(key=participant_uid+'_head')
        if butler.participants.get(key=participant_uid+'_curr_iteration') < burn_in:
            selected_tuple = [h]+list(rng.choice(n, A-1, replace=False))
        else: 
            candidates = permutations(filter(lambda x: x is not h, range(n)), A-1)
            tuples = map(lambda x: [h] + list(x), candidates)
            selected_tuple, tuple_qualities, tuple_probabilities = utilsInfoTuple.primal_body_selector(X, tuples, rng)
        return selected_tuple

    def processAnswer(self, butler, target_winner, participant_uid):
        #Gather necessary parameters for processAnswer
        X = np.array(butler.algorithms.get(key='X'))
        n, d = X.shape
        h = butler.participants.get(key=participant_uid+'_head')
        iteration = butler.algorithms.get(key='iteration')
        curr_iteration = butler.participants.get(key=participant_uid+'_curr_iteration')
        
        for i in range(len(target_winner)-2):
            pairwise_comparison = (target_winner[0], target_winner[i+1], target_winner[i+2])
            butler.participants.append(key=participant_uid+'_responses', value=pairwise_comparison)
            butler.algorithms.append(key='responses', value=pairwise_comparison)
        
        num_reported_answers = butler.algorithms.increment(
            key='num_reported_answers')
       
        if h == n - 1:
            butler.job('incremental_embedding_update', {}, time_limit=30)
        else:
            butler.job('full_embedding_update', {}, time_limit=5)
        
        #Update participant parameters
        if h == n - 1:
            if curr_iteration == iteration - 1:
                # Update overall embedding
                butler.job('full_embedding_update', {}, time_limit=30)
            else:
                # Update participant's own embedding
                butler.job('incremental_embedding_update', {}, time_limit=30)
            butler.participants.set(key=participant_uid+'_head', value=0)
            butler.participants.increment(key=participant_uid+'_curr_iteration')
        else:
            butler.participants.increment(key=participant_uid+'_head')
            
        return True

    def getModel(self, butler):
        return butler.algorithms.get(key=['X', 'num_reported_answers'])

    def incremental_embedding_update(self, butler, args):
        participant_uid = args.get('participant_uid', butler.exp_uid)
        responses = butler.participants.get(key=participant_uid+'_responses')
        embedder = butler.algorithms.get(key='embedder')
        X = np.array(butler.participants.get(key='X'))
        n, d = X.shape
        # set maximum time allowed to update embedding
        # t_max = 1.0
        # take a single gradient step
        #t_start = time.time()
        #while (time.time()-t_start < 0.5*t_max):
        X = embedder.fit_transform(responses, n_objects=n, init=X)
        butler.participants.set(key='X', value=X.tolist())

    def full_embedding_update(self, butler, args):
        responses = butler.algorithms.get(key='responses')
        embedder = butler.algorithms.get(key='embedder')
        X = np.array(butler.algorithms.get(key='X'))
        n, d = X.shape
        X = embedder.fit_transform(responses, n_objects=n, init=X)
        butler.algorithms.set(key='X', value=X.tolist())
