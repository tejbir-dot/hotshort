"use client";

import { useEffect, useRef } from "react";
import glowEngine from "@/engine/GlowEngine";
import graphLayout from "@/engine/GraphLayout";
import nodeRegistry from "@/engine/NodeRegistry";

const CENTER_OFFSET = 350; // half the container (700px)

export default function GlowLayer() {
  const containerRef = useRef<HTMLDivElement>(null);
  const glowDivs = useRef<Map<string, HTMLDivElement>>(new Map());

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const nodes = nodeRegistry.getAll();

    // Create one glow div per node (once)
    nodes.forEach((node) => {
      if (glowDivs.current.has(node.id)) return;

      const point = graphLayout.getNode(node.id);
      if (!point) return;

      const div = document.createElement("div");
      div.style.position = "absolute";
      div.style.borderRadius = "50%";
      div.style.pointerEvents = "none";
      div.style.willChange = "transform, opacity, width, height, background";

      // Position at node center
      const x = CENTER_OFFSET + point.x;
      const y = CENTER_OFFSET + point.y;
      div.style.left = `${x}px`;
      div.style.top = `${y}px`;
      div.style.transform = "translate(-50%,-50%)";

      container.appendChild(div);
      glowDivs.current.set(node.id, div);
    });

    // Subscribe to GlowEngine and mutate DOM directly
    const unsub = glowEngine.subscribe((glowMap) => {
      glowMap.forEach((glow, nodeId) => {
        const div = glowDivs.current.get(nodeId);
        if (!div) return;

        const size = glow.radius * 2;
        div.style.width = `${size}px`;
        div.style.height = `${size}px`;
        div.style.opacity = glow.intensity.toFixed(3);
        div.style.background = `radial-gradient(circle, ${glow.color}33 0%, ${glow.color}11 40%, transparent 72%)`;
        div.style.filter = `blur(${glow.bloom.toFixed(1)}px)`;
      });
    });

    return () => {
      unsub();
      glowDivs.current.forEach((div) => div.remove());
      glowDivs.current.clear();
    };
  }, []);

  return (
    <div
      ref={containerRef}
      className="absolute inset-0 pointer-events-none overflow-hidden"
    />
  );
}
