"use client";

import { motion } from "framer-motion";

const rings = [
  {
    size: 180,
    duration: 12,
    reverse: false,
    opacity: 0.45,
    dash: "8 18",
  },
  {
    size: 235,
    duration: 18,
    reverse: true,
    opacity: 0.35,
    dash: "12 22",
  },
  {
    size: 295,
    duration: 26,
    reverse: false,
    opacity: 0.22,
    dash: "18 26",
  },
  {
    size: 360,
    duration: 40,
    reverse: true,
    opacity: 0.14,
    dash: "24 36",
  },
];

export default function ReactorRings() {
  return (
    <>
      {rings.map((ring, index) => (
        <motion.svg
          key={index}
          animate={{
            rotate: ring.reverse ? -360 : 360,
          }}
          transition={{
            duration: ring.duration,
            ease: "linear",
            repeat: Infinity,
          }}
          className="absolute overflow-visible"
          width={ring.size}
          height={ring.size}
          viewBox={`0 0 ${ring.size} ${ring.size}`}
        >
          {/* Main Ring */}
          <circle
            cx={ring.size / 2}
            cy={ring.size / 2}
            r={ring.size / 2 - 2}
            fill="none"
            stroke={`rgba(246,196,83,${ring.opacity})`}
            strokeWidth="1.2"
            strokeDasharray={ring.dash}
            strokeLinecap="round"
          />

          {/* Soft Ring */}
          <circle
            cx={ring.size / 2}
            cy={ring.size / 2}
            r={ring.size / 2 - 6}
            fill="none"
            stroke={`rgba(255,255,255,${ring.opacity * 0.25})`}
            strokeWidth=".8"
            strokeDasharray="2 12"
          />

          {/* Orbit Nodes */}
          {[0, 90, 180, 270].map((deg) => {
            const radius = ring.size / 2 - 2;

            const x =
              ring.size / 2 +
              radius * Math.cos((deg * Math.PI) / 180);

            const y =
              ring.size / 2 +
              radius * Math.sin((deg * Math.PI) / 180);

            return (
              <g key={deg}>
                <circle
                  cx={x}
                  cy={y}
                  r="2.2"
                  fill="#FFE08A"
                />

                <circle
                  cx={x}
                  cy={y}
                  r="6"
                  fill="none"
                  stroke="rgba(246,196,83,.18)"
                  strokeWidth=".8"
                />
              </g>
            );
          })}

          {/* Scanner Arc */}
          <motion.circle
            cx={ring.size / 2}
            cy={ring.size / 2}
            r={ring.size / 2 - 2}
            fill="none"
            stroke="#FFE08A"
            strokeWidth="2"
            strokeDasharray="32 800"
            strokeLinecap="round"
            animate={{
              rotate: 360,
            }}
            transition={{
              duration: 5 + index,
              repeat: Infinity,
              ease: "linear",
            }}
            style={{
              transformOrigin: "50% 50%",
              filter: "drop-shadow(0 0 10px rgba(246,196,83,.9))",
            }}
          />
        </motion.svg>
      ))}

      {/* Energy Sweep */}
      <motion.div
        animate={{
          rotate: 360,
        }}
        transition={{
          duration: 8,
          repeat: Infinity,
          ease: "linear",
        }}
        className="
          absolute
          h-[390px]
          w-[390px]
          rounded-full
        "
        style={{
          background:
            "conic-gradient(from 0deg, transparent 0%, transparent 92%, rgba(255,224,138,.9) 97%, transparent 100%)",
          WebkitMask:
            "radial-gradient(circle, transparent 96%, white 100%)",
          mask:
            "radial-gradient(circle, transparent 96%, white 100%)",
          opacity: .75,
        }}
      />
    </>
  );
}