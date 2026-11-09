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


def unrank_combinations(ranks, m, k):
    """
    Turn combination numbers into the combinations themselves, vectorized.

    Every k-subset of range(m) has one number in 0 .. C(m, k)-1 (the
    "combinatorial number system", colex order):
        rank({c_1 < c_2 < ... < c_k}) = C(c_1, 1) + C(c_2, 2) + ... + C(c_k, k)
    Decoding goes from the largest element down: c_k is the largest c with
    C(c, k) <= rank; subtract C(c_k, k) and repeat for k-1. Each step is one
    np.searchsorted over a table of m binomials, so the whole thing is
    O(len(ranks) * k * log m) time and O(len(ranks) * k) memory, with no
    enumeration of the C(m, k) subsets.

    Inputs:
        ranks: integer array of distinct or repeated numbers in [0, C(m, k))
        m: size of the ground set range(m)
        k: subset size
    Returns:
        len(ranks) x k int64 array; each row strictly increasing.
        unrank_combinations(np.arange(C(m, k)), m, k) lists every subset once,
        in the order of sorted(itertools.combinations(range(m), k), key=reversed).
    """
    total = math.comb(m, k)
    if total >= 2 ** 62:
        raise ValueError('C(%d, %d) does not fit in int64' % (m, k))
    ranks = np.array(ranks, dtype=np.int64).ravel()       # copy: modified below
    if ranks.size and (ranks.min() < 0 or ranks.max() >= total):
        raise ValueError('ranks must lie in [0, C(%d, %d)) = [0, %d)' % (m, k, total))
    out = np.empty((ranks.size, k), dtype=np.int64)
    for j in range(k, 0, -1):
        # binom[c] = C(c, j) for c in 0..m-1: non-decreasing (0 for c < j), so
        # searchsorted(side='right') - 1 is the largest c with C(c, j) <= rank
        binom = np.array([math.comb(c, j) for c in range(m)], dtype=np.int64)
        c = np.searchsorted(binom, ranks, side='right') - 1
        out[:, j - 1] = c
        ranks -= binom[c]
    return out


def sample_distinct_integers(total, size, rng):
    """
    `size` distinct integers drawn uniformly from range(total), using
    O(size) memory when size is small next to total.

    numpy's Generator.choice(replace=False) does that (Floyd's algorithm for
    small samples, a partial shuffle otherwise); the legacy RandomState.choice
    shuffles all of range(total) first. The Generator is seeded from `rng`, so
    the result is fully determined by rng's state and rng advances by a fixed
    amount (one draw of 4 integers) per call.
    """
    size = int(size)
    if size >= total:
        return np.arange(total, dtype=np.int64)
    seed = rng.randint(0, 2 ** 32, size=4, dtype=np.uint64)
    gen = np.random.Generator(np.random.PCG64(np.random.SeedSequence([int(s) for s in seed])))
    return gen.choice(total, size=size, replace=False, shuffle=False).astype(np.int64)


def candidate_queries(n, head, body_size, rate, rng):
    """
    Candidate queries for one head: the head plus a SET of body_size other
    items. Each set appears at most once; the order of a body doesn't matter
    to the score (it already sums over every ordering of the body).

    Inputs:
        n: number of items
        head: the head item
        body_size: items per body (A)
        rate: fraction of the C(n-1, body_size) possible bodies to score,
              picked uniformly at random without repeats; rate >= 1 means
              all of them (and draws nothing from rng)
        rng: numpy RandomState
    Returns:
        k x (1 + body_size) int64 array, k = ceil(C(n-1, body_size) * rate)
        clipped to [1, C(n-1, body_size)]; column 0 is the head, each body
        is in increasing item order.
    """
    m = n - 1                                    # items other than the head
    total = math.comb(m, body_size)
    k = min(total, max(1, math.ceil(total * float(rate))))
    bodies = unrank_combinations(sample_distinct_integers(total, k, rng), m, body_size)
    bodies += bodies >= head                     # 0..m-1 -> items, skipping the head
    return np.column_stack([np.full(len(bodies), head, dtype=np.int64), bodies])


def score_queries(M, queries, rng, mu, n_samples=None):
    """
    Information score of each query row ([head] + body) on the embedding M.
    n_samples None -> ceil(N/10). The distance-noise width is the spread of
    all pairwise distances in M.
    """
    dist_std = np.sqrt(np.var(pdist(M), axis=0))
    if n_samples is None:
        n_samples = math.ceil(M.shape[0] / 10)
    queries = np.asarray(queries)
    return mutual_information_batch(M, queries[:, 0], queries[:, 1:], n_samples, dist_std, mu, rng)


def select_query(M, head, body_size, rng, mu=0.05, rate=1.0, n_samples=None):
    """
    Inner loop of Algorithm 1: pick the body for `head` that maximizes the
    mutual-information score (section 3.1 of the InfoTuple paper).

    Scores a uniform random fraction `rate` of the distinct body sets (each at
    most once), takes the best, then shuffles the body with rng so the order
    shown to the participant is random rather than increasing item index.

    rng use, in order: candidate sampling (only when rate < 1), the score's
    noise, the display shuffle.

    Returns:
        selected: [head] + body as a list of python ints, body in display order
        queries: the scored candidates (k x (1 + body_size), bodies sorted)
        infogains: their scores
    """
    M = np.asarray(M, dtype=float)
    queries = candidate_queries(M.shape[0], head, body_size, rate, rng)
    infogains = score_queries(M, queries, rng, mu, n_samples)
    selected = queries[np.argmax(infogains)].copy()
    rng.shuffle(selected[1:])                    # in place on the body view
    return [int(x) for x in selected], queries, infogains

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