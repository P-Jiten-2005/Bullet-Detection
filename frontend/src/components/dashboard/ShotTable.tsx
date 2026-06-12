"use client";

import React from "react";
import { useStore, Shot } from "@/store/useStore";
import { Eye, EyeOff, HelpCircle } from "lucide-react";

export default function ShotTable() {
  const { shots, selectedShotId, setSelectedShotId, setShots } = useStore();

  const handleRowHover = (id: string | null) => {
    setSelectedShotId(id);
  };

  const toggleShotValidity = async (shot: Shot, e: React.MouseEvent) => {
    e.stopPropagation();
    
    // In a real application, call the backend: PATCH /shots/{id}/validity
    // Here we update Zustand store locally to simulate the toggle
    const updatedShots = shots.map((s) => 
      s.id === shot.id ? { ...s, is_valid: !s.is_valid } : s
    );
    setShots(updatedShots);
  };

  const formatTime = (timeStr: string) => {
    const d = new Date(timeStr);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  };

  const getBoundaryBadge = (status: string | null | undefined) => {
    if (!status) return <span className="text-gray-600">-</span>;
    switch (status) {
      case "certain":
        return <span className="px-1.5 py-0.5 rounded text-[9px] bg-emerald-950/40 text-emerald-400 border border-emerald-500/20 font-bold uppercase tracking-wider">Certain</span>;
      case "probable":
        return <span className="px-1.5 py-0.5 rounded text-[9px] bg-blue-950/40 text-blue-400 border border-blue-500/20 font-bold uppercase tracking-wider">Probable</span>;
      case "review_required":
        return <span className="px-1.5 py-0.5 rounded text-[9px] bg-amber-950/40 text-amber-400 border border-amber-500/20 font-bold uppercase tracking-wider animate-pulse">Review</span>;
      default:
        return <span className="text-gray-500">{status}</span>;
    }
  };

  return (
    <div className="glass-panel p-6 flex flex-col h-full">
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-base font-bold font-mono tracking-wider uppercase">Shot History Table</h3>
        <span className="text-xs text-gray-400 font-mono">
          TOTAL RECORDED: {shots.length}
        </span>
      </div>

      <div className="flex-1 overflow-y-auto max-h-[380px] pr-2 scrollbar-thin">
        {shots.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-48 border border-dashed border-white/5 rounded-lg text-center">
            <HelpCircle className="w-8 h-8 text-gray-600 mb-2" />
            <p className="text-xs text-gray-500 font-mono">No bullet holes detected yet</p>
          </div>
        ) : (
          <div className="overflow-x-auto w-full scrollbar-thin">
            <table className="w-full text-left text-xs font-mono whitespace-nowrap">
              <thead>
                <tr className="border-b border-white/5 text-gray-400 uppercase text-[10px] pb-2">
                  <th className="py-2 px-1">Shot</th>
                  <th className="py-2 px-2">Position (mm)</th>
                  <th className="py-2 px-2">Caliber</th>
                  <th className="py-2 px-2">Score (Dec)</th>
                  <th className="py-2 px-2">Boundary</th>
                  <th className="py-2 px-2">Timestamp</th>
                  <th className="py-2 px-2 text-right">Action</th>
                </tr>
              </thead>
              <tbody>
                {shots.map((shot) => {
                  const isSelected = shot.id === selectedShotId;
                  return (
                    <tr
                      key={shot.id}
                      onMouseEnter={() => handleRowHover(shot.id)}
                      onMouseLeave={() => handleRowHover(null)}
                      onClick={() => handleRowHover(shot.id)}
                      className={`border-b border-white/5 cursor-pointer transition-colors ${
                        !shot.is_valid 
                          ? "opacity-45 hover:bg-white/2" 
                          : isSelected 
                            ? "bg-white/5 text-neon" 
                            : "hover:bg-white/3"
                      }`}
                    >
                      <td className="py-3 px-1 font-bold">
                        #{shot.shot_number}
                      </td>
                      <td className="py-3 px-2">
                        {shot.x_calibrated !== null && shot.x_calibrated !== undefined && shot.y_calibrated !== null && shot.y_calibrated !== undefined ? (
                          <span>{shot.x_calibrated.toFixed(1)}, {shot.y_calibrated.toFixed(1)}</span>
                        ) : (
                          <span className="text-gray-500">Uncalibrated</span>
                        )}
                      </td>
                      <td className="py-3 px-2">
                        {shot.diameter_mm !== null && shot.diameter_mm !== undefined ? (
                          <span>{shot.diameter_mm.toFixed(1)} mm</span>
                        ) : (
                          <span>{shot.diameter_px.toFixed(0)} px</span>
                        )}
                      </td>
                      <td className="py-3 px-2 font-bold text-white">
                        {shot.score !== null && shot.score !== undefined ? (
                          <span>{shot.score} <span className="text-[10px] font-normal text-gray-400">({shot.decimal_score?.toFixed(1) || "0.0"})</span></span>
                        ) : (
                          <span className="text-gray-500">-</span>
                        )}
                      </td>
                      <td className="py-3 px-2">
                        {getBoundaryBadge(shot.boundary_status)}
                      </td>
                      <td className="py-3 px-2 text-gray-400">
                        {formatTime(shot.created_at)}
                      </td>
                      <td className="py-3 px-2 text-right">
                        <button
                          onClick={(e) => toggleShotValidity(shot, e)}
                          className={`p-1.5 rounded border transition-colors ${
                            shot.is_valid 
                              ? "border-emerald-500/10 text-emerald-400 hover:bg-emerald-400/10" 
                              : "border-red-500/10 text-red-400 hover:bg-red-400/10"
                          }`}
                          title={shot.is_valid ? "Exclude Shot" : "Include Shot"}
                        >
                          {shot.is_valid ? <Eye className="w-3.5 h-3.5" /> : <EyeOff className="w-3.5 h-3.5" />}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
