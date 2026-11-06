import unittest
import numpy as np

from physiolab.spherical_spline import spherical_spline_matrix


def sphere_points(count, phase=0.):
    z = 1 - 2*(np.arange(count)+.5)/count
    phi = np.arange(count)*np.pi*(3-np.sqrt(5)) + phase
    r = np.sqrt(1-z*z)
    return np.column_stack((r*np.cos(phi), r*np.sin(phi), z))


class SphericalSplineTests(unittest.TestCase):
    def test_unregularized_values_at_sensor_locations(self):
        points = sphere_points(16)
        matrix = spherical_spline_matrix(points, points, regularization=0.)
        np.testing.assert_allclose(matrix, np.eye(16), atol=1e-9)

    def test_regularized_constant_and_known_spherical_field(self):
        source, target = sphere_points(64), sphere_points(117, .7)
        matrix = spherical_spline_matrix(source, target)
        np.testing.assert_allclose(matrix @ np.full(64, 7.), 7., atol=1e-9)
        # Degree-one spherical harmonic with a DC offset; independent test targets.
        actual = matrix @ (2*source[:, 0] - source[:, 1] + .3*source[:, 2] + 4.)
        expected = 2*target[:, 0] - target[:, 1] + .3*target[:, 2] + 4.
        self.assertLess(np.sqrt(np.mean((actual-expected)**2)), .003)

    def test_rotation_and_channel_order_invariance(self):
        source, target = sphere_points(20), sphere_points(17, .2)
        rotation = np.linalg.qr(np.random.default_rng(42).normal(size=(3, 3)))[0]
        expected = spherical_spline_matrix(source, target)
        rotated = spherical_spline_matrix(source @ rotation, target @ rotation)
        np.testing.assert_allclose(rotated, expected, atol=1e-10)
        reordered = spherical_spline_matrix(source[::-1], target)
        np.testing.assert_allclose(reordered[:, ::-1], expected, atol=1e-10)

    def test_invalid_origin_and_regularization_fail_clearly(self):
        source = sphere_points(8)
        with self.assertRaises(ValueError):
            spherical_spline_matrix(source, np.zeros((1, 3)))
        with self.assertRaises(ValueError):
            spherical_spline_matrix(source, source, regularization=-1.)


if __name__ == '__main__':
    unittest.main()
