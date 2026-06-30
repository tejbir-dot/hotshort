"use client";

import { motion } from "framer-motion";

const rings = [
  { size: 180, duration: 40, reverse: false, opacity: 1 },
  { size: 260, duration: 55, reverse: true,  opacity: 0.8 },
  { size: 350, duration: 75, reverse: false, opacity: 0.6 },
  { size: 450, duration: 100, reverse: true,  opacity: 0.4 },
  { size: 560, duration: 140, reverse: false, opacity: 0.25 },
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
            border: "1px solid rgba(120, 160, 255, 0.15)",
            background: "rgba(10, 15, 30, 0.2)",
            boxShadow: `
              inset 0 0 20px rgba(20, 40, 100, 0.3),
              inset 0 0 5px rgba(255, 255, 255, 0.05),
              0 0 15px rgba(0, 0, 0, 0.5)
            `,
            backdropFilter: "blur(4px)",
            opacity: ring.opacity,
          }}
        >
          {/* Inner Golden Shine Arc */}
          <motion.div
            className="absolute inset-0 rounded-full"
            animate={{ rotate: ring.reverse ? -360 : 360 }}
            transition={{ duration: ring.duration, ease: "linear", repeat: Infinity }}
            style={{
              background: "conic-gradient(from 0deg, transparent 0%, transparent 80%, rgba(246,196,83,0.15) 90%, rgba(246,196,83,0.8) 100%)",
              WebkitMask: "radial-gradient(circle, transparent 48%, black 50%)",
              mask: "radial-gradient(circle, transparent 48%, black 50%)",
            }}
          />

          {/* Core Glint on the track */}
          <motion.div
            className="absolute inset-0"
            animate={{ rotate: ring.reverse ? -360 : 360 }}
            transition={{ duration: ring.duration, ease: "linear", repeat: Infinity }}
          >
            <div
              className="absolute rounded-full bg-[#ffe08a]"
              style={{
                width: 4,
                height: 4,
                top: -2,
                left: "50%",
                transform: "translateX(-50%)",
                boxShadow: "0 0 10px rgba(246,196,83,1), 0 0 20px rgba(246,196,83,0.8)",
              }}
            />
          </motion.div>
        </div>
      ))}
    </div>
  );
}
