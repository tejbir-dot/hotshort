"use client";

import { motion } from "framer-motion";

// Neural pulse waveform path
const PULSE_PATH = "M -40 0 L -28 0 L -22 -16 L -14 18 L -6 -10 L 0 12 L 6 -8 L 14 0 L 40 0";

export default function ReactorCenter() {
  return (
    <div className="absolute flex items-center justify-center">

      {/* Deep ambient glow — blue-purple outer */}
      <div
        className="absolute rounded-full"
        style={{
          width: 320,
          height: 320,
          background: "radial-gradient(circle, rgba(80,120,255,0.09) 0%, rgba(117,91,255,0.05) 40%, transparent 70%)",
          filter: "blur(40px)",
        }}
      />

      {/* Gold inner glow */}
      <div
        className="absolute rounded-full"
        style={{
          width: 180,
          height: 180,
          background: "radial-gradient(circle, rgba(246,196,83,0.22) 0%, transparent 65%)",
          filter: "blur(20px)",
        }}
      />

      {/* Outer metallic shell — dark glass */}
      <div
        className="absolute rounded-full"
        style={{
          width: 120,
          height: 120,
          background: "radial-gradient(circle at 35% 28%, rgba(160,180,220,0.12), rgba(30,40,70,0.7) 55%, rgba(10,15,30,0.9) 100%)",
          border: "1px solid rgba(150,180,255,0.18)",
          boxShadow: `
            inset 0 1px 0 rgba(255,255,255,0.1),
            inset 0 -1px 0 rgba(0,0,0,0.4),
            0 0 30px rgba(246,196,83,0.2),
            0 0 60px rgba(80,120,255,0.12)
          `,
        }}
      />

      {/* Inner metallic sphere */}
      <motion.div
        animate={{ scale: [1, 1.04, 1] }}
        transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
        className="absolute rounded-full"
        style={{
          width: 88,
          height: 88,
          background: "radial-gradient(circle at 32% 26%, rgba(200,215,255,0.18) 0%, rgba(20,28,55,0.95) 50%, rgba(8,12,25,1) 100%)",
          border: "1px solid rgba(120,160,255,0.22)",
          boxShadow: `
            inset 0 2px 4px rgba(200,220,255,0.08),
            0 0 20px rgba(246,196,83,0.18),
            0 0 40px rgba(80,100,255,0.1)
          `,
        }}
      />

      {/* Neural pulse waveform */}
      <motion.svg
        width="90"
        height="40"
        viewBox="-45 -20 90 40"
        className="absolute"
        animate={{ opacity: [0.6, 1, 0.6] }}
        transition={{ duration: 2.2, repeat: Infinity, ease: "easeInOut" }}
      >
        <motion.path
          d={PULSE_PATH}
          fill="none"
          stroke="rgba(246,196,83,0.9)"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{
            filter: "drop-shadow(0 0 6px rgba(246,196,83,0.9)) drop-shadow(0 0 14px rgba(246,196,83,0.5))",
          }}
          animate={{
            pathLength: [0, 1, 1],
            opacity: [0, 1, 0.8],
          }}
          transition={{
            duration: 2,
            repeat: Infinity,
            ease: "easeInOut",
          }}
        />
      </motion.svg>

      {/* Specular highlight — top-left glint */}
      <div
        className="absolute rounded-full"
        style={{
          width: 28,
          height: 18,
          background: "radial-gradient(ellipse, rgba(200,220,255,0.25), transparent 70%)",
          transform: "translate(-18px, -22px)",
          filter: "blur(2px)",
        }}
      />

      {/* Pulsing core dot */}
      <motion.div
        animate={{
          scale: [0.7, 1.15, 0.7],
          opacity: [0.5, 1, 0.5],
        }}
        transition={{ duration: 2.2, repeat: Infinity, ease: "easeInOut" }}
        className="absolute rounded-full"
        style={{
          width: 10,
          height: 10,
          background: "#fff",
          boxShadow: "0 0 16px rgba(255,255,255,0.9), 0 0 40px rgba(246,196,83,0.7)",
        }}
      />

    </div>
  );
}
