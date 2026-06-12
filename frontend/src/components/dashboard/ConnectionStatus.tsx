"use client";

import React from "react";
import { useStore } from "@/store/useStore";
import { Activity, Camera, Cpu } from "lucide-react";

export default function ConnectionStatus() {
  const { wsStatus, activeSession, statistics } = useStore();

  const getStatusColor = (status: string) => {
    switch (status) {
      case "connected":
        return "text-emerald-400 bg-emerald-400/10 border-emerald-500/20";
      case "connecting":
        return "text-amber-400 bg-amber-400/10 border-amber-500/20 animate-pulse";
      default:
        return "text-red-400 bg-red-400/10 border-red-500/20";
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-3">
      {/* Platform Status */}
      <div className={`flex items-center gap-2 px-3 py-1.5 border rounded-full text-xs font-mono transition-colors ${getStatusColor(wsStatus)}`}>
        <Activity className="w-3.5 h-3.5" />
        <span>TELEMETRY: {wsStatus.toUpperCase()}</span>
      </div>

      {/* Camera Status */}
      <div className={`flex items-center gap-2 px-3 py-1.5 border rounded-full text-xs font-mono transition-colors ${
        statistics.camera_status === "online" 
          ? "text-emerald-400 bg-emerald-400/10 border-emerald-500/20" 
          : "text-red-400 bg-red-400/10 border-red-500/20"
      }`}>
        <Camera className="w-3.5 h-3.5" />
        <span>CAMERA: {statistics.camera_status.toUpperCase()}</span>
      </div>

      {/* Session Mode */}
      <div className={`flex items-center gap-2 px-3 py-1.5 border rounded-full text-xs font-mono ${
        activeSession 
          ? "text-neon bg-emerald-500/5 border-emerald-500/10" 
          : "text-gray-400 bg-gray-500/5 border-gray-500/10"
      }`}>
        <Cpu className="w-3.5 h-3.5" />
        <span>MODE: {activeSession ? "ACTIVE_DETECTION" : "IDLE"}</span>
      </div>
    </div>
  );
}
