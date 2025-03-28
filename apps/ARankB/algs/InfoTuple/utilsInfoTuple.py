import numpy as np
from itertools import permutations
from scipy.spatial.distance import pdist
import math
from functools import reduce



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
    n_samples = min(int(n_samples), 1)
    
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

def primal_body_selector(M, tuples, rng, mu = 0.05, tuple_downsample_rate = 0.1):
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
########################################################################################