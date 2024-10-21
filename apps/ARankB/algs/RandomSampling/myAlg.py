import time
import numpy.random
import numpy as np
from apps.ARankB.algs.RandomSampling import utilsMDS
import next.utils as utils





class MyAlg:
    def initExp(self, butler, A, B, n, d, failure_probability):
        X = numpy.random.randn(n, d)
        
        #Set parameters A, B in bulter.algo
        butler.algorithms.set(key='A', value=A)
        butler.algorithms.set(key='B', value=B)
        
        butler.algorithms.set(key='n', value=n)
        butler.algorithms.set(key='d', value=d)
        butler.algorithms.set(key='delta', value=failure_probability)
        butler.algorithms.set(key='X', value=X.tolist())
        butler.algorithms.set(key='num_reported_answers', value=0)
        return True


    def getQuery(self, butler):
        X = numpy.array(butler.algorithms.get(key='X'))
        A = numpy.array(butler.algorithms.get(key='A'))
        q, score = utilsMDS.getRandomQuery(X, A+1)
        return q

    def processAnswer(self, butler, target_winner):
        anchor = target_winner[0]
        targets = target_winner[1:]
        #Optimizable with np.meshgrid 
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
        X = numpy.array(butler.algorithms.get(key='X'))
        # set maximum time allowed to update embedding
        t_max = 1.0
        epsilon = 0.01  # a relative convergence criterion, see computeEmbeddingWithGD documentation
        # take a single gradient step
        t_start = time.time()
        X, emp_loss_new, hinge_loss_new, acc = utilsMDS.computeEmbeddingWithGD(
            X, S, max_iters=1)
        k = 1
        while (time.time()-t_start < 0.5*t_max) and (acc > epsilon):
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
