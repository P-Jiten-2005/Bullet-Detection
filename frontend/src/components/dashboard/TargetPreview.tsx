"use client";

import React from "react";
import { ImageOff } from "lucide-react";

interface TargetRing {
  value: number;
  outer_radius_mm: number;
  color?: string;
}

interface Bullseye {
  id: number;
  center_x_mm: number;
  center_y_mm: number;
  rings: TargetRing[];
  scoring_rule: string;
}

interface ScoringRegion {
  id: number;
  name?: string | null;
  value: number;
  x_min_mm: number;
  y_min_mm: number;
  x_max_mm: number;
  y_max_mm: number;
}

interface TargetDefinition {
  id?: string;
  name: string;
  width_mm: number;
  height_mm: number;
  bullseyes: Bullseye[];
  scoring_regions?: ScoringRegion[];
  bullet_compatibility: string[];
  decimal_scoring_supported: boolean;
  preview_url?: string | null;
}

interface TargetPreviewProps {
  target: TargetDefinition | null;
  className?: string;
}

export default function TargetPreview({ target, className = "" }: TargetPreviewProps) {
  if (!target) {
    return (
      <div className={`flex flex-col items-center justify-center bg-white/2 border border-dashed border-white/5 rounded-lg p-6 ${className}`}>
        <ImageOff className="w-8 h-8 text-gray-600 mb-2" />
        <p className="text-xs font-mono text-gray-500">No Target Selected</p>
      </div>
    );
  }

  // Handle preview_url case
  if (target.preview_url) {
    const imageUrl = target.preview_url.startsWith("http") 
      ? target.preview_url 
      : `http://localhost:8000${target.preview_url}`;
      
    return (
      <div className={`relative bg-white/2 border border-white/10 rounded-lg overflow-hidden flex items-center justify-center p-2 ${className}`}>
        <img
          src={imageUrl}
          alt={`${target.name} Preview`}
          className="max-w-full max-h-full object-contain rounded"
          onError={(e) => {
            // If image fails to load, fallback to SVG rendering
            e.currentTarget.style.display = "none";
            const fallback = e.currentTarget.parentElement?.querySelector(".svg-fallback");
            if (fallback) fallback.classList.remove("hidden");
          }}
        />
        <div className="svg-fallback hidden w-full h-full">
          <SVGPreview target={target} />
        </div>
      </div>
    );
  }

  // Handle no-image case (draw concentric rings dynamically via SVG)
  return (
    <div className={`bg-white/2 border border-white/10 rounded-lg flex items-center justify-center ${className}`}>
      <SVGPreview target={target} />
    </div>
  );
}

function SVGPreview({ target }: { target: TargetDefinition }) {
  // If target has rectangular scoring regions, draw them
  if (target.scoring_regions && target.scoring_regions.length > 0) {
    const w = target.width_mm;
    const h = target.height_mm;
    return (
      <div className="flex flex-col items-center justify-center w-full h-full p-4 font-mono">
        <svg
          viewBox={`0 0 ${w} ${h}`}
          className="w-full h-full max-w-[180px] max-h-[180px] text-gray-400"
        >
          {/* White background sheet */}
          <rect x="0" y="0" width={w} height={h} fill="#ffffff" stroke="#cccccc" strokeWidth={2} rx={4} />

          {/* Draw Rectangular Scoring Regions */}
          {target.scoring_regions.map((region, idx) => {
            const rx = region.x_min_mm;
            const ry = region.y_min_mm;
            const rw = region.x_max_mm - region.x_min_mm;
            const rh = region.y_max_mm - region.y_min_mm;
            
            return (
              <g key={idx}>
                <rect
                  x={rx}
                  y={ry}
                  width={rw}
                  height={rh}
                  fill="none"
                  stroke="#000000"
                  strokeWidth={1.5}
                />
                {/* Draw value text in center of region */}
                <text
                  x={rx + rw / 2}
                  y={ry + rh / 2}
                  fontSize={Math.max(12, Math.min(rw, rh) * 0.15)}
                  fill="#374151"
                  textAnchor="middle"
                  dominantBaseline="middle"
                  fontWeight="bold"
                >
                  {region.value}
                </text>
              </g>
            );
          })}
        </svg>
        
        {/* Target details footer overlay */}
        <div className="mt-2 text-center text-[10px] leading-tight text-gray-400">
          <p className="font-bold text-white uppercase text-[9px]">{target.name}</p>
          <p className="text-[8px] text-gray-500 mt-0.5">{target.width_mm}x{target.height_mm} mm (Rectangular)</p>
        </div>
      </div>
    );
  }

  // Find the largest ring radius to scale the SVG correctly
  const bullseye = target.bullseyes?.[0];
  const rings = bullseye?.rings || [];
  
  const maxRadius = rings.length > 0 
    ? Math.max(...rings.map(r => r.outer_radius_mm)) 
    : 30.0;
    
  // SVG ViewBox calculations (keep margin around outer ring)
  const padding = maxRadius * 0.15;
  const size = (maxRadius + padding) * 2;
  const center = size / 2;
  const scale = (size - 10) / (maxRadius * 2); // Scale to fit size minus some boundary

  return (
    <div className="flex flex-col items-center justify-center w-full h-full p-4 font-mono">
      <svg
        viewBox={`0 0 ${size} ${size}`}
        className="w-full h-full max-w-[180px] max-h-[180px] text-gray-400"
      >
        {/* White background sheet */}
        <rect x="0" y="0" width={size} height={size} fill="#ffffff" rx={4} />

        {/* Dynamic Concentric Rings */}
        {rings.map((ring, idx) => {
          const rPx = ring.outer_radius_mm * scale;
          // Rings alternate black lines. Bullseye centers (e.g. 9 & 10) can be filled black
          const isInnerRing = ring.value >= 9;
          return (
            <circle
              key={idx}
              cx={center}
              cy={center}
              r={rPx}
              fill={isInnerRing ? "#111827" : "none"}
              stroke="#000000"
              strokeWidth={isInnerRing ? 0.5 : 1}
            />
          );
        })}

        {/* Center Target Bullseye Pin (Red dot) */}
        <circle cx={center} cy={center} r={1.5} fill="#ef4444" />
        
        {/* Crosshair indicator markings */}
        <line x1={center - 4} y1={center} x2={center + 4} y2={center} stroke="#ef4444" strokeWidth={0.5} />
        <line x1={center} y1={center - 4} x2={center} y2={center + 4} stroke="#ef4444" strokeWidth={0.5} />
      </svg>
      
      {/* Target details footer overlay */}
      <div className="mt-2 text-center text-[10px] leading-tight text-gray-400">
        <p className="font-bold text-white uppercase text-[9px]">{target.name}</p>
        <p className="text-[8px] text-gray-500 mt-0.5">{target.width_mm}x{target.height_mm} mm</p>
      </div>
    </div>
  );
}
