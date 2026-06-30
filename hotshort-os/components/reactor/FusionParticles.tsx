"use client";

import { motion } from "framer-motion";

const PARTICLE_COUNT = 80;

const particles = Array.from({ length: PARTICLE_COUNT }, (_, i) => {
  const angle = Math.random() * Math.PI * 2;
  const radius = Math.random() * 70;

  return {
    id: i,
    x: Math.cos(angle) * radius,
    y: Math.sin(angle) * radius,
    size: Math.random() * 3 + 1,
    duration: 2 + Math.random() * 3,
    delay: Math.random() * 2,
    gold: Math.random() > 0.4,
  };
});

export default function FusionParticles() {
  return (
    <div className="absolute flex items-center justify-center">
      {particles.map((p) => (
        <motion.div
          key={p.id}
          className="absolute rounded-full"
          initial={{
            x: p.x,
            y: p.y,
          }}
          animate={{
            x: [
              p.x,
              p.x + (Math.random() * 20 - 10),
              p.x,
            ],
            y: [
              p.y,
              p.y + (Math.random() * 20 - 10),
              p.y,
            ],
            opacity: [0.2, 1, 0.2],
            scale: [0.6, 1.5, 0.6],
          }}
          transition={{
            duration: p.duration,
            delay: p.delay,
            repeat: Infinity,
            ease: "easeInOut",
          }}
          style={{
            width: p.size,
            height: p.size,
            background: p.gold ? "#FFE08A" : "#FFFFFF",
            boxShadow: p.gold
              ? "0 0 12px rgba(246,196,83,.95)"
              : "0 0 8px rgba(255,255,255,.9)",
          }}
        />
      ))}

      {/* Plasma Ring */}
      <motion.div
        animate={{
          rotate: 360,
        }}
        transition={{
          duration: 14,
          repeat: Infinity,
          ease: "linear",
        }}
        className="
          absolute
          h-[150px]
          w-[150px]
          rounded-full
        "
        style={{
          background:
            "conic-gradient(from 0deg, transparent, rgba(255,224,138,.45), transparent, rgba(246,196,83,.35), transparent)",
          WebkitMask:
            "radial-gradient(circle, transparent 92%, white 100%)",
          mask:
            "radial-gradient(circle, transparent 92%, white 100%)",
        }}
      />

      {/* White Energy Core */}
      <motion.div
        animate={{
          scale: [0.9, 1.15, 0.9],
          opacity: [0.6, 1, 0.6],
        }}
        transition={{
          duration: 1.5,
          repeat: Infinity,
          ease: "easeInOut",
        }}
        className="
          absolute
          h-5
          w-5
          rounded-full
          bg-white
        "
        style={{
          boxShadow: `
            0 0 20px #fff,
            0 0 50px rgba(255,255,255,.9),
            0 0 100px rgba(246,196,83,.9)
          `,
        }}
      />
    </div>
  );
}