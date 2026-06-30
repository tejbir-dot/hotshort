"use client";

import { motion } from "framer-motion";

const rings = [
  { size: 340, duration: 40, reverse: false, opacity: 1, glowIntensity: 0.8 },
  { size: 440, duration: 55, reverse: true,  opacity: 0.7, glowIntensity: 0.6 },
  { size: 550, duration: 75, reverse: false, opacity: 0.5, glowIntensity: 0.4 },
  { size: 680, duration: 100, reverse: true,  opacity: 0.3, glowIntensity: 0.2 },
  { size: 820, duration: 140, reverse: false, opacity: 0.15, glowIntensity: 0.1 },
];

export default function ReactorRings() {
  return (
    <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
      {rings.map((ring, index) => (
        <div
          key={index}
          className="absolute rounded-full"
          style={{
            width: ring.size,
            height: ring.size,
            border: "1px solid rgba(120, 160, 255, 0.12)",
            background: "rgba(10, 15, 30, 0.15)",
            boxShadow: `
              inset 0 0 30px rgba(20, 40, 100, 0.4),
              inset 0 0 8px rgba(255, 255, 255, 0.05),
              0 20px 40px rgba(0, 0, 0, 0.4)
            `,
            backdropFilter: "blur(6px)",
            opacity: ring.opacity,
          }}
        >
          {/* Outer Thin Glass Ring (Rim light) */}
          <div className="absolute inset-0 rounded-full border border-white/5" style={{ transform: "scale(1.01)" }} />

          {/* Inner Golden Shine Arc (The continuous flow) */}
          <motion.div
            className="absolute inset-0 rounded-full"
            animate={{ rotate: ring.reverse ? -360 : 360 }}
            transition={{ duration: ring.duration, ease: "linear", repeat: Infinity }}
            style={{
              background: `conic-gradient(from 0deg, transparent 0%, transparent 75%, rgba(246,196,83,${0.2 * ring.glowIntensity}) 90%, rgba(246,196,83,${0.9 * ring.glowIntensity}) 100%)`,
              WebkitMask: "radial-gradient(circle, transparent 48%, black 50%)",
              mask: "radial-gradient(circle, transparent 48%, black 50%)",
            }}
          />

          {/* The "Stripes" (Segmented bright golden tracks) */}
          <motion.svg
            className="absolute inset-0 w-full h-full"
            viewBox={`0 0 ${ring.size} ${ring.size}`}
            animate={{ rotate: ring.reverse ? 360 : -360 }}
            transition={{ duration: ring.duration * 0.7, ease: "linear", repeat: Infinity }}
          >
            <circle
              cx={ring.size / 2}
              cy={ring.size / 2}
              r={ring.size / 2 - 2}
              fill="none"
              stroke="rgba(246,196,83,0.8)"
              strokeWidth="3"
              strokeDasharray={`10 30 20 40 5 100 ${ring.size * 2}`}
              strokeLinecap="round"
              style={{ filter: "drop-shadow(0 0 10px rgba(246,196,83,0.8))" }}
            />
            
            {/* Secondary stripes */}
            <circle
              cx={ring.size / 2}
              cy={ring.size / 2}
              r={ring.size / 2 - 2}
              fill="none"
              stroke="rgba(255,255,255,0.6)"
              strokeWidth="1.5"
              strokeDasharray={`2 40 4 60 ${ring.size * 2}`}
              strokeLinecap="round"
            />
          </motion.svg>

          {/* Core Glint on the track */}
          <motion.div
            className="absolute inset-0"
            animate={{ rotate: ring.reverse ? -360 : 360 }}
            transition={{ duration: ring.duration, ease: "linear", repeat: Infinity }}
          >
            <div
              className="absolute rounded-full bg-[#ffe08a]"
              style={{
                width: 6,
                height: 6,
                top: -3,
                left: "50%",
                transform: "translateX(-50%)",
                boxShadow: "0 0 15px rgba(246,196,83,1), 0 0 30px rgba(246,196,83,0.8)",
              }}
            />
          </motion.div>
        </div>
      ))}
    </div>
  );
}
