"use client";

import { useEffect, useRef } from "react";
import ConnectionLayer from "./ConnectionLayer";
import PacketLayer from "./PacketLayer";
import ScannerLayer from "./ScannerLayer";
import GlowLayer from "./GlowLayer";
import RippleLayer from "./RippleLayer";
import FocusLayer from "./FocusLayer";
import cameraEngine from "@/engine/CameraEngine";

// Idle neural activity — keeps the graph alive without real data
import neuralFlowEngine from "@/engine/NeuralFlowEngine";
import packetScheduler from "@/engine/PacketScheduler";
import eventBus from "@/engine/EventBus";

// Boot idle simulation
function bootIdleSimulation() {
  const pipeline = [
    { event: "WHISPER_STARTED" as const, delay: 800 },
    { event: "TRANSCRIPT_READY" as const, delay: 2400 },
    { event: "HOOK_DETECTED" as const, delay: 3800 },
    { event: "RANKING_UPDATED" as const, delay: 5000 },
    { event: "EDITOR_STARTED" as const, delay: 6200 },
    { event: "RENDER_STARTED" as const, delay: 7800 },
    { event: "RENDER_FINISHED" as const, delay: 9400 },
  ];

  let offset = 0;
  function runCycle() {
    pipeline.forEach(({ event, delay }) => {
      setTimeout(() => eventBus.emit(event), offset + delay);
    });
    // Restart cycle every 14 seconds
    offset = 0;
    setTimeout(runCycle, 14000);
  }

  setTimeout(runCycle, 1200);
}

export default function NeuralGraph() {
  const containerRef = useRef<HTMLDivElement>(null);

  // Camera drift applied to root container via direct DOM mutation
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const unsub = cameraEngine.subscribe((cam) => {
      container.style.transform = `translate(${cam.x.toFixed(2)}px, ${cam.y.toFixed(2)}px) scale(${cam.scale.toFixed(5)})`;
    });

    return () => unsub();
  }, []);

  // Boot idle neural activity on mount
  useEffect(() => {
    bootIdleSimulation();
  }, []);

  return (
    <div
      ref={containerRef}
      className="absolute inset-0 pointer-events-none"
      style={{ willChange: "transform" }}
    >
      {/* Layer order: deepest → topmost */}

      {/* 1. Per-node ambient glow blobs */}
      <GlowLayer />

      {/* 2. Bezier connection curves */}
      <ConnectionLayer />

      {/* 3. Ripple pulses on nodes */}
      <RippleLayer />

      {/* 4. Live data packets (canvas) */}
      <PacketLayer />

      {/* 5. Rotating scanner beam */}
      <ScannerLayer />

      {/* 6. Focus highlight ring for scanner-active node */}
      <FocusLayer />
    </div>
  );
}
