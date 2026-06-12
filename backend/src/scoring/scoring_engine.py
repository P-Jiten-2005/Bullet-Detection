"""
Scoring Engine for PILSS.
Calculates official integer and decimal scores from impact coordinates.
"""

import math
from typing import Dict, Any, Tuple, Optional
from src.target_definition.target_definition import TargetDefinition, Bullseye, TargetRing


class ScoringEngine:
    """Computes geometric scoring and distance metrics for projectile impacts."""

    @staticmethod
    def calculate_distance(x1: float, y1: float, x2: float, y2: float) -> float:
        """Helper to calculate Euclidean distance between two points in mm."""
        return math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)

    def score_shot(
        self,
        impact_x_mm: float,
        impact_y_mm: float,
        bullet_radius_mm: float,
        target: TargetDefinition
    ) -> Dict[str, Any]:
        """
        Scores a single shot impact against the target definition.

        Args:
            impact_x_mm: X coordinate of impact center in target space (mm).
            impact_y_mm: Y coordinate of impact center in target space (mm).
            bullet_radius_mm: Radius of the projectile in mm.
            target: The TargetDefinition configuration.

        Returns:
            Dict containing:
                "score": Integer score (0-10).
                "decimal_score": Decimal score (0.0-10.9) if supported, else None.
                "nearest_ring_value": Value of the nearest ring.
                "distance_to_nearest_ring_mm": Distance from bullet edge to the nearest ring boundary.
                "bullseye_id": ID of the closest bullseye.
                "distance_to_center_mm": Distance from impact center to bullseye center.
        """
        if target.scoring_regions:
            # Score against rectangular regions
            highest_score = 0
            nearest_region = None
            min_boundary_dist = float('inf')
            
            for region in target.scoring_regions:
                # Calculate closest point on rectangle to impact center
                cx = max(region.x_min_mm, min(impact_x_mm, region.x_max_mm))
                cy = max(region.y_min_mm, min(impact_y_mm, region.y_max_mm))
                
                # Distance from impact center to closest point on rectangle boundary
                center_dist = math.sqrt((impact_x_mm - cx) ** 2 + (impact_y_mm - cy) ** 2)
                
                # If center_dist is 0, the bullet center is inside the rectangle.
                # The boundary distance represents how far the center is to the closest edge:
                if center_dist == 0:
                    d_left = impact_x_mm - region.x_min_mm
                    d_right = region.x_max_mm - impact_x_mm
                    d_top = impact_y_mm - region.y_min_mm
                    d_bottom = region.y_max_mm - impact_y_mm
                    boundary_dist = -min(d_left, d_right, d_top, d_bottom)
                else:
                    boundary_dist = center_dist
                
                # Edge distance: boundary distance minus bullet radius
                edge_dist = boundary_dist - bullet_radius_mm
                
                # Inward scoring rule (default for military targets): if any part of bullet overlaps region, award score
                if edge_dist <= 0:
                    if region.value > highest_score:
                        highest_score = region.value
                        
                # Track nearest region boundary for line-break verification feedback
                if abs(edge_dist) < abs(min_boundary_dist):
                    min_boundary_dist = edge_dist
                    nearest_region = region
            
            return {
                "score": highest_score,
                "decimal_score": float(highest_score),
                "nearest_ring_value": nearest_region.value if nearest_region else 0,
                "distance_to_nearest_ring_mm": min_boundary_dist,
                "bullseye_id": nearest_region.id if nearest_region else 1,
                "distance_to_center_mm": min_boundary_dist
            }

        if not target.bullseyes:
            raise ValueError("Target definition does not contain any bullseyes or scoring regions.")

        # 1. Find the closest bullseye
        closest_bullseye = None
        min_center_dist = float('inf')

        for bullseye in target.bullseyes:
            dist = self.calculate_distance(impact_x_mm, impact_y_mm, bullseye.center_x_mm, bullseye.center_y_mm)
            if dist < min_center_dist:
                min_center_dist = dist
                closest_bullseye = bullseye

        if closest_bullseye is None:
            raise ValueError("Failed to locate closest bullseye.")

        bull = closest_bullseye
        rule = bull.scoring_rule

        # 2. Determine integer score
        integer_score = 0
        
        # Rings are sorted from largest radius (outermost) to smallest (innermost).
        # We search from the center outwards (highest score to lowest) to find the first ring hit.
        for ring in reversed(bull.rings):
            # Calculate boundary distance for this ring
            if rule == "inward":
                boundary = ring.outer_radius_mm + bullet_radius_mm
            elif rule == "outward":
                boundary = ring.outer_radius_mm - bullet_radius_mm
            else:
                raise ValueError(f"Unknown scoring rule: {rule}")

            if min_center_dist <= boundary:
                integer_score = ring.value
                break

        # 3. Determine decimal score
        decimal_score = None
        if target.decimal_scoring_supported:
            if integer_score > 0 and target.ring_spacing_mm is not None and target.ring_spacing_mm > 0:
                # Find the 10 ring outer radius
                ten_ring = next((r for r in bull.rings if r.value == 10), None)
                if ten_ring:
                    if rule == "inward":
                        d_10 = ten_ring.outer_radius_mm + bullet_radius_mm
                    else:
                        d_10 = ten_ring.outer_radius_mm - bullet_radius_mm
                    
                    # Decimal formula: score = 10.0 + (d_10 - distance) / spacing
                    raw_dec = 10.0 + (d_10 - min_center_dist) / target.ring_spacing_mm
                    # Round to 1 decimal place
                    rounded_dec = round(raw_dec, 1)
                    # Capped at 10.9 (maximum possible ISSF decimal score)
                    decimal_score = max(0.0, min(10.9, rounded_dec))
            else:
                decimal_score = 0.0

        # 4. Find nearest ring and boundary distance
        nearest_ring_value = None
        distance_to_nearest_ring = float('inf')

        for ring in bull.rings:
            if rule == "inward":
                boundary = ring.outer_radius_mm + bullet_radius_mm
            else:
                boundary = ring.outer_radius_mm - bullet_radius_mm
            
            # Distance from bullet center to the boundary.
            # Negative means inside the boundary, positive means outside.
            dist_to_boundary = min_center_dist - boundary
            if abs(dist_to_boundary) < abs(distance_to_nearest_ring):
                distance_to_nearest_ring = dist_to_boundary
                nearest_ring_value = ring.value

        return {
            "score": integer_score,
            "decimal_score": decimal_score,
            "nearest_ring_value": nearest_ring_value,
            "distance_to_nearest_ring_mm": distance_to_nearest_ring,
            "bullseye_id": bull.id,
            "distance_to_center_mm": min_center_dist
        }
