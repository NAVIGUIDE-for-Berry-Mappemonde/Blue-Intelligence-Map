import unittest

import numpy as np

from download_scenes import is_l2a_scene, product_name, require_l1c
from mndwi_coastline import extract_lines, mndwi, pick_band
from search_stac import DEFAULT_COLLECTION
from stamp import stamp_features


class HelpersTest(unittest.TestCase):
    def test_product_name_ajoute_safe(self):
        self.assertEqual(
            product_name("S2C_MSIL2A_20260912T110631_N0512_R137_T30TWR_20260912T145321"),
            "S2C_MSIL2A_20260912T110631_N0512_R137_T30TWR_20260912T145321.SAFE",
        )
        self.assertEqual(product_name("X.SAFE"), "X.SAFE")

    def test_recherche_par_defaut_l1c(self):
        self.assertEqual(DEFAULT_COLLECTION, "sentinel-2-l1c")

    def test_refuse_l2a_pour_acolite(self):
        self.assertTrue(is_l2a_scene(
            "S2C_MSIL2A_20260912T110631_N0512_R137_T30TWR_20260912T145321"
        ))
        self.assertFalse(is_l2a_scene(
            "S2C_MSIL1C_20260912T110631_N0512_R137_T30TWR_20260912T123456"
        ))
        with self.assertRaises(SystemExit) as ctx:
            require_l1c("S2C_MSIL2A_20260912T110631_N0512_R137_T30TWR_20260912T145321")
        self.assertIn("L2A", str(ctx.exception))

    def test_mndwi_choisit_vert_et_swir(self):
        names = ["rhos_444", "rhos_561", "rhos_1612", "rhos_2191"]
        self.assertEqual(pick_band(names, ("561", "560")), "rhos_561")
        self.assertEqual(pick_band(names, ("1612", "1614")), "rhos_1612")

    def test_mndwi_eau_positive_terre_negative(self):
        green = np.array([[0.05, 0.20], [0.05, 0.20]])
        swir = np.array([[0.01, 0.25], [0.01, 0.25]])
        z = mndwi(green, swir)
        self.assertGreater(z[0, 0], 0)
        self.assertLess(z[0, 1], 0)

    def test_mndwi_contour_separe_eau_et_terre(self):
        n = 24
        lon = np.tile(np.linspace(-1.4, -0.9, n), (n, 1))
        lat = np.tile(np.linspace(46.0, 46.4, n).reshape(-1, 1), (1, n))
        z = np.where(lon < -1.15, 0.4, -0.4)
        bbox = [-1.5, 45.9, -0.8, 46.5]
        lines = extract_lines(lon, lat, z, bbox)
        self.assertTrue(lines)
        xs = [pt[0] for line in lines for pt in line]
        self.assertTrue(all(-1.25 < x < -1.05 for x in xs))

    def test_stamp_coastline(self):
        raw = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[-1.2, 46.1], [-1.1, 46.2]]},
                "properties": {},
            }],
        }
        out = stamp_features(raw, "sentinel-coastline")
        p = out["features"][0]["properties"]
        self.assertEqual(p["source"], "sentinel-pilot")
        self.assertEqual(p["natural"], "coastline")
        self.assertTrue(p["name"])


if __name__ == "__main__":
    unittest.main()
