"use client";

import { useEffect, useRef } from "react";
import scannerEngine from "@/engine/ScannerEngine";
import graphLayout from "@/engine/GraphLayout";
import nodeRegistry from "@/engine/NodeRegistry";

const SVG_SIZE = 700;
const CENTER = SVG_SIZE / 2;

export default function FocusLayer() {
  const svgRef = useRef<SVGSVGElement>(null);
  const ringMap = useRef<Map<string, SVGCircleElement>>(new Map());
  const prevActive = useRef<string | null>(null);

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;

    const nodes = nodeRegistry.getAll().filter((n) => n.radius > 0);

    // Create a focus ring per node (hidden by default)
    nodes.forEach((node) => {
      const point = graphLayout.getNode(node.id);
      if (!point) return;

      const cx = CENTER + point.x;
      const cy = CENTER + point.y;

      const ring = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      ring.setAttribute("cx", String(cx));
      ring.setAttribute("cy", String(cy));
      ring.setAttribute("r", "38");
      ring.setAttribute("fill", "none");
      ring.setAttribute("stroke", "rgba(255,255,255,0)");
      ring.setAttribute("stroke-width", "1.2");
      ring.setAttribute("stroke-dasharray", "4 8");
      svg.appendChild(ring);
      ringMap.current.set(node.id, ring);
    });

    const unsub = scannerEngine.subscribe((state) => {
      // Fade out previous
      if (prevActive.current && prevActive.current !== state.activeNodeId) {
        const prev = ringMap.current.get(prevActive.current);
        if (prev) prev.setAttribute("stroke", "rgba(255,255,255,0)");
      }

      // Light up current
      if (state.activeNodeId) {
        const ring = ringMap.current.get(state.activeNodeId);
        if (ring) {
          ring.setAttribute("stroke", "rgba(246,196,83,0.55)");
          ring.setAttribute("r", "40");
        }
      }

      prevActive.current = state.activeNodeId;
    });

    return () => {
      unsub();
      ringMap.current.forEach((el) => el.remove());
      ringMap.current.clear();
    };
  }, []);

  return (
    <svg
      ref={svgRef}
      className="absolute overflow-visible pointer-events-none"
      width={SVG_SIZE}
      height={SVG_SIZE}
      viewBox={`0 0 ${SVG_SIZE} ${SVG_SIZE}`}
      style={{ left: "50%", top: "50%", transform: "translate(-50%,-50%)" }}
    />
  );
}
