"use client";

import { motion } from "framer-motion";

const RADIUS = 270;

const nodes = [
  -90,
  -45,
  0,
  45,
  90,
  135,
  180,
  225,
];

export default function ConnectionLines() {
  const points = nodes.map((angle) => {
    const r = (angle * Math.PI) / 180;

    return {
      x: 320 + Math.cos(r) * RADIUS,
      y: 320 + Math.sin(r) * RADIUS,
    };
  });

  return (
    <div className="absolute">

      <svg
        width="640"
        height="640"
        viewBox="0 0 640 640"
        className="overflow-visible"
      >
        <defs>

          <linearGradient
            id="orbit-gradient"
            x1="0%"
            y1="0%"
            x2="100%"
            y2="100%"
          >
            <stop
              offset="0%"
              stopColor="#FFE08A"
              stopOpacity=".05"
            />

            <stop
              offset="50%"
              stopColor="#F6C453"
              stopOpacity=".55"
            />

            <stop
              offset="100%"
              stopColor="#FFE08A"
              stopOpacity=".05"
            />

          </linearGradient>

        </defs>

        {points.map((point, index) => {
          const next = points[(index + 1) % points.length];

          return (
            <motion.line
              key={index}
              x1={point.x}
              y1={point.y}
              x2={next.x}
              y2={next.y}
              stroke="url(#orbit-gradient)"
              strokeWidth="1.3"
              strokeLinecap="round"
              strokeDasharray="6 10"
              animate={{
                strokeDashoffset: [0, -120],
                opacity: [.15, .75, .15],
              }}
              transition={{
                duration: 5,
                delay: index * .2,
                repeat: Infinity,
                ease: "linear",
              }}
            />
          );
        })}

        {/* Cross Neural Links */}

        {[0, 2, 4, 6].map((i) => (
          <motion.line
            key={i}
            x1={points[i].x}
            y1={points[i].y}
            x2={points[(i + 4) % 8].x}
            y2={points[(i + 4) % 8].y}
            stroke="rgba(255,255,255,.08)"
            strokeWidth=".8"
            strokeDasharray="4 12"
            animate={{
              strokeDashoffset: [0, -80],
              opacity: [.05, .35, .05],
            }}
            transition={{
              duration: 8,
              repeat: Infinity,
              ease: "linear",
            }}
          />
        ))}

      </svg>

    </div>
  );
}