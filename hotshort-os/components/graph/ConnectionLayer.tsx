"use client";

import { useEffect, useRef } from "react";
import nodeRegistry from "@/engine/NodeRegistry";
import graphLayout from "@/engine/GraphLayout";
import nodeAnimationEngine from "@/engine/NodeAnimationEngine";
import animationClock from "@/engine/AnimationClock";

const SVG_SIZE = 640;
const CENTER = SVG_SIZE / 2;

export default function ConnectionLayer() {
  const svgRef = useRef<SVGSVGElement>(null);
  const pathRefs = useRef<Map<string, SVGPathElement>>(new Map());
  const glowRefs = useRef<Map<string, SVGPathElement>>(new Map());

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;

    // Build paths from graph layout (once, connections are static)
    const nodes = nodeRegistry.getAll();

    nodes.forEach((node) => {
      node.connections.forEach((targetId) => {
        const key = `${node.id}->${targetId}`;
        if (pathRefs.current.has(key)) return;

        const bezier = graphLayout.getBezier(node.id, targetId);
        if (!bezier) return;

        // Glow path (thick, blurred)
        const glowPath = document.createElementNS(
          "http://www.w3.org/2000/svg",
          "path"
        );
        glowPath.setAttribute("d", bezier.path);
        glowPath.setAttribute("fill", "none");
        glowPath.setAttribute("stroke", "#FFE08A");
        glowPath.setAttribute("stroke-width", "4");
        glowPath.setAttribute("stroke-linecap", "round");
        glowPath.setAttribute("opacity", "0.06");
        glowPath.setAttribute("filter", "url(#connection-blur)");
        svg.appendChild(glowPath);
        glowRefs.current.set(key, glowPath);

        // Main path (crisp, thin)
        const path = document.createElementNS(
          "http://www.w3.org/2000/svg",
          "path"
        );
        path.setAttribute("d", bezier.path);
        path.setAttribute("fill", "none");
        path.setAttribute("stroke", "rgba(255,255,255,0.15)");
        path.setAttribute("stroke-width", "1");
        path.setAttribute("stroke-linecap", "round");
        path.setAttribute("stroke-dasharray", "5 9");

        // Animated dash offset
        const length = 200; // approx
        path.style.strokeDashoffset = "0";

        svg.appendChild(path);
        pathRefs.current.set(key, path);
      });
    });

    // RAF loop — directly mutate stroke opacity based on engine state
    const unsub = animationClock.subscribe(() => {
      nodes.forEach((node) => {
        node.connections.forEach((targetId) => {
          const key = `${node.id}->${targetId}`;
          const path = pathRefs.current.get(key);
          const glow = glowRefs.current.get(key);
          if (!path || !glow) return;

          const fromState = nodeAnimationEngine.getState(node.id);
          const toState = nodeAnimationEngine.getState(targetId);

          const fromEnergy = fromState?.glowIntensity ?? 0.18;
          const toEnergy = toState?.glowIntensity ?? 0.18;
          const energy = (fromEnergy + toEnergy) / 2;

          const baseOpacity = 0.08 + energy * 0.35;
          const glowOpacity = energy * 0.18;

          path.setAttribute(
            "stroke",
            `rgba(255,255,255,${baseOpacity.toFixed(3)})`
          );
          glow.setAttribute("opacity", glowOpacity.toFixed(3));

          // Scroll dash offset
          const current =
            parseFloat(path.style.strokeDashoffset || "0") - 0.4;
          path.style.strokeDashoffset = String(current);
        });
      });
    });

    return () => {
      unsub();
      // Cleanup SVG children on unmount
      pathRefs.current.forEach((el) => el.remove());
      glowRefs.current.forEach((el) => el.remove());
      pathRefs.current.clear();
      glowRefs.current.clear();
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
    >
      <defs>
        <filter id="connection-blur" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="6" />
        </filter>
      </defs>
    </svg>
  );
}
