import React from "react";
import { useCurrentFrame, useVideoConfig, spring, interpolate, Img, OffthreadVideo } from "remotion";

interface CardProps {
  src: string;
  viewCount: number;
  isCenter?: boolean;
  popStartFrame: number;
  exitFrame?: number;
  rotation: number;
  x: number;
}

function formatViews(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(0) + "K";
  return String(n);
}

const SingleCard: React.FC<CardProps> = ({
  src,
  viewCount,
  isCenter = false,
  popStartFrame,
  exitFrame = 64,
  rotation,
  x,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  if (frame < popStartFrame) return null;
  if (frame >= exitFrame + 6) return null;

  const localFrame = frame - popStartFrame;

  // Spring drop from top with overshoot
  const ySpring = spring({
    frame: localFrame,
    fps,
    config: { damping: isCenter ? 11 : 13, stiffness: isCenter ? 230 : 200, mass: 0.8 },
    from: -650,
    to: 0,
  });

  const scaleSpring = spring({
    frame: localFrame,
    fps,
    config: { damping: 11, stiffness: 220, mass: 0.8 },
    from: 0.35,
    to: 1.0,
  });

  // Fast exit animation
  const exitScale = frame >= exitFrame ? interpolate(frame, [exitFrame, exitFrame + 5], [1, 0.4], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) : 1;
  const exitOpacity = frame >= exitFrame ? interpolate(frame, [exitFrame, exitFrame + 5], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) : 1;
  const exitY = frame >= exitFrame ? interpolate(frame, [exitFrame, exitFrame + 5], [0, -350], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) : 0;

  // Floating organic bobbing after landing
  const bob = Math.sin((frame + (isCenter ? 10 : 0)) * 0.09) * 8;

  // View counter ticker
  const tickEnd = 45;
  const progress = interpolate(localFrame, [0, tickEnd], [0, 1], {
    extrapolateRight: "clamp",
    easing: (t) => t * t,
  });
  const displayViews = Math.floor(progress * viewCount);

  const w = isCenter ? 330 : 275;
  const h = isCenter ? 570 : 475;

  const isVideo = src.endsWith(".mp4") || src.endsWith(".webm");

  return (
    <div
      style={{
        position: "absolute",
        left: "50%",
        top: "28.5%",
        transform: `translate(calc(-50% + ${x}px), calc(-50% + ${ySpring + bob + exitY}px)) rotate(${rotation}deg) scale(${scaleSpring * exitScale})`,
        opacity: exitOpacity,
        width: w,
        height: h,
        borderRadius: 28,
        border: `${isCenter ? 4 : 2.5}px solid rgba(255,255,255,${isCenter ? 0.95 : 0.65})`,
        overflow: "hidden",
        boxShadow: `0 ${isCenter ? 32 : 18}px ${isCenter ? 65 : 36}px rgba(0,0,0,0.8), 0 0 ${isCenter ? 25 : 10}px rgba(255,255,255,${isCenter ? 0.18 : 0.05})`,
        zIndex: isCenter ? 10 : 5,
        backgroundColor: "#111",
      }}
    >
      {isVideo ? (
        <OffthreadVideo
          src={src}
          style={{ width: "100%", height: "100%", objectFit: "cover" }}
          muted
        />
      ) : (
        <Img src={src} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
      )}

      {isCenter && (
        <div
          style={{
            position: "absolute",
            top: 18,
            left: 18,
            fontFamily: "'Impact', 'Arial Black', sans-serif",
            fontSize: 26,
            fontWeight: 900,
            color: "#ffffff",
            letterSpacing: 2,
            padding: "4px 14px",
            background: "linear-gradient(135deg, #ff1a3c, #ff4d00)",
            borderRadius: 8,
            boxShadow: "0 4px 14px rgba(255,26,60,0.5)",
            border: "1.5px solid rgba(255,255,255,0.4)",
            zIndex: 12,
          }}
        >
          VIRAL
        </div>
      )}

      {/* View counter pill - Item 7: min 28px readable text */}
      <div
        style={{
          position: "absolute",
          bottom: 16,
          left: "50%",
          transform: "translateX(-50%)",
          background: "rgba(10, 10, 14, 0.94)",
          border: "2px solid rgba(255, 255, 255, 0.38)",
          borderRadius: 100,
          padding: "8px 24px",
          display: "flex",
          alignItems: "center",
          gap: 10,
          whiteSpace: "nowrap",
          boxShadow: "0 8px 24px rgba(0, 0, 0, 0.75)",
        }}
      >
        <div
          style={{
            width: 0,
            height: 0,
            borderTop: "8px solid transparent",
            borderBottom: "8px solid transparent",
            borderLeft: "13px solid #ffffff",
          }}
        />
        <span
          style={{
            fontFamily: "'Montserrat', 'Arial Black', sans-serif",
            fontSize: 30, // >= 28px per rule 7
            fontWeight: 900,
            color: "#ffffff",
            letterSpacing: 1,
            textShadow: "0 2px 4px rgba(0,0,0,0.8)",
          }}
        >
          {formatViews(displayViews)}
        </span>
      </div>
    </div>
  );
};

interface CardFanProps {
  cards: Array<{ src: string; viewCount: number }>;
  popFrames: [number, number, number];
  exitFrame?: number;
}

export const CardFan: React.FC<CardFanProps> = ({ cards, popFrames, exitFrame = 64 }) => {
  const positions = [
    { x: -300, rotation: -6.5 },
    { x: 0, rotation: 0 },
    { x: 300, rotation: 6.5 },
  ];
  return (
    <>
      {cards.map((card, i) => (
        <SingleCard
          key={i}
          src={card.src}
          viewCount={card.viewCount}
          isCenter={i === 1}
          popStartFrame={popFrames[i]}
          exitFrame={exitFrame}
          rotation={positions[i].rotation}
          x={positions[i].x}
        />
      ))}
    </>
  );
};
