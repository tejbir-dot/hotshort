"use client";

import { motion } from "framer-motion";

interface EnergyPacketsProps {
  radius?: number;
}

const COUNT = 12;

export default function EnergyPackets({
  radius = 270,
}: EnergyPacketsProps) {
  return (
    <div className="absolute inset-0 flex items-center justify-center">
      {Array.from({ length: COUNT }).map((_, i) => (
        <motion.div
          key={i}
          className="absolute"
          animate={{
            rotate: 360,
          }}
          transition={{
            duration: 7,
            repeat: Infinity,
            ease: "linear",
            delay: i * 0.55,
          }}
        >
          <motion.div
            className="relative"
            style={{
              transform: `translateY(-${radius}px)`,
            }}
            animate={{
              scale: [0.7, 1.4, 0.7],
              opacity: [0.2, 1, 0.2],
            }}
            transition={{
              duration: 1.6,
              repeat: Infinity,
              ease: "easeInOut",
            }}
          >
            {/* Tail */}
            <div
              className="
                absolute
                top-1/2
                right-2
                h-[2px]
                w-12
                -translate-y-1/2
              "
              style={{
                background:
                  "linear-gradient(to left, rgba(246,196,83,.9), transparent)",
              }}
            />

            {/* Glow */}
            <div
              className="
                absolute
                left-1/2
                top-1/2
                h-8
                w-8
                -translate-x-1/2
                -translate-y-1/2
                rounded-full
                blur-xl
              "
              style={{
                background:
                  "radial-gradient(circle, rgba(246,196,83,.75), transparent 75%)",
              }}
            />

            {/* Packet */}
            <div
              className="
                relative
                h-3
                w-3
                rounded-full
              "
              style={{
                background:
                  "radial-gradient(circle,#ffffff,#FFE08A,#F6C453)",
                boxShadow: `
                  0 0 12px rgba(255,224,138,.95),
                  0 0 28px rgba(246,196,83,.9)
                `,
              }}
            />
          </motion.div>
        </motion.div>
      ))}
    </div>
  );
}