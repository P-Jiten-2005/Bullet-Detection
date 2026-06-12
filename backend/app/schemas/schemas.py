from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List, Any

class SessionBase(BaseModel):
    name: str
    description: Optional[str] = None
    target_type: Optional[str] = "figure_eleven"
    bullet_caliber: Optional[float] = 4.5

class SessionCreate(SessionBase):
    pass

class SessionResponse(SessionBase):
    id: str
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class ImageResponse(BaseModel):
    id: str
    session_id: str
    image_type: str
    file_path: str
    metadata_json: Optional[Any] = None
    created_at: datetime

    class Config:
        from_attributes = True

class DetectionResponse(BaseModel):
    id: str
    area: float
    circularity: float
    solidity: float
    aspect_ratio: float
    raw_contour: Optional[List[List[int]]] = None
    centroid_x_raw: Optional[float] = None
    centroid_y_raw: Optional[float] = None
    ellipse_x_raw: Optional[float] = None
    ellipse_y_raw: Optional[float] = None
    caliber_x_raw: Optional[float] = None
    caliber_y_raw: Optional[float] = None
    weighted_x_raw: Optional[float] = None
    weighted_y_raw: Optional[float] = None

    class Config:
        from_attributes = True

class ShotResponse(BaseModel):
    id: str
    session_id: str
    image_id: Optional[str] = None
    shot_number: int
    x_raw: float
    y_raw: float
    x_calibrated: Optional[float] = None
    y_calibrated: Optional[float] = None
    diameter_px: float
    diameter_mm: Optional[float] = None
    confidence: float
    is_valid: bool
    score: Optional[int] = None
    decimal_score: Optional[float] = None
    nearest_ring_value: Optional[int] = None
    distance_to_nearest_ring_mm: Optional[float] = None
    bullseye_id: Optional[int] = None
    distance_to_center_mm: Optional[float] = None
    boundary_status: Optional[str] = None
    localization_method: Optional[str] = "centroid"
    localization_error_mm: Optional[float] = 0.0
    created_at: datetime
    detection: Optional[DetectionResponse] = None

    class Config:
        from_attributes = True

class StatisticsResponse(BaseModel):
    total_shots: int
    average_diameter_px: float
    largest_diameter_px: float
    smallest_diameter_px: float
    last_shot_time: Optional[datetime] = None
    session_status: str
    camera_status: str

class DetectionPipelineResponse(BaseModel):
    shots_detected: List[ShotResponse]
    new_shots_count: int
    current_frame_url: Optional[str] = None
