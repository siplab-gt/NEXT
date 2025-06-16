import next.utils as utils

class MyAlg:
    def initExp(self, butler, resourceA, resourceSample, resourceTicks, tickFlag):  
        butler.algorithms.set(key='resourceA', value=resourceA)
        butler.algorithms.set(key='resourceSample', value=resourceSample)
        butler.algorithms.set(key='resourceTicks', value=resourceTicks)
        butler.algorithms.set(key='tickFlag', value=tickFlag)
        butler.algorithms.set(key='num_reported_answers', value=0)
        return True


    def getQuery(self, butler, query_id):
        A = butler.algorithms.get(key='resourceA')[query_id]
        sample = butler.algorithms.get(key='resourceSample')[query_id]
        ticks = butler.algorithms.get(key='resourceTicks')[query_id]
        tickFlag = butler.algorithms.get(key='tickFlag')
        return {'A': A, 'sample': sample, 'ticks': ticks, 'tickFlag': tickFlag}

    def processAnswer(self, butler, answer):
        # to be implemented
        return True

    def getModel(self, butler):
        return butler.algorithms.get(key=['num_reported_answers'])

    def incremental_embedding_update(self, butler, args):
        # to be implemented
        pass

    def full_embedding_update(self, butler, args):
        # to be implemented
        pass
