"""Regularized Perrin spherical splines for display-only sensor fields.

Perrin et al. (1989), doi:10.1016/0013-4694(89)90180-6.
Kernel parameters follow MNE-Python's spherical-spline implementation:
m=4, 50 Legendre terms, diagonal regularization 1e-5. See EEG_TOPOGRAPHY.md.
"""
import numpy as np
from numpy.polynomial.legendre import legval
from scipy.linalg import solve


def spline_kernel(cosine):
    orders = np.arange(1., 51.)
    factors = (2*orders + 1) / (4*np.pi * (orders*(orders+1))**4)
    return legval(np.clip(cosine, -1., 1.), np.r_[0., factors])


def spherical_spline_matrix(source, target, regularization=1e-5, dtype=np.float64):
    """Map unit-sphere source values to targets, with a constant-preserving term.

    Source and target coordinates must have the same origin. Small target
    batches bound temporary memory for dense montages and high-resolution maps.
    """
    source, target = np.asarray(source, dtype=float), np.asarray(target, dtype=float)
    if (source.ndim != 2 or target.ndim != 2 or source.shape[1] != 3 or target.shape[1] != 3
            or len(source) < 3 or not np.isfinite(source).all() or not np.isfinite(target).all()
            or not np.isfinite(regularization) or regularization < 0):
        raise ValueError('Invalid spherical-spline coordinates or regularization')
    norms_from = np.linalg.norm(source, axis=1, keepdims=True)
    norms_to = np.linalg.norm(target, axis=1, keepdims=True)
    if (norms_from == 0).any() or (norms_to == 0).any():
        raise ValueError('Spherical-spline coordinates cannot be at the sphere origin')
    source, target = source/norms_from, target/norms_to
    count = len(source)
    system = np.ones((count+1, count+1))
    system[:count, :count] = spline_kernel(source @ source.T) + regularization*np.eye(count)
    system[-1, -1] = 0.
    coefficients = solve(system, np.vstack((np.eye(count), np.zeros((1, count)))), assume_a='sym')
    matrix = np.empty((len(target), count), dtype=dtype)
    for start in range(0, len(target), 512):
        stop = min(start+512, len(target))
        kernel = spline_kernel(target[start:stop] @ source.T)
        matrix[start:stop] = kernel @ coefficients[:count] + coefficients[-1]
    return matrix
