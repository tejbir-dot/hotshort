import React from "react";
import { useCurrentFrame, useVideoConfig, spring, Video } from "remotion";

interface ActiveWord {
  startFrame: number;
  endFrame: number;
}

interface AvatarTalkerProps {
  slideInFrame?: number;
  exitFrame?: number;
  activeWords?: ActiveWord[];
  spriteSrc?: string;
  videoSrc?: string;
}

export const AvatarTalker: React.FC<AvatarTalkerProps> = ({
  slideInFrame = 3,
  exitFrame = 63,
  videoSrc,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // If avatar has exited past screen edge, unmount cleanly
  if (frame >= exitFrame + 10) return null;

  const localFrame = Math.max(0, frame - slideInFrame);

  // Slide-up spring entrance
  const ySpring = spring({
    frame: localFrame,
    fps,
    config: { damping: 18, stiffness: 260, mass: 0.7 },
    from: 350,
    to: 0,
  });

  // Slide-down exit when Phase 2 starts
  const yExit =
    frame >= exitFrame
      ? spring({
          frame: frame - exitFrame,
          fps,
          config: { damping: 16, stiffness: 220, mass: 0.7 },
          from: 0,
          to: 850,
        })
      : 0;

  return (
    <div
      style={{
        position: "absolute",
        bottom: -440, // anchors avatar firmly with hips cropped off-screen
        left: "50%",
        transform: `translateX(-50%) translateY(${ySpring + yExit}px)`,
        width: 830, // broad, big avatar filling bottom third
        height: 1475, // natural proportional height (830 * 1280 / 720)
        zIndex: 25,
        pointerEvents: "none",
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "center",
        opacity: frame < slideInFrame ? 0 : 1,
      }}
    >
      {videoSrc ? (
        <Video
          src={videoSrc}
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
          }}
        />
      ) : null}
    </div>
  );
};
