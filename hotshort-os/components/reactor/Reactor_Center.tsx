"use client";

import { motion } from "framer-motion";
import FusionParticles from "./FusionParticles";

export default function ReactorCenter() {
  return (
    <div className="absolute flex items-center justify-center">

      {/* Outer Plasma */}
      <motion.div
        animate={{
          rotate: 360,
          scale: [1, 1.04, 1],
        }}
        transition={{
          rotate: {
            duration: 18,
            repeat: Infinity,
            ease: "linear",
          },
          scale: {
            duration: 2.8,
            repeat: Infinity,
            ease: "easeInOut",
          },
        }}
        className="
          absolute
          h-36
          w-36
          rounded-full
          blur-md
        "
        style={{
          background: `
            conic-gradient(
              from 0deg,
              rgba(255,255,255,.95),
              rgba(255,224,138,.95),
              rgba(246,196,83,.95),
              rgba(255,160,60,.85),
              rgba(255,255,255,.95)
            )
          `,
        }}
      />

      {/* Middle Plasma */}
      <motion.div
        animate={{
          rotate: -360,
        }}
        transition={{
          duration: 10,
          repeat: Infinity,
          ease: "linear",
        }}
        className="
          absolute
          h-28
          w-28
          rounded-full
          blur-sm
        "
        style={{
          background: `
            conic-gradient(
              from 180deg,
              rgba(255,255,255,.95),
              rgba(255,230,170,.95),
              rgba(255,190,60,.9),
              rgba(255,255,255,.95)
            )
          `,
        }}
      />

      {/* Glass Shell */}
      <div
        className="
          absolute
          h-24
          w-24
          rounded-full
          border
          border-white/15
          backdrop-blur-xl
        "
        style={{
          background:
            "radial-gradient(circle at 35% 30%, rgba(255,255,255,.35), rgba(255,255,255,.08) 55%, rgba(0,0,0,.15) 100%)",
          boxShadow: `
            inset 0 0 35px rgba(255,255,255,.18),
            0 0 40px rgba(246,196,83,.45),
            0 0 90px rgba(246,196,83,.25)
          `,
        }}
      />

      <FusionParticles />

      {/* Fusion Sphere */}
      <motion.div
        animate={{
          scale: [1, 1.08, 1],
        }}
        transition={{
          duration: 2,
          repeat: Infinity,
          ease: "easeInOut",
        }}
        className="
          relative
          flex
          h-16
          w-16
          items-center
          justify-center
          rounded-full
        "
        style={{
          background:
            "radial-gradient(circle at 30% 25%, #FFFFFF 0%, #FFF3BF 18%, #FFD76E 45%, #F6C453 72%, #D88914 100%)",
          boxShadow: `
            0 0 20px rgba(255,255,255,.8),
            0 0 45px rgba(255,224,138,.8),
            0 0 90px rgba(246,196,83,.6)
          `,
        }}
      >
        {/* White Core */}
        <motion.div
          animate={{
            scale: [0.8, 1.2, 0.8],
            opacity: [0.65, 1, 0.65],
          }}
          transition={{
            duration: 1.4,
            repeat: Infinity,
            ease: "easeInOut",
          }}
          className="
            h-5
            w-5
            rounded-full
            bg-white
          "
          style={{
            boxShadow: `
              0 0 25px rgba(255,255,255,.95),
              0 0 60px rgba(255,255,255,.8)
            `,
          }}
        />

        {/* Specular Highlight */}
        <div
          className="
            absolute
            left-3
            top-2
            h-3
            w-3
            rounded-full
            bg-white/80
            blur-[1px]
          "
        />
      </motion.div>

    </div>
  );
}