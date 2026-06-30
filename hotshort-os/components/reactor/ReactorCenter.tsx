"use client";

import { motion } from "framer-motion";
import { BrainCircuit } from "lucide-react";

export default function ReactorCenter() {
  return (
    <div className="absolute flex items-center justify-center">

      {/* Deep ambient background glow */}
      <div
        className="absolute rounded-full"
        style={{
          width: 500,
          height: 500,
          background: "radial-gradient(circle, rgba(117,91,255,0.06) 0%, transparent 60%)",
          filter: "blur(40px)",
        }}
      />

      {/* Massive Glassmorphic Outer Bevel (The Base) */}
      <div
        className="absolute rounded-full"
        style={{
          width: 280,
          height: 280,
          background: "radial-gradient(circle at 50% 0%, rgba(160,180,220,0.06), rgba(10,15,30,0.8) 60%, rgba(5,10,20,0.95) 100%)",
          border: "1px solid rgba(150,180,255,0.08)",
          boxShadow: `
            inset 0 2px 20px rgba(255,255,255,0.03),
            inset 0 -2px 20px rgba(0,0,0,0.8),
            0 20px 50px rgba(0,0,0,0.5)
          `,
          backdropFilter: "blur(12px)",
        }}
      />

      {/* The Thick Metallic Ring */}
      <motion.div
        className="absolute rounded-full"
        style={{
          width: 220,
          height: 220,
          background: "radial-gradient(circle at 30% 20%, rgba(40,60,100,0.4), rgba(10,15,30,1) 80%)",
          boxShadow: `
            inset 0 1px 2px rgba(200,220,255,0.2),
            inset 0 -2px 10px rgba(0,0,0,0.9),
            0 0 10px rgba(0,0,0,0.8),
            0 0 30px rgba(80,120,255,0.1)
          `,
          border: "2px solid rgba(200,220,255,0.1)",
        }}
      />

      {/* Inner Glowing Core Chamber */}
      <motion.div
        animate={{ scale: [1, 1.01, 1] }}
        transition={{ duration: 4, repeat: Infinity, ease: "easeInOut" }}
        className="absolute flex items-center justify-center rounded-full"
        style={{
          width: 170,
          height: 170,
          background: "radial-gradient(circle at 50% 50%, rgba(20,30,50,0.9) 0%, rgba(5,8,15,1) 100%)",
          border: "1px solid rgba(246,196,83,0.3)",
          boxShadow: `
            inset 0 0 30px rgba(246,196,83,0.1),
            inset 0 5px 15px rgba(255,255,255,0.05),
            0 0 40px rgba(246,196,83,0.15)
          `,
        }}
      >
        {/* Core Icon / Entity */}
        <motion.div
          animate={{ opacity: [0.7, 1, 0.7], scale: [0.95, 1.05, 0.95] }}
          transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
          className="relative flex items-center justify-center"
        >
          {/* Intense golden backdrop for the icon */}
          <div className="absolute w-20 h-20 bg-[#f6c453] rounded-full opacity-20 blur-xl" />
          
          <BrainCircuit 
            size={64} 
            className="text-[#ffe08a]" 
            style={{ filter: 'drop-shadow(0 0 15px rgba(246,196,83,0.8)) drop-shadow(0 0 30px rgba(246,196,83,0.4))' }} 
            strokeWidth={1.2} 
          />
        </motion.div>
      </motion.div>

      {/* High-End Glass Reflection (Top Arch) */}
      <div
        className="absolute rounded-full pointer-events-none"
        style={{
          width: 270,
          height: 130,
          top: "calc(50% - 135px)",
          background: "linear-gradient(180deg, rgba(255,255,255,0.08) 0%, transparent 100%)",
          borderTop: "1px solid rgba(255,255,255,0.2)",
          maskImage: "radial-gradient(ellipse 100% 100% at 50% 0%, black 40%, transparent 70%)",
          WebkitMaskImage: "radial-gradient(ellipse 100% 100% at 50% 0%, black 40%, transparent 70%)",
        }}
      />

    </div>
  );
}
