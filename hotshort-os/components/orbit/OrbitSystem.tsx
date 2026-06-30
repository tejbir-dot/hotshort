"use client";

import { Mic2, BrainCircuit, Flame, Sparkles, Trophy, Scissors, Captions, Film } from "lucide-react";
import { motion } from "framer-motion";
import OrbitNode from "./OrbitNode";

const nodes = [
  {
    label: "Whisper",
    icon: <Mic2 size={22} />,
    angle: -90,
    active: true,
  },
  {
    label: "Semantic",
    icon: <BrainCircuit size={22} />,
    angle: -45,
  },
  {
    label: "Hook",
    icon: <Flame size={22} />,
    angle: 0,
  },
  {
    label: "Curiosity",
    icon: <Sparkles size={22} />,
    angle: 45,
  },
  {
    label: "Ranking",
    icon: <Trophy size={22} />,
    angle: 90,
  },
  {
    label: "Editor",
    icon: <Scissors size={22} />,
    angle: 135,
  },
  {
    label: "Caption",
    icon: <Captions size={22} />,
    angle: 180,
  },
  {
    label: "Render",
    icon: <Film size={22} />,
    angle: 225,
  },
];

export default function OrbitSystem() {
  return (
    <div className="absolute flex items-center justify-center">

      {/* Orbit Nodes */}

      {nodes.map((node) => (
        <OrbitNode
          key={node.label}
          radius={410}
          angle={node.angle}
          label={node.label}
          icon={node.icon}
          active={node.active}
        />
      ))}

      {/* Rotating Energy Beam */}

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
          h-[545px]
          w-[545px]
          rounded-full
        "
        style={{
          background: `
            conic-gradient(
              from 0deg,

              transparent 0deg,

              transparent 320deg,

              rgba(255,224,138,.15) 332deg,

              rgba(246,196,83,.95) 344deg,

              rgba(255,255,255,.95) 350deg,

              rgba(246,196,83,.95) 355deg,

              transparent 360deg
            )
          `,
          WebkitMask:
            "radial-gradient(circle, transparent 97.5%, white 100%)",
          mask:
            "radial-gradient(circle, transparent 97.5%, white 100%)",
          filter: "blur(.4px)",
        }}
      />

      {/* Scanner Glow */}

      <motion.div
        animate={{
          rotate: -360,
        }}
        transition={{
          duration: 14,
          repeat: Infinity,
          ease: "linear",
        }}
        className="
          absolute
          h-[600px]
          w-[600px]
          rounded-full
          blur-3xl
          opacity-30
        "
        style={{
          background: `
            conic-gradient(

              transparent,

              rgba(246,196,83,.15),

              transparent,

              rgba(117,91,255,.12),

              transparent
            )
          `,
          WebkitMask:
            "radial-gradient(circle, transparent 62%, white 70%, transparent 78%)",
        }}
      />
    </div>
  );
}