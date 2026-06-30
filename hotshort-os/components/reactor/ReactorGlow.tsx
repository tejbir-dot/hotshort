"use client";

import { motion } from "framer-motion";

export default function ReactorGlow() {
  return (
    <>
      {/* Outer Energy Field */}
      <motion.div
        animate={{
          scale: [1, 1.12, 1],
          opacity: [0.12, 0.22, 0.12],
        }}
        transition={{
          duration: 6,
          repeat: Infinity,
          ease: "easeInOut",
        }}
        className="
          absolute
          h-[720px]
          w-[720px]
          rounded-full
          blur-[180px]
        "
        style={{
          background:
            "radial-gradient(circle, rgba(246,196,83,.20) 0%, rgba(246,196,83,.06) 45%, transparent 75%)",
        }}
      />

      {/* Golden Plasma */}
      <motion.div
        animate={{
          rotate: 360,
          scale: [1, 1.05, 1],
        }}
        transition={{
          rotate: {
            duration: 45,
            repeat: Infinity,
            ease: "linear",
          },
          scale: {
            duration: 4,
            repeat: Infinity,
            ease: "easeInOut",
          },
        }}
        className="
          absolute
          h-[520px]
          w-[520px]
          rounded-full
          blur-[100px]
        "
        style={{
          background: `
            conic-gradient(
              from 0deg,
              transparent,
              rgba(255,224,138,.25),
              rgba(246,196,83,.45),
              rgba(255,224,138,.20),
              transparent
            )
          `,
        }}
      />

      {/* Purple Atmosphere */}
      <motion.div
        animate={{
          rotate: -360,
        }}
        transition={{
          duration: 70,
          repeat: Infinity,
          ease: "linear",
        }}
        className="
          absolute
          h-[620px]
          w-[620px]
          rounded-full
          blur-[150px]
        "
        style={{
          background: `
            conic-gradient(
              from 180deg,
              transparent,
              rgba(117,91,255,.18),
              transparent,
              rgba(117,91,255,.10),
              transparent
            )
          `,
        }}
      />

      {/* Core Halo */}
      <motion.div
        animate={{
          scale: [1, 1.08, 1],
          opacity: [0.5, 0.85, 0.5],
        }}
        transition={{
          duration: 2.8,
          repeat: Infinity,
          ease: "easeInOut",
        }}
        className="
          absolute
          h-[260px]
          w-[260px]
          rounded-full
          blur-[70px]
        "
        style={{
          background:
            "radial-gradient(circle, rgba(255,224,138,.85), rgba(246,196,83,.28), transparent 72%)",
        }}
      />

      {/* Inner White Heat */}
      <motion.div
        animate={{
          scale: [0.95, 1.05, 0.95],
          opacity: [0.55, 0.95, 0.55],
        }}
        transition={{
          duration: 1.8,
          repeat: Infinity,
          ease: "easeInOut",
        }}
        className="
          absolute
          h-[120px]
          w-[120px]
          rounded-full
          blur-[35px]
        "
        style={{
          background:
            "radial-gradient(circle, rgba(255,255,255,.95), rgba(255,235,170,.55), transparent 78%)",
        }}
      />
    </>
  );
}