"use client";

import React from "react";
import { useStore } from "@/store/useStore";
import { Target, Clock, Shield, Camera } from "lucide-react";

export default function OverviewCards() {
  const { statistics, activeSession } = useStore();

  const formatTime = (timeStr: string | null) => {
    if (!timeStr) return "N/A";
    const date = new Date(timeStr);
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  };

  const cards = [
    {
      title: "Total Shots Detected",
      value: statistics.total_shots,
      description: "Validated bullet impacts",
      icon: Target,
      colorClass: "text-emerald-400",
      glowColor: "rgba(16, 185, 129, 0.2)"
    },
    {
      title: "Last Detection Time",
      value: formatTime(statistics.last_shot_time),
      description: activeSession ? "Live session timeline" : "No active recordings",
      icon: Clock,
      colorClass: "text-blue-400",
      glowColor: "rgba(59, 130, 246, 0.2)"
    },
    {
      title: "Current Session",
      value: activeSession ? activeSession.name : "None Active",
      description: activeSession ? `${activeSession.target_type.split("_").map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(" ")} • Cal: ${activeSession.bullet_caliber}mm` : "Start a session to capture",
      icon: Shield,
      colorClass: "text-amber-400",
      glowColor: "rgba(245, 158, 11, 0.2)"
    },
    {
      title: "Optical Sensor",
      value: statistics.camera_status.toUpperCase(),
      description: "Fixed mounted camera feed",
      icon: Camera,
      colorClass: statistics.camera_status === "online" ? "text-emerald-400" : "text-red-400",
      glowColor: statistics.camera_status === "online" ? "rgba(16, 185, 129, 0.2)" : "rgba(239, 68, 68, 0.2)"
    }
  ];

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
      {cards.map((card, idx) => {
        const Icon = card.icon;
        return (
          <div
            key={idx}
            className="glass-panel p-5 relative overflow-hidden group transition-all duration-300 hover:-translate-y-1 hover:border-white/15 cursor-pointer"
            style={{
              boxShadow: `0 8px 32px 0 rgba(0, 0, 0, 0.25), 0 0 10px ${card.glowColor}`
            }}
          >
            {/* Hover reflection */}
            <div className="absolute top-0 right-0 w-32 h-32 bg-white/2 rounded-full blur-2xl -mr-8 -mt-8 transition-transform group-hover:scale-125 duration-500" />
            
            <div className="flex justify-between items-start">
              <div>
                <p className="text-xs text-gray-400 font-medium tracking-wide uppercase">{card.title}</p>
                <h3 className="text-2xl font-bold font-mono tracking-tight mt-1.5">{card.value}</h3>
              </div>
              <div className={`p-2.5 rounded-lg bg-white/3 border border-white/5 ${card.colorClass}`}>
                <Icon className="w-5 h-5" />
              </div>
            </div>
            
            <p className="text-xs text-gray-500 mt-3 font-medium">{card.description}</p>
          </div>
        );
      })}
    </div>
  );
}
