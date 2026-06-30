"use client";

import { motion } from "framer-motion";

const rings = [
  { size: 170, duration: 55, reverse: false, opacity: 0.55, strokeW: 1.5, glow: 6 },
  { size: 240, duration: 75, reverse: true,  opacity: 0.42, strokeW: 1.2, glow: 5 },
  { size: 320, duration: 100, reverse: false, opacity: 0.28, strokeW: 1.0, glow: 4 },
  { size: 415, duration: 140, reverse: true,  opacity: 0.18, strokeW: 0.8, glow: 3 },
  { size: 520, duration: 190, reverse: false, opacity: 0.10, strokeW: 0.6, glow: 2 },
];

// A fast glimmer arc that orbits each ring
const GlimmerArc = ({ size, duration, index }: { size: number; duration: number; index: number }) => (
  <motion.circle
    cx={size / 2}
    cy={size / 2}
    r={size / 2 - 2}
    fill="none"
    stroke="rgba(246,196,83,0.9)"
    strokeWidth={2.5 - index * 0.3}
    strokeDasharray={`${24 + index * 6} ${size * 3}`}
    strokeLinecap="round"
    animate={{ rotate: 360 }}
    transition={{
      duration: 6 + index * 1.5,
      repeat: Infinity,
      ease: "linear",
    }}
    style={{
      transformOrigin: "50% 50%",
      filter: `drop-shadow(0 0 ${8 - index}px rgba(246,196,83,1)) drop-shadow(0 0 ${20 - index * 2}px rgba(246,196,83,0.6))`,
    }}
  />
);

export default function ReactorRings() {
  return (
    <>
      {rings.map((ring, index) => (
        <motion.svg
          key={index}
          animate={{ rotate: ring.reverse ? -360 : 360 }}
          transition={{ duration: ring.duration, ease: "linear", repeat: Infinity }}
          className="absolute overflow-visible"
          width={ring.size}
          height={ring.size}
          viewBox={`0 0 ${ring.size} ${ring.size}`}
          style={{ willChange: "transform" }}
        >
          {/* Outer glow ring */}
          <circle
            cx={ring.size / 2}
            cy={ring.size / 2}
            r={ring.size / 2 - 2}
            fill="none"
            stroke={`rgba(100,150,255,${ring.opacity * 0.3})`}
            strokeWidth={ring.strokeW * 5}
            filter={`blur(${ring.glow + 4}px)`}
          />

          {/* Main ring — solid, metallic blue-gold */}
          <circle
            cx={ring.size / 2}
            cy={ring.size / 2}
            r={ring.size / 2 - 2}
            fill="none"
            stroke={`rgba(180,200,255,${ring.opacity})`}
            strokeWidth={ring.strokeW}
            style={{
              filter: `drop-shadow(0 0 ${ring.glow}px rgba(150,180,255,0.6))`,
            }}
          />

          {/* Inner thin accent */}
          <circle
            cx={ring.size / 2}
            cy={ring.size / 2}
            r={ring.size / 2 - 8}
            fill="none"
            stroke={`rgba(246,196,83,${ring.opacity * 0.35})`}
            strokeWidth={0.5}
          />

          {/* Glimmer arc */}
          <GlimmerArc size={ring.size} duration={ring.duration} index={index} />

          {/* Small orbital nodes at key positions */}
          {[0, 72, 144, 216, 288].slice(0, 3 + index).map((deg) => {
            const r = ring.size / 2 - 2;
            const x = ring.size / 2 + r * Math.cos((deg * Math.PI) / 180);
            const y = ring.size / 2 + r * Math.sin((deg * Math.PI) / 180);
            return (
              <g key={deg}>
                <circle cx={x} cy={y} r={3.5 - index * 0.4} fill="rgba(246,196,83,0.9)"
                  style={{ filter: "drop-shadow(0 0 6px rgba(246,196,83,1))" }}
                />
                <circle cx={x} cy={y} r={9 - index} fill="none"
                  stroke="rgba(246,196,83,0.2)" strokeWidth="0.8"
                />
              </g>
            );
          })}
        </motion.svg>
      ))}
    </>
  );
}
