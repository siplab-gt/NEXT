import time
import numpy.random
import next.utils as utils


class MyAlg:
    def initExp(self, butler, B):
        return True

    def getQuery(self, butler):
        return True

    def processAnswer(self, butler):
        num_reported_answers = butler.algorithms.increment(
            key='num_reported_answers')
        return True

    def getModel(self, butler):
        return butler.algorithms.get(key=['X', 'num_reported_answers'])

  
        