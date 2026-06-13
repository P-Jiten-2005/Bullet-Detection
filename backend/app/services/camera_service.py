import cv2
import numpy as np
import threading
import time
import os
import logging
from typing import Optional, Tuple
from datetime import datetime
from app.core.config import settings
from app.services.cv_engine import cv_engine
from app.services.ws_manager import ws_manager
from app.services.apriltag_service import apriltag_service, A4_W, A4_H, get_adjusted_target_definition
from app.models import models
from app.core.database import AsyncSessionLocal
from sqlalchemy import select, func

logger = logging.getLogger("app.camera_service")

class CameraService:
    def __init__(self):
        self.cap: Optional[cv2.VideoCapture] = None
        self.current_frame: Optional[np.ndarray] = None
        self.is_running = False
        self.is_capturing_snapshot = False
        self.camera_source = "0"  # Default webcam index
        self._thread: Optional[threading.Thread] = None
        self._auto_thread: Optional[threading.Thread] = None
        self._auto_session_id: Optional[str] = None
        self._tag_stable_count = 0
        self.is_auto_pipeline = False
        self.lock = threading.Lock()
        
        # Calibration state
        self.calibrated_baseline: Optional[np.ndarray] = None
        self.active_session_id: Optional[str] = None
        self.is_calibrated = False
        self.zoom_factor = 1.0
        self.homography_matrix: Optional[np.ndarray] = None
        self.calibration_method: Optional[str] = None
        self.corners_pixel: Optional[np.ndarray] = None



    def set_active_session(self, session_id: str):
        with self.lock:
            self._auto_session_id = session_id

    def start_camera(self, source: str = "0") -> bool:
        with self.lock:
            if self.is_running:
                if self.camera_source == source:
                    return True
                self.stop_camera_unlocked()

            try:
                src = int(source)
            except ValueError:
                src = source

            if isinstance(src, int):
                if os.name == "nt":
                    logger.info(f"Attempting to open camera index {src} via DirectShow...")
                    self.cap = cv2.VideoCapture(src, cv2.CAP_DSHOW)
                    if not self.cap.isOpened():
                        logger.warning(f"DirectShow failed to open index {src}. Falling back to default MSMF backend...")
                        self.cap = cv2.VideoCapture(src)
                else:
                    self.cap = cv2.VideoCapture(src)
            else:
                self.cap = cv2.VideoCapture(src)

            if not self.cap.isOpened():
                logger.error(f"Failed to open video source: {source}")
                self.cap = None
                return False

            ret, test_frame = self.cap.read()
            if not ret or test_frame is None:
                logger.warning(f"Camera index {source} opened successfully but failed to return frames. The device might be locked by another app or is an inactive virtual camera.")

            self.camera_source = source
            self.is_running = True
            self.is_auto_pipeline = True
            self._thread = threading.Thread(target=self._capture_loop, daemon=True)
            self._thread.start()
            self._auto_thread = threading.Thread(target=self._auto_pipeline_loop, daemon=True)
            self._auto_thread.start()
            logger.info(f"Camera stream started successfully: Source {source}")
            return True

    def stop_camera(self):
        with self.lock:
            self.stop_camera_unlocked()

    def stop_camera_unlocked(self):
        self.is_auto_pipeline = False
        self.is_running = False
        self.is_capturing_snapshot = False
        if self.cap:
            self.cap.release()
            self.cap = None
        self.current_frame = None
        self._tag_stable_count = 0
        logger.info("Camera stream stopped.")

    def _capture_loop(self):
        while self.is_running:
            if self.is_capturing_snapshot:
                time.sleep(0.02)
                continue
            if self.cap:
                ret, frame = self.cap.read()
                if ret:
                    # Apply digital zoom cropping if factor is active
                    if self.zoom_factor > 1.0:
                        h, w = frame.shape[:2]
                        new_h, new_w = int(h / self.zoom_factor), int(w / self.zoom_factor)
                        startY = (h - new_h) // 2
                        startX = (w - new_w) // 2
                        cropped = frame[startY:startY+new_h, startX:startX+new_w]
                        frame = cv2.resize(cropped, (w, h))
                    with self.lock:
                        self.current_frame = frame
                else:
                    time.sleep(0.01)
            time.sleep(0.01)

    def _auto_pipeline_loop(self):
        STABLE_REQUIRED = 3
        CHECK_INTERVAL = 1.0
        while self.is_auto_pipeline:
            time.sleep(CHECK_INTERVAL)
            if self.is_calibrated:
                continue
            session_id = None
            with self.lock:
                session_id = self._auto_session_id
            if not session_id:
                continue
            with self.lock:
                if self.current_frame is None:
                    continue
                frame = self.current_frame.copy()
            try:
                tag_count = apriltag_service.get_tag_count(frame)
            except Exception:
                continue
            if tag_count >= 3:
                self._tag_stable_count += 1
            else:
                self._tag_stable_count = 0
                continue
            if self._tag_stable_count < STABLE_REQUIRED:
                continue
            logger.info(f"Auto-pipeline: {tag_count} tags stable for {STABLE_REQUIRED} frames. Calibrating...")
            success = self.calibrate_homography(session_id)
            if not success:
                logger.warning("Auto-pipeline: calibration failed, retrying...")
                self._tag_stable_count = 0
                continue
            logger.info("Auto-pipeline: calibration succeeded. Ready for rounds.")

    def _get_target_for_active_session(self) -> Tuple[Optional[any], float, float, float, float, str]:
        """
        Synchronously retrieves session parameters and loads target definition from configs.
        Returns (target, target_width_mm, target_height_mm, tag_size_mm, tag_margin_mm, target_type)
        """
        session_id = self.active_session_id
        target_width_mm = 210.0
        target_height_mm = 297.0
        tag_size_mm = 15.0
        tag_margin_mm = 20.0
        target_type = "figure_eleven"
        target = None

        if session_id:
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
                from app.main import load_target_definition
                target = load_target_definition(target_type)
                target_width_mm = target.width_mm
                target_height_mm = target.height_mm
                tag_size_mm = target.tag_size_mm
                tag_margin_mm = target.tag_margin_mm
            except Exception:
                pass
        return target, target_width_mm, target_height_mm, tag_size_mm, tag_margin_mm, target_type

    def get_latest_frame_jpeg(self) -> Optional[bytes]:
        with self.lock:
            if self.current_frame is None:
                return None
            # Draw crosshairs/bounding markers on the preview if calibrated
            preview_frame = self.current_frame.copy()

            # Dynamic target overlay registration (Phase 5)
            target, target_width_mm, target_height_mm, tag_size_mm, tag_margin_mm, target_type = self._get_target_for_active_session()
            
            if target is not None:
                try:
                    # Detect AprilTags dynamically on the current frame
                    from app.services.apriltag_service import apriltag_service
                    warped, corners, tags = apriltag_service.detect_and_warp(
                        preview_frame,
                        tag_size_mm=tag_size_mm,
                        tag_margin_mm=tag_margin_mm,
                        target_width_mm=target_width_mm,
                        target_height_mm=target_height_mm
                    )
                    if warped is not None and len(tags) >= apriltag_service.min_tags:
                        # Draw zones dynamically using the detected corners
                        preview_frame = draw_zones_on_image(preview_frame, corners, target)
                        # Dynamically update calibration parameters
                        self.corners_pixel = corners
                        self.is_calibrated = True
                        cv2.putText(preview_frame, "DYNAMIC OVERLAY ACTIVE", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                    else:
                        # Fallback to drawing zones using static corners if calibrated
                        if self.is_calibrated and self.corners_pixel is not None:
                            preview_frame = draw_zones_on_image(preview_frame, self.corners_pixel, target)
                            cv2.putText(preview_frame, "OVERLAY STATIC FALLBACK", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)
                        else:
                            cv2.putText(preview_frame, "ALIGNING TARGET...", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                except Exception as e:
                    logger.warning(f"Dynamic overlay registration failed: {e}")
                    cv2.putText(preview_frame, "OVERLAY ERROR", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            else:
                if self.is_calibrated:
                    cv2.putText(preview_frame, "CALIBRATED FEED", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                else:
                    cv2.putText(preview_frame, "UNCONNECTED FEED - PLACE TARGET", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

            ret, jpeg = cv2.imencode('.jpg', preview_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 100])
            return jpeg.tobytes() if ret else None

    def _find_paper_contour(self, img: np.ndarray) -> Optional[np.ndarray]:
        """
        Robustly finds the 4-corner paper target contour using multiple image processing strategies:
        1. Adaptive Thresholding (great for local shadows/uneven lighting)
        2. Canny Edge Detection + Dilation (great for strong outlines/contrast edges)
        3. Otsu global thresholding (standard fallback)
        """
        try:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            frame_area = img.shape[0] * img.shape[1]
            
            # Strategies to generate binary/edge images for contour finding
            binaries = []
            
            # Strategy 1: Bilateral Filter + Adaptive Thresholding (handles shadows best)
            try:
                blurred_adaptive = cv2.bilateralFilter(gray, 9, 75, 75)
                thresh_adaptive = cv2.adaptiveThreshold(
                    blurred_adaptive, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                    cv2.THRESH_BINARY_INV, 21, 4
                )
                binaries.append(("adaptive", thresh_adaptive))
            except Exception as e:
                logger.warning(f"Adaptive threshold prep failed: {e}")
                
            # Strategy 2: Gaussian Blur + Canny Edge Detection + Morphological Dilation
            try:
                blurred_canny = cv2.GaussianBlur(gray, (5, 5), 0)
                edged = cv2.Canny(blurred_canny, 30, 150)
                kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
                dilated = cv2.dilate(edged, kernel, iterations=1)
                binaries.append(("canny", dilated))
            except Exception as e:
                logger.warning(f"Canny edge prep failed: {e}")

            # Strategy 3: Otsu thresholding (global threshold)
            try:
                blurred_otsu = cv2.GaussianBlur(gray, (5, 5), 0)
                _, thresh_otsu = cv2.threshold(blurred_otsu, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
                binaries.append(("otsu_inv", thresh_otsu))
                
                _, thresh_otsu_normal = cv2.threshold(blurred_otsu, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                binaries.append(("otsu", thresh_otsu_normal))
            except Exception as e:
                logger.warning(f"Otsu prep failed: {e}")
                
            # Try finding the best quad contour using each binary representation
            for name, binary_img in binaries:
                contours, _ = cv2.findContours(binary_img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                contours = sorted(contours, key=cv2.contourArea, reverse=True)
                
                for c in contours:
                    area = cv2.contourArea(c)
                    # Filter out small inner shapes and huge room features (4% to 95% of frame area)
                    if not (0.04 * frame_area <= area <= 0.95 * frame_area):
                        continue
                        
                    peri = cv2.arcLength(c, True)
                    
                    # Scan epsilon factors dynamically to approximate to a 4-point quad
                    approx = None
                    for eps_factor in [0.01, 0.015, 0.02, 0.025, 0.03, 0.04, 0.05, 0.06]:
                        candidate = cv2.approxPolyDP(c, eps_factor * peri, True)
                        if len(candidate) == 4 and cv2.isContourConvex(candidate):
                            approx = candidate
                            break
                    
                    if approx is not None:
                        # Aspect ratio check
                        x, y, w, h = cv2.boundingRect(approx)
                        aspect_ratio = float(w) / h
                        # Accept sheets between 0.5 and 2.0 aspect ratios
                        if 0.5 <= aspect_ratio <= 2.0:
                            logger.info(f"Target paper contour detected using strategy: {name} (area: {area}, aspect: {aspect_ratio:.2f})")
                            return approx.reshape(4, 2)
        except Exception as e:
            logger.error(f"Error in _find_paper_contour: {e}")
            
        logger.warning("No robust 4-corner paper target detected with any strategy.")
        return None

    def rectify_target_paper(self, img: np.ndarray) -> Tuple[np.ndarray, bool]:
        """
        Detects the largest high-contrast rectangular contours (the paper target boundaries)
        and warps perspective to normalize and calibrate the scale to 1000x1000 pixels.
        """
        pts = self._find_paper_contour(img)
        if pts is not None:
            try:
                rect = np.zeros((4, 2), dtype="float32")
                # Order points: top-left, top-right, bottom-right, bottom-left
                s = pts.sum(axis=1)
                rect[0] = pts[np.argmin(s)]
                rect[2] = pts[np.argmax(s)]
                
                diff = np.diff(pts, axis=1)
                rect[1] = pts[np.argmin(diff)]
                rect[3] = pts[np.argmax(diff)]
                
                # Use a 15% (150px) margin to keep target centered, fully visible and zoomed out slightly
                margin = 150
                dst = np.array([
                    [margin, margin],
                    [999 - margin, margin],
                    [999 - margin, 999 - margin],
                    [margin, 999 - margin]
                ], dtype="float32")
                
                M = cv2.getPerspectiveTransform(rect, dst)
                warped = cv2.warpPerspective(img, M, (1000, 1000), flags=cv2.INTER_LANCZOS4)
                return warped, True
            except Exception as e:
                logger.error(f"Error rectifying target paper from detected contour: {e}")
                
        # Fallback to entire image cropped square if paper contour search fails
        h, w = img.shape[:2]
        crop_size = min(h, w)
        startY, startX = (h - crop_size) // 2, (w - crop_size) // 2
        cropped = img[startY:startY+crop_size, startX:startX+crop_size]
        resized = cv2.resize(cropped, (1000, 1000), interpolation=cv2.INTER_LANCZOS4)
        return resized, False

    def capture_fresh_frame(self, num_frames: int = 5) -> Optional[np.ndarray]:
        """
        Captures a fresh sequence of frames directly from the video capture device.
        It temporarily pauses background capture loop reads, reads multiple frames
        sequentially to flush the hardware queue/buffer, and returns the latest frame.
        """
        if not self.is_running or self.cap is None:
            logger.error("capture_fresh_frame: Camera is not running.")
            return None

        self.is_capturing_snapshot = True
        time.sleep(0.05)  # Wait for any active background read to complete/yield

        with self.lock:
            frame = None
            try:
                for _ in range(num_frames):
                    ret, f = self.cap.read()
                    if ret and f is not None:
                        frame = f
                    time.sleep(0.03)
            except Exception as e:
                logger.error(f"Error reading frames from device during snapshot: {e}")
            finally:
                self.is_capturing_snapshot = False

        if frame is not None:
            # Apply digital zoom cropping if factor is active
            if self.zoom_factor > 1.0:
                h, w = frame.shape[:2]
                new_h, new_w = int(h / self.zoom_factor), int(w / self.zoom_factor)
                startY = (h - new_h) // 2
                startX = (w - new_w) // 2
                cropped = frame[startY:startY+new_h, startX:startX+new_w]
                frame = cv2.resize(cropped, (w, h))
            return frame
        return None

    def calibrate_homography(self, session_id: str) -> bool:
        # Load session/target info synchronously to avoid database locking in background thread
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
            from app.main import load_target_definition
            target = load_target_definition(target_type)
            target_width_mm = target.width_mm
            target_height_mm = target.height_mm
            tag_size_mm = target.tag_size_mm
            tag_margin_mm = target.tag_margin_mm
            logger.info(f"Loaded target physical properties for calibration: {target_type} ({target_width_mm}x{target_height_mm}mm, tag: {tag_size_mm}mm, margin: {tag_margin_mm}mm)")
        except Exception as e:
            logger.warning(f"Could not load target physical parameters for calibration: {e}")

        frame_to_calibrate = self.capture_fresh_frame(num_frames=5)
        if frame_to_calibrate is None:
            logger.error("No active camera frame to calibrate.")
            return False

        try:
            warped, corners, tags = apriltag_service.detect_and_warp(
                frame_to_calibrate,
                tag_size_mm=tag_size_mm,
                tag_margin_mm=tag_margin_mm,
                target_width_mm=target_width_mm,
                target_height_mm=target_height_mm
            )
            if warped is not None and len(tags) >= apriltag_service.min_tags:
                tag_ids = [t["id"] for t in tags]
                
                # Estimate distance
                h, w = frame_to_calibrate.shape[:2]
                estimated_dist = apriltag_service.estimate_camera_distance(
                    tags, 
                    tag_size_mm=tag_size_mm, 
                    zoom_factor=self.zoom_factor, 
                    image_width=w
                )
                if estimated_dist:
                    logger.info(f"AprilTag calibration: Estimated camera distance to target is {estimated_dist/1000.0:.2f} meters ({estimated_dist:.1f} mm)")
                
                logger.info(f"AprilTag calibration: {len(tags)} tags detected (IDs: {tag_ids})")
                dst_1k = np.array([[0, 0], [999, 0], [999, 999], [0, 999]], dtype=np.float32)
                M = cv2.getPerspectiveTransform(corners, dst_1k)
                baseline_name = f"baseline_{session_id}.jpg"
                file_path = os.path.join(settings.UPLOAD_DIR, baseline_name)
                cv2.imwrite(file_path, frame_to_calibrate, [int(cv2.IMWRITE_JPEG_QUALITY), 100])
                
                # Draw calibration debug overlay (AprilTag method)
                try:
                    debug_img = frame_to_calibrate.copy()
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
                    
                    # Draw scoring zones and their bounding boxes
                    if target is not None:
                        target = get_adjusted_target_definition(target, file_path, corners)
                        debug_img = draw_zones_on_image(debug_img, corners, target)
                        generate_rectified_debug_image(session_id, file_path, target, corners, [])

                    debug_path = os.path.join(settings.UPLOAD_DIR, f"debug_calibration_{session_id}.jpg")
                    cv2.imwrite(debug_path, debug_img, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
                except Exception as ex:
                    logger.warning(f"Failed to save AprilTag calibration debug image: {ex}")

                with self.lock:
                    self.homography_matrix = M
                    self.corners_pixel = corners
                    self.calibrated_baseline = frame_to_calibrate
                    self.active_session_id = session_id
                    self.is_calibrated = True
                    self.calibration_method = "apriltag"
                logger.info("Camera calibrated via AprilTag warp (raw baseline saved).")
                return True
            else:
                logger.info(f"AprilTag calibration: only {len(tags)} tags found, falling back to contour detection.")
        except Exception as e:
            logger.warning(f"AprilTag calibration failed: {e}")
 
        pts = self._find_paper_contour(frame_to_calibrate)
        if pts is not None:
            try:
                rect = np.zeros((4, 2), dtype="float32")
                s = pts.sum(axis=1)
                rect[0] = pts[np.argmin(s)]
                rect[2] = pts[np.argmax(s)]
                diff = np.diff(pts, axis=1)
                rect[1] = pts[np.argmin(diff)]
                rect[3] = pts[np.argmax(diff)]
                margin = 150
                dst = np.array([
                    [margin, margin],
                    [999 - margin, margin],
                    [999 - margin, 999 - margin],
                    [margin, 999 - margin]
                ], dtype="float32")
                M = cv2.getPerspectiveTransform(rect, dst)
                baseline_name = f"baseline_{session_id}.jpg"
                file_path = os.path.join(settings.UPLOAD_DIR, baseline_name)
                cv2.imwrite(file_path, frame_to_calibrate, [int(cv2.IMWRITE_JPEG_QUALITY), 100])

                # Draw calibration debug overlay (contour method)
                try:
                    debug_img = frame_to_calibrate.copy()
                    pts_draw = np.array(rect, dtype=np.int32).reshape((-1, 1, 2))
                    cv2.polylines(debug_img, [pts_draw], isClosed=True, color=(0, 255, 0), thickness=3)
                    cv2.putText(debug_img, "Detected Target Sheet (Contour)", (int(rect[0][0]), int(rect[0][1] - 15)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
                    cv2.putText(debug_img, "No AprilTags detected (Fallback to contour)", (30, 40),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)

                    # Draw scoring zones and their bounding boxes
                    if target is not None:
                        target = get_adjusted_target_definition(target, file_path, rect)
                        debug_img = draw_zones_on_image(debug_img, rect, target)
                        generate_rectified_debug_image(session_id, file_path, target, rect, [])

                    debug_path = os.path.join(settings.UPLOAD_DIR, f"debug_calibration_{session_id}.jpg")
                    cv2.imwrite(debug_path, debug_img, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
                except Exception as ex:
                    logger.warning(f"Failed to save contour calibration debug image: {ex}")

                with self.lock:
                    self.homography_matrix = M
                    self.corners_pixel = rect
                    self.calibrated_baseline = frame_to_calibrate
                    self.active_session_id = session_id
                    self.is_calibrated = True
                    self.calibration_method = "paper"
                logger.info("Homography matrix calibrated successfully from paper borders (raw baseline saved).")
                return True
            except Exception as e:
                logger.error(f"Failed to calibrate homography from detected paper borders: {e}")
 
        try:
            h, w = frame_to_calibrate.shape[:2]
            crop_size = min(h, w)
            startY, startX = (h - crop_size) // 2, (w - crop_size) // 2
            rect = np.array([
                [startX, startY],
                [startX + crop_size - 1, startY],
                [startX + crop_size - 1, startY + crop_size - 1],
                [startX, startY + crop_size - 1]
            ], dtype="float32")
            dst = np.array([
                [0, 0],
                [999, 0],
                [999, 999],
                [0, 999]
            ], dtype="float32")
            M = cv2.getPerspectiveTransform(rect, dst)
            baseline_name = f"baseline_{session_id}.jpg"
            file_path = os.path.join(settings.UPLOAD_DIR, baseline_name)
            cv2.imwrite(file_path, frame_to_calibrate, [int(cv2.IMWRITE_JPEG_QUALITY), 100])

            # Draw calibration debug overlay (fallback center crop method)
            try:
                debug_img = frame_to_calibrate.copy()
                pts_draw = np.array(rect, dtype=np.int32).reshape((-1, 1, 2))
                cv2.polylines(debug_img, [pts_draw], isClosed=True, color=(0, 0, 255), thickness=3)
                cv2.putText(debug_img, "Target Sheet (Fallback Center Crop)", (int(rect[0][0]), int(rect[0][1] - 15)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

                # Draw scoring zones and their bounding boxes
                if target is not None:
                    target = get_adjusted_target_definition(target, file_path, rect)
                    debug_img = draw_zones_on_image(debug_img, rect, target)

                debug_path = os.path.join(settings.UPLOAD_DIR, f"debug_calibration_{session_id}.jpg")
                cv2.imwrite(debug_path, debug_img, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
            except Exception as ex:
                logger.warning(f"Failed to save fallback calibration debug image: {ex}")

            with self.lock:
                self.homography_matrix = M
                self.corners_pixel = rect
                self.calibrated_baseline = frame_to_calibrate
                self.active_session_id = session_id
                self.is_calibrated = True
                self.calibration_method = "fallback"
            logger.info("Homography calibrated via fallback central square crop (raw baseline saved).")
            return True
        except Exception as e:
            logger.error(f"Fallback homography calibration failed: {e}")
            return False

    def capture_before_fire(self, session_id: str) -> Optional[np.ndarray]:
        frame = self.capture_fresh_frame(num_frames=5)
        if frame is None:
            logger.error("No active camera frame to capture before fire.")
            return None

        baseline_name = f"baseline_{session_id}.jpg"
        file_path = os.path.join(settings.UPLOAD_DIR, baseline_name)
        cv2.imwrite(file_path, frame, [int(cv2.IMWRITE_JPEG_QUALITY), 100])
        with self.lock:
            self.calibrated_baseline = frame
            self.active_session_id = session_id
        logger.info(f"Captured raw reference baseline target for session {session_id}")
        return frame

    def start_round(self, session_id: str) -> Optional[str]:
        if not self.calibrate_homography(session_id):
            logger.warning("start_round: recalibration failed, using existing homography.")
            if self.homography_matrix is None:
                logger.error("start_round: no homography available.")
                return None
        baseline = self.capture_before_fire(session_id)
        if baseline is None:
            logger.error("start_round: baseline capture failed.")
            return None
        baseline_name = f"baseline_{session_id}.jpg"
        file_path = os.path.join(settings.UPLOAD_DIR, baseline_name)
        logger.info(f"Round started for session {session_id}.")
        return file_path

    def end_round(self, session_id: str) -> Tuple[Optional[str], Optional[str]]:
        frame = self.capture_fresh_frame(num_frames=5)
        if frame is None:
            logger.error("No active camera frame to end round.")
            return None, None
        timestamp_str = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
        file_name = f"capture_round_{session_id}_{timestamp_str}.jpg"
        file_path = os.path.join(settings.UPLOAD_DIR, file_name)
        cv2.imwrite(file_path, frame, [int(cv2.IMWRITE_JPEG_QUALITY), 100])
        return file_path, f"/static/uploads/{file_name}?t={int(time.time())}"

    def rectify_frame(self, img: np.ndarray) -> np.ndarray:
        try:
            target_width_mm = 210.0
            target_height_mm = 297.0
            tag_size_mm = 15.0
            tag_margin_mm = 20.0
            
            session_id = self.active_session_id
            if session_id:
                paths = [
                    "./data/target_analysis.db",
                    "../../data/target_analysis.db",
                    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "target_analysis.db")
                ]
                target_type = "figure_eleven"
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
                    from app.main import load_target_definition
                    target = load_target_definition(target_type)
                    target_width_mm = target.width_mm
                    target_height_mm = target.height_mm
                    tag_size_mm = target.tag_size_mm
                    tag_margin_mm = target.tag_margin_mm
                except Exception:
                    pass

            warped, corners, tags = apriltag_service.detect_and_warp(
                img,
                tag_size_mm=tag_size_mm,
                tag_margin_mm=tag_margin_mm,
                target_width_mm=target_width_mm,
                target_height_mm=target_height_mm
            )
            if warped is not None and len(tags) >= 3:
                return cv2.resize(warped, (1000, 1000), interpolation=cv2.INTER_LANCZOS4)
        except Exception as e:
            logger.warning(f"AprilTag rectification failed: {e}")
        with self.lock:
            M = self.homography_matrix
        if M is not None:
            return cv2.warpPerspective(img, M, (1000, 1000), flags=cv2.INTER_LANCZOS4)
        warped, _ = self.rectify_target_paper(img)
        return warped


def draw_zones_on_image(img: np.ndarray, corners: np.ndarray, target: any) -> np.ndarray:
    """
    Draws the scoring zones (bullseyes/rings and rectangular scoring regions)
    projected onto the original image using homography mapping.
    Also draws a bounding box around each recognized zone.
    """
    if target is None or corners is None:
        return img
    
    try:
        from src.transformation.coordinate_transformer import CoordinateTransformer
        transformer = CoordinateTransformer(
            corners_pixel=np.array(corners, dtype=np.float32),
            target_width_mm=target.width_mm,
            target_height_mm=target.height_mm
        )
    except Exception as e:
        logger.warning(f"Could not build CoordinateTransformer for drawing zones: {e}")
        return img

    # 1. Draw Rectangular Scoring Regions and their bounding boxes
    if hasattr(target, "scoring_regions") and target.scoring_regions:
        for region in target.scoring_regions:
            rx_min, ry_min = region.x_min_mm, region.y_min_mm
            rx_max, ry_max = region.x_max_mm, region.y_max_mm

            # Project the 4 corners of the rectangular region
            p1 = transformer.target_mm_to_raw_pixel(rx_min, ry_min)
            p2 = transformer.target_mm_to_raw_pixel(rx_max, ry_min)
            p3 = transformer.target_mm_to_raw_pixel(rx_max, ry_max)
            p4 = transformer.target_mm_to_raw_pixel(rx_min, ry_max)

            pts = np.array([p1, p2, p3, p4], dtype=np.int32).reshape((-1, 1, 2))
            
            # Draw the region outline in purple/magenta
            color = (180, 105, 255)  # BGR Purple
            cv2.polylines(img, [pts], isClosed=True, color=color, thickness=2)

            # Draw a bounding box for the region (axis-aligned bounding box around the projected points)
            all_pts = np.array([p1, p2, p3, p4])
            x_min_px, y_min_px = np.min(all_pts, axis=0)
            x_max_px, y_max_px = np.max(all_pts, axis=0)
            
            # Draw a bounding box (thin orange box) around the recognized zone
            cv2.rectangle(img, (int(x_min_px), int(y_min_px)), (int(x_max_px), int(y_max_px)), (0, 165, 255), 1)

            # Label the region
            label = f"{region.name or 'Zone'} ({region.value} pts)"
            cv2.putText(img, label, (int(x_min_px), int(y_min_px) - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)

    # 2. Draw Circular Concentric Rings and their bounding boxes
    if hasattr(target, "bullseyes") and target.bullseyes:
        for bullseye in target.bullseyes:
            cx_mm, cy_mm = bullseye.center_x_mm, bullseye.center_y_mm
            
            # Draw the center crosshair
            cx_px, cy_px = transformer.target_mm_to_raw_pixel(cx_mm, cy_mm)
            cv2.circle(img, (int(cx_px), int(cy_px)), 3, (0, 0, 255), -1)

            if hasattr(bullseye, "rings") and bullseye.rings:
                outermost_r_mm = 0.0
                for ring in bullseye.rings:
                    r_mm = ring.outer_radius_mm
                    if r_mm > outermost_r_mm:
                        outermost_r_mm = r_mm

                    # Generate points on the circle in target mm space
                    theta = np.linspace(0, 2 * np.pi, 36)
                    circle_pts = []
                    for t in theta:
                        rx = cx_mm + r_mm * np.cos(t)
                        ry = cy_mm + r_mm * np.sin(t)
                        px, py = transformer.target_mm_to_raw_pixel(rx, ry)
                        circle_pts.append([px, py])
                    
                    pts = np.array(circle_pts, dtype=np.int32).reshape((-1, 1, 2))
                    # Draw ring outline (BGR teal/emerald)
                    cv2.polylines(img, [pts], isClosed=True, color=(100, 200, 100), thickness=1)

                    # Label the ring value
                    px, py = transformer.target_mm_to_raw_pixel(cx_mm, cy_mm - r_mm)
                    cv2.putText(img, str(ring.value), (int(px), int(py) + 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (100, 200, 100), 1, cv2.LINE_AA)

                # Draw bounding box for the outermost ring of the bullseye
                if outermost_r_mm > 0:
                    theta = np.linspace(0, 2 * np.pi, 36)
                    outer_pts = []
                    for t in theta:
                        rx = cx_mm + outermost_r_mm * np.cos(t)
                        ry = cy_mm + outermost_r_mm * np.sin(t)
                        px, py = transformer.target_mm_to_raw_pixel(rx, ry)
                        outer_pts.append([px, py])
                    
                    outer_pts_arr = np.array(outer_pts)
                    x_min_px, y_min_px = np.min(outer_pts_arr, axis=0)
                    x_max_px, y_max_px = np.max(outer_pts_arr, axis=0)
                    
                    # Draw a bounding box for the bullseye zone (orange)
                    cv2.rectangle(img, (int(x_min_px), int(y_min_px)), (int(x_max_px), int(y_max_px)), (0, 165, 255), 1)
                    
                    label = f"Bullseye (Max R: {outermost_r_mm}mm)"
                    cv2.putText(img, label, (int(x_min_px), int(y_min_px) - 5),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 165, 255), 1, cv2.LINE_AA)

    return img


def generate_rectified_debug_image(
    session_id: str,
    image_path: str,
    target: any,
    corners: np.ndarray,
    shots: list
) -> bool:
    """
    Generates a perspective-rectified (homographed) target view (1000x1000px)
    with scoring rings/regions and detected holes overlaid on it.
    """
    try:
        img = cv2.imread(image_path)
        if img is None:
            logger.warning(f"Could not load image at {image_path} to generate rectified debug image.")
            return False

        from src.transformation.coordinate_transformer import CoordinateTransformer
        transformer = CoordinateTransformer(
            corners_pixel=np.array(corners, dtype=np.float32),
            target_width_mm=target.width_mm,
            target_height_mm=target.height_mm
        )

        # Warp image to standard 1000x1000 square perspective
        warped_img = cv2.warpPerspective(img, transformer.H_pixel_to_warped, (1000, 1000))

        # 1. Draw Rectangular Scoring Regions (Purple/Magenta)
        if hasattr(target, "scoring_regions") and target.scoring_regions:
            for region in target.scoring_regions:
                # Convert region corners to warped pixels
                p1_w = transformer.target_mm_to_warped_pixel(region.x_min_mm, region.y_min_mm)
                p2_w = transformer.target_mm_to_warped_pixel(region.x_max_mm, region.y_max_mm)
                
                color = (180, 105, 255) # BGR Purple
                cv2.rectangle(warped_img, (int(p1_w[0]), int(p1_w[1])), (int(p2_w[0]), int(p2_w[1])), color, 2)
                
                label = f"{region.name or 'Zone'} ({region.value} pts)"
                cv2.putText(warped_img, label, (int(p1_w[0]) + 5, int(p1_w[1]) + 15),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)

        # 2. Draw Circular Bullseye Rings (Green/Teal)
        if hasattr(target, "bullseyes") and target.bullseyes:
            for bullseye in target.bullseyes:
                cx_w, cy_w = transformer.target_mm_to_warped_pixel(bullseye.center_x_mm, bullseye.center_y_mm)
                cv2.circle(warped_img, (int(cx_w), int(cy_w)), 3, (0, 0, 255), -1) # Center dot
                
                for ring in bullseye.rings:
                    rx_w, ry_w = transformer.target_mm_to_warped_pixel(bullseye.center_x_mm + ring.outer_radius_mm, bullseye.center_y_mm)
                    r_w_px = int(abs(rx_w - cx_w))
                    cv2.circle(warped_img, (int(cx_w), int(cy_w)), r_w_px, (100, 200, 100), 1)
                    cv2.putText(warped_img, str(ring.value), (int(cx_w), int(cy_w - r_w_px) + 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.35, (100, 200, 100), 1, cv2.LINE_AA)

        # 3. Draw Shots (Green/Gray circles with yellow labels)
        for shot in shots:
            x_raw = shot.x_raw if hasattr(shot, "x_raw") else shot.get("x_raw")
            y_raw = shot.y_raw if hasattr(shot, "y_raw") else shot.get("y_raw")
            diameter_px = shot.diameter_px if hasattr(shot, "diameter_px") else shot.get("diameter_px", 15.0)
            shot_number = shot.shot_number if hasattr(shot, "shot_number") else shot.get("shot_number", 1)
            is_valid = shot.is_valid if hasattr(shot, "is_valid") else shot.get("is_valid", True)
            
            x_calib = shot.x_calibrated if hasattr(shot, "x_calibrated") else shot.get("x_calibrated")
            y_calib = shot.y_calibrated if hasattr(shot, "y_calibrated") else shot.get("y_calibrated")
            diameter_mm = shot.diameter_mm if hasattr(shot, "diameter_mm") else shot.get("diameter_mm")
            
            if x_calib is not None and y_calib is not None:
                wx, wy = transformer.target_mm_to_warped_pixel(x_calib, y_calib)
                if diameter_mm is not None:
                    wd_px = diameter_mm * (transformer.warped_width_px / transformer.target_width_mm)
                else:
                    wx2, wy2 = transformer.raw_pixel_to_warped_pixel(x_raw + diameter_px, y_raw)
                    wd_px = int(np.sqrt((wx2 - wx)**2 + (wy2 - wy)**2))
            else:
                wx, wy = transformer.raw_pixel_to_warped_pixel(x_raw, y_raw)
                wx2, wy2 = transformer.raw_pixel_to_warped_pixel(x_raw + diameter_px, y_raw)
                wd_px = int(np.sqrt((wx2 - wx)**2 + (wy2 - wy)**2))
                
            wr_px = max(4, int(wd_px // 2))

            color = (0, 255, 0) if is_valid else (128, 128, 128)
            cv2.circle(warped_img, (int(wx), int(wy)), wr_px, color, 2)
            cv2.circle(warped_img, (int(wx), int(wy)), 1, (255, 0, 0), -1) # center point
            
            cv2.putText(warped_img, f"#{shot_number}", (int(wx) - 5, int(wy) - wr_px - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1, cv2.LINE_AA)

        debug_path = os.path.join(settings.UPLOAD_DIR, f"debug_rectified_{session_id}.png")
        cv2.imwrite(debug_path, warped_img)
        logger.info(f"Generated rectified debug view: {debug_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to generate rectified debug image: {e}")
        return False


camera_service = CameraService()
