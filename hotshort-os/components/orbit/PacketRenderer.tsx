"use client";

import { motion } from "framer-motion";
import usePackets from "@/hooks/usePackets";
import flowField from "@/engine/FlowField";

export default function PacketRenderer() {
  const { packets } = usePackets();

  return (
    <svg
      className="absolute overflow-visible pointer-events-none"
      width="640"
      height="640"
      viewBox="0 0 640 640"
    >
      {packets.map((packet) => {
        const { x, y } = flowField.getPoint(
          packet.from,
          packet.to,
          packet.progress
        );

        const angle = flowField.getDirection(
          packet.from,
          packet.to,
          packet.progress
        );

        return (
          <g
            key={packet.id}
            transform={`translate(${x},${y}) rotate(${angle})`}
          >
            {/* Glow */}
            <motion.circle
              cx={0}
              cy={0}
              r={packet.size * 3}
              fill={packet.color}
              opacity=".18"
              animate={{
                r: [
                  packet.size * 2,
                  packet.size * 4,
                  packet.size * 2,
                ],
              }}
              transition={{
                duration: 0.8,
                repeat: Infinity,
              }}
            />

            {/* Packet */}
            <circle
              cx={0}
              cy={0}
              r={packet.size}
              fill={packet.color}
              style={{
                filter: `
                  drop-shadow(0 0 10px ${packet.color})
                  drop-shadow(0 0 18px ${packet.color})
                `,
              }}
            />

            {/* Tail */}
            <line
              x1={0}
              y1={0}
              x2={-20}
              y2={0}
              stroke={packet.color}
              strokeWidth="2"
              strokeLinecap="round"
              opacity=".6"
            />
          </g>
        );
      })}
    </svg>
  );
}