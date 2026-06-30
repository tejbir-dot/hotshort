"use client";

import { useEffect, useRef } from "react";
import rippleEngine, { Ripple } from "@/engine/RippleEngine";

const CANVAS_SIZE = 700;

export default function RippleLayer() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rippleRef = useRef<Ripple[]>([]);
  const rafRef = useRef<number>(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d", { alpha: true })!;
    canvas.width = CANVAS_SIZE;
    canvas.height = CANVAS_SIZE;

    // Keep local ref in sync (no re-renders)
    const unsub = rippleEngine.subscribe((ripples) => {
      rippleRef.current = ripples;
    });

    function render() {
      ctx.clearRect(0, 0, CANVAS_SIZE, CANVAS_SIZE);

      rippleRef.current.forEach((ripple) => {
        if (ripple.opacity <= 0.01) return;

        const rgb =
          ripple.color.startsWith("#")
            ? `${parseInt(ripple.color.slice(1, 3), 16)},${parseInt(ripple.color.slice(3, 5), 16)},${parseInt(ripple.color.slice(5, 7), 16)}`
            : "246,196,83";

        // Main ring
        ctx.beginPath();
        ctx.arc(ripple.x, ripple.y, ripple.radius, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(${rgb},${ripple.opacity.toFixed(3)})`;
        ctx.lineWidth = 1.5;
        ctx.stroke();

        // Secondary soft ring (slightly larger, more transparent)
        if (ripple.radius > 12) {
          ctx.beginPath();
          ctx.arc(ripple.x, ripple.y, ripple.radius * 1.15, 0, Math.PI * 2);
          ctx.strokeStyle = `rgba(${rgb},${(ripple.opacity * 0.3).toFixed(3)})`;
          ctx.lineWidth = 4;
          ctx.stroke();
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
