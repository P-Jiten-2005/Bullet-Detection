"use client";

import React, { useEffect, useState, useRef } from "react";
import { useStore, Shot, Session } from "@/store/useStore";
import OverviewCards from "@/components/dashboard/OverviewCards";
import LiveTargetView from "@/components/dashboard/LiveTargetView";
import ShotTable from "@/components/dashboard/ShotTable";
import StatsPanel from "@/components/dashboard/StatsPanel";
import ConnectionStatus from "@/components/dashboard/ConnectionStatus";
import TargetPreview from "@/components/dashboard/TargetPreview";
import { PlusCircle, Upload, Play, Terminal, CircleCheck, AlertTriangle, Trash } from "lucide-react";

export default function DashboardPage() {
  const {
    activeSession,
    setActiveSession,
    setWsStatus,
    setShots,
    addShot,
    setStatistics,
    setBaselineUrl,
    baselineUrl,
    setCurrentFrameUrl,
    setTargetDefinition,
    userRole,
    setUserRole
  } = useStore();

  const [newSessionName, setNewSessionName] = useState("");
  const [newSessionDesc, setNewSessionDesc] = useState("");
  const [newSessionTargetType, setNewSessionTargetType] = useState("figure_eleven");
  const [newSessionBulletCaliber, setNewSessionBulletCaliber] = useState(5.56);
  const [targetDefinitions, setTargetDefinitions] = useState<any[]>([]);
  const [showCreateModal, setShowCreateModal] = useState(false);
  
  // Custom Target creation states
  const [showCreateTargetModal, setShowCreateTargetModal] = useState(false);
  const [customTargetName, setCustomTargetName] = useState("");
  const [customTargetWidth, setCustomTargetWidth] = useState(80.0);
  const [customTargetHeight, setCustomTargetHeight] = useState(80.0);
  const [customTargetDecimalScoring, setCustomTargetDecimalScoring] = useState(true);
  const [customTargetRingSpacing, setCustomTargetRingSpacing] = useState(2.5);
  const [customTargetCalibers, setCustomTargetCalibers] = useState<string[]>(["5.56", "7.62", "9.0"]);
  const [customTargetRings, setCustomTargetRings] = useState<{ value: number; outer_radius_mm: number }[]>([
    { value: 10, outer_radius_mm: 2.5 },
    { value: 9, outer_radius_mm: 5.0 },
    { value: 8, outer_radius_mm: 7.5 },
    { value: 7, outer_radius_mm: 10.0 },
    { value: 6, outer_radius_mm: 12.5 },
    { value: 5, outer_radius_mm: 15.0 },
    { value: 4, outer_radius_mm: 17.5 },
    { value: 3, outer_radius_mm: 20.0 },
    { value: 2, outer_radius_mm: 22.5 },
    { value: 1, outer_radius_mm: 25.0 }
  ]);
  const [customTargetPreviewBase64, setCustomTargetPreviewBase64] = useState<string | null>(null);
  const [customTargetType, setCustomTargetType] = useState<"circular" | "rectangular">("rectangular");
  const [customTargetTagSizeMm, setCustomTargetTagSizeMm] = useState(50.0);
  const [customTargetTagMarginMm, setCustomTargetTagMarginMm] = useState(20.0);
  const [customTargetRegions, setCustomTargetRegions] = useState<{ id: number; name: string; value: number; x_min_mm: number; y_min_mm: number; x_max_mm: number; y_max_mm: number }[]>([
    { id: 1, name: "Outer Torso", value: 4, x_min_mm: 40.0, y_min_mm: 42.5, x_max_mm: 540.0, y_max_mm: 842.5 },
    { id: 2, name: "Inner Center", value: 5, x_min_mm: 190.0, y_min_mm: 292.5, x_max_mm: 390.0, y_max_mm: 592.5 }
  ]);
  const [isDraggingCenter, setIsDraggingCenter] = useState(false);
  const [dragStart, setDragStart] = useState<{ x: number; y: number } | null>(null);
  const [dragCurrent, setDragCurrent] = useState<{ x: number; y: number } | null>(null);
  const [circularCenterMm, setCircularCenterMm] = useState<{ x: number; y: number }>({ x: 40.0, y: 40.0 });
  const [hoverMm, setHoverMm] = useState<{ x: number; y: number } | null>(null);
  const [selectedZoneId, setSelectedZoneId] = useState<number | null>(null);
  const [selectedRingIdx, setSelectedRingIdx] = useState<number | null>(null);

  const [isUploadingBaseline, setIsUploadingBaseline] = useState(false);
  const [isDetecting, setIsDetecting] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  
  // Camera Integration states
  const [cameraSource, setCameraSource] = useState("0");
  const [isCameraActive, setIsCameraActive] = useState(false);
  const [isCalibrating, setIsCalibrating] = useState(false);
  const [zoomFactor, setZoomFactor] = useState(1.0);
  const [isCapturingBeforeFire, setIsCapturingBeforeFire] = useState(false);


  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);

  // Helper to append log lines
  const addLog = (message: string) => {
    const time = new Date().toLocaleTimeString();
    setLogs((prev) => [`[${time}] ${message}`, ...prev.slice(0, 20)]);
  };

  // Fetch target config details
  const fetchTargetDefinition = async (targetType: string) => {
    try {
      const res = await fetch(`http://localhost:8000/api/v1/targets/${targetType}`);
      if (res.ok) {
        const data = await res.json();
        setTargetDefinition(data);
      }
    } catch (e) {
      console.error("Failed to load target definition", e);
    }
  };

  useEffect(() => {
    setCircularCenterMm({
      x: customTargetWidth / 2,
      y: customTargetHeight / 2
    });
  }, [customTargetWidth, customTargetHeight]);

  // Load target definitions list and active session on mount
  useEffect(() => {
    async function loadTargets() {
      try {
        const res = await fetch("http://localhost:8000/api/v1/targets");
        if (res.ok) {
          const data = await res.json();
          setTargetDefinitions(data);
        }
      } catch (err) {
        console.error("Failed to load target definitions:", err);
      }
    }
    loadTargets();

    async function initSession() {
      addLog("Initializing Shooting Target Analysis Platform...");
      try {
        const res = await fetch("http://localhost:8000/api/v1/sessions/active");
        if (res.ok) {
          const session: Session = await res.json();
          if (session) {
            addLog(`Found active session: "${session.name}"`);
            setActiveSession(session);
            await fetchSessionDetails(session.id);
            await fetchTargetDefinition(session.target_type);
          } else {
            addLog("No active session detected. Automatically creating a default session...");
            const createRes = await fetch("http://localhost:8000/api/v1/sessions", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ 
                name: "Default Live Session", 
                description: "Automatically initialized live shooting session.",
                target_type: "figure_eleven",
                bullet_caliber: 5.56
              })
            });
            if (createRes.ok) {
              const newSession: Session = await createRes.json();
              setActiveSession(newSession);
              await fetchSessionDetails(newSession.id);
              await fetchTargetDefinition(newSession.target_type);
              addLog(`Default session initialized: "${newSession.name}"`);
            }
          }
        }
      } catch (error) {
        addLog("Error connecting to backend API. Ensure Uvicorn server is running on port 8000.");
        console.error("Session init failed:", error);
      }
    }
    initSession();
    
    return () => {
      if (wsRef.current) wsRef.current.close();
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
    };
  }, []);

  // 2. Fetch shots and image baseline info
  const fetchSessionDetails = async (sessionId: string) => {
    try {
      // Fetch shots
      const shotsRes = await fetch(`http://localhost:8000/api/v1/sessions/${sessionId}/shots`);
      if (shotsRes.ok) {
        const shotsData: Shot[] = await shotsRes.json();
        setShots(shotsData);
        addLog(`Loaded ${shotsData.length} existing shots for this session.`);
      }

      // Fetch statistics
      const statsRes = await fetch(`http://localhost:8000/api/v1/sessions/${sessionId}/statistics`);
      if (statsRes.ok) {
        const statsData = await statsRes.json();
        setStatistics(statsData);
      }

      // Check if baseline exists on backend
      const baselineRes = await fetch(`http://localhost:8000/api/v1/sessions/${sessionId}/baseline`);
      if (baselineRes.ok) {
        const baselineData = await baselineRes.json();
        if (baselineData && baselineData.file_path) {
          setBaselineUrl(baselineData.file_path);
          addLog("Loaded existing target baseline calibration.");
        } else {
          setBaselineUrl(null);
          addLog("No baseline calibration found. Connect camera and calibrate target.");
        }
      } else {
        setBaselineUrl(null);
      }
    } catch (e) {
      console.error("Failed to load session details", e);
    }
  };

  // 3. Connect to WebSockets
  useEffect(() => {
    if (!activeSession) {
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      return;
    }

    const connectWebSocket = () => {
      setWsStatus("connecting");
      addLog(`Connecting WebSocket subscription for session ${activeSession.id.slice(0, 8)}...`);

      const ws = new WebSocket(`ws://localhost:8000/ws/session/${activeSession.id}`);
      wsRef.current = ws;

      ws.onopen = () => {
        setWsStatus("connected");
        addLog("WebSocket link established. Awaiting live trigger events...");
      };

      ws.onmessage = (event) => {
        try {
          // Check if heartbeat echo
          if (event.data.startsWith("heartbeat")) return;

          const payload = JSON.parse(event.data);
          if (payload.event === "SHOT_DETECTED") {
            const newShot: Shot = payload.data;
            addShot(newShot);
            const scoreStr = newShot.score !== undefined && newShot.score !== null ? `Score: ${newShot.score} (Decimal: ${newShot.decimal_score?.toFixed(1) || '0.0'})` : `at (${newShot.x_raw.toFixed(1)}, ${newShot.y_raw.toFixed(1)})`;
            addLog(`LIVE TELEMETRY: Shot #${newShot.shot_number} detected. ${scoreStr} (confidence ${(newShot.confidence * 100).toFixed(0)}%)`);
          } else if (payload.event === "BASELINE_UPLOADED") {
            setBaselineUrl(payload.data.file_path);
            setCurrentFrameUrl(null);
            if (payload.data.method === "fallback") {
              addLog("⚠️ LIVE TELEMETRY: Baseline updated via fallback center-crop (corners not detected).");
            } else {
              addLog("LIVE TELEMETRY: Baseline target calibration completed successfully.");
            }
          } else if (payload.event === "SHOTS_CLEARED") {
            setShots([]);
            setStatistics({
              total_shots: 0,
              average_diameter_px: 0.0,
              largest_diameter_px: 0.0,
              smallest_diameter_px: 0.0,
              last_shot_time: null,
              session_status: activeSession ? activeSession.status : "active",
              camera_status: "online"
            });
            addLog("LIVE TELEMETRY: All shot markings cleared from this session.");
          }
        } catch (e) {
          console.error("Failed to parse websocket message", e);
        }
      };

      ws.onclose = () => {
        setWsStatus("disconnected");
        addLog("WebSocket disconnected. Retrying connection in 5 seconds...");
        reconnectTimeoutRef.current = window.setTimeout(() => {
          connectWebSocket();
        }, 5000);
      };

      ws.onerror = (error) => {
        console.error("WebSocket error:", error);
        ws.close();
      };
    };

    connectWebSocket();

    return () => {
      if (wsRef.current) {
        wsRef.current.onclose = null; // Prevent reconnect callbacks
        wsRef.current.close();
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
    };
  }, [activeSession]);

  // 4. API Event: Create Session
  const handleCreateSession = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newSessionName.trim()) return;

    try {
      addLog(`Creating session "${newSessionName}"...`);
      const res = await fetch("http://localhost:8000/api/v1/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
          name: newSessionName, 
          description: newSessionDesc,
          target_type: newSessionTargetType,
          bullet_caliber: newSessionBulletCaliber
        })
      });

      if (res.ok) {
        const session: Session = await res.json();
        setActiveSession(session);
        setShots([]);
        setBaselineUrl(null);
        setCurrentFrameUrl(null);
        await fetchTargetDefinition(session.target_type);
        setNewSessionName("");
        setNewSessionDesc("");
        setShowCreateModal(false);
        addLog(`New session active: ${session.name} (Target: ${session.target_type}, Caliber: ${session.bullet_caliber}mm)`);
        // Force refresh stats
        setStatistics({
          total_shots: 0,
          average_diameter_px: 0.0,
          largest_diameter_px: 0.0,
          smallest_diameter_px: 0.0,
          last_shot_time: null,
          session_status: "active",
          camera_status: "online"
        });
      }
    } catch (error) {
      addLog("Failed to create new session.");
      console.error(error);
    }
  };

  // API Event: Create Target
  const handlePreviewImageChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onloadend = () => {
      setCustomTargetPreviewBase64(reader.result as string);
    };
    reader.readAsDataURL(file);
  };

  const handleAddRing = () => {
    const nextValue = customTargetRings.length > 0 
      ? Math.min(...customTargetRings.map(r => r.value)) - 1
      : 10;
    const finalValue = Math.max(nextValue, 0);
    const nextRadius = customTargetRings.length > 0
      ? Math.max(...customTargetRings.map(r => r.outer_radius_mm)) + 2.5
      : 2.5;
    setCustomTargetRings([...customTargetRings, { value: finalValue, outer_radius_mm: nextRadius }]);
  };

  const handleRemoveRing = (index: number) => {
    setCustomTargetRings(customTargetRings.filter((_, i) => i !== index));
  };

  const handleRingChange = (index: number, field: "value" | "outer_radius_mm", val: number) => {
    const updated = customTargetRings.map((r, i) => {
      if (i === index) {
        return { ...r, [field]: val };
      }
      return r;
    });
    // Sort rings descending by radius
    updated.sort((a, b) => b.outer_radius_mm - a.outer_radius_mm);
    setCustomTargetRings(updated);
  };

  const handleAddRegion = () => {
    const nextId = customTargetRegions.length > 0 ? Math.max(...customTargetRegions.map(r => r.id)) + 1 : 1;
    setCustomTargetRegions([
      ...customTargetRegions,
      { id: nextId, name: `Zone ${nextId}`, value: 1, x_min_mm: 0, y_min_mm: 0, x_max_mm: 100, y_max_mm: 100 }
    ]);
  };

  const handleRemoveRegion = (id: number) => {
    setCustomTargetRegions(customTargetRegions.filter(r => r.id !== id));
  };

  const handleRegionChange = (id: number, field: string, val: any) => {
    setCustomTargetRegions(
      customTargetRegions.map(r => (r.id === id ? { ...r, [field]: val } : r))
    );
  };

  const handleCreateTarget = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!customTargetName.trim()) return;

    const targetPayload = {
      name: customTargetName,
      width_mm: parseFloat(customTargetWidth.toString()) || 80.0,
      height_mm: parseFloat(customTargetHeight.toString()) || 80.0,
      bullet_compatibility: customTargetCalibers,
      decimal_scoring_supported: customTargetDecimalScoring,
      ring_spacing_mm: parseFloat(customTargetRingSpacing.toString()) || 2.5,
      tag_size_mm: parseFloat(customTargetTagSizeMm.toString()) || 50.0,
      tag_margin_mm: parseFloat(customTargetTagMarginMm.toString()) || 20.0,
      bullseyes: customTargetType === "circular" ? [
        {
          id: 1,
          center_x_mm: (parseFloat(customTargetWidth.toString()) || 80.0) / 2.0,
          center_y_mm: (parseFloat(customTargetHeight.toString()) || 80.0) / 2.0,
          scoring_rule: "inward",
          rings: customTargetRings.map(r => ({
            value: parseInt(r.value.toString()),
            outer_radius_mm: parseFloat(r.outer_radius_mm.toString())
          }))
        }
      ] : [],
      scoring_regions: customTargetType === "rectangular" ? customTargetRegions.map(r => ({
        id: r.id,
        name: r.name,
        value: parseInt(r.value.toString()),
        x_min_mm: parseFloat(r.x_min_mm.toString()),
        y_min_mm: parseFloat(r.y_min_mm.toString()),
        x_max_mm: parseFloat(r.x_max_mm.toString()),
        y_max_mm: parseFloat(r.y_max_mm.toString())
      })) : [],
      preview_image_base64: customTargetPreviewBase64
    };

    try {
      addLog(`Creating custom target "${customTargetName}"...`);
      const res = await fetch("http://localhost:8000/api/v1/targets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(targetPayload)
      });

      if (res.ok) {
        addLog(`Custom target "${customTargetName}" successfully added.`);
        const targetsRes = await fetch("http://localhost:8000/api/v1/targets");
        if (targetsRes.ok) {
          const data = await targetsRes.json();
          setTargetDefinitions(data);
          const newTargetId = data.find((t: any) => t.name === customTargetName)?.id;
          if (newTargetId) {
            setNewSessionTargetType(newTargetId);
          }
        }
        
        setCustomTargetName("");
        setCustomTargetWidth(80.0);
        setCustomTargetHeight(80.0);
        setCustomTargetPreviewBase64(null);
        setShowCreateTargetModal(false);
      } else {
        const errData = await res.json();
        addLog(`Failed to add target: ${errData.detail || 'unknown error'}`);
      }
    } catch (error) {
      addLog("Failed to connect to target creation endpoint.");
      console.error(error);
    }
  };

  // 5. API Event: Upload Baseline Image
  const handleBaselineUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0 || !activeSession) return;

    const file = files[0];
    const formData = new FormData();
    formData.append("file", file);

    setIsUploadingBaseline(true);
    addLog(`Uploading baseline target frame: "${file.name}"...`);

    try {
      const res = await fetch(`http://localhost:8000/api/v1/sessions/${activeSession.id}/baseline`, {
        method: "POST",
        body: formData
      });

      if (res.ok) {
        const data = await res.json();
        // Extract static path
        setBaselineUrl(data.file_path);
        addLog("Baseline target registered successfully.");
      } else {
        addLog("Failed to register baseline target image.");
      }
    } catch (err) {
      addLog("Error uploading baseline.");
      console.error(err);
    } finally {
      setIsUploadingBaseline(false);
    }
  };

  // 6. API Event: Trigger Detection Frame
  const handleDetectUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0 || !activeSession) return;
    if (!baselineUrl) {
      alert("Please upload a baseline target image before analyzing shooting frames.");
      return;
    }

    const file = files[0];
    const formData = new FormData();
    formData.append("file", file);

    setIsDetecting(true);
    addLog(`Ingesting capture frame: "${file.name}"...`);

    try {
      const res = await fetch(`http://localhost:8000/api/v1/sessions/${activeSession.id}/detect`, {
        method: "POST",
        body: formData
      });

      if (res.ok) {
        const data = await res.json();
        addLog(`Analysis complete. Found ${data.new_shots_count} new bullet holes in frame.`);
        if (data.shots_detected && data.shots_detected.length > 0) {
          data.shots_detected.forEach((shot: Shot) => {
            addShot(shot);
          });
        }
        if (data.current_frame_url) {
          setCurrentFrameUrl(data.current_frame_url);
        }
      } else {
        const errorData = await res.json();
        addLog(`Error during CV detection: ${errorData.detail || "Server error"}`);
      }
    } catch (err) {
      addLog("Error running target detection pipeline.");
      console.error(err);
    } finally {
      setIsDetecting(false);
    }
  };

  // 7. API Event: Camera Controls
  const toggleCamera = async () => {
    if (!activeSession) return;
    if (isCameraActive) {
      try {
        addLog("Disconnecting camera source...");
        const res = await fetch("http://localhost:8000/api/v1/camera/stop", { method: "POST" });
        if (res.ok) {
          setIsCameraActive(false);
          addLog("Camera disconnected.");
        }
      } catch (err) {
        addLog("Failed to disconnect camera.");
      }
    } else {
      try {
        addLog(`Connecting camera source: "${cameraSource}"...`);
        const res = await fetch(`http://localhost:8000/api/v1/camera/start?source=${encodeURIComponent(cameraSource)}`, { method: "POST" });
        if (res.ok) {
          setIsCameraActive(true);
          addLog("Camera connected. Live feed active on preview panel.");
        } else {
          addLog("Failed to connect to camera. Check source index or URL.");
        }
      } catch (err) {
        addLog("Error starting camera service.");
      }
    }
  };

  const handleCalibrate = async () => {
    if (!activeSession || !isCameraActive) return;
    setIsCalibrating(true);
    addLog("Analyzing frame for rectangular paper target. Calibrating homography...");
    try {
      const res = await fetch(`http://localhost:8000/api/v1/camera/calibrate?session_id=${activeSession.id}`, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        setBaselineUrl(data.file_path);
        setCurrentFrameUrl(null);
        if (data.method === "fallback") {
          addLog("⚠️ Calibration completed using fallback center-crop. (Paper corners not detected. Check lighting/contrast).");
        } else {
          addLog("Target calibration completed. Perspective rectified to 1000x1000 pixels.");
        }
      } else {
        const errorData = await res.json();
        addLog(`Calibration failed: ${errorData.detail || "Paper borders not detected"}`);
      }
    } catch (err) {
      addLog("Error executing target calibration.");
    } finally {
      setIsCalibrating(false);
    }
  };

  const handleBeforeFire = async () => {
    if (!activeSession || !isCameraActive) return;
    setIsCapturingBeforeFire(true);
    addLog("Capturing pristine baseline target frame (before fire)...");
    try {
      const res = await fetch(`http://localhost:8000/api/v1/camera/before_fire?session_id=${activeSession.id}`, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        setBaselineUrl(data.file_path);
        setCurrentFrameUrl(null);
        if (data.method === "fallback") {
          addLog("📷 Pristine baseline target frame captured via fallback center-crop.");
        } else {
          addLog("📷 Pristine baseline target frame captured and registered (perspective rectified).");
        }
      } else {
        const errorData = await res.json();
        addLog(`Capture failed: ${errorData.detail || "Server error"}`);
      }
    } catch (err) {
      addLog("Error executing target baseline capture.");
    } finally {
      setIsCapturingBeforeFire(false);
    }
  };



  const handleZoomChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = parseFloat(e.target.value);
    setZoomFactor(val);
    try {
      await fetch(`http://localhost:8000/api/v1/camera/zoom?factor=${val}`, { method: "POST" });
    } catch (err) {
      console.error("Failed to update camera zoom:", err);
    }
  };

  const handleFire = async () => {
    if (!activeSession || !isCameraActive || !baselineUrl) return;
    setIsDetecting(true);
    addLog("FIRED! Capturing camera frame and analyzing bullet hole impacts...");
    try {
      const res = await fetch(`http://localhost:8000/api/v1/camera/fire?session_id=${activeSession.id}`, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        addLog(`Analysis complete. Found ${data.new_shots_count} new bullet holes in frame.`);
        if (data.shots_detected && data.shots_detected.length > 0) {
          data.shots_detected.forEach((shot: Shot) => {
            addShot(shot);
          });
        }
        if (data.current_frame_url) {
          setCurrentFrameUrl(data.current_frame_url);
        }
      } else {
        const errorData = await res.json();
        addLog(`Analysis failed: ${errorData.detail || "Server error"}`);
      }
    } catch (err) {
      addLog("Error executing target detection pipeline.");
      console.error(err);
    } finally {
      setIsDetecting(false);
    }
  };


  return (
    <main className="min-h-screen flex flex-col p-4 md:p-6 lg:p-8 space-y-6">
      
      {/* Top Banner Header */}
      <header className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 border-b border-white/5 pb-5">
        <div>
          <div className="flex items-center gap-2.5">
            <span className="w-2.5 h-2.5 rounded-full bg-neon animate-pulse neon-glow" />
            <h1 className="text-xl md:text-2xl font-bold font-mono tracking-wider uppercase text-white">
              CXR-AIM Platform
            </h1>
            <span className="text-[10px] px-2 py-0.5 border border-white/10 rounded-full font-mono bg-white/5 text-gray-400">
              v1.0.0
            </span>
          </div>
          <p className="text-xs text-gray-500 font-mono mt-1">
            Tactical Live-Fire Target Acquisition & Scoring Analytics
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-4">
          <ConnectionStatus />
          
          {/* User Role Switcher */}
          <div className="flex items-center bg-[#0d1527] border border-white/10 rounded-lg p-0.5 gap-1 font-mono">
            <button
              onClick={() => setUserRole("trainer")}
              className={`px-3 py-1.5 rounded-md text-xs font-bold transition-all duration-150 ${
                userRole === "trainer"
                  ? "bg-gradient-to-r from-blue-600 to-indigo-600 text-white shadow-md border border-blue-500/20"
                  : "text-gray-400 hover:text-white hover:bg-white/5 border border-transparent"
              }`}
            >
              TRAINER
            </button>
            <button
              onClick={() => setUserRole("trainee")}
              className={`px-3 py-1.5 rounded-md text-xs font-bold transition-all duration-150 ${
                userRole === "trainee"
                  ? "bg-gradient-to-r from-emerald-600 to-teal-600 text-white shadow-md border border-emerald-500/20"
                  : "text-gray-400 hover:text-white hover:bg-white/5 border border-transparent"
              }`}
            >
              TRAINEE
            </button>
          </div>
          
          <button
            onClick={() => setShowCreateTargetModal(true)}
            className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white text-xs font-mono font-bold rounded-lg border border-blue-500/20 shadow-lg hover:shadow-indigo-500/10 active:scale-95 transition-all duration-150"
          >
            <PlusCircle className="w-4 h-4" />
            <span>CREATE TARGET</span>
          </button>
          
          <button
            onClick={() => setShowCreateModal(true)}
            className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white text-xs font-mono font-bold rounded-lg border border-emerald-500/20 shadow-lg hover:shadow-emerald-500/10 active:scale-95 transition-all duration-150"
          >
            <PlusCircle className="w-4 h-4" />
            <span>NEW SESSION</span>
          </button>
        </div>
      </header>

      {/* Main Grid dashboard layout */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-6 items-stretch">
        
        {/* Left Column: Visualizer & Calibration Control */}
        <div className="xl:col-span-5 flex flex-col gap-6">
          <LiveTargetView />

          {/* Session Controller Panel (Camera Streaming & Calibration) */}
          <div className="glass-panel p-6">
            <div className="flex items-center gap-2 mb-4">
              <Play className="w-5 h-5 text-neon" />
              <h3 className="text-sm font-bold font-mono tracking-wider uppercase">Live Camera Integration</h3>
            </div>

            {!activeSession ? (
              <div className="flex items-center gap-3 p-4 border border-white/5 bg-white/2 rounded-lg text-xs font-mono text-amber-500">
                <AlertTriangle className="w-5 h-5 flex-shrink-0" />
                <span>No active shooting session. Click "NEW SESSION" above to begin.</span>
              </div>
            ) : (
              <div className="space-y-4">
                
                {/* Camera Source Selector */}
                <div className="flex gap-2 items-end">
                  <div className="flex-1 space-y-1">
                    <label className="text-[9px] font-mono uppercase text-gray-500">Camera Source (Index or IP URL)</label>
                    <input
                      type="text"
                      placeholder="e.g. 0 (webcam) or http://192.168.1.100:8080/video"
                      value={cameraSource}
                      onChange={(e) => setCameraSource(e.target.value)}
                      disabled={isCameraActive}
                      className="w-full bg-[#030712] border border-white/10 rounded px-2.5 py-1.5 text-xs font-mono text-white focus:outline-none focus:border-neon transition"
                    />
                  </div>
                  <button
                    onClick={toggleCamera}
                    className={`px-4 py-1.5 rounded text-xs font-mono font-bold transition-all duration-150 ${
                      isCameraActive
                        ? "bg-red-600 hover:bg-red-500 text-white"
                        : "bg-white/5 border border-white/10 hover:bg-white/10 text-gray-300 hover:text-white"
                    }`}
                  >
                    {isCameraActive ? "DISCONNECT" : "CONNECT"}
                  </button>
                </div>

                {/* Video Preview Feed & Zoom Slider */}
                {isCameraActive && (
                  <div className="space-y-3">
                    <div className="relative border border-white/10 rounded-lg overflow-hidden bg-black flex items-center justify-center aspect-video">
                      <img
                        src="http://localhost:8000/api/v1/camera/stream"
                        alt="Camera Video Stream Feed"
                        className="w-full h-full object-cover"
                      />
                      <div className="absolute top-2 right-2 px-2 py-0.5 bg-black/60 rounded text-[9px] font-mono text-neon border border-neon/20 animate-pulse">
                        LIVE FEED
                      </div>
                    </div>

                    {/* Digital Zoom Slider */}
                    <div className="space-y-1.5 p-3 bg-white/2 border border-white/5 rounded-lg">
                      <div className="flex justify-between text-[10px] font-mono text-gray-400">
                        <span>DIGITAL FEED ZOOM:</span>
                        <span className="text-neon font-bold">{zoomFactor.toFixed(1)}x</span>
                      </div>
                      <input
                        type="range"
                        min="1.0"
                        max="3.0"
                        step="0.1"
                        value={zoomFactor}
                        onChange={handleZoomChange}
                        className="w-full h-1.5 bg-white/10 rounded-lg appearance-none cursor-pointer accent-neon focus:outline-none"
                        style={{
                          accentColor: "#10b981"
                        }}
                      />
                    </div>
                  </div>
                )}

                {/* Calibration & Monitoring Actions */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-2">
                  
                  {/* Calibrate target on wall */}
                  <button
                    onClick={handleCalibrate}
                    disabled={!isCameraActive || isCalibrating}
                    className={`flex flex-col justify-between items-start text-left p-4 rounded-lg border transition min-h-[8.5rem] pb-3 ${
                      !isCameraActive
                        ? "opacity-45 border-white/5 bg-white/2 cursor-not-allowed"
                        : "border-white/10 bg-white/2 hover:bg-white/3 text-white"
                    }`}
                  >
                    <div className="mb-2">
                      <h4 className="text-xs font-bold font-mono uppercase tracking-wider mb-1">
                        1. Calibrate Target
                      </h4>
                      <p className="text-[9px] text-gray-500 leading-tight">
                        Place target sheet on the wall, then auto-detect corners and lock perspective homography mapping.
                      </p>
                    </div>
                    <span className="text-[10px] font-mono font-bold px-2 py-0.5 bg-white/5 border border-white/10 rounded mt-2">
                      {isCalibrating ? "ANALYZING..." : "CALIBRATE"}
                    </span>
                  </button>

                  {/* Capture Before Fire (Reference image) */}
                  <button
                    onClick={handleBeforeFire}
                    disabled={!isCameraActive || isCapturingBeforeFire}
                    className={`flex flex-col justify-between items-start text-left p-4 rounded-lg border transition min-h-[8.5rem] pb-3 ${
                      !isCameraActive
                        ? "opacity-45 border-white/5 bg-white/2 cursor-not-allowed"
                        : "border-blue-500/20 bg-blue-500/5 hover:bg-blue-500/10 text-white"
                    }`}
                  >
                    <div className="mb-2">
                      <h4 className="text-xs font-bold font-mono uppercase tracking-wider mb-1 text-blue-400">
                        2. Before Fire
                      </h4>
                      <p className="text-[9px] text-gray-500 leading-tight">
                        Click before firing shots. Takes a pristine snapshot to serve as the reference for differencing.
                      </p>
                    </div>
                    <span className="text-[10px] font-mono font-bold px-3 py-1 bg-blue-600 hover:bg-blue-500 text-white rounded mt-2">
                      {isCapturingBeforeFire ? "CAPTURING..." : "📷 BEFORE FIRE"}
                    </span>
                  </button>
 
                  {/* Fired snapshot trigger */}
                  <button
                    onClick={handleFire}
                    disabled={!isCameraActive || !baselineUrl || isDetecting}
                    className={`flex flex-col justify-between items-start text-left p-4 rounded-lg border transition min-h-[8.5rem] pb-3 ${
                      !isCameraActive || !baselineUrl
                        ? "opacity-45 border-white/5 bg-white/2 cursor-not-allowed"
                        : "border-red-500/20 bg-red-500/5 hover:bg-red-500/10 text-white"
                    }`}
                  >
                    <div className="mb-2">
                      <h4 className="text-xs font-bold font-mono uppercase tracking-wider mb-1 text-red-400">
                        3. Trigger Fired
                      </h4>
                      <p className="text-[9px] text-gray-500 leading-tight">
                        Click after firing a shot. Snaps the live camera feed and compares it against the "Before Fire" baseline.
                      </p>
                    </div>
                    <span className="text-[10px] font-mono font-bold px-3 py-1 bg-red-600 hover:bg-red-500 text-white rounded mt-2">
                      {isDetecting ? "ANALYZING IMPACT..." : "🔥 TRIGGER FIRED"}
                    </span>
                  </button>
 
                </div>

                {/* Manual file upload fallback */}
                <div className="border-t border-white/5 pt-3 mt-3 flex flex-wrap justify-between items-center gap-2 text-[10px] font-mono text-gray-500">
                  <span className="whitespace-nowrap">MANUAL FILE UPLOADS:</span>
                  <div className="flex items-center gap-2 flex-wrap">
                    <label className="text-neon hover:underline cursor-pointer whitespace-nowrap">
                      UPLOAD BASE
                      <input
                        type="file"
                        accept="image/*"
                        onChange={handleBaselineUpload}
                        className="hidden"
                      />
                    </label>
                    <span>|</span>
                    <label className={`text-neon hover:underline cursor-pointer whitespace-nowrap ${!baselineUrl ? "pointer-events-none opacity-40" : ""}`}>
                      ANALYZE FILE
                      <input
                        type="file"
                        accept="image/*"
                        onChange={handleDetectUpload}
                        className="hidden"
                        disabled={!baselineUrl}
                      />
                    </label>
                  </div>
                </div>

              </div>
            )}
          </div>
        </div>

        {/* Right Column: Key Overview & Tables */}
        <div className="xl:col-span-7 flex flex-col gap-6">
          <OverviewCards />

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 flex-1 items-stretch">
            <ShotTable />
            <StatsPanel />
          </div>

          {/* Telemetry Log Console */}
          <div className="glass-panel p-5">
            <div className="flex flex-wrap items-center justify-between gap-2 mb-3 border-b border-white/5 pb-2">
              <div className="flex items-center gap-2 text-gray-400">
                <Terminal className="w-4 h-4 text-neon" />
                <span className="text-xs font-mono tracking-wider uppercase font-bold text-white">System Console Log</span>
              </div>
              <span className="text-[9px] font-mono text-gray-500 uppercase whitespace-nowrap">SYS_LOGS // STDOUT</span>
            </div>
            
            <div className="h-24 overflow-y-auto font-mono text-[10px] text-emerald-500/80 space-y-1.5 scrollbar-thin">
              {logs.length === 0 ? (
                <p className="text-gray-600">Console idle. Awaiting user interaction...</p>
              ) : (
                logs.map((log, index) => (
                  <p key={index} className="leading-relaxed whitespace-pre-wrap">
                    {log}
                  </p>
                ))
              )}
            </div>
          </div>

        </div>

      </div>

      {/* New Session Modal Overlay */}
       {showCreateModal && (
        <div className="fixed inset-0 flex items-center justify-center bg-black/70 backdrop-blur-md z-50 p-4">
          <div className="glass-panel max-w-md w-full max-h-[90vh] overflow-y-auto p-6 border-white/10 relative scrollbar-thin">
            <h3 className="text-base font-bold font-mono tracking-wider uppercase mb-4 text-white">
              Initialize New Shooting Session
            </h3>
            
            <form onSubmit={handleCreateSession} className="space-y-4">
              <div className="space-y-1">
                <label className="text-[10px] font-mono uppercase text-gray-400">Session Name</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Morning Rifle Cal.22"
                  value={newSessionName}
                  onChange={(e) => setNewSessionName(e.target.value)}
                  className="w-full bg-[#030712] border border-white/10 rounded px-3 py-2 text-xs font-mono text-white focus:outline-none focus:border-neon transition"
                />
              </div>

              <div className="space-y-1">
                <label className="text-[10px] font-mono uppercase text-gray-400">Description (Optional)</label>
                <textarea
                  placeholder="Practice details, distance, windage etc."
                  value={newSessionDesc}
                  onChange={(e) => setNewSessionDesc(e.target.value)}
                  rows={2}
                  className="w-full bg-[#030712] border border-white/10 rounded px-3 py-2 text-xs font-mono text-white focus:outline-none focus:border-neon transition resize-none"
                />
              </div>

              <div className="space-y-1">
                <label className="text-[10px] font-mono uppercase text-gray-400">Target Type</label>
                <select
                  value={newSessionTargetType}
                  onChange={(e) => setNewSessionTargetType(e.target.value)}
                  className="w-full bg-[#030712] border border-white/10 rounded px-3 py-2 text-xs font-mono text-white focus:outline-none focus:border-neon transition"
                >
                  {targetDefinitions.map((target) => (
                    <option key={target.id} value={target.id}>
                      {target.name} ({target.width_mm}x{target.height_mm} mm)
                    </option>
                  ))}
                  {targetDefinitions.length === 0 && (
                    <>
                      <option value="figure_eleven">Figure Eleven (580x885 mm)</option>
                      <option value="issf_10m_air_rifle">ISSF 10m Air Rifle (80x80 mm)</option>
                    </>
                  )}
                </select>
              </div>

              {/* Live Target Template Preview */}
              <div className="space-y-1">
                <label className="text-[10px] font-mono uppercase text-gray-400">Target Preview</label>
                <TargetPreview 
                  target={
                    targetDefinitions.find(t => t.id === newSessionTargetType) || 
                    (newSessionTargetType === "figure_eleven" ? {
                      name: "Figure Eleven",
                      width_mm: 580.0,
                      height_mm: 885.0,
                      bullseyes: [],
                      scoring_regions: [
                        {
                          id: 1,
                          name: "Outer Torso",
                          value: 4,
                          x_min_mm: 40.0,
                          y_min_mm: 42.5,
                          x_max_mm: 540.0,
                          y_max_mm: 842.5
                        },
                        {
                          id: 2,
                          name: "Inner Center",
                          value: 5,
                          x_min_mm: 190.0,
                          y_min_mm: 292.5,
                          x_max_mm: 390.0,
                          y_max_mm: 592.5
                        }
                      ],
                      bullet_compatibility: ["5.56", "7.62", "9.0"],
                      decimal_scoring_supported: false
                    } : newSessionTargetType === "issf_10m_air_rifle" ? {
                      name: "ISSF 10m Air Rifle",
                      width_mm: 80.0,
                      height_mm: 80.0,
                      bullseyes: [{
                        id: 1,
                        center_x_mm: 40,
                        center_y_mm: 40,
                        scoring_rule: "inward",
                        rings: [
                          { value: 10, outer_radius_mm: 0.25 },
                          { value: 9, outer_radius_mm: 2.75 },
                          { value: 8, outer_radius_mm: 5.25 },
                          { value: 7, outer_radius_mm: 7.75 },
                          { value: 6, outer_radius_mm: 10.25 },
                          { value: 5, outer_radius_mm: 12.75 },
                          { value: 4, outer_radius_mm: 15.25 },
                          { value: 3, outer_radius_mm: 17.75 },
                          { value: 2, outer_radius_mm: 20.25 },
                          { value: 1, outer_radius_mm: 22.75 }
                        ]
                      }],
                      bullet_compatibility: ["5.56", "7.62", "9.0"],
                      decimal_scoring_supported: true
                    } : null)
                  }
                  className="h-32 w-full"
                />
              </div>

              <div className="space-y-1">
                <label className="text-[10px] font-mono uppercase text-gray-400">Bullet Caliber (mm)</label>
                <select
                  value={newSessionBulletCaliber}
                  onChange={(e) => setNewSessionBulletCaliber(parseFloat(e.target.value))}
                  className="w-full bg-[#030712] border border-white/10 rounded px-3 py-2 text-xs font-mono text-white focus:outline-none focus:border-neon transition"
                >
                  <option value="5.56">5.56 mm (.223)</option>
                  <option value="7.62">7.62 mm (.308)</option>
                  <option value="9.0">9.0 mm (9mm)</option>
                </select>
              </div>

              <div className="flex justify-end gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  className="px-4 py-2 border border-white/10 hover:bg-white/5 rounded text-xs font-mono text-gray-400 hover:text-white transition"
                >
                  CANCEL
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 rounded text-xs font-mono text-white font-bold transition"
                >
                  CREATE SESSION
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* New Target Modal Overlay */}
      {showCreateTargetModal && (() => {
        const canvasDisplayWidth = 320;
        const aspect = customTargetWidth > 0 ? (customTargetHeight / customTargetWidth) : 1.0;
        let finalWidth = canvasDisplayWidth;
        let finalHeight = canvasDisplayWidth * aspect;
        if (finalHeight > 420) {
          finalHeight = 420;
          finalWidth = aspect > 0 ? (finalHeight / aspect) : canvasDisplayWidth;
        }

        return (
          <div className="fixed inset-0 flex items-center justify-center bg-black/75 backdrop-blur-md z-50 p-4">
            <div className="glass-panel max-w-5xl w-full max-h-[95vh] overflow-y-auto p-6 border-white/10 relative scrollbar-thin">
              <h3 className="text-base font-bold font-mono tracking-wider uppercase mb-4 text-white">
                Target Designer Studio
              </h3>
              
              <form onSubmit={handleCreateTarget} className="space-y-6">
                <div className="grid grid-cols-1 md:grid-cols-12 gap-6 items-start">
                  {/* Left Column: Configuration Settings */}
                  <div className="md:col-span-7 space-y-4">
                    <div className="space-y-1">
                      <label className="text-[10px] font-mono uppercase text-gray-400">Target Name</label>
                      <input
                        type="text"
                        required
                        placeholder="e.g. Tactical Pistol 25m"
                        value={customTargetName}
                        onChange={(e) => setCustomTargetName(e.target.value)}
                        className="w-full bg-[#030712] border border-white/10 rounded px-3 py-2 text-xs font-mono text-white focus:outline-none focus:border-neon transition"
                      />
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                      <div className="space-y-1">
                        <label className="text-[10px] font-mono uppercase text-gray-400">Width (mm)</label>
                        <input
                          type="number"
                          step="0.1"
                          min="10"
                          required
                          value={customTargetWidth}
                          onChange={(e) => setCustomTargetWidth(parseFloat(e.target.value) || 0)}
                          className="w-full bg-[#030712] border border-white/10 rounded px-3 py-2 text-xs font-mono text-white focus:outline-none focus:border-neon transition"
                        />
                      </div>
                      <div className="space-y-1">
                        <label className="text-[10px] font-mono uppercase text-gray-400">Height (mm)</label>
                        <input
                          type="number"
                          step="0.1"
                          min="10"
                          required
                          value={customTargetHeight}
                          onChange={(e) => setCustomTargetHeight(parseFloat(e.target.value) || 0)}
                          className="w-full bg-[#030712] border border-white/10 rounded px-3 py-2 text-xs font-mono text-white focus:outline-none focus:border-neon transition"
                        />
                      </div>
                    </div>

                    {/* AprilTag Physical Configurations */}
                    <div className="space-y-1">
                      <label className="text-[10px] font-mono uppercase text-gray-400">AprilTag Real Size (mm)</label>
                      <input
                        type="number"
                        step="0.1"
                        min="1"
                        required
                        value={customTargetTagSizeMm}
                        onChange={(e) => setCustomTargetTagSizeMm(parseFloat(e.target.value) || 50.0)}
                        className="w-full bg-[#030712] border border-white/10 rounded px-3 py-2 text-xs font-mono text-white focus:outline-none focus:border-neon transition"
                      />
                    </div>

                    {/* Target Image Preview Uploader */}
                    <div className="space-y-1.5 border-t border-white/5 pt-3">
                      <label className="text-[10px] font-mono uppercase text-gray-400 block">Upload Soft Copy Image (Target Preview)</label>
                      <div className="flex items-center gap-3">
                        <input
                          type="file"
                          accept="image/*"
                          onChange={handlePreviewImageChange}
                          className="text-xs font-mono text-gray-500 file:mr-3 file:py-1 file:px-3 file:rounded file:border-0 file:text-xs file:font-mono file:bg-white/5 file:text-gray-300 hover:file:bg-white/10 file:cursor-pointer"
                        />
                      </div>
                    </div>

                    {/* Zone Value Editor List */}
                    {customTargetType === "circular" ? (
                      <div className="space-y-2 border-t border-white/5 pt-3">
                        <label className="text-[10px] font-mono uppercase text-gray-400 block">Circular Rings list (Sorted by radius)</label>
                        <div className="max-h-[180px] overflow-y-auto space-y-2 pr-1 scrollbar-thin">
                          {customTargetRings.map((ring, idx) => (
                            <div key={idx} className="flex items-center gap-2 bg-white/2 p-2 rounded border border-white/2">
                              <span className="text-[10px] font-mono text-gray-500 min-w-[50px] font-bold">Ring {idx + 1}</span>
                              <div className="flex items-center gap-1.5 flex-1">
                                <label className="text-[8px] font-mono text-gray-500 uppercase">Val:</label>
                                <input
                                  type="number"
                                  min="0"
                                  value={ring.value}
                                  onChange={(e) => handleRingChange(idx, "value", parseInt(e.target.value) || 0)}
                                  className="w-12 bg-[#030712] border border-white/10 rounded px-1.5 py-0.5 text-center text-xs font-mono text-white focus:outline-none"
                                />
                              </div>
                              <div className="flex items-center gap-1.5 flex-1">
                                <label className="text-[8px] font-mono text-gray-500 uppercase">Rad (mm):</label>
                                <input
                                  type="number"
                                  step="0.05"
                                  min="0.1"
                                  value={ring.outer_radius_mm}
                                  onChange={(e) => handleRingChange(idx, "outer_radius_mm", parseFloat(e.target.value) || 0)}
                                  className="w-18 bg-[#030712] border border-white/10 rounded px-1.5 py-0.5 text-center text-xs font-mono text-white focus:outline-none"
                                />
                              </div>
                              <button
                                type="button"
                                onClick={() => handleRemoveRing(idx)}
                                className="p-1 text-red-500 hover:text-red-400 hover:bg-red-500/10 rounded"
                                disabled={customTargetRings.length <= 1}
                              >
                                <Trash className="w-3.5 h-3.5" />
                              </button>
                            </div>
                          ))}
                          {customTargetRings.length === 0 && (
                            <p className="text-[10px] font-mono text-gray-500 text-center py-2">No rings added yet. Draw them on the canvas.</p>
                          )}
                        </div>
                      </div>
                    ) : (
                      <div className="space-y-2 border-t border-white/5 pt-3">
                        <label className="text-[10px] font-mono uppercase text-gray-400 block">Rectangular Zones list</label>
                        <div className="max-h-[180px] overflow-y-auto space-y-2 pr-1 scrollbar-thin">
                          {customTargetRegions.map((region) => (
                            <div key={region.id} className="flex items-center gap-2 bg-white/2 p-2 rounded border border-white/2">
                              <input
                                type="text"
                                value={region.name}
                                onChange={(e) => handleRegionChange(region.id, "name", e.target.value)}
                                className="bg-[#030712] border border-white/10 rounded px-1.5 py-0.5 text-xs font-mono text-white focus:outline-none w-24"
                              />
                              <div className="flex items-center gap-1.5 flex-1">
                                <label className="text-[8px] font-mono text-gray-500 uppercase">Val:</label>
                                <input
                                  type="number"
                                  value={region.value}
                                  onChange={(e) => handleRegionChange(region.id, "value", parseInt(e.target.value) || 0)}
                                  className="w-10 bg-[#030712] border border-white/10 rounded px-1 py-0.5 text-center text-xs font-mono text-white focus:outline-none"
                                />
                              </div>
                              <span className="text-[8px] font-mono text-gray-500">
                                {region.x_min_mm},{region.y_min_mm} to {region.x_max_mm},{region.y_max_mm} mm
                              </span>
                              <button
                                type="button"
                                onClick={() => handleRemoveRegion(region.id)}
                                className="p-1 text-red-500 hover:text-red-400 hover:bg-red-500/10 rounded"
                              >
                                <Trash className="w-3.5 h-3.5" />
                              </button>
                            </div>
                          ))}
                          {customTargetRegions.length === 0 && (
                            <p className="text-[10px] font-mono text-gray-500 text-center py-2">No zones added yet. Click and drag on the canvas to draw.</p>
                          )}
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Right Column: Interactive Canvas Editor */}
                  <div className="md:col-span-5 flex flex-col items-center justify-start bg-white/2 border border-white/5 rounded-lg p-4 space-y-4 min-h-[480px]">
                    <div className="text-center w-full">
                      <h4 className="text-xs font-bold font-mono text-neon uppercase tracking-wider">Canvas Zone Designer</h4>
                      
                      {/* Zone Drawing Mode Selector */}
                      <div className="flex gap-2 justify-center mt-2 mb-1">
                        <button
                          type="button"
                          onClick={() => setCustomTargetType("rectangular")}
                          className={`px-3 py-1 text-[9px] font-mono font-bold rounded transition-all ${
                            customTargetType === "rectangular"
                              ? "bg-indigo-600 text-white"
                              : "bg-white/5 text-gray-400 hover:text-white border border-white/10"
                          }`}
                        >
                          Rectangular Zones
                        </button>
                        <button
                          type="button"
                          onClick={() => setCustomTargetType("circular")}
                          className={`px-3 py-1 text-[9px] font-mono font-bold rounded transition-all ${
                            customTargetType === "circular"
                              ? "bg-indigo-600 text-white"
                              : "bg-white/5 text-gray-400 hover:text-white border border-white/10"
                          }`}
                        >
                          Circular Rings
                        </button>
                      </div>

                      <p className="text-[9px] text-gray-400 mt-1">
                        {customTargetType === "circular" 
                          ? "Drag red crosshair to relocate target center. Drag outward from center to define ring boundaries."
                          : "Draw rectangular score zones by clicking and dragging directly on the image below."}
                      </p>
                    </div>

                    {/* Interactive Drawing Box */}
                    <div 
                      className="relative border border-white/10 bg-black/45 rounded overflow-hidden cursor-crosshair flex items-center justify-center transition-all shadow-inner"
                      style={{ width: finalWidth, height: finalHeight }}
                    >
                      {customTargetPreviewBase64 ? (
                        <img 
                          src={customTargetPreviewBase64} 
                          className="absolute inset-0 w-full h-full object-contain pointer-events-none select-none" 
                          alt="Target Soft Copy" 
                        />
                      ) : (
                        <div className="absolute inset-0 bg-white pointer-events-none border border-gray-300 flex items-center justify-center">
                          <span className="text-[10px] font-mono text-gray-400">SOFT COPY PREVIEW SHEET</span>
                        </div>
                      )}

                      <svg
                        className="absolute inset-0 w-full h-full select-none"
                        onMouseDown={(e) => {
                          const rect = e.currentTarget.getBoundingClientRect();
                          const x = e.clientX - rect.left;
                          const y = e.clientY - rect.top;
                          const x_mm = (x / finalWidth) * customTargetWidth;
                          const y_mm = (y / finalHeight) * customTargetHeight;

                          if (customTargetType === "circular") {
                            const cx_px = (circularCenterMm.x / customTargetWidth) * finalWidth;
                            const cy_px = (circularCenterMm.y / customTargetHeight) * finalHeight;
                            const dist = Math.sqrt((x - cx_px)**2 + (y - cy_px)**2);
                            if (dist < 15) {
                              setIsDraggingCenter(true);
                              return;
                            }
                            // Start drawing ring
                            setDragStart({ x: circularCenterMm.x, y: circularCenterMm.y });
                            setDragCurrent({ x: x_mm, y: y_mm });
                          } else {
                            // Start drawing rectangular zone
                            setDragStart({ x: x_mm, y: y_mm });
                            setDragCurrent({ x: x_mm, y: y_mm });
                          }
                        }}
                        onMouseMove={(e) => {
                          const rect = e.currentTarget.getBoundingClientRect();
                          const x = e.clientX - rect.left;
                          const y = e.clientY - rect.top;
                          const x_mm = (x / finalWidth) * customTargetWidth;
                          const y_mm = (y / finalHeight) * customTargetHeight;
                          
                          setHoverMm({ x: parseFloat(x_mm.toFixed(1)), y: parseFloat(y_mm.toFixed(1)) });

                          if (isDraggingCenter) {
                            setCircularCenterMm({
                              x: Math.max(0, Math.min(customTargetWidth, parseFloat(x_mm.toFixed(1)))),
                              y: Math.max(0, Math.min(customTargetHeight, parseFloat(y_mm.toFixed(1))))
                            });
                          } else if (dragStart) {
                            setDragCurrent({ x: x_mm, y: y_mm });
                          }
                        }}
                        onMouseUp={() => {
                          if (isDraggingCenter) {
                            setIsDraggingCenter(false);
                          } else if (dragStart && dragCurrent) {
                            if (customTargetType === "rectangular") {
                              const x_min = Math.min(dragStart.x, dragCurrent.x);
                              const x_max = Math.max(dragStart.x, dragCurrent.x);
                              const y_min = Math.min(dragStart.y, dragCurrent.y);
                              const y_max = Math.max(dragStart.y, dragCurrent.y);
                              
                              if (x_max - x_min > 5 && y_max - y_min > 5) {
                                const nextId = customTargetRegions.length > 0 ? Math.max(...customTargetRegions.map(r => r.id)) + 1 : 1;
                                setCustomTargetRegions([
                                  ...customTargetRegions,
                                  {
                                    id: nextId,
                                    name: `Zone ${nextId}`,
                                    value: 1,
                                    x_min_mm: parseFloat(x_min.toFixed(1)),
                                    y_min_mm: parseFloat(y_min.toFixed(1)),
                                    x_max_mm: parseFloat(x_max.toFixed(1)),
                                    y_max_mm: parseFloat(y_max.toFixed(1))
                                  }
                                ]);
                                setSelectedZoneId(nextId);
                              }
                            } else if (customTargetType === "circular") {
                              const dist_mm = Math.sqrt((dragCurrent.x - circularCenterMm.x)**2 + (dragCurrent.y - circularCenterMm.y)**2);
                              if (dist_mm > 2) {
                                const nextVal = customTargetRings.length > 0 ? Math.min(...customTargetRings.map(r => r.value)) - 1 : 10;
                                const updated = [...customTargetRings, { value: nextVal, outer_radius_mm: parseFloat(dist_mm.toFixed(2)) }];
                                updated.sort((a, b) => b.outer_radius_mm - a.outer_radius_mm);
                                setCustomTargetRings(updated);
                              }
                            }
                          }
                          setDragStart(null);
                          setDragCurrent(null);
                        }}
                        onMouseLeave={() => {
                          setHoverMm(null);
                          setIsDraggingCenter(false);
                          setDragStart(null);
                          setDragCurrent(null);
                        }}
                      >
                        {/* Render Circular rings */}
                        {customTargetType === "circular" && (
                          <>
                            {customTargetRings.map((ring, idx) => {
                              const r_px = (ring.outer_radius_mm / customTargetWidth) * finalWidth;
                              const cx_px = (circularCenterMm.x / customTargetWidth) * finalWidth;
                              const cy_px = (circularCenterMm.y / customTargetHeight) * finalHeight;
                              return (
                                <circle
                                  key={idx}
                                  cx={cx_px}
                                  cy={cy_px}
                                  r={r_px}
                                  fill="none"
                                  stroke={selectedRingIdx === idx ? "#10b981" : "rgba(16, 185, 129, 0.4)"}
                                  strokeWidth={selectedRingIdx === idx ? 2.5 : 1.5}
                                  className="transition-all cursor-pointer"
                                  onClick={() => setSelectedRingIdx(idx)}
                                />
                              );
                            })}
                            
                            {/* Center Pin Indicator (draggable) */}
                            <g className="cursor-move">
                              <circle
                                cx={(circularCenterMm.x / customTargetWidth) * finalWidth}
                                cy={(circularCenterMm.y / customTargetHeight) * finalHeight}
                                r={6}
                                fill="#ef4444"
                                fillOpacity={0.7}
                              />
                              <line
                                x1={(circularCenterMm.x / customTargetWidth) * finalWidth - 15}
                                y1={(circularCenterMm.y / customTargetHeight) * finalHeight}
                                x2={(circularCenterMm.x / customTargetWidth) * finalWidth + 15}
                                y2={(circularCenterMm.y / customTargetHeight) * finalHeight}
                                stroke="#ef4444"
                                strokeWidth={2}
                              />
                              <line
                                x1={(circularCenterMm.x / customTargetWidth) * finalWidth}
                                y1={(circularCenterMm.y / customTargetHeight) * finalHeight - 15}
                                x2={(circularCenterMm.x / customTargetWidth) * finalWidth}
                                y2={(circularCenterMm.y / customTargetHeight) * finalHeight + 15}
                                stroke="#ef4444"
                                strokeWidth={2}
                              />
                            </g>

                            {/* Circular drawing preview */}
                            {dragStart && dragCurrent && (
                              <circle
                                cx={(circularCenterMm.x / customTargetWidth) * finalWidth}
                                cy={(circularCenterMm.y / customTargetHeight) * finalHeight}
                                r={(Math.sqrt((dragCurrent.x - circularCenterMm.x)**2 + (dragCurrent.y - circularCenterMm.y)**2) / customTargetWidth) * finalWidth}
                                fill="none"
                                stroke="#10b981"
                                strokeWidth={2}
                                strokeDasharray="4,4"
                              />
                            )}
                          </>
                        )}

                        {/* Render Rectangular zones */}
                        {customTargetType === "rectangular" && (
                          <>
                            {customTargetRegions.map((region) => {
                              const x_px = (region.x_min_mm / customTargetWidth) * finalWidth;
                              const y_px = (region.y_min_mm / customTargetHeight) * finalHeight;
                              const w_px = ((region.x_max_mm - region.x_min_mm) / customTargetWidth) * finalWidth;
                              const h_px = ((region.y_max_mm - region.y_min_mm) / customTargetHeight) * finalHeight;
                              const isSelected = selectedZoneId === region.id;
                              return (
                                <g key={region.id}>
                                  <rect
                                    x={x_px}
                                    y={y_px}
                                    width={w_px}
                                    height={h_px}
                                    fill={isSelected ? "rgba(16, 185, 129, 0.2)" : "rgba(99, 102, 241, 0.12)"}
                                    stroke={isSelected ? "#10b981" : "#6366f1"}
                                    strokeWidth={isSelected ? 2.5 : 1.5}
                                    className="transition-all cursor-pointer"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setSelectedZoneId(region.id);
                                    }}
                                  />
                                  <text
                                    x={x_px + w_px / 2}
                                    y={y_px + h_px / 2}
                                    fill={isSelected ? "#10b981" : "#ffffff"}
                                    fontSize={10}
                                    fontWeight="bold"
                                    textAnchor="middle"
                                    dominantBaseline="middle"
                                    className="pointer-events-none drop-shadow"
                                  >
                                    {region.name} ({region.value} pts)
                                  </text>
                                </g>
                              );
                            })}

                            {/* Rectangular drawing preview */}
                            {dragStart && dragCurrent && (
                              <rect
                                x={(Math.min(dragStart.x, dragCurrent.x) / customTargetWidth) * finalWidth}
                                y={(Math.min(dragStart.y, dragCurrent.y) / customTargetHeight) * finalHeight}
                                width={(Math.abs(dragCurrent.x - dragStart.x) / customTargetWidth) * finalWidth}
                                height={(Math.abs(dragCurrent.y - dragStart.y) / customTargetHeight) * finalHeight}
                                fill="rgba(16, 185, 129, 0.15)"
                                stroke="#10b981"
                                strokeWidth={2}
                                strokeDasharray="4,4"
                              />
                            )}
                          </>
                        )}
                      </svg>
                    </div>

                    {/* Coordinate HUD */}
                    <div className="w-full flex justify-between items-center text-[10px] text-gray-400 font-mono">
                      <span>HUD: {hoverMm ? `${hoverMm.x} mm, ${hoverMm.y} mm` : "hover to display position"}</span>
                      <span>SIZE: {customTargetWidth}x{customTargetHeight} mm</span>
                    </div>

                    <div className="flex gap-2 w-full pt-1">
                      <button
                        type="button"
                        onClick={() => {
                          if (customTargetType === "circular") {
                            setCustomTargetRings([]);
                          } else {
                            setCustomTargetRegions([]);
                          }
                        }}
                        className="flex-1 py-1 rounded bg-red-950/20 border border-red-500/20 hover:bg-red-900/20 text-red-400 hover:text-red-300 text-xs font-mono transition"
                      >
                        CLEAR ALL ZONES
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          if (customTargetType === "circular") {
                            setCustomTargetRings([
                              { value: 10, outer_radius_mm: 2.5 },
                              { value: 9, outer_radius_mm: 5.0 },
                              { value: 8, outer_radius_mm: 7.5 },
                              { value: 7, outer_radius_mm: 10.0 },
                              { value: 6, outer_radius_mm: 12.5 },
                              { value: 5, outer_radius_mm: 15.0 },
                              { value: 4, outer_radius_mm: 17.5 },
                              { value: 3, outer_radius_mm: 20.0 },
                              { value: 2, outer_radius_mm: 22.5 },
                              { value: 1, outer_radius_mm: 25.0 }
                            ]);
                            setCircularCenterMm({ x: customTargetWidth/2, y: customTargetHeight/2 });
                          } else {
                            setCustomTargetRegions([
                              { id: 1, name: "Outer Torso", value: 4, x_min_mm: 40.0, y_min_mm: 42.5, x_max_mm: 540.0, y_max_mm: 842.5 },
                              { id: 2, name: "Inner Center", value: 5, x_min_mm: 190.0, y_min_mm: 292.5, x_max_mm: 390.0, y_max_mm: 592.5 }
                            ]);
                          }
                        }}
                        className="flex-1 py-1 rounded bg-white/5 border border-white/10 hover:bg-white/10 text-gray-300 text-xs font-mono transition"
                      >
                        RESET TEMPLATE
                      </button>
                    </div>
                  </div>
                </div>

                <div className="flex justify-end gap-3 pt-3 border-t border-white/5">
                  <button
                    type="button"
                    onClick={() => setShowCreateTargetModal(false)}
                    className="px-4 py-2 border border-white/10 hover:bg-white/5 rounded text-xs font-mono text-gray-400 hover:text-white transition"
                  >
                    CANCEL
                  </button>
                  <button
                    type="submit"
                    className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 rounded text-xs font-mono text-white font-bold transition"
                  >
                    SAVE TARGET
                  </button>
                </div>
              </form>
            </div>
          </div>
        );
      })()}

    </main>
  );
}
