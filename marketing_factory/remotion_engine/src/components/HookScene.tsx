// HookScene.tsx - 0-3.7s viral hook: 3D Spiral Wireframe background + CardFan + ProofCardsPop + AvatarTalker + WordPopSequence + Audio
import React from "react";
import { useVideoConfig, Audio, OffthreadVideo, Sequence, staticFile } from "remotion";
import { CardFan } from "./CardFan";
import { ProofCardsPop, ProofCardItem } from "./ProofCardsPop";
import { AvatarTalker } from "./AvatarTalker";
import { WordPopSequence, WordTimestamp } from "./WordPop";

export interface HookSceneProps {
  words: Array<{ text: string; start: number; end: number; isEmphasis?: boolean }>;
  cards: Array<{ src: string; viewCount: number }>;
  cardPopFrames: [number, number, number];
  proofCards?: ProofCardItem[];
  avatarSlideFrame?: number;
  phaseTransitionFrame?: number;
  avatarVideoSrc?: string;
  audioSrc?: string;
  whooshSfxSrc?: string;
}

// 3D Spiral Wireframe Grid Motion Background (Pure White Lines on Deep Black)
const SpiralWireframeBackground: React.FC = () => {
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        backgroundColor: "#050505",
        overflow: "hidden",
      }}
    >
      {/* 3D Spiral Wireframe Motion Video - Pure monochrome white lines */}
      <OffthreadVideo
        src={staticFile("bg_spiral.mp4")}
        style={{
          width: "104%",
          height: "104%",
          objectFit: "cover",
          transform: "translate(-2%, -2%)",
          opacity: 0.85,
          filter: "grayscale(100%) contrast(1.25) brightness(0.92)",
        }}
        muted
      />
      {/* Pure black depth vignette overlay - zero purple tint */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background:
            "radial-gradient(circle at 50% 40%, rgba(0, 0, 0, 0.08) 0%, rgba(5, 5, 5, 0.90) 85%)",
          pointerEvents: "none",
        }}
      />
    </div>
  );
};

export const HookScene: React.FC<HookSceneProps> = ({
  words,
  cards,
  cardPopFrames,
  proofCards,
  avatarSlideFrame = 3,
  phaseTransitionFrame = 64,
  avatarVideoSrc,
  audioSrc,
  whooshSfxSrc = staticFile("sfx/whoosh_fast.mp3"),
}) => {
  const { fps } = useVideoConfig();

  // Convert word timestamps (seconds) to frames
  const wordFrames: WordTimestamp[] = words.map((w) => ({
    text: w.text,
    startFrame: Math.round(w.start * fps),
    endFrame: Math.round(w.end * fps),
    isEmphasis: w.isEmphasis,
  }));

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        overflow: "hidden",
        width: "100%",
        height: "100%",
        backgroundColor: "#070707",
      }}
    >
      {/* Synced Reference Audio */}
      {audioSrc ? <Audio src={audioSrc} /> : null}

      {/* Transition Whoosh SFX at frame 63 */}
      {whooshSfxSrc && (
        <Sequence from={phaseTransitionFrame - 1} durationInFrames={20}>
          <Audio src={whooshSfxSrc} volume={0.4} />
        </Sequence>
      )}

      {/* Layer 1: 3D Spiral Wireframe background */}
      <SpiralWireframeBackground />

      {/* Layer 2: Phase 1 viral clip card fan (exits at phaseTransitionFrame) */}
      {cards.length === 3 && (
        <CardFan
          cards={cards}
          popFrames={[cardPopFrames[0], cardPopFrames[1], cardPopFrames[2]]}
          exitFrame={phaseTransitionFrame}
        />
      )}

      {/* Layer 3: Phase 2 Proof Cards (cascades in at frames 68, 78, 89 with pop SFX) */}
      <ProofCardsPop cards={proofCards} />

      {/* Layer 4: Avatar at bottom (exits downward at phaseTransitionFrame) */}
      <AvatarTalker
        slideInFrame={avatarSlideFrame}
        exitFrame={phaseTransitionFrame - 1}
        videoSrc={avatarVideoSrc}
      />

      {/* Layer 5: Word captions (z-index 100) — centered over all cards and avatar */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          pointerEvents: "none",
          zIndex: 100,
        }}
      >
        <WordPopSequence words={wordFrames} forceWhite={true} />
      </div>
    </div>
  );
};
