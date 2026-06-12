"""
AprilTag A4 warp service for CXR-AIM platform.
Detects 4+ AprilTags, recovers paper corners, warps to canonical A4 (2100x2970).
"""

import os
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple
from src.target_definition.target_definition import TargetDefinition

import cv2
import numpy as np
A4_W, A4_H = 2100, 2970
TAG_MIN_COUNT = 3

TAG_MARGIN_MM = 20.0
MM_PER_PX = 10.0

# --- AprilTag outdoor detection settings ---
ENABLE_CLAHE = True
CLAHE_CLIP_LIMIT = 3.5
AUTO_MARGIN_MIN = 0.15
AUTO_MARGIN_MAX = 0.5
DETECT_AT_NATIVE_RESOLUTION = False
# --- End settings ---


# ---------------------------------------------------------------------------
# Multi-scale AprilTag detection using OpenCV Aruco
# ---------------------------------------------------------------------------

def _preprocess(gray: np.ndarray) -> np.ndarray:
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    eq = clahe.apply(gray)
    blur = cv2.GaussianBlur(eq, (0, 0), 1.0)
    return cv2.addWeighted(eq, 1.5, blur, -0.5, 0)


def _detect_at_scale(gray: np.ndarray, family: str, scale: float,
                     min_area_px: float) -> list:
    if scale != 1.0:
        h, w = gray.shape
        gray = cv2.resize(gray, (int(w * scale), int(h * scale)),
                          interpolation=cv2.INTER_CUBIC)

    if ENABLE_CLAHE:
        processed = cv2.createCLAHE(clipLimit=CLAHE_CLIP_LIMIT, tileGridSize=(8, 8)).apply(gray)
    else:
        processed = _preprocess(gray)

    # Map string family to OpenCV ArUco constants
    fam_lower = family.lower()
    fam_id = cv2.aruco.DICT_APRILTAG_36h11
    if "36h10" in fam_lower:
        fam_id = cv2.aruco.DICT_APRILTAG_36h10
    elif "25h9" in fam_lower:
        fam_id = cv2.aruco.DICT_APRILTAG_25h9
    elif "16h5" in fam_lower:
        fam_id = cv2.aruco.DICT_APRILTAG_16h5
    elif "4x4" in fam_lower:
        fam_id = cv2.aruco.DICT_4X4_50
    elif "5x5" in fam_lower:
        fam_id = cv2.aruco.DICT_5X5_50
    elif "6x6" in fam_lower:
        fam_id = cv2.aruco.DICT_6X6_250

    try:
        dictionary = cv2.aruco.getPredefinedDictionary(fam_id)
        parameters = cv2.aruco.DetectorParameters()
        # Enable subpixel refinement for corners to get high precision
        parameters.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        # Tune parameters for robust detection under shadows, angles, and low light
        parameters.adaptiveThreshWinSizeMin = 3
        parameters.adaptiveThreshWinSizeMax = 23
        parameters.adaptiveThreshWinSizeStep = 4
        parameters.adaptiveThreshConstant = 7
        parameters.minMarkerPerimeterRate = 0.01 # Lower to detect smaller or tilted tags
        detector = cv2.aruco.ArucoDetector(dictionary, parameters)
        corners, ids, rejected = detector.detectMarkers(processed)
    except Exception as e:
        return []

    validated = []
    if ids is None or len(ids) == 0:
        return validated

    h_h, w_w = processed.shape[:2]
    for i in range(len(ids)):
        corners_px = corners[i][0].astype(np.float32)
        cx = float(corners_px[:, 0].mean())
        cy = float(corners_px[:, 1].mean())
        
        if cx < 3 or cx > w_w - 3 or cy < 3 or cy > h_h - 3:
            continue
            
        area = cv2.contourArea(corners_px.reshape(-1, 1, 2))
        if area < min_area_px or area > h_h * w_w * 0.5:
            continue

        if scale != 1.0:
            corners_px /= scale
            cx, cy = cx / scale, cy / scale

        validated.append({
            "id": int(ids[i][0]),
            "corners": corners_px,
            "center": np.array([cx, cy], dtype=np.float32),
            "hamming": 0,
            "decision_margin": 10.0,
        })
    return validated


def detect_tags(gray: np.ndarray, family: str = "tag36h11",
                tag_size_mm: float = 15.0) -> list:
    scales = [1.0] if DETECT_AT_NATIVE_RESOLUTION else [1.0, 1.5]
    
    # 1. Try with the requested tag family first
    for s in scales:
        tags = _detect_at_scale(gray, family, s, 16)
        if len(tags) >= TAG_MIN_COUNT:
            return tags
            
    # 2. Robust fallback: try other common AprilTag and ArUco families
    fallback_families = ["tag36h11", "tag25h9", "tag16h5", "tag36h10", "4x4_50", "5x5_50", "6x6_250"]
    for fam in fallback_families:
        if fam.lower() == family.lower():
            continue
        for s in scales:
            tags = _detect_at_scale(gray, fam, s, 16)
            if len(tags) >= TAG_MIN_COUNT:
                return tags
                
    return []


# ---------------------------------------------------------------------------
# Paper recovery
# ---------------------------------------------------------------------------

def _sort_tags_by_position(tags: list) -> list:
    centers = [(t["center"][0], t["center"][1], t) for t in tags]
    centers.sort(key=lambda c: c[1])
    top = sorted(centers[:2], key=lambda c: c[0])
    bot = sorted(centers[2:], key=lambda c: c[0])
    return [top[0][2], top[1][2], bot[1][2], bot[0][2]]


_SCORE_FNS = [
    lambda c: c[0] + c[1],   # TL: minimize x+y (top-leftmost)
    lambda c: -c[0] + c[1],  # TR: minimize -x+y (top-rightmost)
    lambda c: -c[0] - c[1],  # BR: minimize -x-y (bottom-rightmost)
    lambda c: c[0] - c[1],   # BL: minimize x-y (bottom-leftmost)
]
_POSITION_NAMES = ["TL", "TR", "BR", "BL"]


def _pick_outward_corner(tag: dict, position_idx: int) -> np.ndarray:
    corners = tag["corners"]
    best = min(range(4), key=lambda j: _SCORE_FNS[position_idx](corners[j]))
    return corners[best]


def _infer_tag_positions(centers_sorted: list) -> tuple:
    """
    Given 3 tags sorted by Y, determine which paper positions they occupy
    and which corner is missing.
    Returns (tag_indices, pos_indices, missing_idx).
    """
    y_gap_12 = centers_sorted[1][1] - centers_sorted[0][1]
    y_gap_23 = centers_sorted[2][1] - centers_sorted[1][1]

    if y_gap_23 > y_gap_12:
        # 2 top (indices 0,1), 1 bottom (index 2)
        top_sorted = sorted(centers_sorted[:2], key=lambda c: c[0])
        bot = centers_sorted[2]
        mid_x = (top_sorted[0][0] + top_sorted[1][0]) / 2
        if bot[0] > mid_x:
            # bottom tag is BR, missing BL
            return [top_sorted[0][2], top_sorted[1][2], bot[2]], [0, 1, 2], 3
        else:
            # bottom tag is BL, missing BR
            return [top_sorted[0][2], top_sorted[1][2], bot[2]], [0, 1, 3], 2
    else:
        # 1 top (index 0), 2 bottom (indices 1,2)
        top = centers_sorted[0]
        bot_sorted = sorted(centers_sorted[1:], key=lambda c: c[0])
        mid_x = (bot_sorted[0][0] + bot_sorted[1][0]) / 2
        if top[0] > mid_x:
            # top tag is TR, missing TL
            return [top[2], bot_sorted[0][2], bot_sorted[1][2]], [1, 3, 2], 0
        else:
            # top tag is TL, missing TR
            return [top[2], bot_sorted[0][2], bot_sorted[1][2]], [0, 3, 2], 1


def _sort_to_tl_tr_br_bl(pts: np.ndarray) -> np.ndarray:
    s = pts[np.argsort(pts[:, 1])]
    top = s[:2][np.argsort(s[:2, 0])]
    bot = s[2:][np.argsort(s[2:, 0])]
    return np.array([top[0], top[1], bot[1], bot[0]], dtype=np.float32)


def sort_corners_geometrically(pts: np.ndarray) -> np.ndarray:
    """Sorts 4 points into TL, TR, BR, BL order geometrically."""
    rect = np.zeros((4, 2), dtype=np.float32)
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]       # TL
    rect[2] = pts[np.argmax(s)]       # BR
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]    # TR
    rect[3] = pts[np.argmax(diff)]    # BL
    return rect


def _compute_auto_margin(tags: list, paper: np.ndarray) -> float:
    tag_diags = []
    for t in tags:
        c = t["corners"]
        tag_diags.append(float(np.linalg.norm(c[0] - c[2])))
    avg_tag_diag = np.mean(tag_diags)
    center = paper.mean(axis=0)
    avg_corner_dist = float(np.mean([np.linalg.norm(pc - center) for pc in paper]))
    if avg_corner_dist < 1.0:
        return 0.2
    margin = avg_tag_diag / (avg_corner_dist * 2)
    return max(AUTO_MARGIN_MIN, min(AUTO_MARGIN_MAX, margin))


def recover_paper_corners(tags: list, image: np.ndarray,
                          margin_factor: float = 0.0,
                          auto_margin: bool = False) -> Optional[np.ndarray]:
    if len(tags) < 3:
        return None

    if len(tags) >= 4:
        sorted_tags = _sort_tags_by_position(tags)
        paper = np.zeros((4, 2), dtype=np.float32)
        for i in range(4):
            paper[i] = _pick_outward_corner(sorted_tags[i], i)
    else:
        # 3-tag: determine positions via Y-sorting, pick outward corners, compute 4th via parallelogram
        centers = [(t["center"][0], t["center"][1], i) for i, t in enumerate(tags)]
        centers.sort(key=lambda c: c[1])
        tag_indices, pos_indices, missing_idx = _infer_tag_positions(centers)

        three_corners = []
        for tag_i, pos_i in zip(tag_indices, pos_indices):
            three_corners.append(_pick_outward_corner(tags[tag_i], pos_i))
        three_corners = np.array(three_corners, dtype=np.float32)

        # Parallelogram rule for 4th corner: P_missing = opposite_pair[0] + opposite_pair[1] - adjacent
        if missing_idx == 0:      # missing TL
            fourth = three_corners[1] + three_corners[2] - three_corners[0]
            all_four = np.array([fourth, three_corners[0], three_corners[1], three_corners[2]])
        elif missing_idx == 1:    # missing TR
            fourth = three_corners[0] + three_corners[2] - three_corners[1]
            all_four = np.array([three_corners[0], fourth, three_corners[1], three_corners[2]])
        elif missing_idx == 2:    # missing BR
            fourth = three_corners[0] + three_corners[1] - three_corners[2]
            all_four = np.array([three_corners[0], three_corners[1], fourth, three_corners[2]])
        else:                     # missing BL
            fourth = three_corners[0] + three_corners[2] - three_corners[1]
            all_four = np.array([three_corners[0], three_corners[1], three_corners[2], fourth])
        paper = _sort_to_tl_tr_br_bl(all_four)

    if auto_margin and len(tags) >= 3:
        margin_factor = _compute_auto_margin(tags, paper)

    if margin_factor > 0:
        cx = paper[:, 0].mean()
        cy = paper[:, 1].mean()
        for i in range(4):
            vec = paper[i] - np.array([cx, cy])
            paper[i] = paper[i] + vec * margin_factor

    return paper


def get_template_tag_data(tag_size: float, margin: float, W: float, H: float) -> Tuple[dict, dict]:
    T = tag_size
    M = margin
    
    # Centers in mm
    centers_mm = {
        0: np.array([M + T/2.0, M + T/2.0], dtype=np.float32),        # TL
        1: np.array([W - M - T/2.0, M + T/2.0], dtype=np.float32),    # TR
        2: np.array([W - M - T/2.0, H - M - T/2.0], dtype=np.float32),# BR
        3: np.array([M + T/2.0, H - M - T/2.0], dtype=np.float32)     # BL
    }
    
    # Corners in mm
    corners_mm = {
        0: np.array([[M, M], [M + T, M], [M + T, M + T], [M, M + T]], dtype=np.float32),
        1: np.array([[W - M - T, M], [W - M, M], [W - M, M + T], [W - M - T, M + T]], dtype=np.float32),
        2: np.array([[W - M - T, H - M - T], [W - M, H - M - T], [W - M, H - M], [W - M - T, H - M]], dtype=np.float32),
        3: np.array([[M, H - M - T], [M + T, H - M - T], [M + T, H - M], [M, H - M]], dtype=np.float32)
    }
    return centers_mm, corners_mm


def is_convex_quadrilateral(pts: np.ndarray) -> bool:
    """Checks if a 4-point polygon is a convex quadrilateral."""
    if pts.shape != (4, 2):
        return False
    for i in range(4):
        p0 = pts[i]
        p1 = pts[(i + 1) % 4]
        p2 = pts[(i + 2) % 4]
        v1 = p1 - p0
        v2 = p2 - p1
        cross = v1[0] * v2[1] - v1[1] * v2[0]
        if i == 0:
            sign = np.sign(cross)
        else:
            if np.sign(cross) != sign or sign == 0:
                return False
    return True


# ---------------------------------------------------------------------------
# Warp to A4
# ---------------------------------------------------------------------------

def warp_to_a4(image: np.ndarray, corners: np.ndarray) -> np.ndarray:
    src_pts = np.array(corners, dtype=np.float32)
    dst_pts = np.array([
        [0, 0], [A4_W - 1, 0], [A4_W - 1, A4_H - 1], [0, A4_H - 1]
    ], dtype=np.float32)
    H = cv2.getPerspectiveTransform(src_pts, dst_pts)
    return cv2.warpPerspective(image, H, (A4_W, A4_H),
                                flags=cv2.INTER_LINEAR,
                                borderMode=cv2.BORDER_CONSTANT,
                                borderValue=255)


# ---------------------------------------------------------------------------
# Service class for CXR-AIM integration
# ---------------------------------------------------------------------------

class AprilTagService:
    """
    Service wrapper around AprilTag detection + A4 warp.
    Used by CameraService to replace contour-based paper detection.
    """

    def __init__(self, tag_family: str = "tag36h11", tag_size_mm: float = 15.0,
                 margin: float = 0.2, auto_margin: bool = True, min_tags: int = 3):
        self.tag_family = tag_family
        self.tag_size_mm = tag_size_mm
        self.margin = margin
        self.auto_margin = auto_margin
        self.min_tags = min_tags

    def detect_and_warp(
        self, 
        image: np.ndarray,
        tag_size_mm: Optional[float] = None,
        tag_margin_mm: Optional[float] = None,
        target_width_mm: Optional[float] = None,
        target_height_mm: Optional[float] = None
    ) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], list]:
        """
        Detect AprilTags in image, recover paper corners using exact physical specifications,
        and warp image.
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        actual_tag_size = tag_size_mm if tag_size_mm is not None else self.tag_size_mm
        actual_margin = tag_margin_mm if tag_margin_mm is not None else TAG_MARGIN_MM
        actual_w = target_width_mm if target_width_mm is not None else 210.0
        actual_h = target_height_mm if target_height_mm is not None else 297.0
        
        tags = detect_tags(gray, self.tag_family, actual_tag_size)
        if len(tags) < self.min_tags:
            return None, None, tags

        # Reconstruct paper corners using exact real-world dimensions of AprilTags and margin
        try:
            actual_w = target_width_mm if target_width_mm is not None else 210.0
            actual_h = target_height_mm if target_height_mm is not None else 297.0
            
            centers_mm, corners_mm = get_template_tag_data(actual_tag_size, actual_margin, actual_w, actual_h)
            
            best_error = float('inf')
            best_H_pixel_to_mm = None
            best_H_mm_to_pixel = None
            best_perm = None
            best_positions = None
            
            import itertools
            
            if len(tags) >= 4:
                # Try all permutations of matching 4 tags to TL(0), TR(1), BR(2), BL(3)
                for perm in itertools.permutations(tags, 4):
                    src_centers = np.array([t["center"] for t in perm], dtype=np.float32)
                    dst_centers = np.array([centers_mm[0], centers_mm[1], centers_mm[2], centers_mm[3]], dtype=np.float32)
                    
                    H_pixel_to_mm, _ = cv2.findHomography(src_centers, dst_centers)
                    if H_pixel_to_mm is None:
                        continue
                    try:
                        H_mm_to_pixel = np.linalg.inv(H_pixel_to_mm)
                    except np.linalg.LinAlgError:
                        continue
                        
                    # Calculate error on tag corners
                    total_err = 0.0
                    for pos_idx in range(4):
                        tag = perm[pos_idx]
                        det_corners = tag["corners"] # raw corners from detector, already in clockwise order
                        tpl_corners = corners_mm[pos_idx]
                        proj_corners = cv2.perspectiveTransform(tpl_corners.reshape(-1, 1, 2), H_mm_to_pixel).reshape(4, 2)
                        total_err += np.sum(np.linalg.norm(det_corners - proj_corners, axis=1))
                        
                    if total_err < best_error:
                        # Check convexity of projected paper corners
                        paper_corners_mm = np.array([
                            [0.0, 0.0],
                            [actual_w, 0.0],
                            [actual_w, actual_h],
                            [0.0, actual_h]
                        ], dtype=np.float32)
                        cand_corners = cv2.perspectiveTransform(paper_corners_mm.reshape(-1, 1, 2), H_mm_to_pixel).reshape(4, 2)
                        if is_convex_quadrilateral(cand_corners):
                            best_error = total_err
                            best_H_pixel_to_mm = H_pixel_to_mm
                            best_H_mm_to_pixel = H_mm_to_pixel
                            best_perm = perm
                            best_positions = [0, 1, 2, 3]
            else:
                # 3 tags: try all choices of missing corner, and all permutations of active tags
                active_sets = {
                    0: [1, 2, 3],
                    1: [0, 2, 3],
                    2: [0, 1, 3],
                    3: [0, 1, 2]
                }
                for missing_idx, active_pos in active_sets.items():
                    for perm in itertools.permutations(tags, 3):
                        # Map perm[0] -> active_pos[0], perm[1] -> active_pos[1], perm[2] -> active_pos[2]
                        # Estimate missing center in pixel space using affine transform
                        src_tri = np.array([centers_mm[p] for p in active_pos], dtype=np.float32)
                        dst_tri = np.array([perm[i]["center"] for i in range(3)], dtype=np.float32)
                        try:
                            A = cv2.getAffineTransform(src_tri, dst_tri)
                            p_missing = centers_mm[missing_idx]
                            p_missing_h = np.array([p_missing[0], p_missing[1], 1.0], dtype=np.float32)
                            c_missing_px = np.dot(A, p_missing_h)
                        except Exception:
                            continue
                            
                        # Reconstruct all 4 centers in pixel space
                        centers_px = {}
                        for i in range(3):
                            centers_px[active_pos[i]] = perm[i]["center"]
                        centers_px[missing_idx] = c_missing_px
                        
                        src_centers = np.array([centers_px[0], centers_px[1], centers_px[2], centers_px[3]], dtype=np.float32)
                        dst_centers = np.array([centers_mm[0], centers_mm[1], centers_mm[2], centers_mm[3]], dtype=np.float32)
                        
                        H_pixel_to_mm, _ = cv2.findHomography(src_centers, dst_centers)
                        if H_pixel_to_mm is None:
                            continue
                        try:
                            H_mm_to_pixel = np.linalg.inv(H_pixel_to_mm)
                        except np.linalg.LinAlgError:
                            continue
                            
                        # Calculate error on active tag corners
                        total_err = 0.0
                        for i in range(3):
                            pos_idx = active_pos[i]
                            tag = perm[i]
                            det_corners = tag["corners"]
                            tpl_corners = corners_mm[pos_idx]
                            proj_corners = cv2.perspectiveTransform(tpl_corners.reshape(-1, 1, 2), H_mm_to_pixel).reshape(4, 2)
                            total_err += np.sum(np.linalg.norm(det_corners - proj_corners, axis=1))
                            
                        if total_err < best_error:
                            paper_corners_mm = np.array([
                                [0.0, 0.0],
                                [actual_w, 0.0],
                                [actual_w, actual_h],
                                [0.0, actual_h]
                            ], dtype=np.float32)
                            cand_corners = cv2.perspectiveTransform(paper_corners_mm.reshape(-1, 1, 2), H_mm_to_pixel).reshape(4, 2)
                            if is_convex_quadrilateral(cand_corners):
                                best_error = total_err
                                best_H_pixel_to_mm = H_pixel_to_mm
                                best_H_mm_to_pixel = H_mm_to_pixel
                                best_perm = perm
                                best_positions = active_pos
                                
            if best_H_pixel_to_mm is None:
                raise ValueError("No valid tag matching permutation found.")
                
            # Final high-precision refinement using all corners of matched tags
            src_pts = []
            dst_pts = []
            for tag, pos in zip(best_perm, best_positions):
                for px, mm in zip(tag["corners"], corners_mm[pos]):
                    src_pts.append(px)
                    dst_pts.append(mm)
            src_pts = np.array(src_pts, dtype=np.float32)
            dst_pts = np.array(dst_pts, dtype=np.float32)
            
            H_pixel_to_mm, _ = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)
            H_mm_to_pixel = np.linalg.inv(H_pixel_to_mm)
            paper_corners_mm = np.array([
                [0.0, 0.0],
                [actual_w, 0.0],
                [actual_w, actual_h],
                [0.0, actual_h]
            ], dtype=np.float32)
            corners = cv2.perspectiveTransform(paper_corners_mm.reshape(-1, 1, 2), H_mm_to_pixel).reshape(4, 2)
        except Exception as e:
            logger.warning(f"Homography matching failed ({e}), falling back to older recover method.")
            corners = recover_paper_corners(tags, image, self.margin, self.auto_margin)
            
        if corners is None:
            return None, None, tags

        # Warp to canonical shape
        if target_width_mm is not None and target_height_mm is not None:
            scale_px_per_mm = 5.0
            w_px = int(actual_w * scale_px_per_mm)
            h_px = int(actual_h * scale_px_per_mm)
            dst_pts = np.array([
                [0, 0], [w_px - 1, 0], [w_px - 1, h_px - 1], [0, h_px - 1]
            ], dtype=np.float32)
            H_warp = cv2.getPerspectiveTransform(corners, dst_pts)
            warped = cv2.warpPerspective(image, H_warp, (w_px, h_px),
                                        flags=cv2.INTER_LINEAR,
                                        borderMode=cv2.BORDER_CONSTANT,
                                        borderValue=255)
        else:
            warped = warp_to_a4(image, corners)
            
        return warped, corners, tags

    def estimate_camera_distance(self, tags: list, tag_size_mm: float, zoom_factor: float = 1.0, image_width: int = 1920) -> Optional[float]:
        """
        Estimates distance from camera to target paper in mm using AprilTags.
        """
        if not tags:
            return None
        tag_size_px_list = []
        for tag in tags:
            c = tag["corners"]
            side_01 = np.linalg.norm(c[0] - c[1])
            side_12 = np.linalg.norm(c[1] - c[2])
            side_23 = np.linalg.norm(c[2] - c[3])
            side_30 = np.linalg.norm(c[3] - c[0])
            avg_side = (side_01 + side_12 + side_23 + side_30) / 4.0
            tag_size_px_list.append(avg_side)
            
        if not tag_size_px_list:
            return None
            
        avg_tag_size_px = np.mean(tag_size_px_list)
        focal_length_px = image_width * 1.25 # focal length approx. 70 deg FOV
        
        # Adjust for zoom
        raw_tag_size_px = avg_tag_size_px / zoom_factor
        if raw_tag_size_px <= 0:
            return None
            
        estimated_distance_mm = (focal_length_px * tag_size_mm) / raw_tag_size_px
        return float(estimated_distance_mm)

    def get_tag_count(self, image: np.ndarray) -> int:
        """Quick check: how many AprilTags are visible in the image."""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        tags = detect_tags(gray, self.tag_family, self.tag_size_mm)
        return len(tags)


apriltag_service = AprilTagService()


def get_adjusted_target_definition(target: TargetDefinition, baseline_path: Optional[str], corners: Optional[np.ndarray]) -> TargetDefinition:
    """
    Detects physical white line zones inside the homographed/warped baseline image,
    and adjusts target.scoring_regions in-memory to align with the detected lines.
    """
    if not target.scoring_regions or not baseline_path or not os.path.exists(baseline_path) or corners is None:
        return target

    try:
        from src.transformation.coordinate_transformer import CoordinateTransformer
        from src.target_definition.target_definition import ScoringRegion

        # Load baseline image
        img = cv2.imread(baseline_path)
        if img is None:
            return target

        # Build transformer
        transformer = CoordinateTransformer(
            corners_pixel=np.array(corners, dtype=np.float32),
            target_width_mm=target.width_mm,
            target_height_mm=target.height_mm
        )

        # Warp image to 1000x1000 square perspective
        warped_img = cv2.warpPerspective(img, transformer.H_pixel_to_warped, (1000, 1000))
        gray = cv2.cvtColor(warped_img, cv2.COLOR_BGR2GRAY)

        # Find candidate rectangles across different thresholds
        candidates = []
        for th_val in range(80, 190, 5):
            _, thresh = cv2.threshold(gray, th_val, 255, cv2.THRESH_BINARY)
            contours, _ = cv2.findContours(thresh, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
            for c in contours:
                area = cv2.contourArea(c)
                x, y, w_box, h_box = cv2.boundingRect(c)
                ar = w_box / float(h_box) if h_box > 0 else 0
                
                # Check center of bounding box in 1000x1000 space
                cx = x + w_box / 2.0
                cy = y + h_box / 2.0
                
                if 400 < cx < 600 and 400 < cy < 650:
                    if 0.55 < ar < 1.15:
                        candidates.append({
                            "x_min_w": x,
                            "y_min_w": y,
                            "x_max_w": x + w_box,
                            "y_max_w": y + h_box,
                            "w_w": w_box,
                            "h_w": h_box,
                            "cx_w": cx,
                            "cy_w": cy,
                            "area": area
                        })

        if not candidates:
            return target

        # Group candidates that are very close (similar bounding box) to avoid duplicates
        grouped = []
        for cand in candidates:
            found_dup = False
            for g in grouped:
                dist_x_min = abs(g["x_min_w"] - cand["x_min_w"])
                dist_x_max = abs(g["x_max_w"] - cand["x_max_w"])
                dist_y_min = abs(g["y_min_w"] - cand["y_min_w"])
                dist_y_max = abs(g["y_max_w"] - cand["y_max_w"])
                
                if dist_x_min < 15 and dist_x_max < 15 and dist_y_min < 15 and dist_y_max < 15:
                    found_dup = True
                    break
            if not found_dup:
                grouped.append(cand)

        theoretical_regions = target.scoring_regions
        matched_regions = {r.id: [] for r in theoretical_regions}

        for cand in grouped:
            cx_mm = cand["cx_w"] * (target.width_mm / 1000.0)
            cy_mm = cand["cy_w"] * (target.height_mm / 1000.0)
            w_mm = cand["w_w"] * (target.width_mm / 1000.0)
            h_mm = cand["h_w"] * (target.height_mm / 1000.0)
            
            # Find closest theoretical region by width & height
            best_r = None
            min_diff = float('inf')
            for r in theoretical_regions:
                th_w = r.x_max_mm - r.x_min_mm
                th_h = r.y_max_mm - r.y_min_mm
                diff = abs(w_mm - th_w) + abs(h_mm - th_h)
                if diff < min_diff:
                    min_diff = diff
                    best_r = r
                    
            if min_diff < 25.0:
                matched_regions[best_r.id].append({
                    "cand": cand,
                    "diff": min_diff,
                    "w_mm": w_mm,
                    "h_mm": h_mm,
                    "cx_mm": cx_mm,
                    "cy_mm": cy_mm
                })

        best_matches = {}
        scale_factors_w = []
        scale_factors_h = []
        offsets_x = []
        offsets_y = []

        for r_id, matches in matched_regions.items():
            if matches:
                matches.sort(key=lambda x: x["diff"])
                best = matches[0]
                best_matches[r_id] = best
                
                r = next(tr for tr in theoretical_regions if tr.id == r_id)
                th_w = r.x_max_mm - r.x_min_mm
                th_h = r.y_max_mm - r.y_min_mm
                th_cx = (r.x_min_mm + r.x_max_mm) / 2.0
                th_cy = (r.y_min_mm + r.y_max_mm) / 2.0
                
                scale_factors_w.append(best["w_mm"] / th_w)
                scale_factors_h.append(best["h_mm"] / th_h)
                offsets_x.append(best["cx_mm"] - th_cx)
                offsets_y.append(best["cy_mm"] - th_cy)

        # Compute average scale and offsets to fallback if some zones are missing
        avg_scale_w = np.mean(scale_factors_w) if scale_factors_w else 1.0
        avg_scale_h = np.mean(scale_factors_h) if scale_factors_h else 1.0
        avg_off_x = np.mean(offsets_x) if offsets_x else 0.0
        avg_off_y = np.mean(offsets_y) if offsets_y else 0.0

        # Create new adjusted scoring regions
        adjusted_regions = []
        for r in theoretical_regions:
            th_w = r.x_max_mm - r.x_min_mm
            th_h = r.y_max_mm - r.y_min_mm
            th_cx = (r.x_min_mm + r.x_max_mm) / 2.0
            th_cy = (r.y_min_mm + r.y_max_mm) / 2.0
            
            if r.id in best_matches:
                best = best_matches[r.id]
                new_w = best["w_mm"]
                new_h = best["h_mm"]
                new_cx = best["cx_mm"]
                new_cy = best["cy_mm"]
            else:
                new_w = th_w * avg_scale_w
                new_h = th_h * avg_scale_h
                new_cx = th_cx + avg_off_x
                new_cy = th_cy + avg_off_y
                
            x_min = new_cx - new_w / 2.0
            x_max = new_cx + new_w / 2.0
            y_min = new_cy - new_h / 2.0
            y_max = new_cy + new_h / 2.0
            
            adjusted_regions.append(ScoringRegion(
                id=r.id,
                name=r.name,
                value=r.value,
                x_min_mm=float(x_min),
                y_min_mm=float(y_min),
                x_max_mm=float(x_max),
                y_max_mm=float(y_max)
            ))

        target_copy = target.copy(update={"scoring_regions": adjusted_regions})
        return target_copy
    except Exception as e:
        return target
