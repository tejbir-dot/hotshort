"use client";

import { useEffect, useRef } from "react";
import packetEngine, { Packet } from "@/engine/PacketEngine";
import flowField from "@/engine/FlowField";

const CANVAS_SIZE = 700;
const TRAIL_LENGTH = 18;

interface TrailPoint {
  x: number;
  y: number;
  opacity: number;
}

interface RenderPacket extends Packet {
  trail: TrailPoint[];
  arrivalFlash: number; // 0-1, 1 = just arrived
}

function hexToRgb(hex: string) {
  const r = parseInt(hex.slice(1, 3), 16) || 255;
  const g = parseInt(hex.slice(3, 5), 16) || 224;
  const b = parseInt(hex.slice(5, 7), 16) || 138;
  return `${r},${g},${b}`;
}

export default function PacketLayer() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const packetsRef = useRef<Map<string, RenderPacket>>(new Map());
  const rafRef = useRef<number>(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d", { alpha: true })!;
    canvas.width = CANVAS_SIZE;
    canvas.height = CANVAS_SIZE;

    // Sync with PacketEngine
    const unsub = packetEngine.subscribe((packets) => {
      const existing = packetsRef.current;

      // Remove completed packets
      const activeIds = new Set(packets.map((p) => p.id));
      existing.forEach((_, id) => {
        if (!activeIds.has(id)) existing.delete(id);
      });

      // Add new packets
      packets.forEach((p) => {
        if (!existing.has(p.id)) {
          existing.set(p.id, { ...p, trail: [], arrivalFlash: 0 });
        }
      });

      // Update progress
      packets.forEach((p) => {
        const rp = existing.get(p.id);
        if (!rp) return;

        const prev = flowField.getPoint(p.from, p.to, Math.max(p.progress - 0.02, 0));
        const curr = flowField.getPoint(p.from, p.to, p.progress);

        // Build trail
        rp.trail.unshift({ x: prev.x + CANVAS_SIZE / 2, y: prev.y + CANVAS_SIZE / 2, opacity: 1 });
        if (rp.trail.length > TRAIL_LENGTH) rp.trail.pop();
        rp.trail.forEach((pt, i) => {
          pt.opacity = (1 - i / TRAIL_LENGTH) * 0.6;
        });

        rp.progress = p.progress;

        // Arrival flash
        if (p.progress >= 0.98 && rp.arrivalFlash === 0) {
          rp.arrivalFlash = 1;
        }
      });
    });

    // RAF render loop
    function render() {
      ctx.clearRect(0, 0, CANVAS_SIZE, CANVAS_SIZE);

      packetsRef.current.forEach((packet) => {
        const progress = Math.min(packet.progress, 1);
        const pos = flowField.getPoint(packet.from, packet.to, progress);
        const dir = flowField.getDirection(packet.from, packet.to, progress);

        // Convert to canvas coords
        const cx = pos.x + CANVAS_SIZE / 2;
        const cy = pos.y + CANVAS_SIZE / 2;
        const angleRad = (dir * Math.PI) / 180;

        const rgb = hexToRgb(packet.color);

        // --- Trail ---
        if (packet.trail.length > 1) {
          for (let i = 0; i < packet.trail.length - 1; i++) {
            const a = packet.trail[i];
            const b = packet.trail[i + 1];
            ctx.beginPath();
            ctx.moveTo(a.x, a.y);
            ctx.lineTo(b.x, b.y);
            const trailAlpha = a.opacity * (1 - i / packet.trail.length);
            ctx.strokeStyle = `rgba(${rgb},${trailAlpha.toFixed(3)})`;
            ctx.lineWidth = packet.size * (1 - i / packet.trail.length) * 0.8;
            ctx.lineCap = "round";
            ctx.stroke();
          }
        }

        // --- Outer glow ---
        const glowGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, packet.size * 8);
        glowGrad.addColorStop(0, `rgba(${rgb},0.28)`);
        glowGrad.addColorStop(1, `rgba(${rgb},0)`);
        ctx.beginPath();
        ctx.arc(cx, cy, packet.size * 8, 0, Math.PI * 2);
        ctx.fillStyle = glowGrad;
        ctx.fill();

        // --- Tail line (in heading direction) ---
        ctx.save();
        ctx.translate(cx, cy);
        ctx.rotate(angleRad);
        const tailGrad = ctx.createLinearGradient(-22, 0, 0, 0);
        tailGrad.addColorStop(0, `rgba(${rgb},0)`);
        tailGrad.addColorStop(1, `rgba(${rgb},0.85)`);
        ctx.beginPath();
        ctx.moveTo(-22, 0);
        ctx.lineTo(0, 0);
        ctx.strokeStyle = tailGrad;
        ctx.lineWidth = packet.size * 0.9;
        ctx.lineCap = "round";
        ctx.stroke();
        ctx.restore();

        // --- Core packet dot ---
        const coreGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, packet.size);
        coreGrad.addColorStop(0, "#FFFFFF");
        coreGrad.addColorStop(0.4, `rgba(${rgb},1)`);
        coreGrad.addColorStop(1, `rgba(${rgb},0.4)`);
        ctx.beginPath();
        ctx.arc(cx, cy, packet.size, 0, Math.PI * 2);
        ctx.fillStyle = coreGrad;
        ctx.fill();

        // --- Arrival flash ---
        if (packet.arrivalFlash > 0) {
          const flashR = (1 - packet.arrivalFlash) * 50;
          const flashGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, flashR);
          flashGrad.addColorStop(0, `rgba(${rgb},${(packet.arrivalFlash * 0.9).toFixed(3)})`);
          flashGrad.addColorStop(1, `rgba(${rgb},0)`);
          ctx.beginPath();
          ctx.arc(cx, cy, flashR, 0, Math.PI * 2);
          ctx.fillStyle = flashGrad;
          ctx.fill();
          packet.arrivalFlash = Math.max(0, packet.arrivalFlash - 0.04);
        }
      });

      rafRef.current = requestAnimationFrame(render);
    }

    rafRef.current = requestAnimationFrame(render);

    return () => {
      unsub();
      cancelAnimationFrame(rafRef.current);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className="absolute pointer-events-none"
      style={{
        left: "50%",
        top: "50%",
        transform: "translate(-50%,-50%)",
        width: CANVAS_SIZE,
        height: CANVAS_SIZE,
      }}
    />
  );
}
