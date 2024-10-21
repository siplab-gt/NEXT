# Copyright (C) 2021 Georgia Tech Research Corporation. All rights reserved.

#############################################################################################
### body metrics file
#############################################################################################
"""
    This file contains methods for calculating the probability of a tuplewise ranking
    and the information provided by a tuple query. Relevant references describing
    in detail these procedures and the requisite assumptions are found in Sections 3.1 and 3.2.
"""

import numpy as np
from random import shuffle
from scipy.stats import entropy
from itertools import permutations
from collections import defaultdict
from scipy.spatial.distance import pdist
import math
import torch
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

def primal_body_selector(M, tuples, __, rng, intermediate_params={'mu':0.05, 'tuple_downsample_rate':0.1, 'dist_cache':{}}):
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
   
    mu = intermediate_params['mu']

    distances = pdist(M)
    dist_std  = np.sqrt(np.var(distances, axis=0))

    for i in range(len(tuples)):
        a = tuples[i][0]
        B = tuples[i][1:]

        infogains[i] = mutual_information(M, a, B, int(M.shape[0]/10), dist_std, mu, rng)

    selected_tuple = tuples[np.argmax(infogains)]

    return selected_tuple, infogains, tuple_probabilities, intermediate_params

#############################################################################################
### metric learners file
#############################################################################################
"""
    This file contains the embedding technique presented in Section 3.4
"""

import numpy as np
from scipy import linalg
from copy import copy

def empirical_loss(X, constraints, mu):
    """
    A helper function to compute empirical loss
    """
    empirical_loss = 0.

    for query in constraints:
        i, j, k = query
        a, b, c = X[i], X[j], X[k]
        
        ab_dist = np.linalg.norm(b - a)
        ac_dist = np.linalg.norm(c - a)
        
        if ab_dist > ac_dist:
            empirical_loss += 1.
    
    empirical_loss = 1. - (empirical_loss/len(constraints))

    return empirical_loss

def log_loss(X, constraints, mu):
    """
    A helper function to compute empirical log loss
    """

    log_loss = 0.

    for query in constraints:
        i, j, k = query
        a, b, c = X[i], X[j], X[k]
        
        ab_dist = np.linalg.norm(b - a)
        ac_dist = np.linalg.norm(c - a)
        log_loss -= np.log((mu+ac_dist)/(2*mu+ab_dist+ac_dist)) 
         
    log_loss = log_loss/len(constraints)
    
    return log_loss

def gradient(X, constraints, mu):
    """
    Analytic gradient calculation reliant on the response model proposed in 3.2
    """

    n, d = X.shape
    grad = np.zeros((n,d))
    grad = torch.from_numpy(grad)
    
    for query in constraints:
        i,j,k   = query
        a, b, c = X[i], X[j], X[k]
        
        ab_dist = np.linalg.norm(b-a)
        ac_dist = np.linalg.norm(c-a)
        
        grad[i] += 2 * (a-b)/(2* mu + ab_dist**2 + ac_dist**2) 
        grad[j] += 2 * ((a-c)/(mu+ac_dist**2) - (a-c)/(2*mu + ab_dist**2 + ac_dist**2))
        grad[k] += 2 * ((a-c)/(mu + ac_dist**2) - (2*a - b - c)/(2*mu + ab_dist**2 + ac_dist**2))
        
    grad *= -1./len(constraints)
   
    return grad

def probabilistic_mds(X, constraints, evaluation_constraints=None, loss=empirical_loss, mu=.5, n_iterations=5000, learning_rate=1., momentum=0., verbose=True):
    """
    Inputs:
        X: initial estimate of an Nxd embedding
        constraints: List of ordinal constraints to be preserved in the final embedding
    """

    best_X = copy(X)
    best_loss = loss(best_X, constraints, mu) 
    n, d = X.shape
    curr_X = best_X
    
    decomposed_queries = []

    for query in constraints:
        for i in range(1,len(query)-1):
            pairwise_comparison = (query[0], query[i], query[i+1])
            decomposed_queries.append(pairwise_comparison) 
   
    constraints = decomposed_queries
    n_iterations = max(1, n_iterations)

    prev_grad = np.zeros((n,d))
    
    for epoch in range(n_iterations):
       
        grad = gradient(curr_X, constraints, mu)
        curr_X -= (learning_rate * grad + momentum * prev_grad)
        prev_grad = grad
        
        curr_X = curr_X / np.linalg.norm(curr_X)

        if evaluation_constraints is not None:
            evaluation_loss = loss(curr_X, evaluation_constraints, mu)
    
            if evaluation_loss < loss(curr_X, evaluation_constraints, mu):
                best_X = curr_X
                best_loss = iteration_loss

        else:
            iteration_loss = loss(curr_X, constraints, mu)
            
            if iteration_loss  < best_loss:
                best_X = curr_X
                best_loss = iteration_loss

    # if verbose:
    #     print "loss: ", best_loss
    
    return best_X

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
from sklearn.utils import check_random_state

def selection_algorithm(M, R, T, crowd_oracle, metric_learner, body_selector, rng, tuple_size=3, verbose_output=True):

    """
    Inputs:
        M: An initial Nxd embedding from which an initial similarity matrix can be calculated
        R: An initial number of ``burn-in'' iterations to initialize the similarity matrix
        T: A number of iterations
        crowd_oracle: An oracle function that takes as input a tuple and returns a ranking.
        metric_learner: A function that takes as inputs a set of ordinal constraints and outputs an Nxd embedding
                        that implicitly corresponds to a similarity function preserving those constraints
        body_selector: A function that takes as input a set of candidate tuples and chooses one
        tuple_size: The size of tuples to be considered
    Returns:
        M: An embedding that captures the selected ordinal constraints
    """
    if verbose_output:
        Ms, selections, selection_qualities, oracled = [], [], [], []
    
    #rng = check_random_state(seed)

    n = range(len(M))

    initial_constraints = []
    #print(f"Starting Burnin")
    for _ in range(R):
        for h in range(len(M)):
            candidate_tuple = [h]+list(rng.choice(n, tuple_size-1, replace=False))
            oracle_sorted_tuple = crowd_oracle(candidate_tuple)
            
            for i in range(len(oracle_sorted_tuple)-2):
                pairwise_comparison = (oracle_sorted_tuple[0], oracle_sorted_tuple[i+1], oracle_sorted_tuple[i+2])
                initial_constraints.append(pairwise_comparison)
                if verbose_output:
                    oracled.append(oracle_sorted_tuple)
    M_prime = metric_learner.fit_transform(initial_constraints, n_objects=len(M), init=M)
    previous_selections = defaultdict(list)

    for constraint in initial_constraints:
        head, body = constraint[0], constraint[1:]
        previous_selections[head].append(constraint)

    constraints = list(initial_constraints)
    #print(f"Burn-in done, starting main loop")
    for i in trange(T, leave=False):

        if verbose_output:
            Ms.append(M_prime)

        for a in range(len(M)):
            candidates = permutations(filter(lambda x: x is not a, n), tuple_size - 1)
            tuples = map(lambda x: [a] + list(x), candidates)
            # M_as_numpy = M.cpu().detach().numpy()
            # selected_tuple, tuple_qualities, tuple_probabilities, intermediate_params = body_selector(a, M_as_numpy, tuples, previous_selections)
            selected_tuple, tuple_qualities, tuple_probabilities, intermediate_params = body_selector(M_prime, tuples, previous_selections, rng=rng)
            
            previous_selections[a].append(selected_tuple)
            oracle_sorted_tuple = crowd_oracle(selected_tuple)
            constraints.append(oracle_sorted_tuple)

            if verbose_output:
                selections.append(selected_tuple)
                selection_qualities.append(tuple_qualities)
                oracled.append(oracle_sorted_tuple)

        new_constraints = []
        for c in constraints:
            for ix in range(len(oracle_sorted_tuple)-2):
                pairwise_comparison = (c[0], c[ix+1], c[ix+2])
                new_constraints.append(pairwise_comparison)

        M_prime = metric_learner.fit_transform(new_constraints, n_objects=len(M), init=M_prime)

    if verbose_output:
        Ms.append(M_prime)
        return Ms, (initial_constraints, np.array(selections)), selection_qualities, oracled

    return M_prime

########################################################################################
# driver for infotuple
def run_infotuple(oracle):
    print("Running infotuple from command line...")

    # create a set of random vectors in the required embedding size
    n = 10
    dim = 5
    device = 'cpu'
    X = torch.rand(size=(n, dim), dtype=torch.float).to(device)
    # X = torch.rand(size=(n, dim)).to(device)
    # X = np.ndarray(X)

    selection_algorithm(X, 1, 1, oracle, probabilistic_mds, primal_body_selector)

    print("Finished running")

# give a random ordering for a tuple query
# just for command line functionality
# just reverses the body of the original tuple
def random_oracle(some_tuple):
    # print(some_tuple)
    # some_tuple = tuple(some_tuple[0], *(some_tuple[:0:-1]))
    # print(some_tuple)
    new_tuple = some_tuple[0], some_tuple[2], some_tuple[1]
    return new_tuple

#run_infotuple(random_oracle)
import numpy as np
from scipy.spatial.distance import pdist, squareform
from itertools import permutations
import random

def data_oracle_generator(true_points, failure_prob=0.1):
    """
    This method  returns an oracle function that responds to tuplewise ranking queries
    of the form "which of b_1, ..., b_n is closer to a in the true embedding space"
    without any additional noise.
    Input:
        true_points: ``true'' embedding coordinates for an object set
    Returns:
        oracle: A function that accepts a tuple and returns an oracle response ranking 
    """
    oracle = lambda x: [x[0]] + sorted(x[1:], key=lambda a:np.sqrt(np.sum((true_points[x[0]]-true_points[a])**2)))
    return oracle

import numpy as np

def vectorized_data_oracle_generator(true_points, failure_prob=0.1):
    """
    This method returns an oracle function that responds to tuplewise ranking queries
    of the form "which of b_1, ..., b_n is closer to a in the true embedding space"
    without any additional noise.
    
    Input:
        true_points: ``true'' embedding coordinates for an object set
    Returns:
        oracle: A function that accepts a tuple and returns an oracle response ranking 
    """
    
    def oracle(x):
        ref_point = true_points[x[0]]
        candidates = np.array(x[1:])
        # Compute the squared differences
        differences = true_points[candidates] - ref_point
        # Calculate distances using vectorized operations
        distances = np.sqrt(np.sum(differences ** 2, axis=1))
        # Sort candidates based on computed distances
        sorted_indices = np.argsort(distances)
        sorted_candidates = candidates[sorted_indices]
        return [x[0]] + sorted_candidates.tolist()

    return oracle


def plackett_luce_data_oracle_generator(true_points, rng, P=0.95, failure_prob=0.05):
    """
    
    This method  returns an oracle function that responds to tuplewise ranking queries
    of the form "which of b_1, ..., b_n is closer to a in the true embedding space"
    according to the Plackett-Luce model specified in Section 4.1
   
    Inputs:
        true_points: ``true'' embedding coordinates for an object set
        P: percentile encompassing all distances in true_points
    Returns:
        oracle: A function that accepts a tuple and returns an oracle response ranking 
    
    """
    
    if failure_prob != None:
        P = 1. - failure_prob

    all_distances = pdist(true_points)
    alpha = -np.log(1-P)/float(np.log(max(all_distances)+1))
    
    pareto = lambda x: alpha/float((x+1)**(alpha+1))
    
    def probabilistic_oracle(x):
        distances = np.sqrt([sum((true_points[x[0]] - true_points[x[i]])**2) for i in range(1, len(x))])
        pmf_unnorm = [pareto(z) for z in distances];
        
        response = [x[0]]
        candidates = list(x[1:])
        while len(candidates) > 0:
            pmf = np.array(pmf_unnorm)/float(sum(pmf_unnorm))
            close_idx = rng.choice(range(len(candidates)),p=pmf)
            response.append(candidates.pop(close_idx))
            del pmf_unnorm[close_idx]
            
        return tuple(response)

    return probabilistic_oracle


import numpy as np
from scipy.spatial.distance import pdist
import numpy.random as rng

def vectorized_plackett_luce_data_oracle_generator(true_points, rng, P=0.95, failure_prob=0.05):
    """
    This method returns an oracle function that responds to tuplewise ranking queries
    of the form "which of b_1, ..., b_n is closer to a in the true embedding space"
    according to the Plackett-Luce model specified in Section 4.1
   
    Inputs:
        true_points: ``true'' embedding coordinates for an object set
        P: percentile encompassing all distances in true_points
    Returns:
        oracle: A function that accepts a tuple and returns an oracle response ranking 
    """
    
    if failure_prob is not None:
        P = 1. - failure_prob

    all_distances = pdist(true_points)
    alpha = -np.log(1 - P) / float(np.log(max(all_distances) + 1))

    def pareto(x):
        return alpha / float((x + 1) ** (alpha + 1))
    
    def probabilistic_oracle(x):
        ref_point = true_points[x[0]]
        candidates = np.array(x[1:])
        # Compute the squared differences
        differences = true_points[candidates] - ref_point
        # Calculate distances using vectorized operations
        distances = np.sqrt(np.sum(differences ** 2, axis=1))
        # Calculate the Pareto distribution for each distance
        pmf_unnorm = np.array([pareto(z) for z in distances])
        
        response = [x[0]]
        while len(candidates) > 0:
            # Normalize the PMF
            pmf = pmf_unnorm / pmf_unnorm.sum()
            # Choose index based on PMF
            close_idx = rng.choice(len(candidates), p=pmf)
            response.append(candidates[close_idx])
            # Remove the selected candidate
            candidates = np.delete(candidates, close_idx)
            pmf_unnorm = np.delete(pmf_unnorm, close_idx)

        return tuple(response)

    return probabilistic_oracle
