"use client";

import { motion } from "framer-motion";

export default function ReactorPulse() {
  return (
    <>
      {/* Pulse Ring 1 */}
      <motion.div
        className="absolute rounded-full border border-yellow-300/40"
        initial={{
          width: 80,
          height: 80,
          opacity: 0.8,
          scale: 1,
        }}
        animate={{
          width: 360,
          height: 360,
          opacity: 0,
          scale: 1.15,
        }}
        transition={{
          duration: 3,
          repeat: Infinity,
          ease: "easeOut",
        }}
      />

      {/* Pulse Ring 2 */}
      <motion.div
        className="absolute rounded-full border border-yellow-200/30"
        initial={{
          width: 80,
          height: 80,
          opacity: 0,
          scale: 1,
        }}
        animate={{
          width: 420,
          height: 420,
          opacity: [0, 0.55, 0],
          scale: 1.18,
        }}
        transition={{
          duration: 3,
          delay: 1,
          repeat: Infinity,
          ease: "easeOut",
        }}
      />

      {/* Pulse Ring 3 */}
      <motion.div
        className="absolute rounded-full border border-yellow-100/20"
        initial={{
          width: 80,
          height: 80,
          opacity: 0,
          scale: 1,
        }}
        animate={{
          width: 520,
          height: 520,
          opacity: [0, 0.35, 0],
          scale: 1.2,
        }}
        transition={{
          duration: 3,
          delay: 2,
          repeat: Infinity,
          ease: "easeOut",
        }}
      />

      {/* Energy Flash */}
      <motion.div
        animate={{
          scale: [1, 1.25, 1],
          opacity: [0.2, 0.45, 0.2],
        }}
        transition={{
          duration: 2,
          repeat: Infinity,
          ease: "easeInOut",
        }}
        className="
          absolute
          h-[180px]
          w-[180px]
          rounded-full
          blur-[60px]
        "
        style={{
          background:
            "radial-gradient(circle, rgba(255,224,138,.55), rgba(246,196,83,.18), transparent 75%)",
        }}
      />
    </>
  );
}