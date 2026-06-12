import unittest
import numpy as np
import os
import sys

# Add backend directory to path to load app and src
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.cv_engine import cv_engine
from src.transformation.coordinate_transformer import CoordinateTransformer

class TestCVEngineAndLocalization(unittest.TestCase):

    def setUp(self):
        self.backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.baseline_path = os.path.join(self.backend_dir, "test_baseline.jpg")
        self.capture_path = os.path.join(self.backend_dir, "test_capture.jpg")
        
        # If test images do not exist, run generate_test_images to create them
        if not os.path.exists(self.baseline_path) or not os.path.exists(self.capture_path):
            import subprocess
            subprocess.run([sys.executable, os.path.join(self.backend_dir, "generate_test_images.py")])

    def test_ssim_map_computation(self):
        """Verify that SSIM difference map is successfully calculated and bounded."""
        img1 = np.ones((100, 100), dtype=np.uint8) * 255
        img2 = np.ones((100, 100), dtype=np.uint8) * 255
        # Perfect match should yield all 1s
        ssim = cv_engine.compute_ssim_map(img1, img2)
        self.assertTrue(np.allclose(ssim, 1.0, atol=0.01))
        
        # Draw a black box in img2
        img2[40:60, 40:60] = 0
        ssim_diff = cv_engine.compute_ssim_map(img1, img2)
        self.assertTrue(np.any(ssim_diff < 0.8)) # Drops significantly in change region
        self.assertTrue(np.all(ssim_diff >= -1.0) and np.all(ssim_diff <= 1.0))

    def test_detect_holes_with_localization_methods(self):
        """Verify detect_holes returns all 4 sub-pixel center metrics for each candidate."""
        # Setup mock transformer
        corners_pixel = np.array([[0, 0], [999, 0], [999, 999], [0, 999]], dtype=np.float32)
        transformer = CoordinateTransformer(
            corners_pixel=corners_pixel,
            target_width_mm=80.0,
            target_height_mm=80.0
        )
        
        new_holes = cv_engine.detect_holes(
            baseline_path=self.baseline_path,
            current_path=self.capture_path,
            existing_shots=[],
            align=True,
            transformer=transformer,
            bullet_caliber_mm=1.28
        )
        
        # We expect to detect the 3 simulated holes
        self.assertTrue(len(new_holes) > 0)
        
        for hole in new_holes:
            # Check presence of raw fields
            self.assertIn("x_raw", hole)
            self.assertIn("y_raw", hole)
            self.assertIn("centroid_x_raw", hole)
            self.assertIn("centroid_y_raw", hole)
            self.assertIn("ellipse_x_raw", hole)
            self.assertIn("ellipse_y_raw", hole)
            self.assertIn("caliber_x_raw", hole)
            self.assertIn("caliber_y_raw", hole)
            self.assertIn("weighted_x_raw", hole)
            self.assertIn("weighted_y_raw", hole)
            self.assertIn("selected_method", hole)
            
            # Verify coordinates are valid float numbers
            for key in ["centroid_x_raw", "centroid_y_raw", "ellipse_x_raw", "ellipse_y_raw", 
                        "caliber_x_raw", "caliber_y_raw", "weighted_x_raw", "weighted_y_raw"]:
                self.assertIsInstance(hole[key], float)
                self.assertFalse(np.isnan(hole[key]))
                
            # Verify fallbacks or coordinates are close (sub-pixel deviations)
            self.assertLess(abs(hole["caliber_x_raw"] - hole["centroid_x_raw"]), 15.0)
            self.assertLess(abs(hole["caliber_y_raw"] - hole["centroid_y_raw"]), 15.0)

if __name__ == '__main__':
    unittest.main()
