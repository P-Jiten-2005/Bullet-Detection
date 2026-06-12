import unittest
import numpy as np
import os
import json
import sys
# Add backend directory to path to load src
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.target_definition.target_definition import TargetDefinition, Bullseye, TargetRing
from src.scoring.scoring_engine import ScoringEngine
from src.scoring.boundary_verification import BoundaryVerificationEngine
from src.transformation.coordinate_transformer import CoordinateTransformer


class TestTargetAndScoring(unittest.TestCase):

    def setUp(self):
        # Paths to target configs created
        self.config_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "configs", "targets")
        self.rifle_10m_path = os.path.join(self.config_dir, "issf_10m_air_rifle.json")

    def test_target_definition_loading(self):
        """Verify that target definition files load correctly and rings are sorted."""
        target = TargetDefinition.load_from_json(self.rifle_10m_path)
        self.assertEqual(target.name, "ISSF 10m Air Rifle")
        self.assertEqual(target.width_mm, 80.0)
        self.assertEqual(target.height_mm, 80.0)
        self.assertEqual(len(target.bullseyes), 1)
        
        bull = target.bullseyes[0]
        self.assertEqual(bull.center_x_mm, 40.0)
        self.assertEqual(bull.center_y_mm, 40.0)
        self.assertEqual(len(bull.rings), 10)
        
        # Verify rings are sorted in descending order of radius
        radii = [r.outer_radius_mm for r in bull.rings]
        self.assertEqual(radii, sorted(radii, reverse=True))

    def test_scoring_engine_integer(self):
        """Verify integer scoring calculations under standard best-edge (inward) rules."""
        target = TargetDefinition.load_from_json(self.rifle_10m_path)
        engine = ScoringEngine()
        
        # Projectile: 4.5 mm caliber (radius 2.25 mm)
        bullet_radius = 2.25
        
        # 1. Dead center shot
        result = engine.score_shot(40.0, 40.0, bullet_radius, target)
        self.assertEqual(result["score"], 10)
        self.assertEqual(result["bullseye_id"], 1)
        self.assertEqual(result["distance_to_center_mm"], 0.0)
        
        # 2. Shot hitting the 9 ring
        # 10 ring outer radius = 0.25. 10-ring boundary = 0.25 + 2.25 = 2.5 mm.
        # A distance of 3.0 mm should be outside the 10-ring, but inside 9-ring (boundary = 2.75 + 2.25 = 5.0 mm).
        result = engine.score_shot(40.0, 43.0, bullet_radius, target)
        self.assertEqual(result["score"], 9)
        
        # 3. Shot touching the 10 ring boundary exactly (2.5 mm distance)
        result = engine.score_shot(40.0, 42.5, bullet_radius, target)
        self.assertEqual(result["score"], 10)
        
        # 4. Shot completely off the target rings (outermost boundary = 22.75 + 2.25 = 25.0 mm)
        result = engine.score_shot(40.0, 70.0, bullet_radius, target)
        self.assertEqual(result["score"], 0)

    def test_scoring_engine_decimal(self):
        """Verify decimal scoring calculations on ISSF targets."""
        target = TargetDefinition.load_from_json(self.rifle_10m_path)
        engine = ScoringEngine()
        bullet_radius = 2.25
        
        # Dead center (distance 0) -> 10.9
        result = engine.score_shot(40.0, 40.0, bullet_radius, target)
        self.assertEqual(result["decimal_score"], 10.9)
        
        # 10.0 boundary (distance 2.5) -> 10.0
        result = engine.score_shot(40.0, 42.5, bullet_radius, target)
        self.assertEqual(result["decimal_score"], 10.0)
        
        # 9.0 boundary (distance 5.0) -> 9.0
        result = engine.score_shot(40.0, 45.0, bullet_radius, target)
        self.assertEqual(result["decimal_score"], 9.0)
        
        # In-between shot (distance 1.0) -> 10.0 + (2.5 - 1.0) / 2.5 = 10.6
        result = engine.score_shot(40.0, 41.0, bullet_radius, target)
        self.assertEqual(result["decimal_score"], 10.6)

    def test_scoring_engine_rectangular(self):
        """Verify rectangular scoring calculations for Figure Eleven."""
        figure_eleven_path = os.path.join(self.config_dir, "figure_eleven.json")
        target = TargetDefinition.load_from_json(figure_eleven_path)
        engine = ScoringEngine()
        
        # Projectile: 5.56 mm caliber (radius 2.78 mm)
        bullet_radius = 2.78
        
        # 1. Hit inside Inner Center (190 to 390, 292.5 to 592.5) -> should score 5
        result = engine.score_shot(290.0, 442.5, bullet_radius, target)
        self.assertEqual(result["score"], 5)
        
        # 2. Hit inside Outer Torso but outside Inner Center -> should score 4
        result = engine.score_shot(100.0, 200.0, bullet_radius, target)
        self.assertEqual(result["score"], 4)
        
        # 3. Line touch on Inner Center (center at 188.0, 300.0 -> distance to 190.0 is 2.0mm, within radius 2.78mm)
        result = engine.score_shot(188.0, 300.0, bullet_radius, target)
        self.assertEqual(result["score"], 5)
        
        # 4. Miss completely off the outer torso
        result = engine.score_shot(30.0, 30.0, bullet_radius, target)
        self.assertEqual(result["score"], 0)

    def test_boundary_verification(self):
        """Verify line-break classification based on uncertainty."""
        verifier = BoundaryVerificationEngine()
        
        # 1. Close to boundary, within uncertainty margin -> review_required
        res1 = verifier.verify_boundary(distance_to_nearest_ring_mm=0.05, localization_error_mm=0.3)
        self.assertEqual(res1["status"], "review_required")
        self.assertFalse(res1["is_crossed"])
        
        # 2. Outside uncertainty margin but within 2-sigma -> probable
        res2 = verifier.verify_boundary(distance_to_nearest_ring_mm=0.3, localization_error_mm=0.2)
        self.assertEqual(res2["status"], "probable")
        self.assertFalse(res2["is_crossed"])
        
        # 3. Well outside uncertainty bounds -> certain
        res3 = verifier.verify_boundary(distance_to_nearest_ring_mm=-1.5, localization_error_mm=0.3)
        self.assertEqual(res3["status"], "certain")
        self.assertTrue(res3["is_crossed"])

    def test_coordinate_transformer(self):
        """Verify coordinate transformation forward/backward mapping and round-tripping."""
        # Simple square raw pixel area mapping to 80x80 mm target space
        corners_pixel = np.array([
            [100, 100],  # TL
            [900, 100],  # TR
            [900, 900],  # BR
            [100, 900]   # BL
        ], dtype=np.float32)
        
        transformer = CoordinateTransformer(
            corners_pixel=corners_pixel,
            target_width_mm=80.0,
            target_height_mm=80.0,
            warped_width_px=1000.0,
            warped_height_px=1000.0
        )
        
        # 1. Center of raw pixel square should map to center of target (40.0, 40.0) mm
        mx, my = transformer.raw_pixel_to_target_mm(500.0, 500.0)
        self.assertAlmostEqual(mx, 40.0, places=3)
        self.assertAlmostEqual(my, 40.0, places=3)
        
        # 2. Target space center to raw pixel should map back to (500.0, 500.0)
        px, py = transformer.target_mm_to_raw_pixel(40.0, 40.0)
        self.assertAlmostEqual(px, 500.0, places=3)
        self.assertAlmostEqual(py, 500.0, places=3)
        
        # 3. Warped space mapping: center of 1000x1000 warped image should scale to (40.0, 40.0) mm
        wx, wy = transformer.warped_pixel_to_target_mm(500.0, 500.0)
        self.assertAlmostEqual(wx, 40.0, places=3)
        self.assertAlmostEqual(wy, 40.0, places=3)
        
        # 4. Round-trip raw pixel to mm and back
        rx, ry = 350.5, 412.7
        tx, ty = transformer.raw_pixel_to_target_mm(rx, ry)
        rx_rt, ry_rt = transformer.target_mm_to_raw_pixel(tx, ty)
        self.assertAlmostEqual(rx, rx_rt, places=3)
        self.assertAlmostEqual(ry, ry_rt, places=3)


if __name__ == '__main__':
    unittest.main()
