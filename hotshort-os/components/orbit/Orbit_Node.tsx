"use client";

import { motion } from "framer-motion";
import { ReactNode } from "react";

interface OrbitNodeProps {
  angle: number;
  radius: number;
  label: string;
  icon: ReactNode;
  active?: boolean;
}

export default function OrbitNode({
  angle,
  radius,
  label,
  icon,
  active = false,
}: OrbitNodeProps) {
  const rad = (angle * Math.PI) / 180;

  const x = Math.cos(rad) * radius;
  const y = Math.sin(rad) * radius;

  return (
    <motion.div
      className="absolute"
      style={{
        transform: `translate(${x}px, ${y}px)`,
      }}
      animate={
        active
          ? {
              scale: [1, 1.12, 1],
            }
          : {}
      }
      transition={{
        duration: 2,
        repeat: Infinity,
        ease: "easeInOut",
      }}
    >
      {/* Outer Glow */}
      <motion.div
        animate={{
          opacity: active ? [0.2, 0.7, 0.2] : [0.1, 0.25, 0.1],
          scale: [1, 1.2, 1],
        }}
        transition={{
          duration: 2.5,
          repeat: Infinity,
          ease: "easeInOut",
        }}
        className="
          absolute
          left-1/2
          top-1/2
          h-24
          w-24
          -translate-x-1/2
          -translate-y-1/2
          rounded-full
          blur-2xl
        "
        style={{
          background:
            "radial-gradient(circle, rgba(246,196,83,.45), transparent 72%)",
        }}
      />

      {/* Glass Card */}
      <motion.div
        whileHover={{
          scale: 1.05,
        }}
        className="
          relative
          flex
          h-16
          w-16
          items-center
          justify-center
          rounded-2xl
          border
          border-white/10
          backdrop-blur-xl
        "
        style={{
          background:
            "linear-gradient(180deg, rgba(255,255,255,.08), rgba(255,255,255,.03))",
          boxShadow: `
            inset 0 0 25px rgba(255,255,255,.06),
            0 0 30px rgba(246,196,83,.15)
          `,
        }}
      >
        <div className="text-yellow-300">{icon}</div>

        {active && (
          <motion.div
            layoutId="scanner"
            className="
              absolute
              inset-0
              rounded-2xl
              border
              border-yellow-300
            "
            animate={{
              opacity: [0.2, 1, 0.2],
            }}
            transition={{
              duration: 1.4,
              repeat: Infinity,
            }}
          />
        )}
      </motion.div>

      {/* Label */}
      <div
        className="
          absolute
          left-1/2
          top-[78px]
          -translate-x-1/2
          whitespace-nowrap
          text-[11px]
          font-medium
          tracking-[0.18em]
          uppercase
          text-white/70
        "
      >
        {label}
      </div>
    </motion.div>
  );
}