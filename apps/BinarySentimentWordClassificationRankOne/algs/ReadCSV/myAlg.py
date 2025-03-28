import time
import numpy.random
import next.utils as utils


class MyAlg:
    def initExp(self, butler, n, d, failure_probability):
        X = numpy.random.randn(n, d)
        butler.algorithms.set(key='n', value=n)
        butler.algorithms.set(key='d', value=d)
        butler.algorithms.set(key='delta', value=failure_probability)
        butler.algorithms.set(key='X', value=X.tolist())
        butler.algorithms.set(key='num_reported_answers', value=0)
        return True

    def getQuery(self, butler):
        return True

    def processAnswer(self, butler):
        num_reported_answers = butler.algorithms.increment(
            key='num_reported_answers')
        return True

    def getModel(self, butler):
        return butler.algorithms.get(key=['X', 'num_reported_answers'])

  
        