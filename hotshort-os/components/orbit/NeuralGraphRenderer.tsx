"use client";

import ConnectionLines from "./ConnectionLines";
import PacketRenderer from "./PacketRenderer";
import EnergyPackets from "./EnergyPackets";
import OrbitSystem from "./OrbitSystem";

export default function NeuralGraphRenderer() {
  return (
    <div
      className="
        absolute
        left-1/2
        top-1/2
        -translate-x-1/2
        -translate-y-1/2
        w-[700px]
        h-[700px]
        pointer-events-none
      "
    >
      {/* Neural Network */}
      <ConnectionLines />

      {/* Live Packets */}
      <PacketRenderer />

      {/* Ambient Orbit Packets */}
      <EnergyPackets radius={270} />

      {/* Orbit Nodes */}
      <OrbitSystem />

      {/* Scanner */}
      <div
        className="
          absolute
          inset-0
          rounded-full
          overflow-hidden
        "
      >
        <div
          className="
            scanner-beam
            absolute
            left-1/2
            top-1/2
            h-[700px]
            w-[700px]
            -translate-x-1/2
            -translate-y-1/2
            rounded-full
          "
        />
      </div>

      {/* Core Ripple */}
      <div className="absolute inset-0 flex items-center justify-center">
        <div className="reactor-ripple" />
      </div>

      {/* Outer Glow */}
      <div
        className="
          absolute
          left-1/2
          top-1/2
          h-[760px]
          w-[760px]
          -translate-x-1/2
          -translate-y-1/2
          rounded-full
          blur-[120px]
          opacity-20
        "
        style={{
          background:
            "radial-gradient(circle, rgba(246,196,83,.22), transparent 72%)",
        }}
      />
    </div>
  );
}