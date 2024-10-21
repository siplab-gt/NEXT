import numpy as np
import numpy as np
from random import shuffle
from scipy.stats import entropy
from itertools import permutations
from collections import defaultdict
from scipy.spatial.distance import pdist
import math
import torch
from functools import reduce

from cblearn.datasets import LinearSubspace
from cblearn.embedding import SOE
import torch
import numpy as np
from functools import partial
from tqdm import tqdm
from sklearn.utils import check_random_state

# InfoTuple Specific
from infotuple.infotuple import primal_body_selector
from infotuple.infotuple import probabilistic_mds
from infotuple.infotuple import plackett_luce_data_oracle_generator, data_oracle_generator
from infotuple.infotuple import selection_algorithm

from cblearn.datasets import make_all_triplet_indices
from cblearn.datasets import triplet_response
from sklearn.metrics import pairwise
from cblearn.metrics import procrustes_distance, query_accuracy

import pandas as pd



def random_body_selector(head, M, tuples, intermediate_params=None):
    """
    Random tuple body selection, provided only as a baseline for comparison 
    """
    index = np.random.choice(len(tuples))
    return tuples[index], [], [], None


def probability_model(bdist, cdist, mu):
    """
    This is a helper method for the tuplewise probability calculation (Section 3.2)
    It computes the probability of a response for an individual 3-tuple
    bdist: Distance between a and b_i
    cdist: Distance between a and b_{i+1}
    mu: Optional parameter to specify response model
    """
    prob = (mu+cdist**2)/(2*mu + bdist**2 + cdist**2)
    return prob


def tuple_probability_model(distances, mu):
    """
    This is the tuplewise response model described in (Section 3.2)
    
    Inputs:
        distances: The precomputed set of pairwise distances between a and each body object,
        mu: Optional regularization parameter, set to 0.5 to ignore
    returns:
        tuple_probability: The probability of the specified tuple
    """
    
    probs = []

    for i in range(len(distances)-1):
        bdist = distances[i]
        cdist = distances[i+1]
        prob = probability_model(bdist, cdist, mu)
        probs.append(prob)

    tuple_probability = reduce(lambda x, y: x * y, probs)
    return tuple_probability


def mutual_information(X, head, body, n_samples, dist_std, mu, rng):
    """
    This method corresponds to the mutual information calculation specified in Section 3.1
    Specifically, the method returns the result of inputting the method parameters into formula (9).
    
    Inputs:
        X: An Nxd embedding of objects
        head: The head of the tuple comparison under consideration
        body: The body of the tuple comparison under consideration
        n_samples: Number of samples to estimate D_s as described in (A3)
        dist_std: Variance parameter as specified in (A3)
        mu: Optional regularization parameter for the probabilistic response model
    returns:
        information: Mutual information as specified in (9) in Section 3.1
    """
    n_samples = int(n_samples)
    nrank = math.factorial(len(body))
    # print(f"nrank: {nrank}")
    # print(f"n_samples: {n_samples}")
    first_term_sampled_probabilities  = np.zeros((n_samples,nrank))
    second_term_sampled_entropies = []

    for d in range(n_samples):
        p_rab = []

        for permutation in permutations(body, len(body)):
            B = permutation
            head_distances = []

            for i in range(len(body)):
                dist = abs(rng.normal(np.linalg.norm(X[head] - X[B[i]]), dist_std))
                head_distances.append(dist)

            p_rab.append(tuple_probability_model(head_distances, mu))

        normalization_constant = sum(p_rab)
        p_rab = [p / normalization_constant for p in p_rab]

        first_term_sampled_probabilities[d,:] = p_rab

        sample_entropy = -sum([p *np.log(p) for p in p_rab if p > 0])
        second_term_sampled_entropies.append(sample_entropy)

    first_term_expected_probabilities = np.sum(first_term_sampled_probabilities,axis=0) / n_samples
    first_term_expected_entropy  = -np.sum(first_term_expected_probabilities * np.log(first_term_expected_probabilities))
    second_term_expected_entropy = sum(second_term_sampled_entropies) / len(second_term_sampled_entropies)
    information = first_term_expected_entropy - second_term_expected_entropy
    
    return information

def fast_mutual_information(X, head, body, n_samples, dist_std, mu):

    ix_permutations = list(permutations(body, len(body)))
    #print(f"ix_permutations: {ix_permutations}")
    #print(f"n_samples: {n_samples}")
    first_term_sampled_probabilities  = np.zeros((n_samples,len(ix_permutations)))
    second_term_sampled_entropies = np.zeros(n_samples)

    for d in range(n_samples):

        full_distances = X[head] - X[ix_permutations]
        head_distances = abs(np.random.normal(np.linalg.norm(full_distances), dist_std, size=(len(ix_permutations), len(body))))

        windows = np.lib.stride_tricks.sliding_window_view(head_distances, 2, axis=1)
        windows = windows.reshape((windows.shape[0]*windows.shape[1],2))
        numerator = mu + (windows[:, 1])**2
        denominator = 2 * mu + windows[:,0]**2 + windows[:,1]**2

        probabilities = numerator / denominator
        p_rab = np.multiply.reduce(probabilities, axis=-1)
        p_rab /= np.sum(p_rab)
        first_term_sampled_probabilities[d,:] = p_rab

        sample_entropy = -sum([p *np.log(p) for p in probabilities if p > 0])
        second_term_sampled_entropies[d] = sample_entropy

    first_term_expected_probabilities = np.sum(first_term_sampled_probabilities,axis=0) / n_samples
    first_term_expected_entropy  = -np.sum(first_term_expected_probabilities * np.log(first_term_expected_probabilities))
    second_term_expected_entropy = sum(second_term_sampled_entropies) / len(second_term_sampled_entropies)
    information = first_term_expected_entropy - second_term_expected_entropy

    return information

def primal_body_selector(M, tuples, __, rng, mu = 0.05, tuple_downsample_rate = 0.1):
    """
    Inner loop of Algorithm 1, this method selects the tuple body that maximizes our mutual information metric
    Used at each algorithm iteration to compute an optimal query to request, as described in section 3.1.
    Inputs:
        M: Nxd coordinates with respect to which to select an informative query
        tuples: list of possible tuples over M
        __: Placeholder for the list of previous selections to standardize the method header
            across tested selection algorithms. Not used in this method.
    Returns:
    infogains, tuple_probabilities, intermediate_params
        selected_tuple: The selected informative tuple
        infogains: A list of information gains from all tuples,
                    provided for visualization purposes.
        tuple_probabilities: A list of probabilities for each tuple,
                    provided for visualization purposes
    """

    # downsample_rate = intermediate_params['tuple_downsample_rate']
    # TODO: pass in argument from infotuple caller
    tuples = list(tuples)
    downsample_rate = 1
    downsample_indices = rng.choice(range(len(tuples)), int(len(tuples)*downsample_rate), replace=False)
    tuples = [tuples[i] for i in downsample_indices]

    tuple_probabilities = np.ones(len(tuples))
    infogains = np.zeros(len(tuples))
   

    distances = pdist(M)
    dist_std  = np.sqrt(np.var(distances, axis=0))

    for i in range(len(tuples)):
        a = tuples[i][0]
        B = tuples[i][1:]

        infogains[i] = mutual_information(M, a, B, int(M.shape[0]/10), dist_std, mu, rng)

    selected_tuple = tuples[np.argmax(infogains)]

    return selected_tuple, infogains, tuple_probabilities

def sliding_window(arr, window_size, random_state=None):
    arr_extended = np.concatenate((arr, arr[:window_size-1]))
    shape = (arr.shape[0], window_size)
    strides = (arr.strides[0], arr.strides[0])
    result = np.lib.stride_tricks.as_strided(arr_extended, shape=shape, strides=strides)
    result = np.roll(result, -1, axis=0)

    # Initialize a random generator
    # If random_state is a RandomState instance, extract the seed
    if isinstance(random_state, np.random.RandomState):
        random_state = random_state.get_state()[1][0]
        
    rng = np.random.default_rng(random_state)

    # Define a function to shuffle elements from index 1 onwards
    def shuffle_from_index_1(subarray):
        rng.shuffle(subarray[1:])
        return subarray

    # Apply the function along the first axis
    result = np.apply_along_axis(shuffle_from_index_1, 1, result)

    return result


def random_tuple_sampler(n, tuple_size, random_state=None):
    # Generate an array of n elements
    x = np.arange(n)

    # Call the sliding_window function with window_size = n - 1
    result = sliding_window(x, n - 1, random_state)

    # Take the first tuple_size elements from each tuple
    sampled_tuples = result[:, :tuple_size]
    sampled_tuples = np.roll(sampled_tuples, 1, axis=0)
    return sampled_tuples

#############################################################################################
### selection algorithms file
#############################################################################################
"""
    
    This file contains code corresponding to a generalized version of Algorithm 1 from Section 3.4    
    The parametrization of the crowd oracle, metric learner, and body selector is intended for the ease of 
    Iterating over the different selection strategies tested in this paper.
"""

import numpy as np
from scipy.spatial.distance import pdist, squareform
from itertools import permutations
from collections import defaultdict
from tqdm import tqdm, trange

def selection_algorithm(M, R, body_selector, rng, tuple_size=3, verbose_output=True):

    """
    Inputs:
        M: An initial Nxd embedding from which an initial similarity matrix can be calculated
        R: An initial number of ``burn-in'' iterations to initialize the similarity matrix
        body_selector: A function that takes as input a set of candidate tuples and chooses one
        tuple_size: The size of tuples to be considered
    Returns:
        M: An embedding that captures the selected ordinal constraints
    """

    n = range(len(M))

    initial_constraints = []
    #print(f"Starting Burnin")
    for _ in range(R):
        for h in range(len(M)):
            candidate_tuple = [h]+list(rng.choice(n, tuple_size-1, replace=False))
            
            for i in range(len(oracle_sorted_tuple)-2):
                pairwise_comparison = (oracle_sorted_tuple[0], oracle_sorted_tuple[i+1], oracle_sorted_tuple[i+2])
                initial_constraints.append(pairwise_comparison)
    previous_selections = defaultdict(list)

    for constraint in initial_constraints:
        head, body = constraint[0], constraint[1:]
        previous_selections[head].append(constraint)

    constraints = list(initial_constraints)
    #print(f"Burn-in done, starting main loop")

    for a in range(len(M)):
    candidates = permutations(filter(lambda x: x is not a, n), tuple_size - 1)
    tuples = map(lambda x: [a] + list(x), candidates)
    # M_as_numpy = M.cpu().detach().numpy()
    # selected_tuple, tuple_qualities, tuple_probabilities, intermediate_params = body_selector(a, M_as_numpy, tuples, previous_selections)
    selected_tuple, tuple_qualities, tuple_probabilities, intermediate_params = body_selector(M_prime, tuples, previous_selections, rng=rng)

    previous_selections[a].append(selected_tuple)
    constraints.append(oracle_sorted_tuple)
    new_constraints = []
    for c in constraints:
        for ix in range(len(oracle_sorted_tuple)-2):
            pairwise_comparison = (c[0], c[ix+1], c[ix+2])
            new_constraints.append(pairwise_comparison)
    return M_prime

########################################################################################