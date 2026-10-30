import unittest

from core.gee_tools import _gee_bbox, _gee_safe_slug

class GeeTests(unittest.TestCase):
    def test_bbox_validation(self):
        self.assertEqual(_gee_bbox({"bbox":[77,28,77.5,28.8]})[0], [77.0,28.0,77.5,28.8])
    def test_bbox_rejects_invalid_order(self):
        with self.assertRaises(ValueError): _gee_bbox({"bbox":[77.5,28,77,28.8]})
    def test_bbox_rejects_world_scale(self):
        with self.assertRaises(ValueError): _gee_bbox({"bbox":[-180,-90,180,90]})
    def test_slug(self):
        self.assertNotIn("/", _gee_safe_slug("Delhi / DEM"))

if __name__ == "__main__": unittest.main()
