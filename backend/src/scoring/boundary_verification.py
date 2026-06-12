"""
Boundary Verification Engine for PILSS.
Classifies line-break decisions based on geometric distance to boundaries and localization uncertainty.
"""

from typing import Dict, Any


class BoundaryVerificationEngine:
    """Verifies boundary crossings and handles line-break scenarios with quantified confidence."""

    @staticmethod
    def verify_boundary(
        distance_to_nearest_ring_mm: float,
        localization_error_mm: float,
        probable_threshold_factor: float = 2.0
    ) -> Dict[str, Any]:
        """
        Classifies the confidence of a boundary intersection.

        Args:
            distance_to_nearest_ring_mm: Distance from bullet edge to the nearest ring boundary (mm).
                                         Negative means inside, positive means outside.
            localization_error_mm: Estimated error margin of the localization system in mm (e.g., 0.3 mm).
            probable_threshold_factor: Factor multiplied by the error margin to distinguish
                                       'certain' from 'probable'. Defaults to 2.0 (e.g., 2-sigma).

        Returns:
            Dict containing:
                "status": "certain", "probable", or "review_required"
                "reason": Human-readable explanation of the boundary classification.
        """
        abs_dist = abs(distance_to_nearest_ring_mm)
        margin = localization_error_mm
        outer_bound = margin * probable_threshold_factor

        # Determine the direction of the boundary relation
        is_crossed = distance_to_nearest_ring_mm <= 0

        if abs_dist <= margin:
            # Overlaps within the 1-sigma / standard error range
            status = "review_required"
            action = "awarded (crossed)" if is_crossed else "denied (not crossed)"
            reason = (
                f"Impact edge is extremely close to the boundary (distance: {distance_to_nearest_ring_mm:.3f} mm). "
                f"It is within the localization uncertainty margin of +/- {margin:.3f} mm. "
                f"Decision is currently {action} but manual review is recommended."
            )
        elif abs_dist <= outer_bound:
            # Overlaps within the outer confidence bound (e.g. 1-sigma to 2-sigma range)
            status = "probable"
            action = "awarded (crossed)" if is_crossed else "denied (not crossed)"
            reason = (
                f"Impact edge is close to the boundary (distance: {distance_to_nearest_ring_mm:.3f} mm). "
                f"It is within the probable bounds of +/- {outer_bound:.3f} mm. "
                f"Decision is {action}."
            )
        else:
            # Well outside any uncertainty range
            status = "certain"
            action = "awarded (crossed)" if is_crossed else "denied (not crossed)"
            reason = (
                f"Impact edge is safely away from the boundary (distance: {distance_to_nearest_ring_mm:.3f} mm, "
                f"uncertainty boundary: {outer_bound:.3f} mm). Decision is {action}."
            )

        return {
            "status": status,
            "reason": reason,
            "is_crossed": is_crossed
        }
