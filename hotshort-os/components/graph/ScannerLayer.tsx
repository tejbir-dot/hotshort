"use client";

import { useEffect, useRef } from "react";
import scannerEngine from "@/engine/ScannerEngine";

const SVG_SIZE = 700;
const CENTER = SVG_SIZE / 2;
const ORBIT_RADIUS = 270;

export default function ScannerLayer() {
  const groupRef = useRef<SVGGElement>(null);
  const beamRef = useRef<SVGPathElement>(null);
  const glowRef = useRef<SVGPathElement>(null);

  useEffect(() => {
    const unsub = scannerEngine.subscribe((state) => {
      const group = groupRef.current;
      if (!group) return;
      // Rotate the whole group to the current beam angle
      group.setAttribute(
        "transform",
        `rotate(${state.angle.toFixed(2)}, ${CENTER}, ${CENTER})`
      );
    });

    return () => {
      unsub();
    };
  }, []);

  const beamPath = `M ${CENTER} ${CENTER} L ${CENTER} ${CENTER - ORBIT_RADIUS - 40}`;

  return (
    <svg
      className="absolute overflow-visible pointer-events-none"
      width={SVG_SIZE}
      height={SVG_SIZE}
      viewBox={`0 0 ${SVG_SIZE} ${SVG_SIZE}`}
      style={{ left: "50%", top: "50%", transform: "translate(-50%,-50%)" }}
    >
      <defs>
        <linearGradient id="scanner-grad" x1="0" y1="1" x2="0" y2="0" gradientUnits="userSpaceOnUse"
          gradientTransform={`rotate(-90, ${CENTER}, ${CENTER})`}>
          <stop offset="0%" stopColor="rgba(246,196,83,0)" />
          <stop offset="60%" stopColor="rgba(246,196,83,0.06)" />
          <stop offset="100%" stopColor="rgba(255,255,255,0.22)" />
        </linearGradient>
        <filter id="scanner-bloom" x="-60%" y="-60%" width="220%" height="220%">
          <feGaussianBlur stdDeviation="10" />
        </filter>

        {/* Conic mask for sector */}
        <clipPath id="scanner-clip">
          <path d={`M ${CENTER} ${CENTER} L ${CENTER} 0 A ${CENTER} ${CENTER} 0 0 1 ${CENTER + ORBIT_RADIUS + 40} ${CENTER} Z`} />
        </clipPath>
      </defs>

      <g ref={groupRef}>
        {/* Bloom beam */}
        <line
          ref={glowRef as any}
          x1={CENTER}
          y1={CENTER}
          x2={CENTER}
          y2={CENTER - ORBIT_RADIUS - 40}
          stroke="rgba(246,196,83,0.55)"
          strokeWidth="20"
          strokeLinecap="round"
          filter="url(#scanner-bloom)"
        />

        {/* Crisp edge beam */}
        <line
          ref={beamRef as any}
          x1={CENTER}
          y1={CENTER}
          x2={CENTER}
          y2={CENTER - ORBIT_RADIUS - 40}
          stroke="rgba(255,255,255,0.55)"
          strokeWidth="1.2"
          strokeLinecap="round"
        />

        {/* Soft sector sweep */}
        <path
          d={`M ${CENTER} ${CENTER} L ${CENTER} ${CENTER - ORBIT_RADIUS - 40} A ${ORBIT_RADIUS + 40} ${ORBIT_RADIUS + 40} 0 0 0 ${CENTER - (ORBIT_RADIUS + 40) * Math.sin(0.35)} ${CENTER - (ORBIT_RADIUS + 40) * Math.cos(0.35)} Z`}
          fill="url(#scanner-grad)"
          opacity="0.55"
        />
      </g>
    </svg>
  );
}
