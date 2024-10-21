import time
import numpy.random
import numpy as np
from apps.ARankB.algs.InfoTuple import utilsInfoTuple
import next.utils as utils
from scipy.spatial.distance import pdist, squareform
from itertools import permutations
from collections import defaultdict
from tqdm import tqdm, trange
from cblearn.datasets import LinearSubspace
from cblearn.embedding import SOE
import torch
import numpy as np
from functools import partial
from tqdm import tqdm
from sklearn.utils import check_random_state

#InfoTuple Specific implementation
from infotuple.infotuple import primal_body_selector
from infotuple.infotuple import probabilistic_mds
from infotuple.infotuple import plackett_luce_data_oracle_generator, data_oracle_generator
from infotuple.infotuple import selection_algorithm

from cblearn.datasets import make_all_triplet_indices
from cblearn.datasets import triplet_response
from sklearn.metrics import pairwise
from cblearn.metrics import procrustes_distance, query_accuracy

import pandas as pd

class MyAlg:
    def initExp(self, butler, A, B, n, d, failure_probability, 
                burn_in_period, down_sample_rate, mu):
        X = numpy.random.randn(n, d)
        #Set parameters A, B in bulter.algo
        butler.algorithms.set(key='A', value=A) #query length
        butler.algorithms.set(key='B', value=B) #answer length
        
        butler.algorithms.set(key='n', value=n)
        butler.algorithms.set(key='d', value=d)
        butler.algorithms.set(key='delta', value=failure_probability)
        butler.algorithms.set(key='X', value=X.tolist())  #embedding
        butler.algorithms.set(key='num_reported_answers', value=0)
        
        #Algo Specific
        butler.algorithms.set(key='mu', value=mu)
        butler.algorithms.set(key='burn_in_period', value=burn_in_period)
        butler.algorithms.set(key='down_sample_rate', value=down_sample_rate)
        butler.algorithms.set(key='currebt_head', value=0)
        seed = np.random.RandomState(42)
        butler.algorithms.set(key='seed', value=seed)
        embedder = SOE(n_components=d, random_state=seed, n_init=10, backend='torch', max_iter=20, margin=5) # Embedding algorithm to get the embeddings
        butler.algorithms.set(key='embedder', value=embedder)
        
        return True


    def getQuery(self, butler):
        X = numpy.array(butler.algorithms.get(key='X'))
        A = numpy.array(butler.algorithms.get(key='A'))
        seed = butler.algorithms.get(key='seed')
        n, d = X.shape

        head = butler.algorithms.get(key='currebt_head')
        candidates = permutations(filter(lambda x: x is not head, range(n)), A - 1)
        tuples = map(lambda x: [head] + list(x), candidates)
        rng = check_random_state(seed)
        # M_as_numpy = M.cpu().detach().numpy()
        # selected_tuple, tuple_qualities, tuple_probabilities, intermediate_params = body_selector(a, M_as_numpy, tuples, previous_selections)
        selected_tuple, tuple_qualities, tuple_probabilities = utilsInfoTuple.primal_body_selector(X, tuples, rng)
        return selected_tuple

    def processAnswer(self, butler, target_winner):
        anchor = target_winner[0]
        targets = target_winner[1:]
        pairs = [(x, y) for i, x in enumerate(targets) for y in targets[i+1:]]
        triplets = [(x, y, anchor) for (x, y) in pairs]
       
        butler.algorithms.extend(key='S', value=triplets)
        n = butler.algorithms.get(key='n')
        num_reported_answers = butler.algorithms.increment(
            key='num_reported_answers')
        if num_reported_answers % int(n) == 0:
            butler.job('full_embedding_update', {}, time_limit=30)
        else:
            butler.job('incremental_embedding_update', {}, time_limit=5)
        return True

    def getModel(self, butler):
        return butler.algorithms.get(key=['X', 'num_reported_answers'])

    def incremental_embedding_update(self, butler, args):
        S = butler.algorithms.get(key='S')
        embedd = butler.algorithms.get(key='embedder')
        X = numpy.array(butler.algorithms.get(key='X'))
        # set maximum time allowed to update embedding
        t_max = 1.0
        epsilon = 0.01  # a relative convergence criterion, see computeEmbeddingWithGD documentation
        # take a single gradient step
        t_start = time.time()
        while (time.time()-t_start < 0.5*t_max):
            X, emp_loss_new, hinge_loss_new, acc = utilsMDS.computeEmbeddingWithGD(
                X, S, max_iters=2**k)
            k += 1
        butler.algorithms.set(key='X', value=X.tolist())

    def full_embedding_update(self, butler, args):
        n = butler.algorithms.get(key='n')
        d = butler.algorithms.get(key='d')
        S = butler.algorithms.get(key='S')

        X_old = numpy.array(butler.algorithms.get(key='X'))

        t_max = 5.0
        epsilon = 0.01  # a relative convergence criterion, see computeEmbeddingWithGD documentation

        emp_loss_old, hinge_loss_old = utilsMDS.getLoss(X_old, S)
        X, tmp = utilsMDS.computeEmbeddingWithEpochSGD(
            n, d, S, max_num_passes=16, epsilon=0, verbose=False)
        t_start = time.time()
        X, emp_loss_new, hinge_loss_new, acc = utilsMDS.computeEmbeddingWithGD(
            X, S, max_iters=1)
        k = 1
        while (time.time()-t_start < 0.5*t_max) and (acc > epsilon):
            X, emp_loss_new, hinge_loss_new, acc = utilsMDS.computeEmbeddingWithGD(
                X, S, max_iters=2**k)
            k += 1
        emp_loss_new, hinge_loss_new = utilsMDS.getLoss(X, S)
        if emp_loss_old < emp_loss_new:
            X = X_old
        butler.algorithms.set(key='X', value=X.tolist())
