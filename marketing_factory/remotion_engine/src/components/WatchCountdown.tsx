import React from "react";
import {
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

export interface WatchCountdownProps {
  startFrame?: number;
  durationInFrames?: number;
}

export const WatchCountdown: React.FC<WatchCountdownProps> = ({
  startFrame = 0,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const localFrame = frame - startFrame;
  if (localFrame < 0) return null;

  // Snappy spring scale pop entrance
  const popScale = spring({
    frame: localFrame,
    fps,
    config: { damping: 11, stiffness: 220, mass: 0.75 },
    from: 0.2,
    to: 1.0,
  });

  // Countdown time: 01:00 for first 15 frames, then 00:59
  const timeText = localFrame < 15 ? "01:00" : "00:59";

  // Pointing hand spring entry from bottom-left
  const handSpring = spring({
    frame: localFrame - 4,
    fps,
    config: { damping: 12, stiffness: 240 },
    from: 0,
    to: 1,
  });

  const handX = interpolate(handSpring, [0, 1], [-180, -30]);
  const handY = interpolate(handSpring, [0, 1], [150, 40]);
  const handScale = interpolate(handSpring, [0, 1], [0.6, 1.0]);

  // Gentle floating bob
  const bob = Math.sin(localFrame * 0.12) * 6;

  return (
    <div
      style={{
        position: "absolute",
        left: "50%",
        top: "42%",
        transform: `translate(-50%, -50%) translateY(${bob}px) scale(${popScale})`,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 90,
        pointerEvents: "none",
      }}
    >
      {/* Orange Sport Loop Strap (Top & Bottom) */}
      <div
        style={{
          position: "absolute",
          width: 140,
          height: 520,
          backgroundColor: "#FF5722",
          borderRadius: 24,
          boxShadow: "0 10px 30px rgba(255, 87, 34, 0.4)",
          background: "linear-gradient(180deg, #FF6F00 0%, #FF3D00 50%, #E64A19 100%)",
        }}
      />

      {/* Titanium Watch Case */}
      <div
        style={{
          width: 320,
          height: 380,
          backgroundColor: "#1C1C1E",
          borderRadius: 64,
          border: "5px solid #8E8E93",
          boxShadow:
            "0 30px 80px rgba(0, 0, 0, 0.9), inset 0 2px 6px rgba(255, 255, 255, 0.2)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          position: "relative",
          overflow: "hidden",
        }}
      >
        {/* Watch Screen Glass */}
        <div
          style={{
            width: 280,
            height: 340,
            backgroundColor: "#000000",
            borderRadius: 48,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            position: "relative",
          }}
        >
          {/* Subtle Orange Arc Ring */}
          <svg width="220" height="220" viewBox="0 0 100 100">
            <circle
              cx="50"
              cy="50"
              r="42"
              fill="none"
              stroke="rgba(255, 87, 34, 0.2)"
              strokeWidth="6"
            />
            <circle
              cx="50"
              cy="50"
              r="42"
              fill="none"
              stroke="#FF5722"
              strokeWidth="6"
              strokeDasharray="264"
              strokeDashoffset={interpolate(localFrame, [0, 45], [0, 60], {
                extrapolateRight: "clamp",
              })}
              strokeLinecap="round"
              transform="rotate(-90 50 50)"
            />
          </svg>

          {/* Digital Time Counter */}
          <div
            style={{
              position: "absolute",
              fontFamily: "'Montserrat', 'Arial Black', sans-serif",
              fontSize: 48,
              fontWeight: 900,
              color: "#FFFFFF",
              letterSpacing: 1,
              textShadow: "0 0 20px rgba(255, 87, 34, 0.6)",
            }}
          >
            {timeText}
          </div>
        </div>
      </div>

      {/* Cartoon Gloved Pointing Hand */}
      <div
        style={{
          position: "absolute",
          left: handX,
          top: handY,
          transform: `scale(${handScale}) rotate(-12deg)`,
          filter: "drop-shadow(0 15px 30px rgba(0,0,0,0.85))",
          zIndex: 100,
        }}
      >
        <svg width="150" height="150" viewBox="0 0 100 100" fill="none">
          {/* White cartoon glove finger pointing */}
          <path
            d="M 25 80 C 25 65 35 55 50 48 L 78 28 C 82 25 88 28 88 33 C 88 37 84 41 74 48 L 65 54 C 70 53 78 55 78 60 C 78 64 72 67 65 67 C 70 67 75 70 75 74 C 75 78 68 81 60 81 L 45 81 C 32 81 25 85 25 80 Z"
            fill="#FFFFFF"
            stroke="#111111"
            strokeWidth="3.5"
            strokeLinejoin="round"
          />
          {/* Glove seam lines */}
          <path d="M 40 68 L 48 70" stroke="#111111" strokeWidth="2.5" strokeLinecap="round" />
          <path d="M 42 74 L 50 76" stroke="#111111" strokeWidth="2.5" strokeLinecap="round" />
        </svg>
      </div>
    </div>
  );
};
