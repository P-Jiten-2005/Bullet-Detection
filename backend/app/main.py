import os
import shutil
import cv2
import numpy as np
import time
import json
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

# Add backend root and project root to sys.path to import from src
backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
project_root = os.path.dirname(backend_root)
sys.path.append(backend_root)
sys.path.append(project_root)

from src.target_definition.target_definition import TargetDefinition
from src.scoring.scoring_engine import ScoringEngine
from src.scoring.boundary_verification import BoundaryVerificationEngine
from src.transformation.coordinate_transformer import CoordinateTransformer

from app.core.config import settings
from app.core.database import engine, Base, get_db
from app.models import models
from app.schemas import schemas
from app.services.cv_engine import cv_engine
from app.services.ws_manager import ws_manager
from app.services.camera_service import camera_service
from app.services.apriltag_service import get_adjusted_target_definition

import logging
logger = logging.getLogger("app.main")

def get_target_corners(baseline_path: Optional[str], session_id: str) -> np.ndarray:
    """
    Retrieves target paper corners.
    1. Reuses camera service calibration if session matches.
    2. Runs AprilTag detection on baseline image.
    3. Runs paper contour search on baseline image.
    4. Falls back to full image size.
    """
    # 1. Reuse active camera calibration corners
    if (
        camera_service.is_calibrated 
        and camera_service.active_session_id == session_id 
        and hasattr(camera_service, "corners_pixel") 
        and camera_service.corners_pixel is not None
    ):
        return camera_service.corners_pixel

    # 2. Extract corners from baseline image (AprilTag or Paper contour)
    if baseline_path and os.path.exists(baseline_path):
        try:
            baseline_img = cv2.imread(baseline_path)
            if baseline_img is not None:
                # Load session/target info synchronously to get physical attributes
                target_width_mm = 210.0
                target_height_mm = 297.0
                tag_size_mm = 15.0
                tag_margin_mm = 20.0
                target_type = "figure_eleven"
                
                paths = [
                    "./data/target_analysis.db",
                    "../../data/target_analysis.db",
                    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "target_analysis.db")
                ]
                for db_path in paths:
                    if os.path.exists(db_path):
                        try:
                            import sqlite3
                            conn = sqlite3.connect(db_path)
                            cursor = conn.cursor()
                            cursor.execute("SELECT target_type FROM sessions WHERE id = ?", (session_id,))
                            row = cursor.fetchone()
                            conn.close()
                            if row:
                                target_type = row[0]
                                break
                        except Exception:
                            pass
                
                try:
                    target = load_target_definition(target_type)
                    target_width_mm = target.width_mm
                    target_height_mm = target.height_mm
                    tag_size_mm = target.tag_size_mm
                    tag_margin_mm = target.tag_margin_mm
                except Exception:
                    pass

                # Try AprilTag
                from app.services.apriltag_service import apriltag_service
                _, corners, tags = apriltag_service.detect_and_warp(
                    baseline_img,
                    tag_size_mm=tag_size_mm,
                    tag_margin_mm=tag_margin_mm,
                    target_width_mm=target_width_mm,
                    target_height_mm=target_height_mm
                )
                if corners is not None and len(tags) >= apriltag_service.min_tags:
                    logger.info(f"AprilTag corner detection: resolved {len(tags)} tags on manual baseline.")
                    try:
                        debug_img = baseline_img.copy()
                        # Sheet border (green)
                        pts_draw = np.array(corners, dtype=np.int32).reshape((-1, 1, 2))
                        cv2.polylines(debug_img, [pts_draw], isClosed=True, color=(0, 255, 0), thickness=3)
                        cv2.putText(debug_img, "Detected Target Sheet", (int(corners[0][0]), int(corners[0][1] - 15)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
                        # AprilTags (cyan)
                        for tag in tags:
                            tc = np.array(tag["corners"], dtype=np.int32).reshape((-1, 1, 2))
                            cv2.polylines(debug_img, [tc], isClosed=True, color=(255, 255, 0), thickness=2)
                            cx, cy = int(tag["center"][0]), int(tag["center"][1])
                            cv2.circle(debug_img, (cx, cy), 5, (0, 0, 255), -1)
                            cv2.putText(debug_img, f"Tag ID: {tag['id']}", (cx - 20, cy - 10),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
                        
                        # Draw scoring zones and bounding boxes
                        if target is not None:
                            from app.services.camera_service import draw_zones_on_image, generate_rectified_debug_image
                            debug_img = draw_zones_on_image(debug_img, corners, target)
                            generate_rectified_debug_image(session_id, baseline_path, target, corners, [])

                        debug_path = os.path.join(settings.UPLOAD_DIR, f"debug_calibration_{session_id}.jpg")
                        cv2.imwrite(debug_path, debug_img, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
                    except Exception as ex:
                        logger.warning(f"Failed to save AprilTag manual baseline debug image: {ex}")
                    return np.array(corners, dtype=np.float32)

                # Try Paper Contour
                pts = camera_service._find_paper_contour(baseline_img)
                if pts is not None:
                    rect = np.zeros((4, 2), dtype="float32")
                    s = pts.sum(axis=1)
                    rect[0] = pts[np.argmin(s)]
                    rect[2] = pts[np.argmax(s)]
                    diff = np.diff(pts, axis=1)
                    rect[1] = pts[np.argmin(diff)]
                    rect[3] = pts[np.argmax(diff)]
                    logger.info("Paper contour corner detection: resolved border on manual baseline.")
                    try:
                        debug_img = baseline_img.copy()
                        pts_draw = np.array(rect, dtype=np.int32).reshape((-1, 1, 2))
                        cv2.polylines(debug_img, [pts_draw], isClosed=True, color=(0, 255, 0), thickness=3)
                        cv2.putText(debug_img, "Detected Target Sheet (Contour)", (int(rect[0][0]), int(rect[0][1] - 15)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
                        cv2.putText(debug_img, "No AprilTags detected (Fallback to contour)", (30, 40),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)

                        # Draw scoring zones and bounding boxes
                        if target is not None:
                            from app.services.camera_service import draw_zones_on_image, generate_rectified_debug_image
                            debug_img = draw_zones_on_image(debug_img, rect, target)
                            generate_rectified_debug_image(session_id, baseline_path, target, rect, [])

                        debug_path = os.path.join(settings.UPLOAD_DIR, f"debug_calibration_{session_id}.jpg")
                        cv2.imwrite(debug_path, debug_img, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
                    except Exception as ex:
                        logger.warning(f"Failed to save contour manual baseline debug image: {ex}")
                    return rect
        except Exception as e:
            logger.warning(f"Failed to detect baseline target paper corners: {e}")

    # 3. Fallback: Full image dimensions
    if baseline_path and os.path.exists(baseline_path):
        try:
            baseline_img = cv2.imread(baseline_path)
            if baseline_img is not None:
                h, w = baseline_img.shape[:2]
                return np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype=np.float32)
        except Exception:
            pass

    return np.array([[0, 0], [999, 0], [999, 999], [0, 999]], dtype=np.float32)

def get_static_baseline_corners(baseline_path: Optional[str], session_id: str, target: Any) -> np.ndarray:
    """
    Detects/calculates target corners on the static baseline image specifically,
    without falling back/reusing the camera_service's dynamic calibration corners.
    """
    if baseline_path and os.path.exists(baseline_path):
        try:
            baseline_img = cv2.imread(baseline_path)
            if baseline_img is not None:
                from app.services.apriltag_service import apriltag_service
                _, corners, tags = apriltag_service.detect_and_warp(
                    baseline_img,
                    tag_size_mm=target.tag_size_mm,
                    tag_margin_mm=target.tag_margin_mm,
                    target_width_mm=target.width_mm,
                    target_height_mm=target.height_mm
                )
                if corners is not None and len(tags) >= apriltag_service.min_tags:
                    return np.array(corners, dtype=np.float32)

                # Try Paper Contour
                pts = camera_service._find_paper_contour(baseline_img)
                if pts is not None:
                    rect = np.zeros((4, 2), dtype="float32")
                    s = pts.sum(axis=1)
                    rect[0] = pts[np.argmin(s)]
                    rect[2] = pts[np.argmax(s)]
                    diff = np.diff(pts, axis=1)
                    rect[1] = pts[np.argmin(diff)]
                    rect[3] = pts[np.argmax(diff)]
                    return rect
        except Exception as e:
            logger.warning(f"Failed to detect static baseline corners: {e}")

    # Fallback to full image size
    if baseline_path and os.path.exists(baseline_path):
        try:
            img = cv2.imread(baseline_path)
            if img is not None:
                h, w = img.shape[:2]
                return np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype=np.float32)
        except Exception:
            pass
    return np.array([[0, 0], [999, 0], [999, 999], [0, 999]], dtype=np.float32)

def load_target_definition(target_type: str) -> TargetDefinition:
    filename = f"{target_type}.json"
    file_path = os.path.join(backend_root, "configs", "targets", filename)
    if not os.path.exists(file_path):
        file_path = os.path.join(backend_root, "configs", "targets", "figure_eleven.json")
    return TargetDefinition.load_from_json(file_path)

def score_shot_record(
    shot: models.Shot, 
    session: models.Session, 
    target: TargetDefinition,
    transformer: CoordinateTransformer,
    detection_dict: Optional[Dict[str, Any]] = None
):
    # Transform raw pixel coordinates directly to target millimeters (Approach B: Detect-then-Transform)
    x_mm, y_mm = transformer.raw_pixel_to_target_mm(shot.x_raw, shot.y_raw)
    shot.x_calibrated = x_mm
    shot.y_calibrated = y_mm

    # Project contour points to mm space and calculate physical equivalent diameter
    if detection_dict is not None and "raw_contour" in detection_dict and detection_dict["raw_contour"] is not None:
        try:
            contour_mm = []
            for pt in detection_dict["raw_contour"]:
                mx, my = transformer.raw_pixel_to_target_mm(float(pt[0]), float(pt[1]))
                contour_mm.append([mx, my])
            contour_mm_arr = np.array(contour_mm, dtype=np.float32)
            # Compute contour area in mm^2
            area_mm = cv2.contourArea(contour_mm_arr)
            # Calculate equivalent circular diameter from mm-space area
            shot.diameter_mm = float(np.sqrt(4.0 * area_mm / np.pi))
        except Exception as e:
            logger.warning(f"Failed to calculate mm-space contour area, falling back: {e}")
            x_offset_mm, y_offset_mm = transformer.raw_pixel_to_target_mm(shot.x_raw + (shot.diameter_px / 2.0), shot.y_raw)
            local_radius_mm = np.sqrt((x_offset_mm - x_mm)**2 + (y_offset_mm - y_mm)**2)
            shot.diameter_mm = local_radius_mm * 2.0
    else:
        # Fallback to local scale estimate
        x_offset_mm, y_offset_mm = transformer.raw_pixel_to_target_mm(shot.x_raw + (shot.diameter_px / 2.0), shot.y_raw)
        local_radius_mm = np.sqrt((x_offset_mm - x_mm)**2 + (y_offset_mm - y_mm)**2)
        shot.diameter_mm = local_radius_mm * 2.0

    # Calculate localization error
    if detection_dict is not None:
        try:
            cx_cent, cy_cent = transformer.raw_pixel_to_target_mm(detection_dict["centroid_x_raw"], detection_dict["centroid_y_raw"])
            cx_ell, cy_ell = transformer.raw_pixel_to_target_mm(detection_dict["ellipse_x_raw"], detection_dict["ellipse_y_raw"])
            cx_cal, cy_cal = transformer.raw_pixel_to_target_mm(detection_dict["caliber_x_raw"], detection_dict["caliber_y_raw"])
            cx_wt, cy_wt = transformer.raw_pixel_to_target_mm(detection_dict["weighted_x_raw"], detection_dict["weighted_y_raw"])

            x_coords = [cx_cent, cx_ell, cx_cal, cx_wt]
            y_coords = [cy_cent, cy_ell, cy_cal, cy_wt]

            error_x = np.std(x_coords)
            error_y = np.std(y_coords)
            shot.localization_error_mm = float(np.sqrt(error_x**2 + error_y**2))
        except Exception:
            shot.localization_error_mm = 0.3
    else:
        shot.localization_error_mm = 0.0

    # Score shot
    scoring_engine = ScoringEngine()
    bullet_radius = (session.bullet_caliber or 4.5) / 2.0
    scores = scoring_engine.score_shot(
        impact_x_mm=x_mm,
        impact_y_mm=y_mm,
        bullet_radius_mm=bullet_radius,
        target=target
    )

    shot.score = scores["score"]
    shot.decimal_score = scores["decimal_score"]
    shot.nearest_ring_value = scores["nearest_ring_value"]
    shot.distance_to_nearest_ring_mm = scores["distance_to_nearest_ring_mm"]
    shot.bullseye_id = scores["bullseye_id"]
    shot.distance_to_center_mm = scores["distance_to_center_mm"]

    # Boundary verification
    boundary_engine = BoundaryVerificationEngine()
    boundary_res = boundary_engine.verify_boundary(
        distance_to_nearest_ring_mm=scores["distance_to_nearest_ring_mm"],
        localization_error_mm=shot.localization_error_mm if shot.localization_error_mm > 0 else 0.3
    )
    shot.boundary_status = boundary_res["status"]

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize SQLite/PostgreSQL schema dynamically on startup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount the upload directory to serve captured frames to the dashboard canvas
app.mount("/static/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")


# --- HTTP Endpoints ---

@app.post(f"{settings.API_V1_STR}/sessions", response_model=schemas.SessionResponse)
async def create_session(session_in: schemas.SessionCreate, db: AsyncSession = Depends(get_db)):
    """
    Creates a new shooting session. If there's an existing 'active' session,
    it marks it as 'completed' first.
    """
    # Deactivate existing sessions
    await db.execute(
        update(models.Session)
        .where(models.Session.status == "active")
        .values(status="completed", updated_at=datetime.utcnow())
    )
    
    # Create new session
    session = models.Session(
        name=session_in.name,
        description=session_in.description,
        status="active",
        target_type=session_in.target_type or "figure_eleven",
        bullet_caliber=session_in.bullet_caliber or 5.56
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session

@app.get(f"{settings.API_V1_STR}/targets")
async def list_targets():
    """
    Lists all available target definitions from the configs/targets directory.
    """
    targets_dir = os.path.join(backend_root, "configs", "targets")
    targets = []
    if os.path.exists(targets_dir):
        for f in os.listdir(targets_dir):
            if f.endswith(".json"):
                target_id = f[:-5]
                try:
                    t_def = TargetDefinition.load_from_json(os.path.join(targets_dir, f))
                    targets.append({
                        "id": target_id,
                        "name": t_def.name,
                        "width_mm": t_def.width_mm,
                        "height_mm": t_def.height_mm,
                        "bullet_compatibility": t_def.bullet_compatibility,
                        "decimal_scoring_supported": t_def.decimal_scoring_supported,
                        "preview_url": t_def.preview_url
                    })
                except Exception as e:
                    logger.error(f"Failed to load target config {f}: {e}")
    return targets

@app.post(f"{settings.API_V1_STR}/targets")
async def create_target(target_data: Dict[str, Any]):
    """
    Creates a new target definition and saves it as a JSON file in configs/targets/
    Optionally saves a preview image if provided as base64 in target_data['preview_image_base64'].
    """
    name = target_data.get("name")
    if not name:
        raise HTTPException(status_code=400, detail="Target name is required")
        
    import re
    import base64
    target_id = re.sub(r'[^a-z0-9_]', '', name.lower().replace(" ", "_"))
    if not target_id:
        target_id = f"target_{int(time.time())}"
        
    targets_dir = os.path.join(backend_root, "configs", "targets")
    os.makedirs(targets_dir, exist_ok=True)
    
    # Check base64 preview image
    preview_url = None
    b64_image = target_data.get("preview_image_base64")
    if b64_image:
        try:
            if "," in b64_image:
                b64_image = b64_image.split(",")[1]
            image_bytes = base64.b64decode(b64_image)
            image_filename = f"target_preview_{target_id}.png"
            image_path = os.path.join(settings.UPLOAD_DIR, image_filename)
            with open(image_path, "wb") as img_f:
                img_f.write(image_bytes)
            preview_url = f"/static/uploads/{image_filename}"
        except Exception as e:
            logger.error(f"Failed to save target preview image: {e}")

    # Remove base64 to keep JSON small
    config_data = {k: v for k, v in target_data.items() if k != "preview_image_base64"}
    config_data["preview_url"] = preview_url
    
    file_path = os.path.join(targets_dir, f"{target_id}.json")
    try:
        with open(file_path, "w") as f:
            json.dump(config_data, f, indent=2)
        return {"success": True, "id": target_id, "name": name, "preview_url": preview_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write target config: {e}")

@app.get(f"{settings.API_V1_STR}/targets/{{target_id}}")
async def get_target(target_id: str):
    """
    Retrieves the full JSON definition of a specific target configuration.
    """
    file_path = os.path.join(backend_root, "configs", "targets", f"{target_id}.json")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Target configuration not found")
    try:
        with open(file_path, "r") as f:
            data = json.load(f)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading target config: {e}")


@app.get(f"{settings.API_V1_STR}/sessions/active", response_model=Optional[schemas.SessionResponse])
async def get_active_session(db: AsyncSession = Depends(get_db)):
    """
    Retrieves the currently active session, if any exists.
    """
    result = await db.execute(
        select(models.Session).where(models.Session.status == "active")
    )
    return result.scalars().first()


@app.get(f"{settings.API_V1_STR}/sessions/{{session_id}}/projected-zones")
async def get_projected_zones(session_id: str, db: AsyncSession = Depends(get_db)):
    """
    Calculates and returns the target scoring zones projected onto the raw baseline image coordinates.
    """
    # 1. Load Session
    session_result = await db.execute(
        select(models.Session).where(models.Session.id == session_id)
    )
    session = session_result.scalars().first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    # 2. Get baseline image path
    baseline_result = await db.execute(
        select(models.Image)
        .where(models.Image.session_id == session_id)
        .where(models.Image.image_type == "baseline")
    )
    baseline_image = baseline_result.scalars().first()
    if not baseline_image:
        return {"scoring_regions": [], "bullseyes": []}
        
    baseline_path = baseline_image.file_path
    if baseline_path.startswith("/static/uploads/") or baseline_path.startswith("static/uploads/"):
        filename = os.path.basename(baseline_path)
        baseline_path = os.path.join(settings.UPLOAD_DIR, filename)
        
    # 3. Load Target Definition & Corners
    try:
        target = load_target_definition(session.target_type)
        corners_pixel = get_target_corners(baseline_path, session_id)
        target = get_adjusted_target_definition(target, baseline_path, corners_pixel)
    except Exception as e:
        logger.error(f"Failed to load target definition or corners for projected-zones: {e}")
        return {"scoring_regions": [], "bullseyes": []}
        
    # 4. Build Transformer
    try:
        transformer = CoordinateTransformer(
            corners_pixel=corners_pixel,
            target_width_mm=target.width_mm,
            target_height_mm=target.height_mm
        )
    except Exception as e:
        logger.error(f"Failed to build CoordinateTransformer: {e}")
        return {"scoring_regions": [], "bullseyes": []}
        
    scoring_regions = []
    bullseyes = []
    
    # Project Rectangular Regions
    if target.scoring_regions:
        for region in target.scoring_regions:
            rx_min, ry_min = region.x_min_mm, region.y_min_mm
            rx_max, ry_max = region.x_max_mm, region.y_max_mm
            
            p1 = transformer.target_mm_to_raw_pixel(rx_min, ry_min)
            p2 = transformer.target_mm_to_raw_pixel(rx_max, ry_min)
            p3 = transformer.target_mm_to_raw_pixel(rx_max, ry_max)
            p4 = transformer.target_mm_to_raw_pixel(rx_min, ry_max)
            
            scoring_regions.append({
                "id": region.id,
                "name": region.name,
                "value": region.value,
                "polygon": [list(p1), list(p2), list(p3), list(p4)]
            })
            
    # Project Bullseyes
    if target.bullseyes:
        for b in target.bullseyes:
            cx_mm, cy_mm = b.center_x_mm, b.center_y_mm
            cx_px, cy_px = transformer.target_mm_to_raw_pixel(cx_mm, cy_mm)
            
            rings = []
            if b.rings:
                for ring in b.rings:
                    r_mm = ring.outer_radius_mm
                    theta = np.linspace(0, 2 * np.pi, 36)
                    polygon = []
                    for t in theta:
                        rx = cx_mm + r_mm * np.cos(t)
                        ry = cy_mm + r_mm * np.sin(t)
                        px, py = transformer.target_mm_to_raw_pixel(rx, ry)
                        polygon.append([px, py])
                    
                    rings.append({
                        "value": ring.value,
                        "outer_radius_mm": r_mm,
                        "polygon": polygon
                    })
            
            bullseyes.append({
                "id": b.id,
                "center_pixel": [cx_px, cy_px],
                "rings": rings
            })
            
    return {
        "scoring_regions": scoring_regions,
        "bullseyes": bullseyes
    }


@app.get(f"{settings.API_V1_STR}/sessions/{{session_id}}/baseline", response_model=Optional[schemas.ImageResponse])
async def get_session_baseline(session_id: str, db: AsyncSession = Depends(get_db)):
    """
    Retrieves the baseline image details if it exists.
    """
    result = await db.execute(
        select(models.Image)
        .where(models.Image.session_id == session_id)
        .where(models.Image.image_type == "baseline")
    )
    db_image = result.scalars().first()
    if not db_image:
        return None
    
    filename = os.path.basename(db_image.file_path)
    return schemas.ImageResponse(
        id=db_image.id,
        session_id=db_image.session_id,
        image_type=db_image.image_type,
        file_path=f"/static/uploads/{filename}",
        metadata_json=db_image.metadata_json,
        created_at=db_image.created_at
    )


@app.post(f"{settings.API_V1_STR}/sessions/{{session_id}}/baseline", response_model=schemas.ImageResponse)
async def upload_baseline(
    session_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Uploads and stores the baseline (reference) image for a shooting session.
    """
    # Verify session exists
    session_result = await db.execute(
        select(models.Session).where(models.Session.id == session_id)
    )
    session = session_result.scalars().first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Save file to uploads folder
    file_ext = os.path.splitext(file.filename)[1]
    file_name = f"baseline_{session_id}{file_ext}"
    file_path = os.path.join(settings.UPLOAD_DIR, file_name)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Save reference in database
    image = models.Image(
        session_id=session_id,
        image_type="baseline",
        file_path=file_path,
        metadata_json={"filename": file.filename, "content_type": file.content_type}
    )
    db.add(image)
    await db.commit()
    await db.refresh(image)
    
    # Run target/tag detection immediately to generate debug calibration overlay
    try:
        get_target_corners(file_path, session_id)
    except Exception as ex:
        logger.warning(f"Failed to generate target corners debug overlay after baseline upload: {ex}")
        
    # Broadcast session update
    await ws_manager.broadcast_to_session(session_id, {
        "event": "BASELINE_UPLOADED",
        "data": {
            "image_id": image.id,
            "file_path": f"/static/uploads/{file_name}"
        }
    })

    return schemas.ImageResponse(
        id=image.id,
        session_id=image.session_id,
        image_type=image.image_type,
        file_path=f"/static/uploads/{file_name}",
        metadata_json=image.metadata_json,
        created_at=image.created_at
    )


@app.post(f"{settings.API_V1_STR}/sessions/{{session_id}}/detect", response_model=schemas.DetectionPipelineResponse)
async def run_detection(
    session_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Uploads the current frame, runs the OpenCV differencing pipeline against the session's
    baseline image, registers new bullet holes in the database, and broadcasts updates over WebSockets.
    """
    # 1. Fetch Session & baseline image
    session_result = await db.execute(
        select(models.Session).where(models.Session.id == session_id)
    )
    session = session_result.scalars().first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    baseline_result = await db.execute(
        select(models.Image)
        .where(models.Image.session_id == session_id)
        .where(models.Image.image_type == "baseline")
    )
    baseline_image = baseline_result.scalars().first()
    if not baseline_image:
        raise HTTPException(status_code=400, detail="No baseline image uploaded for this session")

    # self-healing for corrupted baseline path
    baseline_path = baseline_image.file_path
    if baseline_path.startswith("/static/uploads/") or baseline_path.startswith("static/uploads/"):
        filename = os.path.basename(baseline_path)
        baseline_path = os.path.join(settings.UPLOAD_DIR, filename)
        baseline_image.file_path = baseline_path

    # 2. Save current frame to disk
    file_ext = os.path.splitext(file.filename)[1]
    timestamp_str = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    file_name = f"capture_{session_id}_{timestamp_str}{file_ext}"
    file_path = os.path.join(settings.UPLOAD_DIR, file_name)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    capture_image = models.Image(
        session_id=session_id,
        image_type="capture",
        file_path=file_path,
        metadata_json={"filename": file.filename}
    )
    db.add(capture_image)
    await db.flush() # Generate ID for capture_image

    # 3. Retrieve all existing shots in this session for proximity deduplication
    shots_result = await db.execute(
        select(models.Shot).where(models.Shot.session_id == session_id)
    )
    existing_shots = [
        {
            "x_raw": s.x_raw,
            "y_raw": s.y_raw,
            "diameter_px": s.diameter_px,
            "x_calibrated": s.x_calibrated,
            "y_calibrated": s.y_calibrated
        } 
        for s in shots_result.scalars().all()
    ]

    # 4. Count current shots to establish shot numbering sequence
    current_count_result = await db.execute(
        select(func.count(models.Shot.id)).where(models.Shot.session_id == session_id)
    )
    shot_sequence_counter = current_count_result.scalar() or 0

    # 5. Build Coordinate Transformer and run CV Engine Detection
    target = load_target_definition(session.target_type)
    
    # Try to detect tags on the current uploaded frame to compute a fresh homography
    try:
        curr_img = cv2.imread(capture_image.file_path)
        if curr_img is not None:
            from app.services.apriltag_service import apriltag_service
            _, current_corners, tags = apriltag_service.detect_and_warp(
                curr_img,
                tag_size_mm=target.tag_size_mm,
                tag_margin_mm=target.tag_margin_mm,
                target_width_mm=target.width_mm,
                target_height_mm=target.height_mm
            )
            if current_corners is not None and len(tags) >= apriltag_service.min_tags:
                corners_pixel = current_corners
                logger.info("Successfully detected AprilTags on current uploaded frame for dynamic homography.")
            else:
                corners_pixel = get_target_corners(baseline_path, session_id)
        else:
            corners_pixel = get_target_corners(baseline_path, session_id)
    except Exception as e:
        logger.warning(f"Failed to detect tags on uploaded frame, falling back: {e}")
        corners_pixel = get_target_corners(baseline_path, session_id)

    target = get_adjusted_target_definition(target, baseline_path, corners_pixel)

    transformer = CoordinateTransformer(
        corners_pixel=corners_pixel,
        target_width_mm=target.width_mm,
        target_height_mm=target.height_mm,
        warped_width_px=1000.0,
        warped_height_px=1000.0
    )

    # Build baseline transformer for mapping current-frame coordinates to baseline frame
    baseline_corners = get_static_baseline_corners(baseline_path, session_id, target)
    transformer_baseline = CoordinateTransformer(
        corners_pixel=baseline_corners,
        target_width_mm=target.width_mm,
        target_height_mm=target.height_mm,
        warped_width_px=1000.0,
        warped_height_px=1000.0
    )

    new_hole_detections = cv_engine.detect_holes(
        baseline_path=baseline_path,
        current_path=capture_image.file_path,
        existing_shots=existing_shots,
        transformer=transformer,
        bullet_caliber_mm=session.bullet_caliber,
        session_id=session_id
    )

    new_shots_saved = []

    # 6. Save new shots & detailed metrics
    for detection in new_hole_detections:
        shot_sequence_counter += 1
        
        new_shot = models.Shot(
            session_id=session_id,
            image_id=capture_image.id,
            shot_number=shot_sequence_counter,
            x_raw=detection["x_raw"],
            y_raw=detection["y_raw"],
            diameter_px=detection["diameter_px"],
            confidence=detection["confidence"],
            is_valid=True,
            localization_method=detection["selected_method"]
        )
        score_shot_record(new_shot, session, target, transformer, detection_dict=detection)
        db.add(new_shot)
        await db.flush() # Generate new_shot.id

        new_detection_record = models.Detection(
            shot_id=new_shot.id,
            area=detection["area"],
            circularity=detection["circularity"],
            solidity=detection["solidity"],
            aspect_ratio=detection["aspect_ratio"],
            raw_contour=detection["raw_contour"],
            centroid_x_raw=detection["centroid_x_raw"],
            centroid_y_raw=detection["centroid_y_raw"],
            ellipse_x_raw=detection["ellipse_x_raw"],
            ellipse_y_raw=detection["ellipse_y_raw"],
            caliber_x_raw=detection["caliber_x_raw"],
            caliber_y_raw=detection["caliber_y_raw"],
            weighted_x_raw=detection["weighted_x_raw"],
            weighted_y_raw=detection["weighted_y_raw"]
        )

        # Project raw shot coordinates back to static baseline pixel space for database/display consistency
        try:
            x_mm, y_mm = new_shot.x_calibrated, new_shot.y_calibrated
            x_base, y_base = transformer_baseline.target_mm_to_raw_pixel(x_mm, y_mm)
            new_shot.x_raw = float(x_base)
            new_shot.y_raw = float(y_base)

            # centroid
            cx_mm, cy_mm = transformer.raw_pixel_to_target_mm(detection["centroid_x_raw"], detection["centroid_y_raw"])
            cb_x, cb_y = transformer_baseline.target_mm_to_raw_pixel(cx_mm, cy_mm)
            new_detection_record.centroid_x_raw = float(cb_x)
            new_detection_record.centroid_y_raw = float(cb_y)

            # ellipse
            ex_mm, ey_mm = transformer.raw_pixel_to_target_mm(detection["ellipse_x_raw"], detection["ellipse_y_raw"])
            eb_x, eb_y = transformer_baseline.target_mm_to_raw_pixel(ex_mm, ey_mm)
            new_detection_record.ellipse_x_raw = float(eb_x)
            new_detection_record.ellipse_y_raw = float(eb_y)

            # caliber
            cal_x_mm, cal_y_mm = transformer.raw_pixel_to_target_mm(detection["caliber_x_raw"], detection["caliber_y_raw"])
            calb_x, calb_y = transformer_baseline.target_mm_to_raw_pixel(cal_x_mm, cal_y_mm)
            new_detection_record.caliber_x_raw = float(calb_x)
            new_detection_record.caliber_y_raw = float(calb_y)

            # weighted
            w_mm_x, w_mm_y = transformer.raw_pixel_to_target_mm(detection["weighted_x_raw"], detection["weighted_y_raw"])
            wb_x, wb_y = transformer_baseline.target_mm_to_raw_pixel(w_mm_x, w_mm_y)
            new_detection_record.weighted_x_raw = float(wb_x)
            new_detection_record.weighted_y_raw = float(wb_y)

            # raw_contour
            if detection.get("raw_contour") is not None:
                raw_contour_base = []
                for pt in detection["raw_contour"]:
                    pt_mm_x, pt_mm_y = transformer.raw_pixel_to_target_mm(float(pt[0]), float(pt[1]))
                    pt_base_x, pt_base_y = transformer_baseline.target_mm_to_raw_pixel(pt_mm_x, pt_mm_y)
                    raw_contour_base.append([float(pt_base_x), float(pt_base_y)])
                new_detection_record.raw_contour = raw_contour_base
        except Exception as e:
            logger.warning(f"Failed to map detection coords back to baseline in run_detection: {e}")

        db.add(new_detection_record)
        
        # Keep reference to shape contour in response payload
        new_shots_saved.append((new_shot, new_detection_record))

    await db.commit()

    # Generate perspective-rectified debug view showing all cumulative shots
    try:
        from app.services.camera_service import generate_rectified_debug_image
        all_shots_res = await db.execute(
            select(models.Shot).where(models.Shot.session_id == session_id)
        )
        all_shots = all_shots_res.scalars().all()
        generate_rectified_debug_image(session_id, capture_image.file_path, target, corners_pixel, all_shots)
    except Exception as rect_err:
        logger.warning(f"Failed to generate rectified debug view: {rect_err}")

    # 7. Construct response list & WebSocket broadcasts
    response_shots = []
    for shot, det in new_shots_saved:
        shot_data = schemas.ShotResponse(
            id=shot.id,
            session_id=shot.session_id,
            image_id=shot.image_id,
            shot_number=shot.shot_number,
            x_raw=shot.x_raw,
            y_raw=shot.y_raw,
            x_calibrated=shot.x_calibrated,
            y_calibrated=shot.y_calibrated,
            diameter_px=shot.diameter_px,
            diameter_mm=shot.diameter_mm,
            confidence=shot.confidence,
            is_valid=shot.is_valid,
            score=shot.score,
            decimal_score=shot.decimal_score,
            nearest_ring_value=shot.nearest_ring_value,
            distance_to_nearest_ring_mm=shot.distance_to_nearest_ring_mm,
            bullseye_id=shot.bullseye_id,
            distance_to_center_mm=shot.distance_to_center_mm,
            boundary_status=shot.boundary_status,
            localization_method=shot.localization_method,
            localization_error_mm=shot.localization_error_mm,
            created_at=shot.created_at,
            detection=schemas.DetectionResponse(
                id=det.id,
                area=det.area,
                circularity=det.circularity,
                solidity=det.solidity,
                aspect_ratio=det.aspect_ratio,
                raw_contour=det.raw_contour,
                centroid_x_raw=det.centroid_x_raw,
                centroid_y_raw=det.centroid_y_raw,
                ellipse_x_raw=det.ellipse_x_raw,
                ellipse_y_raw=det.ellipse_y_raw,
                caliber_x_raw=det.caliber_x_raw,
                caliber_y_raw=det.caliber_y_raw,
                weighted_x_raw=det.weighted_x_raw,
                weighted_y_raw=det.weighted_y_raw
            )
        )
        response_shots.append(shot_data)

        # Broadcast each shot to live UI clients immediately
        await ws_manager.broadcast_to_session(session_id, {
            "event": "SHOT_DETECTED",
            "data": shot_data.dict()
        })

    return {
        "shots_detected": response_shots,
        "new_shots_count": len(response_shots),
        "current_frame_url": f"/static/uploads/{file_name}?t={int(time.time())}"
    }


@app.get(f"{settings.API_V1_STR}/sessions/{{session_id}}/shots", response_model=List[schemas.ShotResponse])
async def get_session_shots(session_id: str, db: AsyncSession = Depends(get_db)):
    """
    Fetches all shots recorded in the session, sorted by sequence number.
    """
    result = await db.execute(
        select(models.Shot)
        .where(models.Shot.session_id == session_id)
        .options(selectinload(models.Shot.detection))
        .order_by(models.Shot.shot_number.asc())
    )
    return result.scalars().all()


@app.get(f"{settings.API_V1_STR}/sessions/{{session_id}}/statistics", response_model=schemas.StatisticsResponse)
async def get_session_statistics(session_id: str, db: AsyncSession = Depends(get_db)):
    """
    Calculates aggregated statistics for the shooting session.
    """
    session_result = await db.execute(
        select(models.Session).where(models.Session.id == session_id)
    )
    session = session_result.scalars().first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    stats_query = select(
        func.count(models.Shot.id).label("total"),
        func.avg(models.Shot.diameter_px).label("avg_dia"),
        func.max(models.Shot.diameter_px).label("max_dia"),
        func.min(models.Shot.diameter_px).label("min_dia"),
        func.max(models.Shot.created_at).label("last_shot")
    ).where(models.Shot.session_id == session_id).where(models.Shot.is_valid == True)

    result = await db.execute(stats_query)
    row = result.first()

    return schemas.StatisticsResponse(
        total_shots=row.total or 0,
        average_diameter_px=round(row.avg_dia or 0.0, 2),
        largest_diameter_px=round(row.max_dia or 0.0, 2),
        smallest_diameter_px=round(row.min_dia or 0.0, 2),
        last_shot_time=row.last_shot,
        session_status=session.status,
        camera_status="online" if camera_service.is_running else "offline"
    )


@app.delete(f"{settings.API_V1_STR}/sessions/{{session_id}}/shots")
async def clear_session_shots(session_id: str, db: AsyncSession = Depends(get_db)):
    """
    Deletes all shot and detection records for the session, allowing a clean slate.
    """
    # Delete all shots (cascades to detections in DB)
    await db.execute(
        models.Shot.__table__.delete().where(models.Shot.session_id == session_id)
    )
    await db.commit()
    
    # Broadcast to websocket that shots were cleared
    await ws_manager.broadcast_to_session(session_id, {
        "event": "SHOTS_CLEARED",
        "data": {}
    })
    return {"success": True}


@app.delete(f"{settings.API_V1_STR}/sessions/{{session_id}}")
async def delete_session(session_id: str, db: AsyncSession = Depends(get_db)):
    """
    Deletes the shooting session and cleans up its database records and uploads.
    """
    result = await db.execute(
        select(models.Session).where(models.Session.id == session_id)
    )
    session = result.scalars().first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    await db.delete(session)
    await db.commit()
    return {"success": True}


# --- WebSocket Route ---

@app.websocket("/ws/session/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """
    Handles real-time dashboard subscriptions. Clients connect to this socket
    to receive live telemetry messages when shots are detected.
    """
    await ws_manager.connect(websocket, session_id)
    try:
        while True:
            # Maintain connection, handle client pings
            data = await websocket.receive_text()
            # Simple Echo/Heartbeat support
            await websocket.send_text(f"heartbeat: {data}")
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, session_id)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        ws_manager.disconnect(websocket, session_id)


# --- Camera Integration Endpoints ---

@app.post(f"{settings.API_V1_STR}/camera/start")
async def start_camera(source: str = "0", session_id: Optional[str] = None):
    success = camera_service.start_camera(source)
    if not success:
        raise HTTPException(status_code=400, detail=f"Failed to connect to camera source: {source}")
    if session_id:
        camera_service.set_active_session(session_id)
    return {"success": True}

@app.post(f"{settings.API_V1_STR}/camera/stop")
async def stop_camera():
    camera_service.stop_camera()
    return {"success": True}

@app.post(f"{settings.API_V1_STR}/camera/calibrate")
async def calibrate_camera(session_id: str, db: AsyncSession = Depends(get_db)):
    # Verify session exists
    session_result = await db.execute(
        select(models.Session).where(models.Session.id == session_id)
    )
    session = session_result.scalars().first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    success = camera_service.calibrate_homography(session_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to calibrate target baseline. Ensure camera is running and target sheet is visible.")

    # Save baseline image in db
    file_path = os.path.join(settings.UPLOAD_DIR, f"baseline_{session_id}.jpg")
    
    # Check if there is an existing baseline image for this session
    img_result = await db.execute(
        select(models.Image)
        .where(models.Image.session_id == session_id)
        .where(models.Image.image_type == "baseline")
    )
    existing_img = img_result.scalars().first()
    
    if not existing_img:
        image = models.Image(
            session_id=session_id,
            image_type="baseline",
            file_path=file_path,
            metadata_json={"source": "camera_calibration"}
        )
        db.add(image)
        await db.commit()
    else:
        existing_img.file_path = file_path
        existing_img.created_at = datetime.utcnow()
        await db.commit()

    # Broadcast baseline uploaded
    await ws_manager.broadcast_to_session(session_id, {
        "event": "BASELINE_UPLOADED",
        "data": {
            "file_path": f"/static/uploads/baseline_{session_id}.jpg?t={int(time.time())}",
            "method": camera_service.calibration_method
        }
    })

    return {
        "success": True,
        "method": camera_service.calibration_method,
        "file_path": f"/static/uploads/baseline_{session_id}.jpg?t={int(time.time())}"
    }

@app.post(f"{settings.API_V1_STR}/camera/before_fire")
async def capture_before_fire(session_id: str, db: AsyncSession = Depends(get_db)):
    # Verify session exists
    session_result = await db.execute(
        select(models.Session).where(models.Session.id == session_id)
    )
    session = session_result.scalars().first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if camera_service.homography_matrix is None:
        # If not calibrated, try to calibrate first
        success = camera_service.calibrate_homography(session_id)
        if not success:
            raise HTTPException(status_code=400, detail="Camera has not been calibrated. Run /calibrate first.")

    rectified = camera_service.capture_before_fire(session_id)
    if rectified is None:
        raise HTTPException(status_code=400, detail="Failed to capture reference image before fire.")

    file_path = os.path.join(settings.UPLOAD_DIR, f"baseline_{session_id}.jpg")

    # Update or insert in database
    img_result = await db.execute(
        select(models.Image)
        .where(models.Image.session_id == session_id)
        .where(models.Image.image_type == "baseline")
    )
    existing_img = img_result.scalars().first()

    if not existing_img:
        image = models.Image(
            session_id=session_id,
            image_type="baseline",
            file_path=file_path,
            metadata_json={"source": "camera_before_fire"}
        )
        db.add(image)
        await db.commit()
    else:
        existing_img.file_path = file_path
        existing_img.created_at = datetime.utcnow()
        await db.commit()

    # Broadcast baseline uploaded so frontend refreshes the reference image
    await ws_manager.broadcast_to_session(session_id, {
        "event": "BASELINE_UPLOADED",
        "data": {
            "file_path": f"/static/uploads/baseline_{session_id}.jpg?t={int(time.time())}",
            "method": camera_service.calibration_method
        }
    })

    return {
        "success": True,
        "method": camera_service.calibration_method,
        "file_path": f"/static/uploads/baseline_{session_id}.jpg?t={int(time.time())}"
    }

@app.post(f"{settings.API_V1_STR}/camera/start-round")
async def start_round(session_id: str, db: AsyncSession = Depends(get_db)):
    if not camera_service.is_calibrated or camera_service.active_session_id != session_id:
        raise HTTPException(status_code=400, detail="Camera not calibrated. Wait for auto-calibration.")
    file_path = camera_service.start_round(session_id)
    if file_path is None:
        raise HTTPException(status_code=400, detail="Failed to capture round baseline.")
    await db.execute(
        models.Shot.__table__.delete().where(models.Shot.session_id == session_id)
    )
    await db.commit()
    await ws_manager.broadcast_to_session(session_id, {
        "event": "ROUND_STARTED",
        "data": {"file_path": f"/static/uploads/baseline_{session_id}.jpg?t={int(time.time())}"}
    })
    return {
        "success": True,
        "file_path": f"/static/uploads/baseline_{session_id}.jpg?t={int(time.time())}"
    }

@app.post(f"{settings.API_V1_STR}/camera/end-round", response_model=schemas.DetectionPipelineResponse)
async def end_round(session_id: str, db: AsyncSession = Depends(get_db)):
    if not camera_service.is_running or camera_service.current_frame is None:
        raise HTTPException(status_code=400, detail="Camera is not running or no frame captured.")
    if not camera_service.is_calibrated or camera_service.active_session_id != session_id:
        raise HTTPException(status_code=400, detail="Camera has not been calibrated for this session.")
    cap_path, cap_url = camera_service.end_round(session_id)
    if cap_path is None:
        raise HTTPException(status_code=400, detail="Failed to capture end-of-round frame.")
    capture_image = models.Image(
        session_id=session_id,
        image_type="capture",
        file_path=cap_path,
        metadata_json={"type": "round_end"}
    )
    db.add(capture_image)
    await db.flush()
    baseline_res = await db.execute(
        select(models.Image)
        .where(models.Image.session_id == session_id)
        .where(models.Image.image_type == "baseline")
    )
    baseline_image = baseline_res.scalars().first()
    if not baseline_image:
        raise HTTPException(status_code=400, detail="No baseline target found.")
    baseline_path = baseline_image.file_path
    if baseline_path.startswith("/static/uploads/") or baseline_path.startswith("static/uploads/"):
        filename = os.path.basename(baseline_path)
        baseline_path = os.path.join(settings.UPLOAD_DIR, filename)
        baseline_image.file_path = baseline_path

    session_res = await db.execute(
        select(models.Session).where(models.Session.id == session_id)
    )
    session = session_res.scalars().first()
    target = load_target_definition(session.target_type if session else "figure_eleven")

    # Build Coordinate Transformer
    corners_pixel = get_target_corners(baseline_path, session_id)
    target = get_adjusted_target_definition(target, baseline_path, corners_pixel)

    transformer = CoordinateTransformer(
        corners_pixel=corners_pixel,
        target_width_mm=target.width_mm,
        target_height_mm=target.height_mm,
        warped_width_px=1000.0,
        warped_height_px=1000.0
    )

    new_holes = cv_engine.detect_holes(
        baseline_path=baseline_path,
        current_path=cap_path,
        existing_shots=[],
        align=False,
        transformer=transformer,
        bullet_caliber_mm=session.bullet_caliber if session else 4.5,
        session_id=session_id
    )

    response_shots = []
    shot_counter = 0
    for hole in new_holes:
        shot_counter += 1
        new_shot = models.Shot(
            session_id=session_id,
            image_id=capture_image.id,
            shot_number=shot_counter,
            x_raw=hole["x_raw"],
            y_raw=hole["y_raw"],
            diameter_px=hole["diameter_px"],
            confidence=hole["confidence"],
            is_valid=True,
            localization_method=hole["selected_method"]
        )
        if session:
            score_shot_record(new_shot, session, target, transformer, detection_dict=hole)
        db.add(new_shot)
        await db.flush()
        new_det = models.Detection(
            shot_id=new_shot.id,
            area=hole["area"],
            circularity=hole["circularity"],
            solidity=hole["solidity"],
            aspect_ratio=hole["aspect_ratio"],
            raw_contour=hole["raw_contour"],
            centroid_x_raw=hole["centroid_x_raw"],
            centroid_y_raw=hole["centroid_y_raw"],
            ellipse_x_raw=hole["ellipse_x_raw"],
            ellipse_y_raw=hole["ellipse_y_raw"],
            caliber_x_raw=hole["caliber_x_raw"],
            caliber_y_raw=hole["caliber_y_raw"],
            weighted_x_raw=hole["weighted_x_raw"],
            weighted_y_raw=hole["weighted_y_raw"]
        )
        db.add(new_det)
        shot_data = schemas.ShotResponse(
            id=new_shot.id,
            session_id=new_shot.session_id,
            image_id=new_shot.image_id,
            shot_number=new_shot.shot_number,
            x_raw=new_shot.x_raw,
            y_raw=new_shot.y_raw,
            x_calibrated=new_shot.x_calibrated,
            y_calibrated=new_shot.y_calibrated,
            diameter_px=new_shot.diameter_px,
            diameter_mm=new_shot.diameter_mm,
            confidence=new_shot.confidence,
            is_valid=new_shot.is_valid,
            score=new_shot.score,
            decimal_score=new_shot.decimal_score,
            nearest_ring_value=new_shot.nearest_ring_value,
            distance_to_nearest_ring_mm=new_shot.distance_to_nearest_ring_mm,
            bullseye_id=new_shot.bullseye_id,
            distance_to_center_mm=new_shot.distance_to_center_mm,
            boundary_status=new_shot.boundary_status,
            localization_method=new_shot.localization_method,
            localization_error_mm=new_shot.localization_error_mm,
            created_at=new_shot.created_at,
            detection=schemas.DetectionResponse(
                id=new_det.id,
                area=new_det.area,
                circularity=new_det.circularity,
                solidity=new_det.solidity,
                aspect_ratio=new_det.aspect_ratio,
                raw_contour=new_det.raw_contour,
                centroid_x_raw=new_det.centroid_x_raw,
                centroid_y_raw=new_det.centroid_y_raw,
                ellipse_x_raw=new_det.ellipse_x_raw,
                ellipse_y_raw=new_det.ellipse_y_raw,
                caliber_x_raw=new_det.caliber_x_raw,
                caliber_y_raw=new_det.caliber_y_raw,
                weighted_x_raw=new_det.weighted_x_raw,
                weighted_y_raw=new_det.weighted_y_raw
            )
        )
        response_shots.append(shot_data)
        await ws_manager.broadcast_to_session(session_id, {
            "event": "SHOT_DETECTED",
            "data": shot_data.dict()
        })
    await db.commit()
    return {
        "shots_detected": response_shots,
        "new_shots_count": len(response_shots),
        "current_frame_url": cap_url
    }



@app.post(f"{settings.API_V1_STR}/camera/zoom")
async def zoom_camera(factor: float):
    if factor < 1.0 or factor > 4.0:
        raise HTTPException(status_code=400, detail="Zoom factor must be between 1.0 and 4.0")
    camera_service.zoom_factor = factor
    return {"success": True, "zoom_factor": factor}

@app.post(f"{settings.API_V1_STR}/camera/fire", response_model=schemas.DetectionPipelineResponse)
async def fire_shot(session_id: str, db: AsyncSession = Depends(get_db)):
    if not camera_service.is_running or camera_service.current_frame is None:
        raise HTTPException(status_code=400, detail="Camera is not running or no frame captured.")
    if not camera_service.is_calibrated or camera_service.active_session_id != session_id:
        raise HTTPException(status_code=400, detail="Camera has not been calibrated for this session.")

    # Grab fresh snapshot directly from camera
    frame = camera_service.capture_fresh_frame(num_frames=5)
    if frame is None:
        raise HTTPException(status_code=400, detail="Failed to capture fresh frame from camera.")

    # Save raw frame to disk (Approach B: Detect-then-Transform)
    timestamp_str = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    file_name = f"capture_fire_{session_id}_{timestamp_str}.jpg"
    file_path = os.path.join(settings.UPLOAD_DIR, file_name)
    cv2.imwrite(file_path, frame, [int(cv2.IMWRITE_JPEG_QUALITY), 100])

    # Register in DB
    capture_image = models.Image(
        session_id=session_id,
        image_type="capture",
        file_path=file_path,
        metadata_json={"type": "camera_fire"}
    )
    db.add(capture_image)
    await db.flush()

    # Fetch baseline
    baseline_res = await db.execute(
        select(models.Image)
        .where(models.Image.session_id == session_id)
        .where(models.Image.image_type == "baseline")
    )
    baseline_image = baseline_res.scalars().first()
    if not baseline_image:
        raise HTTPException(status_code=400, detail="No baseline calibrated target found.")

    # self-healing for corrupted baseline path
    baseline_path = baseline_image.file_path
    if baseline_path.startswith("/static/uploads/") or baseline_path.startswith("static/uploads/"):
        filename = os.path.basename(baseline_path)
        baseline_path = os.path.join(settings.UPLOAD_DIR, filename)
        baseline_image.file_path = baseline_path

    # Fetch existing shots
    shots_res = await db.execute(
        select(models.Shot).where(models.Shot.session_id == session_id)
    )
    existing_shots = [
        {
            "x_raw": s.x_raw,
            "y_raw": s.y_raw,
            "diameter_px": s.diameter_px,
            "x_calibrated": s.x_calibrated,
            "y_calibrated": s.y_calibrated
        } 
        for s in shots_res.scalars().all()
    ]

    # Get sequence number
    count_res = await db.execute(
        select(func.count(models.Shot.id)).where(models.Shot.session_id == session_id)
    )
    shot_counter = count_res.scalar() or 0
    session_res = await db.execute(
        select(models.Session).where(models.Session.id == session_id)
    )
    session = session_res.scalars().first()
    target = load_target_definition(session.target_type if session else "figure_eleven")

    # Build Coordinate Transformer
    # Try to detect tags on the current frame to compute a fresh homography
    try:
        from app.services.apriltag_service import apriltag_service
        _, current_corners, tags = apriltag_service.detect_and_warp(
            frame,
            tag_size_mm=target.tag_size_mm,
            tag_margin_mm=target.tag_margin_mm,
            target_width_mm=target.width_mm,
            target_height_mm=target.height_mm
        )
        if current_corners is not None and len(tags) >= apriltag_service.min_tags:
            corners_pixel = current_corners
            logger.info("Successfully detected AprilTags on current camera frame for dynamic homography.")
        else:
            corners_pixel = get_target_corners(baseline_path, session_id)
    except Exception as e:
        logger.warning(f"Failed to detect tags on current camera frame, falling back: {e}")
        corners_pixel = get_target_corners(baseline_path, session_id)

    target = get_adjusted_target_definition(target, baseline_path, corners_pixel)

    transformer = CoordinateTransformer(
        corners_pixel=corners_pixel,
        target_width_mm=target.width_mm,
        target_height_mm=target.height_mm,
        warped_width_px=1000.0,
        warped_height_px=1000.0
    )

    # Build baseline transformer for mapping current-frame coordinates to baseline frame
    baseline_corners = get_static_baseline_corners(baseline_path, session_id, target)
    transformer_baseline = CoordinateTransformer(
        corners_pixel=baseline_corners,
        target_width_mm=target.width_mm,
        target_height_mm=target.height_mm,
        warped_width_px=1000.0,
        warped_height_px=1000.0
    )

    # Run CV Pipeline (align=True to register raw images against camera shifts/drift)
    new_holes = cv_engine.detect_holes(
        baseline_path=baseline_path,
        current_path=file_path,
        existing_shots=existing_shots,
        align=True,
        transformer=transformer,
        bullet_caliber_mm=session.bullet_caliber if session else 4.5,
        session_id=session_id
    )

    response_shots = []
    new_shots_saved = []

    for hole in new_holes:
        shot_counter += 1
        new_shot = models.Shot(
            session_id=session_id,
            image_id=capture_image.id,
            shot_number=shot_counter,
            x_raw=hole["x_raw"],
            y_raw=hole["y_raw"],
            diameter_px=hole["diameter_px"],
            confidence=hole["confidence"],
            is_valid=True,
            localization_method=hole["selected_method"]
        )
        if session:
            score_shot_record(new_shot, session, target, transformer, detection_dict=hole)
        db.add(new_shot)
        await db.flush()

        new_det = models.Detection(
            shot_id=new_shot.id,
            area=hole["area"],
            circularity=hole["circularity"],
            solidity=hole["solidity"],
            aspect_ratio=hole["aspect_ratio"],
            raw_contour=hole["raw_contour"],
            centroid_x_raw=hole["centroid_x_raw"],
            centroid_y_raw=hole["centroid_y_raw"],
            ellipse_x_raw=hole["ellipse_x_raw"],
            ellipse_y_raw=hole["ellipse_y_raw"],
            caliber_x_raw=hole["caliber_x_raw"],
            caliber_y_raw=hole["caliber_y_raw"],
            weighted_x_raw=hole["weighted_x_raw"],
            weighted_y_raw=hole["weighted_y_raw"]
        )

        # Project raw shot coordinates back to static baseline pixel space for database/display consistency
        try:
            x_mm, y_mm = new_shot.x_calibrated, new_shot.y_calibrated
            if x_mm is not None and y_mm is not None:
                x_base, y_base = transformer_baseline.target_mm_to_raw_pixel(x_mm, y_mm)
                new_shot.x_raw = float(x_base)
                new_shot.y_raw = float(y_base)

                # centroid
                cx_mm, cy_mm = transformer.raw_pixel_to_target_mm(hole["centroid_x_raw"], hole["centroid_y_raw"])
                cb_x, cb_y = transformer_baseline.target_mm_to_raw_pixel(cx_mm, cy_mm)
                new_det.centroid_x_raw = float(cb_x)
                new_det.centroid_y_raw = float(cb_y)

                # ellipse
                ex_mm, ey_mm = transformer.raw_pixel_to_target_mm(hole["ellipse_x_raw"], hole["ellipse_y_raw"])
                eb_x, eb_y = transformer_baseline.target_mm_to_raw_pixel(ex_mm, ey_mm)
                new_det.ellipse_x_raw = float(eb_x)
                new_det.ellipse_y_raw = float(eb_y)

                # caliber
                cal_x_mm, cal_y_mm = transformer.raw_pixel_to_target_mm(hole["caliber_x_raw"], hole["caliber_y_raw"])
                calb_x, calb_y = transformer_baseline.target_mm_to_raw_pixel(cal_x_mm, cal_y_mm)
                new_det.caliber_x_raw = float(calb_x)
                new_det.caliber_y_raw = float(calb_y)

                # weighted
                w_mm_x, w_mm_y = transformer.raw_pixel_to_target_mm(hole["weighted_x_raw"], hole["weighted_y_raw"])
                wb_x, wb_y = transformer_baseline.target_mm_to_raw_pixel(w_mm_x, w_mm_y)
                new_det.weighted_x_raw = float(wb_x)
                new_det.weighted_y_raw = float(wb_y)

                # raw_contour
                if hole.get("raw_contour") is not None:
                    raw_contour_base = []
                    for pt in hole["raw_contour"]:
                        pt_mm_x, pt_mm_y = transformer.raw_pixel_to_target_mm(float(pt[0]), float(pt[1]))
                        pt_base_x, pt_base_y = transformer_baseline.target_mm_to_raw_pixel(pt_mm_x, pt_mm_y)
                        raw_contour_base.append([float(pt_base_x), float(pt_base_y)])
                    new_det.raw_contour = raw_contour_base
        except Exception as e:
            logger.warning(f"Failed to map detection coords back to baseline in fire_shot: {e}")

        db.add(new_det)
        new_shots_saved.append((new_shot, new_det))

    await db.commit()

    # Generate perspective-rectified debug view showing all cumulative shots
    try:
        from app.services.camera_service import generate_rectified_debug_image
        all_shots_res = await db.execute(
            select(models.Shot).where(models.Shot.session_id == session_id)
        )
        all_shots = all_shots_res.scalars().all()
        generate_rectified_debug_image(session_id, file_path, target, corners_pixel, all_shots)
    except Exception as rect_err:
        logger.warning(f"Failed to generate rectified debug view: {rect_err}")

    # Construct response & broadcast over WebSocket
    for shot, det in new_shots_saved:
        shot_data = schemas.ShotResponse(
            id=shot.id,
            session_id=shot.session_id,
            image_id=shot.image_id,
            shot_number=shot.shot_number,
            x_raw=shot.x_raw,
            y_raw=shot.y_raw,
            x_calibrated=shot.x_calibrated,
            y_calibrated=shot.y_calibrated,
            diameter_px=shot.diameter_px,
            diameter_mm=shot.diameter_mm,
            confidence=shot.confidence,
            is_valid=shot.is_valid,
            score=shot.score,
            decimal_score=shot.decimal_score,
            nearest_ring_value=shot.nearest_ring_value,
            distance_to_nearest_ring_mm=shot.distance_to_nearest_ring_mm,
            bullseye_id=shot.bullseye_id,
            distance_to_center_mm=shot.distance_to_center_mm,
            boundary_status=shot.boundary_status,
            localization_method=shot.localization_method,
            localization_error_mm=shot.localization_error_mm,
            created_at=shot.created_at,
            detection=schemas.DetectionResponse(
                id=det.id,
                area=det.area,
                circularity=det.circularity,
                solidity=det.solidity,
                aspect_ratio=det.aspect_ratio,
                raw_contour=det.raw_contour,
                centroid_x_raw=det.centroid_x_raw,
                centroid_y_raw=det.centroid_y_raw,
                ellipse_x_raw=det.ellipse_x_raw,
                ellipse_y_raw=det.ellipse_y_raw,
                caliber_x_raw=det.caliber_x_raw,
                caliber_y_raw=det.caliber_y_raw,
                weighted_x_raw=det.weighted_x_raw,
                weighted_y_raw=det.weighted_y_raw
            )
        )
        response_shots.append(shot_data)

        # Broadcast event
        await ws_manager.broadcast_to_session(session_id, {
            "event": "SHOT_DETECTED",
            "data": shot_data.dict()
        })

    return {
        "shots_detected": response_shots,
        "new_shots_count": len(response_shots),
        "current_frame_url": f"/static/uploads/{file_name}?t={int(time.time())}"
    }

def gen_camera_frames():
    while True:
        time.sleep(0.04) # ~25 FPS
        frame = camera_service.get_latest_frame_jpeg()
        if frame is not None:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
        else:
            placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(placeholder, "AWAITING CAMERA CONNECT...", (50, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
            ret, jpeg = cv2.imencode('.jpg', placeholder)
            if ret:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')

@app.get(f"{settings.API_V1_STR}/camera/stream")
async def get_camera_stream():
    return StreamingResponse(gen_camera_frames(), media_type="multipart/x-mixed-replace; boundary=frame")
