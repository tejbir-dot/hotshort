import React from "react";

interface FakeCursorProps {
  x: number;
  y: number;
  scale?: number;
  opacity?: number;
  isClicking?: boolean;
}

export const FakeCursor: React.FC<FakeCursorProps> = ({
  x,
  y,
  scale = 1.0,
  opacity = 1.0,
}) => {
  if (opacity <= 0) return null;

  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        transform: `translate(-25%, -25%) scale(${scale})`,
        opacity,
        zIndex: 300,
        pointerEvents: "none",
        filter: "drop-shadow(0 8px 18px rgba(0, 0, 0, 0.75))",
      }}
    >
      {/* Sleek Touch / Pointer Arrow */}
      <svg
        width="46"
        height="46"
        viewBox="0 0 24 24"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        <path
          d="M5.5 3.21V20.8c0 .45.54.67.85.35l4.58-4.58a1 1 0 0 1 .71-.29h6.15c.45 0 .67-.54.35-.85L5.85 2.85A.5.5 0 0 0 5.5 3.21z"
          fill="#FFFFFF"
          stroke="#000000"
          strokeWidth="1.5"
          strokeLinejoin="round"
        />
      </svg>
    </div>
  );
};
