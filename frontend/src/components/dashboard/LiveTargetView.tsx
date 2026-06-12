"use client";

import React, { useRef, useEffect, useState } from "react";
import { useStore, Shot } from "@/store/useStore";
import { Maximize2, ShieldAlert, Crosshair, Trash2 } from "lucide-react";

export default function LiveTargetView() {
  const { shots, selectedShotId, setSelectedShotId, baselineUrl, currentFrameUrl, activeSession, setShots, setStatistics, setCurrentFrameUrl, targetDefinition } = useStore();
  const [isClearing, setIsClearing] = useState(false);

  const handleClearShots = async () => {
    if (!activeSession) return;
    if (!confirm("Are you sure you want to clear all shot markings from this session?")) return;
    setIsClearing(true);
    try {
      const res = await fetch(`http://localhost:8000/api/v1/sessions/${activeSession.id}/shots`, { method: "DELETE" });
      if (res.ok) {
        setShots([]);
        setCurrentFrameUrl(null);
        setStatistics({
          total_shots: 0,
          average_diameter_px: 0.0,
          largest_diameter_px: 0.0,
          smallest_diameter_px: 0.0,
          last_shot_time: null,
          session_status: activeSession.status,
          camera_status: "online"
        });
      }
    } catch (err) {
      console.error("Failed to clear shots:", err);
    } finally {
      setIsClearing(false);
    }
  };
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [imgLoaded, setImgLoaded] = useState(false);
  const imageRef = useRef<HTMLImageElement | null>(null);
  const [dimensions, setDimensions] = useState({ width: 600, height: 600 });
  const scaleRef = useRef(1);
  const offsetRef = useRef({ x: 0, y: 0 });

  // Use currentFrameUrl if available, otherwise fall back to baselineUrl
  const activeImageUrl = currentFrameUrl || baselineUrl;

  const [activeTab, setActiveTab] = useState<"markings" | "calibration" | "rectified" | "alignment" | "diff">("markings");
  const [debugRefreshKey, setDebugRefreshKey] = useState(Date.now());
  const [alignmentError, setAlignmentError] = useState(false);
  const [diffError, setDiffError] = useState(false);
  const [calibrationError, setCalibrationError] = useState(false);
  const [rectifiedError, setRectifiedError] = useState(false);
  const [projectedZones, setProjectedZones] = useState<{
    scoring_regions: any[];
    bullseyes: any[];
  } | null>(null);

  useEffect(() => {
    if (!activeSession) {
      setProjectedZones(null);
      return;
    }
    const fetchProjectedZones = async () => {
      try {
        const res = await fetch(`http://localhost:8000/api/v1/sessions/${activeSession.id}/projected-zones`);
        if (res.ok) {
          const data = await res.json();
          setProjectedZones(data);
        }
      } catch (err) {
        console.error("Failed to fetch projected zones:", err);
      }
    };
    fetchProjectedZones();
  }, [activeSession?.id, baselineUrl]);

  useEffect(() => {
    setDebugRefreshKey(Date.now());
    setAlignmentError(false);
    setDiffError(false);
    setCalibrationError(false);
    setRectifiedError(false);
  }, [activeImageUrl, shots.length, activeTab]);

  // Handle image loading
  useEffect(() => {
    if (!activeImageUrl) {
      setImgLoaded(false);
      imageRef.current = null;
      return;
    }

    const img = new Image();
    // Resolve absolute path or standard local URL proxying
    img.src = activeImageUrl.startsWith("http") ? activeImageUrl : `http://localhost:8000${activeImageUrl}`;
    img.onload = () => {
      imageRef.current = img;
      setImgLoaded(true);
      triggerResize();
    };
    img.onerror = () => {
      console.error("Failed to load target image from backend.");
      setImgLoaded(false);
    };
  }, [activeImageUrl]);

  // Handle responsive resizing
  const triggerResize = () => {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    // Account for container padding (p-6 = 48px) and canvas wrapper padding (p-2 = 16px) plus borders.
    const size = Math.max(260, Math.min(rect.width - 66, 600));
    setDimensions({ width: size, height: size });
  };

  useEffect(() => {
    triggerResize();
    window.addEventListener("resize", triggerResize);
    return () => window.removeEventListener("resize", triggerResize);
  }, [imgLoaded]);

  // Main Canvas Render loop
  useEffect(() => {
    if (activeTab !== "markings") return;

    let animationFrameId: number;

    const render = () => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;

      // Clear canvas
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.imageSmoothingEnabled = true;
      ctx.imageSmoothingQuality = "high";

      if (imgLoaded && imageRef.current) {
        const img = imageRef.current;
        // Calculate scaling to maintain aspect ratio inside square canvas
        const imgRatio = img.naturalWidth / img.naturalHeight;
        let drawW = canvas.width;
        let drawH = canvas.height;
        let dx = 0;
        let dy = 0;

        if (imgRatio > 1) {
          drawH = canvas.width / imgRatio;
          dy = (canvas.height - drawH) / 2;
        } else {
          drawW = canvas.height * imgRatio;
          dx = (canvas.width - drawW) / 2;
        }

        // Draw background image
        ctx.drawImage(img, dx, dy, drawW, drawH);

        // Save scaling factor & offset details for coordinates mapping
        const currentScale = drawW / img.naturalWidth;
        scaleRef.current = currentScale;
        offsetRef.current = { x: dx, y: dy };

        // Draw target template scoring zones/bullseyes
        if (projectedZones && (projectedZones.scoring_regions.length > 0 || projectedZones.bullseyes.length > 0)) {
          // A. Draw projected rectangular regions
          projectedZones.scoring_regions.forEach((region: any) => {
            ctx.strokeStyle = "rgba(99, 102, 241, 0.4)"; // Indigo border
            ctx.lineWidth = 1.25;
            ctx.beginPath();
            region.polygon.forEach((pt: number[], index: number) => {
              const px = pt[0] * currentScale + dx;
              const py = pt[1] * currentScale + dy;
              if (index === 0) ctx.moveTo(px, py);
              else ctx.lineTo(px, py);
            });
            ctx.closePath();
            ctx.stroke();

            // Label
            const labelX = region.polygon[0][0] * currentScale + dx;
            const labelY = region.polygon[0][1] * currentScale + dy;
            ctx.fillStyle = "rgba(99, 102, 241, 0.75)";
            ctx.font = "bold 8px monospace";
            ctx.textAlign = "left";
            ctx.textBaseline = "top";
            ctx.fillText(`${region.name || "Zone"} (${region.value} pts)`, labelX + 4, labelY + 4);
          });

          // B. Draw projected bullseyes/rings
          projectedZones.bullseyes.forEach((bullseye: any) => {
            // Center crosshair
            const cx = bullseye.center_pixel[0] * currentScale + dx;
            const cy = bullseye.center_pixel[1] * currentScale + dy;
            ctx.strokeStyle = "rgba(239, 68, 68, 0.4)";
            ctx.lineWidth = 1.0;
            ctx.beginPath();
            ctx.moveTo(cx - 10, cy);
            ctx.lineTo(cx + 10, cy);
            ctx.moveTo(cx, cy - 10);
            ctx.lineTo(cx, cy + 10);
            ctx.stroke();

            // Rings
            bullseye.rings.forEach((ring: any) => {
              ctx.strokeStyle = "rgba(16, 185, 129, 0.35)"; // Green ring border
              ctx.lineWidth = 1.0;
              ctx.beginPath();
              ring.polygon.forEach((pt: number[], index: number) => {
                const px = pt[0] * currentScale + dx;
                const py = pt[1] * currentScale + dy;
                if (index === 0) ctx.moveTo(px, py);
                else ctx.lineTo(px, py);
              });
              ctx.closePath();
              ctx.stroke();

              // Find top point of ring polygon for label placement
              let minYPt = ring.polygon[0];
              ring.polygon.forEach((pt: number[]) => {
                if (pt[1] < minYPt[1]) minYPt = pt;
              });
              const labelX = minYPt[0] * currentScale + dx;
              const labelY = minYPt[1] * currentScale + dy;
              ctx.fillStyle = "rgba(16, 185, 129, 0.65)";
              ctx.font = "8px monospace";
              ctx.textAlign = "center";
              ctx.textBaseline = "bottom";
              ctx.fillText(ring.value.toString(), labelX, labelY + 1.5);
            });
          });
        } else if (targetDefinition) {
          // Fallback to flat/linear target definition rendering
          // 1. Draw Rectangular Scoring Regions
          if (targetDefinition.scoring_regions && targetDefinition.scoring_regions.length > 0) {
            targetDefinition.scoring_regions.forEach((region: any) => {
              const rx_mm = region.x_min_mm;
              const ry_mm = region.y_min_mm;
              const rw_mm = region.x_max_mm - region.x_min_mm;
              const rh_mm = region.y_max_mm - region.y_min_mm;

              const rx = rx_mm * (drawW / targetDefinition.width_mm) + dx;
              const ry = ry_mm * (drawH / targetDefinition.height_mm) + dy;
              const rw = rw_mm * (drawW / targetDefinition.width_mm);
              const rh = rh_mm * (drawH / targetDefinition.height_mm);

              ctx.strokeStyle = "rgba(99, 102, 241, 0.35)"; // Indigo border
              ctx.lineWidth = 1.25;
              ctx.strokeRect(rx, ry, rw, rh);

              // Print score label in the corner of region
              ctx.fillStyle = "rgba(99, 102, 241, 0.6)";
              ctx.font = "bold 8px monospace";
              ctx.textAlign = "left";
              ctx.textBaseline = "top";
              ctx.fillText(`${region.name || "Zone"} (${region.value} pts)`, rx + 4, ry + 4);
            });
          }

          // 2. Draw Circular Concentric Bullseye Rings
          if (targetDefinition.bullseyes && targetDefinition.bullseyes.length > 0) {
            targetDefinition.bullseyes.forEach((bullseye: any) => {
              const cx_mm = bullseye.center_x_mm;
              const cy_mm = bullseye.center_y_mm;

              const cx = cx_mm * (drawW / targetDefinition.width_mm) + dx;
              const cy = cy_mm * (drawH / targetDefinition.height_mm) + dy;

              // Draw center crosshair
              ctx.strokeStyle = "rgba(239, 68, 68, 0.4)";
              ctx.lineWidth = 1.0;
              ctx.beginPath();
              ctx.moveTo(cx - 10, cy);
              ctx.lineTo(cx + 10, cy);
              ctx.moveTo(cx, cy - 10);
              ctx.lineTo(cx, cy + 10);
              ctx.stroke();

              if (bullseye.rings && bullseye.rings.length > 0) {
                bullseye.rings.forEach((ring: any) => {
                  const r_mm = ring.outer_radius_mm;
                  const r = r_mm * (drawW / targetDefinition.width_mm);

                  ctx.strokeStyle = "rgba(16, 185, 129, 0.3)"; // Green ring border
                  ctx.lineWidth = 1.0;
                  ctx.beginPath();
                  ctx.arc(cx, cy, r, 0, 2 * Math.PI);
                  ctx.stroke();

                  // Draw ring score number
                  ctx.fillStyle = "rgba(16, 185, 129, 0.55)";
                  ctx.font = "8px monospace";
                  ctx.textAlign = "center";
                  ctx.textBaseline = "bottom";
                  ctx.fillText(ring.value.toString(), cx, cy - r + 1.5);
                });
              }
            });
          }
        }

        // Draw shots
        shots.forEach((shot) => {
          if (!shot.is_valid) return;

          const canvasX = shot.x_raw * currentScale + dx;
          const canvasY = shot.y_raw * currentScale + dy;
          const radius = (shot.diameter_px * currentScale) / 2;

          const isSelected = shot.id === selectedShotId;

          // Draw detailed contour if available
          if (shot.detection && shot.detection.raw_contour) {
            ctx.beginPath();
            shot.detection.raw_contour.forEach((pt, index) => {
              const px = pt[0] * currentScale + dx;
              const py = pt[1] * currentScale + dy;
              if (index === 0) ctx.moveTo(px, py);
              else ctx.lineTo(px, py);
            });
            ctx.closePath();
            ctx.strokeStyle = isSelected ? "#ef4444" : "#10b981";
            ctx.lineWidth = isSelected ? 3 : 1.5;
            ctx.stroke();
            
            // Fill contour with transparent color
            ctx.fillStyle = isSelected ? "rgba(239, 68, 68, 0.2)" : "rgba(16, 185, 129, 0.1)";
            ctx.fill();
          } else {
            // Fallback to bounding circle
            ctx.beginPath();
            ctx.arc(canvasX, canvasY, Math.max(radius, 4), 0, 2 * Math.PI);
            ctx.fillStyle = isSelected ? "rgba(239, 68, 68, 0.3)" : "rgba(16, 185, 129, 0.25)";
            ctx.fill();
            ctx.strokeStyle = isSelected ? "#ef4444" : "#10b981";
            ctx.lineWidth = isSelected ? 2.5 : 1.5;
            ctx.stroke();
          }

          // Selected pulsating effect
          if (isSelected) {
            ctx.beginPath();
            ctx.arc(canvasX, canvasY, Math.max(radius, 4) + 8, 0, 2 * Math.PI);
            ctx.strokeStyle = "rgba(239, 68, 68, 0.4)";
            ctx.lineWidth = 1;
            ctx.stroke();
          }

          // Draw shot label
          ctx.fillStyle = "#ffffff";
          ctx.font = "bold 10px monospace";
          ctx.textAlign = "center";
          ctx.textBaseline = "middle";
          
          // Draw label background circle
          ctx.beginPath();
          ctx.arc(canvasX, canvasY - Math.max(radius, 4) - 10, 8, 0, 2 * Math.PI);
          ctx.fillStyle = isSelected ? "#ef4444" : "#0f172a";
          ctx.fill();
          ctx.strokeStyle = isSelected ? "#ffffff" : "#10b981";
          ctx.lineWidth = 1;
          ctx.stroke();

          ctx.fillStyle = "#ffffff";
          ctx.fillText(shot.shot_number.toString(), canvasX, canvasY - Math.max(radius, 4) - 10);
        });
      } else {
        // Draw clean tactical crosshair and grid backdrop
        scaleRef.current = 1;
        offsetRef.current = { x: 0, y: 0 };

        const cx = canvas.width / 2;
        const cy = canvas.height / 2;

        // Draw grid lines
        ctx.strokeStyle = "rgba(255, 255, 255, 0.02)";
        ctx.lineWidth = 1;
        const gridSize = 40;
        for (let x = gridSize; x < canvas.width; x += gridSize) {
          ctx.beginPath();
          ctx.moveTo(x, 0);
          ctx.lineTo(x, canvas.height);
          ctx.stroke();
        }
        for (let y = gridSize; y < canvas.height; y += gridSize) {
          ctx.beginPath();
          ctx.moveTo(0, y);
          ctx.lineTo(canvas.width, y);
          ctx.stroke();
        }

        // Draw primary crosshairs
        ctx.strokeStyle = "rgba(16, 185, 129, 0.15)"; // neon green glow line
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(0, cy);
        ctx.lineTo(canvas.width, cy);
        ctx.moveTo(cx, 0);
        ctx.lineTo(cx, canvas.height);
        ctx.stroke();

        // Outer bounding safe border
        ctx.strokeStyle = "rgba(255, 255, 255, 0.05)";
        ctx.lineWidth = 1;
        ctx.strokeRect(20, 20, canvas.width - 40, canvas.height - 40);

        // Status text on canvas
        ctx.fillStyle = "rgba(255, 255, 255, 0.35)";
        ctx.font = "bold 11px monospace";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText("AWAITING TARGET CALIBRATION BASELINE", cx, cy);
      }
    };

    render();
    animationFrameId = requestAnimationFrame(render);

    return () => {
      cancelAnimationFrame(animationFrameId);
    };
  }, [imgLoaded, shots, selectedShotId, dimensions, targetDefinition, activeTab, projectedZones]);

  // Handle hover detection
  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!canvasRef.current || shots.length === 0) return;
    const canvas = canvasRef.current;
    const rect = canvas.getBoundingClientRect();
    
    // Relative click on coordinates
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    let hoveredShotId: string | null = null;
    let minDistance = 20; // 20px hit range

    shots.forEach((shot) => {
      if (!shot.is_valid) return;
      const canvasX = shot.x_raw * scaleRef.current + offsetRef.current.x;
      const canvasY = shot.y_raw * scaleRef.current + offsetRef.current.y;
      
      const distance = Math.sqrt((mouseX - canvasX) ** 2 + (mouseY - canvasY) ** 2);
      if (distance < minDistance) {
        minDistance = distance;
        hoveredShotId = shot.id;
      }
    });

    if (hoveredShotId !== selectedShotId) {
      setSelectedShotId(hoveredShotId);
    }
  };

  const handleMouseLeave = () => {
    setSelectedShotId(null);
  };

  return (
    <div ref={containerRef} className="glass-panel p-6 flex flex-col items-center justify-between h-full">
      <div className="flex justify-between items-center w-full mb-4">
        <div className="flex items-center gap-2">
          <Crosshair className="w-5 h-5 text-neon" />
          <h3 className="text-base font-bold font-mono tracking-wider uppercase">Live Target Visualizer</h3>
        </div>
        <div className="flex gap-2">
          {activeSession && shots.length > 0 && (
            <button
              onClick={handleClearShots}
              disabled={isClearing}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-red-950/40 border border-red-500/20 hover:bg-red-900/40 transition text-red-400 hover:text-red-300 text-xs font-mono"
              title="Clear all shot markings"
            >
              <Trash2 className="w-3.5 h-3.5" />
              <span>CLEAR MARKS</span>
            </button>
          )}
          <button onClick={triggerResize} className="p-1.5 rounded bg-white/5 border border-white/5 hover:bg-white/10 transition text-gray-400 hover:text-white" title="Recenter View">
            <Maximize2 className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Dev Pipeline Verification Tabs */}
      <div className="flex w-full border-b border-white/5 mb-4 gap-1">
        <button
          onClick={() => setActiveTab("markings")}
          className={`flex-1 py-1.5 text-center font-mono text-[10px] uppercase font-bold tracking-wider transition border-b-2 ${
            activeTab === "markings"
              ? "text-neon border-neon bg-white/2"
              : "text-gray-500 hover:text-gray-300 border-transparent"
          }`}
        >
          Markings
        </button>
        <button
          onClick={() => setActiveTab("calibration")}
          disabled={!activeSession}
          className={`flex-1 py-1.5 text-center font-mono text-[10px] uppercase font-bold tracking-wider transition border-b-2 ${
            !activeSession ? "opacity-30 cursor-not-allowed border-transparent" : ""
          } ${
            activeTab === "calibration"
              ? "text-neon border-neon bg-white/2"
              : "text-gray-500 hover:text-gray-300 border-transparent"
          }`}
        >
          Calibration
        </button>
        <button
          onClick={() => setActiveTab("rectified")}
          disabled={!activeSession}
          className={`flex-1 py-1.5 text-center font-mono text-[10px] uppercase font-bold tracking-wider transition border-b-2 ${
            !activeSession ? "opacity-30 cursor-not-allowed border-transparent" : ""
          } ${
            activeTab === "rectified"
              ? "text-neon border-neon bg-white/2"
              : "text-gray-500 hover:text-gray-300 border-transparent"
          }`}
        >
          Homographed View
        </button>
        <button
          onClick={() => setActiveTab("alignment")}
          disabled={!activeSession}
          className={`flex-1 py-1.5 text-center font-mono text-[10px] uppercase font-bold tracking-wider transition border-b-2 ${
            !activeSession ? "opacity-30 cursor-not-allowed border-transparent" : ""
          } ${
            activeTab === "alignment"
              ? "text-neon border-neon bg-white/2"
              : "text-gray-500 hover:text-gray-300 border-transparent"
          }`}
        >
          ORB Alignment
        </button>
        <button
          onClick={() => setActiveTab("diff")}
          disabled={!activeSession}
          className={`flex-1 py-1.5 text-center font-mono text-[10px] uppercase font-bold tracking-wider transition border-b-2 ${
            !activeSession ? "opacity-30 cursor-not-allowed border-transparent" : ""
          } ${
            activeTab === "diff"
              ? "text-neon border-neon bg-white/2"
              : "text-gray-500 hover:text-gray-300 border-transparent"
          }`}
        >
          Diff Binary Map
        </button>
      </div>

      <div className="relative border border-white/5 bg-[#030712] rounded-lg overflow-hidden flex items-center justify-center p-2 w-full">
        {/* Markings Tab (Canvas) */}
        <div className={activeTab === "markings" ? "block" : "hidden"}>
          <canvas
            ref={canvasRef}
            width={dimensions.width}
            height={dimensions.height}
            onMouseMove={handleMouseMove}
            onMouseLeave={handleMouseLeave}
            className="cursor-crosshair max-w-full"
          />
        </div>

        {/* Calibration Tab */}
        <div className={activeTab === "calibration" ? "block w-full h-full" : "hidden"}>
          <div className="relative flex items-center justify-center max-w-full" style={{ width: dimensions.width, height: dimensions.height }}>
            {!calibrationError ? (
              <img
                src={`http://localhost:8000/static/uploads/debug_calibration_${activeSession?.id}.jpg?t=${debugRefreshKey}`}
                alt="Calibration Detections View"
                className="max-w-full max-h-full object-contain"
                onError={() => setCalibrationError(true)}
              />
            ) : (
              <div className="flex flex-col items-center justify-center p-6 text-center">
                <ShieldAlert className="w-8 h-8 text-amber-500 mb-2" />
                <h4 className="font-mono text-xs font-semibold text-white uppercase tracking-wider">No Calibration Bounding Boxes Image</h4>
                <p className="text-[10px] text-gray-400 mt-1 max-w-[240px]">
                  Calibrate the camera or upload a baseline image first to detect target corners and AprilTags.
                </p>
              </div>
            )}
          </div>
        </div>

        {/* Rectified View Tab */}
        <div className={activeTab === "rectified" ? "block w-full h-full" : "hidden"}>
          <div className="relative flex items-center justify-center max-w-full" style={{ width: dimensions.width, height: dimensions.height }}>
            {!rectifiedError ? (
              <img
                src={`http://localhost:8000/static/uploads/debug_rectified_${activeSession?.id}.png?t=${debugRefreshKey}`}
                alt="Homographed Rectified View"
                className="max-w-full max-h-full object-contain"
                onError={() => setRectifiedError(true)}
              />
            ) : (
              <div className="flex flex-col items-center justify-center p-6 text-center">
                <ShieldAlert className="w-8 h-8 text-amber-500 mb-2" />
                <h4 className="font-mono text-xs font-semibold text-white uppercase tracking-wider">No Homographed View</h4>
                <p className="text-[10px] text-gray-400 mt-1 max-w-[240px]">
                  Calibrate the target or run detection to generate the flat perspective-rectified view.
                </p>
              </div>
            )}
          </div>
        </div>

        {/* Alignment Tab */}
        <div className={activeTab === "alignment" ? "block w-full h-full" : "hidden"}>
          <div className="relative flex items-center justify-center max-w-full" style={{ width: dimensions.width, height: dimensions.height }}>
            {!alignmentError ? (
              <img
                src={`http://localhost:8000/static/uploads/debug_aligned_${activeSession?.id}.png?t=${debugRefreshKey}`}
                alt="ORB Alignment Frame"
                className="max-w-full max-h-full object-contain"
                onError={() => setAlignmentError(true)}
              />
            ) : (
              <div className="flex flex-col items-center justify-center p-6 text-center">
                <ShieldAlert className="w-8 h-8 text-amber-500 mb-2" />
                <h4 className="font-mono text-xs font-semibold text-white uppercase tracking-wider">No Alignment Frame</h4>
                <p className="text-[10px] text-gray-400 mt-1 max-w-[240px]">
                  Trigger a shot or run impact analysis to generate the ORB alignment view.
                </p>
              </div>
            )}
          </div>
        </div>

        {/* Diff Binary Map Tab */}
        <div className={activeTab === "diff" ? "block w-full h-full" : "hidden"}>
          <div className="relative flex items-center justify-center max-w-full" style={{ width: dimensions.width, height: dimensions.height }}>
            {!diffError ? (
              <img
                src={`http://localhost:8000/static/uploads/debug_diff_${activeSession?.id}.png?t=${debugRefreshKey}`}
                alt="Binary Difference Map"
                className="max-w-full max-h-full object-contain"
                onError={() => setDiffError(true)}
              />
            ) : (
              <div className="flex flex-col items-center justify-center p-6 text-center">
                <ShieldAlert className="w-8 h-8 text-amber-500 mb-2" />
                <h4 className="font-mono text-xs font-semibold text-white uppercase tracking-wider">No Difference Map</h4>
                <p className="text-[10px] text-gray-400 mt-1 max-w-[240px]">
                  Trigger a shot or run impact analysis to generate the binary diff view.
                </p>
              </div>
            )}
          </div>
        </div>

        {activeTab === "markings" && !baselineUrl && (
          <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/60 backdrop-blur-sm p-6 text-center">
            <ShieldAlert className="w-10 h-10 text-amber-500 mb-3" />
            <h4 className="font-mono text-sm font-semibold text-white uppercase tracking-wider">Baseline Required</h4>
            <p className="text-xs text-gray-400 mt-1 max-w-[280px]">
              Upload a baseline camera frame image first to calibrate the camera differencing engine.
            </p>
          </div>
        )}
      </div>

      <div className="w-full flex justify-between items-center text-[10px] text-gray-500 font-mono mt-4">
        <span>RESOLUTION: {imageRef.current ? `${imageRef.current.naturalWidth}x${imageRef.current.naturalHeight}px` : "N/A"}</span>
        <span>SCALE: {imageRef.current ? `${(scaleRef.current * 100).toFixed(1)}%` : "1:1"}</span>
      </div>
    </div>
  );
}
