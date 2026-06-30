"use client";

import { motion } from "framer-motion";
import { BrainCircuit, Activity, Cpu, Database, Network } from "lucide-react";

export default function SidePanels() {
  return (
    <>
      {/* Left Panel */}
      <motion.div
        initial={{ opacity: 0, x: -50 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ duration: 1, delay: 0.2 }}
        className="absolute left-8 top-1/2 -translate-y-1/2 flex flex-col gap-6"
      >
        <div className="w-64 rounded-2xl border border-white/10 bg-white/5 p-5 backdrop-blur-xl"
             style={{ boxShadow: "0 20px 40px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.1)" }}>
          <div className="flex items-center gap-3 mb-4">
            <Cpu className="text-[#59b7ff]" size={20} />
            <h3 className="text-sm font-semibold tracking-wider text-white">NARRATIVE ENGINE</h3>
          </div>
          
          <div className="flex flex-col gap-3">
            <div className="flex justify-between text-xs text-white/60">
              <span>Deep Analysis</span>
              <span className="text-white/90">94%</span>
            </div>
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/10">
              <div className="h-full w-[94%] bg-[#59b7ff] shadow-[0_0_10px_#59b7ff]" />
            </div>

            <div className="flex justify-between text-xs text-white/60 mt-2">
              <span>Semantic Hook</span>
              <span className="text-white/90">88%</span>
            </div>
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/10">
              <div className="h-full w-[88%] bg-[#f6c453] shadow-[0_0_10px_#f6c453]" />
            </div>
          </div>
        </div>

        <div className="w-64 rounded-2xl border border-white/10 bg-white/5 p-5 backdrop-blur-xl"
             style={{ boxShadow: "0 20px 40px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.1)" }}>
          <div className="flex items-center gap-3 mb-4">
            <Network className="text-[#755bff]" size={20} />
            <h3 className="text-sm font-semibold tracking-wider text-white">ORBITAL ROUTING</h3>
          </div>
          
          <div className="flex flex-col gap-2 text-xs text-white/70">
            <div className="flex justify-between py-1 border-b border-white/5">
              <span>Nodes Active</span>
              <span className="text-white">12</span>
            </div>
            <div className="flex justify-between py-1 border-b border-white/5">
              <span>Packet Loss</span>
              <span className="text-[#f6c453]">0.0%</span>
            </div>
            <div className="flex justify-between py-1">
              <span>Latency</span>
              <span className="text-[#59b7ff]">14ms</span>
            </div>
          </div>
        </div>
      </motion.div>

      {/* Right Panel */}
      <motion.div
        initial={{ opacity: 0, x: 50 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ duration: 1, delay: 0.4 }}
        className="absolute right-8 top-1/2 -translate-y-1/2 flex flex-col gap-6"
      >
        <div className="w-64 rounded-2xl border border-white/10 bg-white/5 p-5 backdrop-blur-xl"
             style={{ boxShadow: "0 20px 40px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.1)" }}>
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              <BrainCircuit className="text-[#f6c453]" size={20} />
              <h3 className="text-sm font-semibold tracking-wider text-white">COGNITION</h3>
            </div>
            <span className="flex h-2 w-2 rounded-full bg-[#f6c453] shadow-[0_0_8px_#f6c453] animate-pulse" />
          </div>
          
          <div className="flex flex-col gap-3">
            <div className="flex items-center gap-3 text-xs text-white/60">
              <div className="flex-1">Pattern Rec</div>
              <div className="w-24 h-1 bg-white/10 rounded-full overflow-hidden">
                <div className="h-full w-[98%] bg-white/80" />
              </div>
            </div>
            <div className="flex items-center gap-3 text-xs text-white/60">
              <div className="flex-1">Logic Gate</div>
              <div className="w-24 h-1 bg-white/10 rounded-full overflow-hidden">
                <div className="h-full w-[85%] bg-white/80" />
              </div>
            </div>
            <div className="flex items-center gap-3 text-xs text-white/60">
              <div className="flex-1">Memory Bus</div>
              <div className="w-24 h-1 bg-white/10 rounded-full overflow-hidden">
                <div className="h-full w-[72%] bg-white/80" />
              </div>
            </div>
          </div>
        </div>

        <div className="w-64 rounded-2xl border border-white/10 bg-white/5 p-5 backdrop-blur-xl"
             style={{ boxShadow: "0 20px 40px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.1)" }}>
          <div className="flex items-center gap-3 mb-4">
            <Activity className="text-white" size={20} />
            <h3 className="text-sm font-semibold tracking-wider text-white">SYSTEM LOAD</h3>
          </div>
          
          <div className="h-16 flex items-end gap-1">
            {[40, 65, 30, 80, 50, 90, 70, 45, 85, 60].map((h, i) => (
              <div key={i} className="flex-1 bg-white/20 rounded-t-sm" style={{ height: `${h}%` }}>
                <div className="w-full bg-[#59b7ff] shadow-[0_0_8px_#59b7ff]" style={{ height: '4px', opacity: h / 100 }} />
              </div>
            ))}
          </div>
        </div>
      </motion.div>
    </>
  );
}
