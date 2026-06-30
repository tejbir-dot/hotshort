"use client";

import { motion } from "framer-motion";
import { BrainCircuit } from "lucide-react";

export default function ReactorCenter() {
  return (
    <div className="absolute flex items-center justify-center">

      {/* Deep ambient glow — blue-purple outer */}
      <div
        className="absolute rounded-full"
        style={{
          width: 320,
          height: 320,
          background: "radial-gradient(circle, rgba(80,120,255,0.06) 0%, rgba(117,91,255,0.04) 40%, transparent 70%)",
          filter: "blur(40px)",
        }}
      />

      {/* Outer metallic shell — dark glass */}
      <div
        className="absolute rounded-full"
        style={{
          width: 120,
          height: 120,
          background: "radial-gradient(circle at 35% 28%, rgba(160,180,220,0.08), rgba(30,40,70,0.6) 55%, rgba(10,15,30,0.85) 100%)",
          border: "1px solid rgba(150,180,255,0.15)",
          boxShadow: `
            inset 0 1px 0 rgba(255,255,255,0.08),
            inset 0 -1px 0 rgba(0,0,0,0.5),
            0 0 40px rgba(80,120,255,0.1)
          `,
          backdropFilter: "blur(8px)",
        }}
      />

      {/* Inner metallic sphere */}
      <motion.div
        animate={{ scale: [1, 1.02, 1] }}
        transition={{ duration: 4, repeat: Infinity, ease: "easeInOut" }}
        className="absolute flex items-center justify-center rounded-full"
        style={{
          width: 88,
          height: 88,
          background: "radial-gradient(circle at 32% 26%, rgba(200,215,255,0.15) 0%, rgba(20,28,55,0.9) 50%, rgba(8,12,25,1) 100%)",
          border: "1px solid rgba(120,160,255,0.18)",
          boxShadow: `
            inset 0 2px 4px rgba(200,220,255,0.06),
            0 0 20px rgba(246,196,83,0.12),
            0 0 40px rgba(80,100,255,0.08)
          `,
        }}
      >
        <motion.div
          animate={{ opacity: [0.7, 1, 0.7] }}
          transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
        >
          <BrainCircuit size={32} className="text-[#ffe08a]" style={{ filter: 'drop-shadow(0 0 8px rgba(246,196,83,0.6))' }} strokeWidth={1.5} />
        </motion.div>
      </motion.div>

      {/* Specular highlight — top-left glint */}
      <div
        className="absolute rounded-full"
        style={{
          width: 28,
          height: 18,
          background: "radial-gradient(ellipse, rgba(200,220,255,0.2), transparent 70%)",
          transform: "translate(-18px, -22px)",
          filter: "blur(2px)",
        }}
      />

    </div>
  );
}
