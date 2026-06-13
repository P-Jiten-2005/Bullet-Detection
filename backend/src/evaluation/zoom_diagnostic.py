"""
DroidCam Zoom & AprilTag Scale Validation Utility.
Analyzes target sheets under different camera zoom levels (1x, 2x, 3x)
to report tag edge pixel sizes, homographies, measured reference distances, and measurement errors.
"""

import os
import sys
import cv2
import numpy as np

# Add backend root to path
backend_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(backend_root)
sys.path.append(os.path.dirname(backend_root)) # also append project root if needed

from app.services.apriltag_service import apriltag_service
from src.transformation.coordinate_transformer import CoordinateTransformer

def run_diagnostics(image_paths: list, physical_tag_size_mm: float = 50.0):
    print("=" * 70)
    print(" PILSS APRILTAG SCALE & ZOOM VALIDATION REPORT")
    print("=" * 70)
    print(f"Physical Tag Size: {physical_tag_size_mm} mm")
    print(f"Expected Tag 0 -> Tag 1 Center Distance: 120.0 mm (Standard A4 layout)")
    print("-" * 70)

    for path in image_paths:
        if not os.path.exists(path):
            print(f"Error: File not found at {path}")
            continue

        img = cv2.imread(path)
        if img is None:
            print(f"Error: Failed to read image from {path}")
            continue

        h, w = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # Detect AprilTags
        tags = apriltag_service.detect_and_warp(
            img,
            tag_size_mm=physical_tag_size_mm,
            tag_margin_mm=20.0,
            target_width_mm=210.0,
            target_height_mm=297.0
        )
        warped, corners, detected_tags = tags
        
        print(f"\n[IMAGE]: {os.path.basename(path)} ({w}x{h} px)")

        if corners is None or len(detected_tags) < 3:
            print(f"  --> Status: FAILED (Detected {len(detected_tags)} tags. Need >= 3)")
            continue

        # 1. Tag edge length in pixels
        tag_sides = []
        for tag in detected_tags:
            c = tag["corners"]
            for i in range(4):
                side = np.linalg.norm(c[i] - c[(i + 1) % 4])
                tag_sides.append(side)
        avg_tag_side_px = np.mean(tag_sides)

        # 2. Build Coordinate Transformer (Fresh Homography)
        transformer = CoordinateTransformer(
            corners_pixel=corners,
            target_width_mm=210.0,
            target_height_mm=297.0
        )

        # 3. Measured Reference Distance
        # Let's locate Tag 0 and Tag 1 in pixel space
        t0 = next((t for t in detected_tags if t["id"] == 0), None)
        t1 = next((t for t in detected_tags if t["id"] == 1), None)

        print(f"  Detected Tag IDs: {[t['id'] for t in detected_tags]}")
        print(f"  Avg Tag Edge Size: {avg_tag_side_px:.2f} pixels")
        print(f"  Homography Matrix (Pixel -> Target mm):")
        print(f"    {transformer.H_pixel_to_mm[0]}")
        print(f"    {transformer.H_pixel_to_mm[1]}")
        print(f"    {transformer.H_pixel_to_mm[2]}")

        if t0 is not None and t1 is not None:
            # Map tag centers to target mm space
            t0_mm = transformer.raw_pixel_to_target_mm(t0["center"][0], t0["center"][1])
            t1_mm = transformer.raw_pixel_to_target_mm(t1["center"][0], t1["center"][1])
            
            measured_dist = np.linalg.norm(np.array(t0_mm) - np.array(t1_mm))
            expected_dist = 120.0 # standard center-to-center distance
            error = measured_dist - expected_dist
            
            print(f"  Expected Distance: {expected_dist:.2f} mm")
            print(f"  Measured Distance: {measured_dist:.2f} mm")
            print(f"  Measurement Error: {error:+.3f} mm")
            
            # Zoom Assessment
            zoom_status = "1x"
            # Standard DroidCam focal length estimation focal_px = w * 1.25
            # estimated_dist = (focal_px * tag_size) / tag_size_px
            focal_px = w * 1.25
            est_dist_mm = (focal_px * physical_tag_size_mm) / avg_tag_side_px
            print(f"  Estimated Camera Distance: {est_dist_mm/1000.0:.3f} meters")
        else:
            print("  Measured Distance: N/A (Tag 0 and/or Tag 1 not detected)")

    print("\n" + "=" * 70)

if __name__ == "__main__":
    # If paths are provided via CLI, use them
    if len(sys.argv) > 1:
        run_diagnostics(sys.argv[1:])
    else:
        # Check standard default folders
        default_dir = os.path.join(backend_root, "tests")
        files = [
            os.path.join(default_dir, "test_baseline.jpg"),
            os.path.join(default_dir, "test_capture.jpg"),
            os.path.join(backend_root, "test_baseline.jpg"),
            os.path.join(backend_root, "test_capture.jpg")
        ]
        # Filter existing files
        existing_files = [f for f in files if os.path.exists(f)]
        if existing_files:
            run_diagnostics(existing_files)
        else:
            print("No test images found. Please run the script by passing image file paths as arguments:")
            print("python zoom_diagnostic.py image1.jpg image2.jpg ...")
