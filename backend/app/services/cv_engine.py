import cv2
import numpy as np
import logging
from typing import List, Dict, Any, Tuple

logger = logging.getLogger("app.cv_engine")

class CVEngine:
    def __init__(
        self,
        min_area: float = 3.0,        # Minimum pixel area (lowered to catch smaller holes at distance)
        max_area: float = 5000.0,     # Maximum pixel area
        min_circularity: float = 0.20,  # Roundness threshold (lowered to allow torn/irregular holes)
        min_solidity: float = 0.40,     # Solidity threshold (lowered to allow paper tears)
        aspect_ratio_range: Tuple[float, float] = (0.2, 5.0), # Allowable stretch ratio (widened)
        proximity_threshold_px: float = 15.0 # Max pixel distance to consider a hole as pre-existing
    ):
        self.min_area = min_area
        self.max_area = max_area
        self.min_circularity = min_circularity
        self.min_solidity = min_solidity
        self.aspect_ratio_range = aspect_ratio_range
        self.proximity_threshold_px = proximity_threshold_px

    def align_images(self, baseline_img: np.ndarray, current_img: np.ndarray) -> np.ndarray:
        """
        Aligns current_img to baseline_img using ORB feature matching and Homography.
        Falls back to current_img if alignment fails.
        """
        try:
            gray_base = cv2.cvtColor(baseline_img, cv2.COLOR_BGR2GRAY)
            gray_curr = cv2.cvtColor(current_img, cv2.COLOR_BGR2GRAY)

            # Initialize ORB detector
            orb = cv2.ORB_create(nfeatures=1500)
            kp1, des1 = orb.detectAndCompute(gray_base, None)
            kp2, des2 = orb.detectAndCompute(gray_curr, None)

            if des1 is None or des2 is None or len(kp1) < 10 or len(kp2) < 10:
                logger.warning("Not enough features for image registration. Using unaligned current frame.")
                return current_img

            # Match features using Brute Force Hamming distance
            bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
            matches = bf.match(des1, des2)
            matches = sorted(matches, key=lambda x: x.distance)[:100]

            if len(matches) < 4:
                logger.warning("Fewer than 4 feature matches. Alignment homography calculation skipped.")
                return current_img

            # Extract location of good matches
            src_pts = np.float32([kp1[m.queryIdx].pt for m in matches]).reshape(-1, 1, 2)
            dst_pts = np.float32([kp2[m.trainIdx].pt for m in matches]).reshape(-1, 1, 2)

            # Find homography matrix using RANSAC
            H, mask = cv2.findHomography(dst_pts, src_pts, cv2.RANSAC, 5.0)

            if H is None:
                logger.warning("Homography matrix estimation failed. Using unaligned current frame.")
                return current_img

            # Warp current image to match baseline perspective
            height, width, channels = baseline_img.shape
            aligned_img = cv2.warpPerspective(current_img, H, (width, height))
            return aligned_img

        except Exception as e:
            logger.error(f"Image registration failed with error: {e}. Defaulting to unaligned frame.")
            return current_img

    def compute_ssim_map(self, img1: np.ndarray, img2: np.ndarray) -> np.ndarray:
        """
        Computes the Structural Similarity Index (SSIM) map between two grayscale images.
        """
        x = img1.astype(np.float32)
        y = img2.astype(np.float32)

        C1 = 6.5025
        C2 = 58.5225

        ksize = (11, 11)
        sigma = 1.5

        mu_x = cv2.GaussianBlur(x, ksize, sigma)
        mu_y = cv2.GaussianBlur(y, ksize, sigma)

        mu_x_sq = mu_x ** 2
        mu_y_sq = mu_y ** 2
        mu_x_mu_y = mu_x * mu_y

        sigma_x_sq = cv2.GaussianBlur(x * x, ksize, sigma) - mu_x_sq
        sigma_y_sq = cv2.GaussianBlur(y * y, ksize, sigma) - mu_y_sq
        sigma_xy = cv2.GaussianBlur(x * y, ksize, sigma) - mu_x_mu_y

        # Avoid division by zero by adding constants C1 and C2
        num = (2 * mu_x_mu_y + C1) * (2 * sigma_xy + C2)
        den = (mu_x_sq + mu_y_sq + C1) * (sigma_x_sq + sigma_y_sq + C2)

        ssim_map = num / den
        return ssim_map

    def detect_holes(
        self, 
        baseline_path: str, 
        current_path: str, 
        existing_shots: List[Dict[str, Any]],
        align: bool = True,
        transformer: Any = None,
        bullet_caliber_mm: float = 4.5,
        session_id: str = None
    ) -> List[Dict[str, Any]]:
        """
        Executes the detection pipeline:
        1. Loads baseline & current frame.
        2. Registers (aligns) current frame if align=True.
        3. Computes absolute difference using directed binary diff (Method A)
           and SSIM difference (Method B) combined.
        4. Thresholds & morphological cleaning.
        5. Contour-based candidate extraction & sub-pixel localization using 4 algorithms:
           Centroid, Ellipse Fit, Caliber-Constrained Circle Fit, Weighted Intensity Center.
        6. Deduplicates against already recorded shots in the session.
        """
        baseline_img = cv2.imread(baseline_path)
        current_img = cv2.imread(current_path)

        if baseline_img is None or current_img is None:
            raise ValueError("Failed to load baseline or current image from disk.")

        # Step 1: Align current image to baseline if requested
        if align:
            aligned_current = self.align_images(baseline_img, current_img)
        else:
            aligned_current = current_img

        # Step 2: Grayscale and Blur
        gray_base = cv2.cvtColor(baseline_img, cv2.COLOR_BGR2GRAY)
        gray_curr = cv2.cvtColor(aligned_current, cv2.COLOR_BGR2GRAY)
        
        blur_base = cv2.GaussianBlur(gray_base, (5, 5), 0)
        blur_curr = cv2.GaussianBlur(gray_curr, (5, 5), 0)

        # Normalize brightness to handle auto-exposure changes
        mean_base = np.mean(blur_base)
        mean_curr = np.mean(blur_curr)
        if mean_curr > 0:
            scale_factor = mean_base / mean_curr
            scale_factor = min(max(scale_factor, 0.7), 1.3) # Cap to avoid extreme noise scaling
            blur_curr = np.clip(blur_curr * scale_factor, 0, 255).astype(np.uint8)

        # Step 3: Extract edges of baseline target markings to exclude only boundary transitions (camera shift/drift protection)
        edges_base = cv2.Canny(blur_base, 30, 100)
        edge_dilation_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        dilated_edges = cv2.dilate(edges_base, edge_dilation_kernel, iterations=1)
 
        # Step 4: Directed absolute grayscale difference (Method A) (works in both light and dark regions)
        diff_gray = cv2.absdiff(blur_base, blur_curr)
        _, diff_binary_a = cv2.threshold(diff_gray, 15, 255, cv2.THRESH_BINARY)
        diff_binary_a = cv2.bitwise_and(diff_binary_a, cv2.bitwise_not(dilated_edges))
 
        # Method B: SSIM Difference
        ssim_map = self.compute_ssim_map(blur_base, blur_curr)
        ssim_diff_binary = np.where(ssim_map < 0.55, 255, 0).astype(np.uint8)
        diff_binary_b = cv2.bitwise_and(ssim_diff_binary, cv2.bitwise_not(dilated_edges))
 
        # Combine Method A and Method B using bitwise OR
        diff_binary = cv2.bitwise_or(diff_binary_a, diff_binary_b)

        # Mask out region outside the target paper boundary if corners are not the default full-image corners
        h, w = diff_binary.shape
        paper_mask = np.ones((h, w), dtype=np.uint8) * 255
        if transformer is not None and hasattr(transformer, "corners_pixel") and transformer.corners_pixel is not None:
            corners = transformer.corners_pixel
            # If corners are not the full image (check if TL is 0,0 and BR is close to full width,height or 999,999)
            is_default = (
                np.allclose(corners[0], [0, 0]) and 
                (np.allclose(corners[2], [w - 1, h - 1]) or np.allclose(corners[2], [999, 999]))
            )
            if not is_default:
                paper_mask = np.zeros((h, w), dtype=np.uint8)
                pts_int = np.array(corners, dtype=np.int32).reshape((-1, 1, 2))
                cv2.fillPoly(paper_mask, [pts_int], 255)
                logger.info("Constraining differencing region to target paper quadrilateral mask.")
                
        diff_binary = cv2.bitwise_and(diff_binary, paper_mask)

        # Step 5: Morphological Operations (Opening to remove noise, Closing to fill holes)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        cleaned = cv2.morphologyEx(diff_binary, cv2.MORPH_OPEN, kernel, iterations=1)
        cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, kernel, iterations=1)

        # Save pipeline debug images for verification
        if session_id is not None:
            try:
                import os
                upload_dir = os.path.dirname(current_path)
                aligned_debug_path = os.path.join(upload_dir, f"debug_aligned_{session_id}.png")
                diff_debug_path = os.path.join(upload_dir, f"debug_diff_{session_id}.png")
                cv2.imwrite(aligned_debug_path, aligned_current)
                cv2.imwrite(diff_debug_path, cleaned)
            except Exception as e:
                logger.error(f"Failed to save initial CV pipeline debug frames: {e}")

        # Step 6: Find contours
        contours, _ = cv2.findContours(cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        new_holes = []
        
        for c in contours:
            # Area filtering
            area = cv2.contourArea(c)
            if not (self.min_area <= area <= self.max_area):
                continue

            # Perimeter for circularity
            perimeter = cv2.arcLength(c, True)
            if perimeter == 0:
                continue

            # Circularity filter
            circularity = (4.0 * np.pi * area) / (perimeter ** 2)
            if circularity < self.min_circularity:
                continue

            # Convex hull and solidity filter
            hull = cv2.convexHull(c)
            hull_area = cv2.contourArea(hull)
            solidity = area / hull_area if hull_area > 0 else 0
            if solidity < self.min_solidity:
                continue

            # Aspect ratio check
            x, y, w, h = cv2.boundingRect(c)
            aspect_ratio = float(w) / h
            if not (self.aspect_ratio_range[0] <= aspect_ratio <= self.aspect_ratio_range[1]):
                continue

            # Centroid calculations (Method 1)
            M = cv2.moments(c)
            if M["m00"] == 0:
                continue
            centroid_x = float(M["m10"] / M["m00"])
            centroid_y = float(M["m01"] / M["m00"])

            # Equivalent circle diameter calculation
            equiv_diameter = np.sqrt(4.0 * area / np.pi)

            # Ellipse Fit (Method 2)
            if len(c) >= 5:
                try:
                    (ellipse_x, ellipse_y), _, _ = cv2.fitEllipse(c)
                    ellipse_x = float(ellipse_x)
                    ellipse_y = float(ellipse_y)
                except Exception:
                    ellipse_x, ellipse_y = centroid_x, centroid_y
            else:
                ellipse_x, ellipse_y = centroid_x, centroid_y

            # Caliber-Constrained Circle Fit (Method 3) via custom 2D gradient descent
            if transformer is not None and bullet_caliber_mm > 0:
                try:
                    x_mm, y_mm = transformer.raw_pixel_to_target_mm(centroid_x, centroid_y)
                    x_offset_mm, y_offset_mm = transformer.raw_pixel_to_target_mm(centroid_x + 1.0, centroid_y)
                    mm_per_pixel = np.sqrt((x_offset_mm - x_mm)**2 + (y_offset_mm - y_mm)**2)
                    if mm_per_pixel > 0:
                        caliber_radius_px = (bullet_caliber_mm / 2.0) / mm_per_pixel
                    else:
                        caliber_radius_px = equiv_diameter / 2.0
                except Exception:
                    caliber_radius_px = equiv_diameter / 2.0
            else:
                caliber_radius_px = equiv_diameter / 2.0

            contour_pts = c.reshape(-1, 2)
            caliber_x, caliber_y = centroid_x, centroid_y
            N_pts = len(contour_pts)
            if N_pts > 0:
                alpha = 0.2
                for _ in range(30):
                    grad_x = 0.0
                    grad_y = 0.0
                    for pt in contour_pts:
                        px, py = pt[0], pt[1]
                        dx = px - caliber_x
                        dy = py - caliber_y
                        dist = np.sqrt(dx*dx + dy*dy)
                        if dist > 0.01:
                            factor = 1.0 - (caliber_radius_px / dist)
                            grad_x += factor * (-dx)
                            grad_y += factor * (-dy)
                        else:
                            grad_x += -caliber_radius_px
                            grad_y += -caliber_radius_px
                    
                    grad_x = (2.0 / N_pts) * grad_x
                    grad_y = (2.0 / N_pts) * grad_y
                    
                    caliber_x -= alpha * grad_x
                    caliber_y -= alpha * grad_y

            caliber_x = float(caliber_x)
            caliber_y = float(caliber_y)

            # Weighted Intensity Center (Method 4)
            try:
                if w > 0 and h > 0:
                    mask = np.zeros((h, w), dtype=np.uint8)
                    shifted_c = c - np.array([x, y])
                    cv2.drawContours(mask, [shifted_c], -1, 255, -1)
                    
                    patch = gray_curr[y:y+h, x:x+w]
                    inv_patch = 255.0 - patch.astype(np.float32)
                    weighted_patch = np.where(mask == 255, inv_patch, 0.0)
                    
                    total_weight = np.sum(weighted_patch)
                    if total_weight > 0:
                        grid_y, grid_x = np.indices((h, w))
                        weighted_x_rel = np.sum(grid_x * weighted_patch) / total_weight
                        weighted_y_rel = np.sum(grid_y * weighted_patch) / total_weight
                        weighted_x = float(x + weighted_x_rel)
                        weighted_y = float(y + weighted_y_rel)
                    else:
                        weighted_x, weighted_y = centroid_x, centroid_y
                else:
                    weighted_x, weighted_y = centroid_x, centroid_y
            except Exception:
                weighted_x, weighted_y = centroid_x, centroid_y

            # Confidence calculation (average of normalized roundness & solidity metrics)
            confidence = float((circularity + solidity) / 2.0)
            confidence = min(max(confidence, 0.0), 1.0)

            # Primary coordinates set to caliber_fit (Method 3)
            # Fallback to centroid if caliber fit is nan or invalid
            if np.isnan(caliber_x) or np.isnan(caliber_y):
                primary_x, primary_y = centroid_x, centroid_y
                selected_method = "centroid"
            else:
                primary_x, primary_y = caliber_x, caliber_y
                selected_method = "caliber_fit"

            # Step 7: Deduplicate candidate against existing shots list
            is_new = True
            for shot in existing_shots:
                dist = np.sqrt((primary_x - shot["x_raw"])**2 + (primary_y - shot["y_raw"])**2)
                # If within threshold distance, this hole was already captured
                if dist < self.proximity_threshold_px:
                    is_new = False
                    break

            if is_new:
                # Store contour as a flat coordinate list for serialization [[x1, y1], [x2, y2], ...]
                raw_contour_pts = [pt[0].tolist() for pt in c]
                new_holes.append({
                    "x_raw": primary_x,
                    "y_raw": primary_y,
                    "diameter_px": float(equiv_diameter),
                    "confidence": confidence,
                    "area": float(area),
                    "circularity": float(circularity),
                    "solidity": float(solidity),
                    "aspect_ratio": float(aspect_ratio),
                    "raw_contour": raw_contour_pts,
                    "centroid_x_raw": centroid_x,
                    "centroid_y_raw": centroid_y,
                    "ellipse_x_raw": ellipse_x,
                    "ellipse_y_raw": ellipse_y,
                    "caliber_x_raw": caliber_x,
                    "caliber_y_raw": caliber_y,
                    "weighted_x_raw": weighted_x,
                    "weighted_y_raw": weighted_y,
                    "selected_method": selected_method
                })

        # Overwrite debug images with high-visibility labeled markings of all detected holes
        if session_id is not None and len(new_holes) > 0:
            try:
                import os
                upload_dir = os.path.dirname(current_path)
                aligned_debug_path = os.path.join(upload_dir, f"debug_aligned_{session_id}.png")
                diff_debug_path = os.path.join(upload_dir, f"debug_diff_{session_id}.png")

                # Make color copies for drawing
                diff_color = cv2.cvtColor(cleaned, cv2.COLOR_GRAY2BGR)
                aligned_debug_img = aligned_current.copy()

                for idx, hole in enumerate(new_holes):
                    hx = int(hole["x_raw"])
                    hy = int(hole["y_raw"])
                    r_px = int(hole["diameter_px"] / 2.0)
                    contour_pts = np.array(hole["raw_contour"], dtype=np.int32).reshape((-1, 1, 2))

                    # Draw green contour, red outline circle, blue center point, yellow text label
                    for img_to_draw in [diff_color, aligned_debug_img]:
                        cv2.drawContours(img_to_draw, [contour_pts], -1, (0, 255, 0), 1)
                        cv2.circle(img_to_draw, (hx, hy), max(2, r_px), (0, 0, 255), 2)
                        cv2.circle(img_to_draw, (hx, hy), 1, (255, 0, 0), -1)
                        cv2.putText(
                            img_to_draw, 
                            f"H#{idx + 1}", 
                            (hx + r_px + 2, hy + 4),
                            cv2.FONT_HERSHEY_SIMPLEX, 
                            0.45, 
                            (0, 255, 255), 
                            1, 
                            cv2.LINE_AA
                        )

                cv2.imwrite(aligned_debug_path, aligned_debug_img)
                cv2.imwrite(diff_debug_path, diff_color)
                logger.info(f"Saved labeled CV pipeline debug frames (found {len(new_holes)} holes) for session: {session_id}")
            except Exception as e:
                logger.error(f"Failed to save labeled CV pipeline debug frames: {e}")

        return new_holes

cv_engine = CVEngine()

