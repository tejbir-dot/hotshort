import React from "react";
import {
  Audio,
  Img,
  Sequence,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { AvatarTalker } from "./AvatarTalker";
import { WordPopSequence, WordTimestamp } from "./WordPop";

export interface DmBubbleCtaProps {
  words?: Array<{ text: string; start: number; end: number }>;
  audioSrc?: string;
  avatarVideoSrc?: string;
}

export const DmBubbleCta: React.FC<DmBubbleCtaProps> = ({
  words = [],
  audioSrc = staticFile("vo_ref2/vo_scene5.mp3"),
  avatarVideoSrc = staticFile("avatar_animated.webm"),
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Cyan Bubble "AI" pops in at frame 25 (when speaking "AI")
  const userBubbleSpring = spring({
    frame: frame - 25,
    fps,
    config: { damping: 11, stiffness: 220, mass: 0.8 },
    from: 0,
    to: 1,
  });

  // White Reply Bubble "https://hotshort.ai" pops in at frame 48
  const replyBubbleSpring = spring({
    frame: frame - 48,
    fps,
    config: { damping: 11, stiffness: 200, mass: 0.8 },
    from: 0,
    to: 1,
  });

  const wordFrames: WordTimestamp[] = words.map((w) => ({
    text: w.text,
    startFrame: Math.round(w.start * fps),
    endFrame: Math.round(w.end * fps),
  }));

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        backgroundColor: "#070707",
        overflow: "hidden",
        width: "100%",
        height: "100%",
      }}
    >
      {audioSrc && <Audio src={audioSrc} />}

      {/* Pop SFX for Bubbles */}
      <Sequence from={25} durationInFrames={15}>
        <Audio src={staticFile("sfx/pop_bubble.mp3")} volume={0.8} />
      </Sequence>
      <Sequence from={48} durationInFrames={15}>
        <Audio src={staticFile("sfx/pop_bubble.mp3")} volume={0.8} />
      </Sequence>

      {/* 3D Wireframe Waves Background */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background:
            "radial-gradient(circle at 50% 50%, rgba(30, 20, 25, 0.4) 0%, rgba(5, 5, 5, 0.95) 80%)",
        }}
      />

      {/* User Bubble ("AI" Cyan) */}
      {frame >= 25 && (
        <div
          style={{
            position: "absolute",
            right: 80,
            top: 480,
            transform: `scale(${userBubbleSpring})`,
            transformOrigin: "right center",
            zIndex: 120,
            filter: "drop-shadow(0 15px 35px rgba(0, 180, 255, 0.35))",
          }}
        >
          <Img
            src={staticFile("cta_user_bubble.png")}
            style={{ width: 280, height: "auto" }}
          />
        </div>
      )}

      {/* Reply Bubble ("https://hotshort.ai" White) */}
      {frame >= 48 && (
        <div
          style={{
            position: "absolute",
            left: 80,
            top: 620,
            transform: `scale(${replyBubbleSpring})`,
            transformOrigin: "left center",
            zIndex: 120,
            filter: "drop-shadow(0 20px 45px rgba(255, 255, 255, 0.25))",
          }}
        >
          <Img
            src={staticFile("cta_reply_bubble.png")}
            style={{ width: 440, height: "auto" }}
          />
        </div>
      )}

      {/* Avatar at bottom center */}
      <AvatarTalker
        slideInFrame={0}
        exitFrame={999}
        videoSrc={avatarVideoSrc}
      />

      {/* Word Pop Captions */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          pointerEvents: "none",
          zIndex: 140,
        }}
      >
        <WordPopSequence words={wordFrames} forceWhite={true} />
      </div>
    </div>
  );
};
