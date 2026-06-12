import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.core.database import Base

def generate_uuid():
    return str(uuid.uuid4())

class Session(Base):
    __tablename__ = "sessions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False)
    description = Column(String(1024), nullable=True)
    status = Column(String(50), nullable=False, default="active") # active, completed, paused
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    target_type = Column(String(50), nullable=False, default="figure_eleven")
    bullet_caliber = Column(Float, nullable=False, default=5.56)

    images = relationship("Image", back_populates="session", cascade="all, delete-orphan")
    shots = relationship("Shot", back_populates="session", cascade="all, delete-orphan")

class Image(Base):
    __tablename__ = "images"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    session_id = Column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    image_type = Column(String(50), nullable=False) # baseline, capture
    file_path = Column(String(512), nullable=False)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    session = relationship("Session", back_populates="images")
    shots = relationship("Shot", back_populates="image")

class Shot(Base):
    __tablename__ = "shots"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    session_id = Column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    image_id = Column(String(36), ForeignKey("images.id", ondelete="SET NULL"), nullable=True)
    shot_number = Column(Integer, nullable=False)
    x_raw = Column(Float, nullable=False)
    y_raw = Column(Float, nullable=False)
    x_calibrated = Column(Float, nullable=True)
    y_calibrated = Column(Float, nullable=True)
    diameter_px = Column(Float, nullable=False)
    diameter_mm = Column(Float, nullable=True)
    confidence = Column(Float, nullable=False, default=1.0)
    is_valid = Column(Boolean, default=True, nullable=False)
    score = Column(Integer, nullable=True)
    decimal_score = Column(Float, nullable=True)
    nearest_ring_value = Column(Integer, nullable=True)
    distance_to_nearest_ring_mm = Column(Float, nullable=True)
    bullseye_id = Column(Integer, nullable=True)
    distance_to_center_mm = Column(Float, nullable=True)
    boundary_status = Column(String(50), nullable=True)
    localization_method = Column(String(50), nullable=True, default="centroid")
    localization_error_mm = Column(Float, nullable=True, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    session = relationship("Session", back_populates="shots")
    image = relationship("Image", back_populates="shots")
    detection = relationship("Detection", back_populates="shot", uselist=False, cascade="all, delete-orphan")

class Detection(Base):
    __tablename__ = "detections"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    shot_id = Column(String(36), ForeignKey("shots.id", ondelete="CASCADE"), nullable=False)
    area = Column(Float, nullable=False)
    circularity = Column(Float, nullable=False)
    solidity = Column(Float, nullable=False)
    aspect_ratio = Column(Float, nullable=False)
    raw_contour = Column(JSON, nullable=True) # Point list [[x, y], ...]
    
    # Coordinate centers from all four localization methods
    centroid_x_raw = Column(Float, nullable=True)
    centroid_y_raw = Column(Float, nullable=True)
    ellipse_x_raw = Column(Float, nullable=True)
    ellipse_y_raw = Column(Float, nullable=True)
    caliber_x_raw = Column(Float, nullable=True)
    caliber_y_raw = Column(Float, nullable=True)
    weighted_x_raw = Column(Float, nullable=True)
    weighted_y_raw = Column(Float, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    shot = relationship("Shot", back_populates="detection")
