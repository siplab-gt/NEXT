import numpy as np
from itertools import permutations
from scipy.spatial.distance import pdist
import math
from math import ceil
from functools import reduce
from scipy.special import xlogy



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


# Upper bound on the floats held per working array in mutual_information_batch
# (~16 MB at float64). Candidates are scored in chunks sized to stay under it,
# so memory doesn't grow with n_samples or the downsample rate.
MI_CHUNK_ELEMENTS = 2000000


def mutual_information_batch(X, heads, bodies, n_samples, dist_std, mu, rng):
    """
    Score many candidate queries at once (formula (9) of the InfoTuple paper,
    estimated by Monte Carlo as in its Algorithm 1).

    One sample is one plausible version of the head-to-body distances: each
    distance is drawn from N(embedding distance, dist_std^2), and that one set
    of draws is shared by every ordering of the body. The score is
        H(average over samples of p(ranking))  -  average over samples of H(p(ranking))
    i.e. how much the samples disagree about the answer, beyond the noise in
    the answer itself. It needs >= 2 samples to be non-zero.

    Inputs:
        X: An Nxd embedding of objects
        heads: length-T array of head indices (one per candidate)
        bodies: TxK array of body indices
        n_samples: Number of samples per candidate (floored at 1)
        dist_std: Std of the distance noise (A3)
        mu: Regularization parameter of the response model
        rng: numpy RandomState; consumes T*n_samples*K normals, drawn in
             candidate order so the result doesn't depend on chunking
    returns:
        information: length-T array of scores
    """
    X = np.asarray(X, dtype=float)
    heads = np.asarray(heads, dtype=int)
    bodies = np.asarray(bodies, dtype=int)
    n_samples = max(int(n_samples), 1)
    T, K = bodies.shape
    orders = np.array(list(permutations(range(K))))           # K! x K
    chunk = max(1, MI_CHUNK_ELEMENTS // (n_samples * len(orders) * K))

    information = np.empty(T)
    for start in range(0, T, chunk):
        h = heads[start:start + chunk]
        b = bodies[start:start + chunk]
        # true head-to-body distances in the current embedding: c x K
        dist = np.linalg.norm(X[h][:, None, :] - X[b], axis=-1)
        noise = rng.normal(0.0, dist_std, size=(len(b), n_samples, K))
        sq = (dist[:, None, :] + noise) ** 2                  # c x S x K
        sq = sq[..., orders]                                  # c x S x K! x K
        # tuple_probability_model for every ordering: product over adjacent pairs
        p = np.prod((mu + sq[..., 1:]) / (2 * mu + sq[..., :-1] + sq[..., 1:]), axis=-1)
        p /= p.sum(axis=-1, keepdims=True)                    # c x S x K!
        within = -xlogy(p, p).sum(axis=-1).mean(axis=1)
        pooled = p.mean(axis=1)
        information[start:start + chunk] = -xlogy(pooled, pooled).sum(axis=-1) - within
    return information


def mutual_information(X, head, body, n_samples, dist_std, mu, rng):
    """
    Score a single (head, body) query; see mutual_information_batch.
    """
    return float(mutual_information_batch(X, [head], [list(body)], n_samples,
                                          dist_std, mu, rng)[0])


def primal_body_selector(M, tuples, rng, mu = 0.05, tuple_downsample_rate = 0.1,
                         n_samples = None):
    """
    Inner loop of Algorithm 1, this method selects the tuple body that maximizes our mutual information metric
    Used at each algorithm iteration to compute an optimal query to request, as described in section 3.1.
    Inputs:
        M: Nxd coordinates with respect to which to select an informative query
        tuples: list of possible tuples over M ([head] + body)
        rng: numpy RandomState
        mu: Regularization parameter of the response model
        tuple_downsample_rate: Fraction of the tuples to score (picked at random)
        n_samples: Samples per candidate for the information estimate;
                   None -> ceil(N/10)
    Returns:
        selected_tuple: The selected informative tuple
        infogains: A list of information gains from all scored tuples,
                    provided for visualization purposes.
        tuple_probabilities: A list of probabilities for each tuple,
                    provided for visualization purposes
    """
    tuples = list(tuples)
    downsample_rate = float(tuple_downsample_rate)
    downsample_indices = rng.choice(range(len(tuples)), math.ceil(len(tuples)*downsample_rate), replace=False)
    tuples = [tuples[i] for i in downsample_indices]

    tuple_probabilities = np.ones(len(tuples))

    distances = pdist(M)
    dist_std  = np.sqrt(np.var(distances, axis=0))
    if n_samples is None:
        n_samples = math.ceil(M.shape[0]/10)

    arr = np.asarray(tuples, dtype=int)
    infogains = mutual_information_batch(M, arr[:, 0], arr[:, 1:], n_samples, dist_std, mu, rng)

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
########################################################################################