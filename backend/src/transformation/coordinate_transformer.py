"""
Coordinate Transformation Engine for PILSS.
Translates coordinates between raw pixel space, warped pixel space, and target-space mm.
Supports the research comparison between Warp-then-Detect (Approach A) and Detect-then-Transform (Approach B).
"""

import cv2
import numpy as np
from typing import Tuple, Union, Optional


class CoordinateTransformer:
    """Handles 2D projective transformations and coordinate scaling for scoring."""

    def __init__(
        self,
        corners_pixel: np.ndarray,
        target_width_mm: float,
        target_height_mm: float,
        warped_width_px: float = 1000.0,
        warped_height_px: float = 1000.0,
        corners_warped: Optional[np.ndarray] = None
    ):
        """
        Initializes the coordinate transformer.

        Args:
            corners_pixel: 4x2 array of raw pixel corners ordered: Top-Left, Top-Right, Bottom-Right, Bottom-Left.
            target_width_mm: Real-world width of target paper sheet in mm.
            target_height_mm: Real-world height of target paper sheet in mm.
            warped_width_px: Resolution width of the warped target image in pixels.
            warped_height_px: Resolution height of the warped target image in pixels.
            corners_warped: Optional 4x2 array of corners in warped pixel space.
        """
        self.corners_pixel = np.array(corners_pixel, dtype=np.float32)
        self.target_width_mm = target_width_mm
        self.target_height_mm = target_height_mm
        self.warped_width_px = warped_width_px
        self.warped_height_px = warped_height_px

        # Standardized target corners in mm
        self.corners_mm = np.array([
            [0.0, 0.0],
            [target_width_mm, 0.0],
            [target_width_mm, target_height_mm],
            [0.0, target_height_mm]
        ], dtype=np.float32)

        # Standardized target corners in warped pixel space
        if corners_warped is not None:
            self.corners_warped = np.array(corners_warped, dtype=np.float32)
        else:
            self.corners_warped = np.array([
                [0.0, 0.0],
                [warped_width_px - 1, 0.0],
                [warped_width_px - 1, warped_height_px - 1],
                [0.0, warped_height_px - 1]
            ], dtype=np.float32)

        # Compute homographies
        # 1. Raw pixels <-> mm (Approach B)
        self.H_pixel_to_mm = cv2.getPerspectiveTransform(self.corners_pixel, self.corners_mm)
        self.H_mm_to_pixel = cv2.getPerspectiveTransform(self.corners_mm, self.corners_pixel)

        # 2. Raw pixels <-> Warped pixels
        self.H_pixel_to_warped = cv2.getPerspectiveTransform(self.corners_pixel, self.corners_warped)
        self.H_warped_to_pixel = cv2.getPerspectiveTransform(self.corners_warped, self.corners_pixel)

    def raw_pixel_to_target_mm(self, x_px: float, y_px: float) -> Tuple[float, float]:
        """
        Directly projects a raw pixel coordinate to real-world target mm (Approach B).
        Bypasses any intermediate image warping step.
        """
        point = np.array([[[x_px, y_px]]], dtype=np.float32)
        transformed = cv2.perspectiveTransform(point, self.H_pixel_to_mm)
        return float(transformed[0][0][0]), float(transformed[0][0][1])

    def target_mm_to_raw_pixel(self, x_mm: float, y_mm: float) -> Tuple[float, float]:
        """Maps target mm back to raw pixel space."""
        point = np.array([[[x_mm, y_mm]]], dtype=np.float32)
        transformed = cv2.perspectiveTransform(point, self.H_mm_to_pixel)
        return float(transformed[0][0][0]), float(transformed[0][0][1])

    def raw_pixel_to_warped_pixel(self, x_px: float, y_px: float) -> Tuple[float, float]:
        """Maps raw pixel space to warped pixel space."""
        point = np.array([[[x_px, y_px]]], dtype=np.float32)
        transformed = cv2.perspectiveTransform(point, self.H_pixel_to_warped)
        return float(transformed[0][0][0]), float(transformed[0][0][1])

    def warped_pixel_to_raw_pixel(self, x_w_px: float, y_w_px: float) -> Tuple[float, float]:
        """Maps warped pixel space back to raw pixel space."""
        point = np.array([[[x_w_px, y_w_px]]], dtype=np.float32)
        transformed = cv2.perspectiveTransform(point, self.H_warped_to_pixel)
        return float(transformed[0][0][0]), float(transformed[0][0][1])

    def warped_pixel_to_target_mm(self, x_w_px: float, y_w_px: float) -> Tuple[float, float]:
        """
        Transforms warped pixel coordinate to real-world target mm (Approach A).
        Uses simple linear scaling, assuming the warped image matches the target aspect ratio.
        """
        x_mm = x_w_px * (self.target_width_mm / self.warped_width_px)
        y_mm = y_w_px * (self.target_height_mm / self.warped_height_px)
        return float(x_mm), float(y_mm)

    def target_mm_to_warped_pixel(self, x_mm: float, y_mm: float) -> Tuple[float, float]:
        """Transforms real-world target mm to warped pixel coordinate."""
        x_w_px = x_mm * (self.warped_width_px / self.target_width_mm)
        y_w_px = y_mm * (self.warped_height_px / self.target_height_mm)
        return float(x_w_px), float(y_w_px)
