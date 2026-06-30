"use client";

import Background from "../background/Background";
import ParticleField from "../particles/ParticleField";
import ReactorCore from "../reactor/ReactorCore";
import NeuralGraph from "../graph/NeuralGraph";
import SidePanels from "./SidePanels";

export default function Dashboard() {
  return (
    <main className="relative h-screen w-screen overflow-hidden bg-[#04060B]">
      {/* Background */}
      <Background />

      {/* Floating particles */}
      <ParticleField />

      {/* Neural Graph - connections, packets, scanner, glow, ripples */}
      <div className="absolute inset-0 flex items-center justify-center">
        <NeuralGraph />
      </div>

      {/* Reactor Core - center orb, rings, glow, pulse */}
      <div className="absolute inset-0 flex items-center justify-center">
        <ReactorCore />
      </div>

      {/* 3D Glassmorphic Side Panels */}
      <SidePanels />

      {/* Ambient Light */}
      <div
        className="
          pointer-events-none
          absolute
          left-1/2
          top-1/2
          h-[900px]
          w-[900px]
          -translate-x-1/2
          -translate-y-1/2
          rounded-full
          blur-[160px]
          opacity-40
        "
        style={{
          background:
            "radial-gradient(circle, rgba(246,196,83,.18) 0%, rgba(117,91,255,.08) 45%, transparent 75%)",
        }}
      />

      {/* Vignette */}
      <div
        className="
          pointer-events-none
          absolute
          inset-0
        "
        style={{
          background:
            "radial-gradient(circle at center, transparent 35%, rgba(4,6,11,.35) 70%, rgba(4,6,11,.95) 100%)",
        }}
      />
    </main>
  );
}
