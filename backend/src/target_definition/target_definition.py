"""
Target Definition Engine for PILSS.
Defines target geometries, scoring zones, rings, and calibers.
"""

import json
import os
from typing import List, Optional
from pydantic import BaseModel, Field


class TargetRing(BaseModel):
    """Represents a single scoring ring in a target bullseye."""
    value: int = Field(..., description="The integer score value of this ring.")
    outer_radius_mm: float = Field(..., description="The outer radius of this ring in millimeters.")
    color: Optional[str] = Field(None, description="Hex color or name of the ring for visualization purposes.")


class Bullseye(BaseModel):
    """Represents a bullseye scoring zone, which can contain multiple concentric rings."""
    id: int = Field(..., description="Unique identifier for the bullseye on the target sheet.")
    center_x_mm: float = Field(..., description="X coordinate of the bullseye center relative to Top-Left in mm.")
    center_y_mm: float = Field(..., description="Y coordinate of the bullseye center relative to Top-Left in mm.")
    rings: List[TargetRing] = Field(..., description="List of rings sorted from largest to smallest radius.")
    scoring_rule: str = Field("inward", description="Scoring rule: 'inward' (best edge) or 'outward' (worst edge).")

    def sort_rings(self):
        """Sorts the rings from largest radius to smallest radius to ensure correct search order."""
        self.rings.sort(key=lambda r: r.outer_radius_mm, reverse=True)


class ScoringRegion(BaseModel):
    """Represents a rectangular scoring region on a target sheet (e.g. Figure 11 target zones)."""
    id: int = Field(..., description="Unique identifier for the region.")
    name: Optional[str] = Field(None, description="Name of the scoring region (e.g. 'Inner', 'Head').")
    value: int = Field(..., description="Score value of this region.")
    x_min_mm: float = Field(..., description="Minimum X coordinate relative to Top-Left in mm.")
    y_min_mm: float = Field(..., description="Minimum Y coordinate relative to Top-Left in mm.")
    x_max_mm: float = Field(..., description="Maximum X coordinate relative to Top-Left in mm.")
    y_max_mm: float = Field(..., description="Maximum Y coordinate relative to Top-Left in mm.")


class TargetDefinition(BaseModel):
    """Represents the complete target paper sheet geometry and properties."""
    name: str = Field(..., description="Name of the target template (e.g. 'ISSF 10m Air Rifle').")
    width_mm: float = Field(..., description="Overall target paper width in millimeters.")
    height_mm: float = Field(..., description="Overall target paper height in millimeters.")
    bullseyes: List[Bullseye] = Field(default_factory=list, description="List of bullseyes on the target sheet.")
    scoring_regions: List[ScoringRegion] = Field(default_factory=list, description="List of rectangular scoring regions.")
    tag_size_mm: float = Field(50.0, description="Real-world size of each AprilTag in mm.")
    tag_margin_mm: float = Field(20.0, description="Margin from the AprilTag outer edge to the paper boundary in mm.")
    bullet_compatibility: List[str] = Field(default_factory=list, description="List of compatible caliber names.")
    decimal_scoring_supported: bool = Field(False, description="Whether decimal scoring is officially supported.")
    ring_spacing_mm: Optional[float] = Field(None, description="Spacing between rings in mm.")
    preview_url: Optional[str] = Field(None, description="URL or file path to target preview image.")

    def sort_all_rings(self):
        """Ensure all bullseye rings are sorted correctly."""
        for bullseye in self.bullseyes:
            bullseye.sort_rings()

    @classmethod
    def load_from_json(cls, file_path: str) -> "TargetDefinition":
        """Loads a target definition from a JSON file."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Target definition config file not found: {file_path}")
        
        with open(file_path, 'r') as f:
            data = json.load(f)
        
        target = cls(**data)
        target.sort_all_rings()
        return target

    def save_to_json(self, file_path: str):
        """Saves target definition to a JSON file."""
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w') as f:
            json.dump(self.dict(), f, indent=2)
