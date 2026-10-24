import React from "react";
import {
  useCurrentFrame,
  useVideoConfig,
  spring,
  OffthreadVideo,
  Sequence,
  Audio,
  staticFile,
} from "remotion";

export interface ProofCardItem {
  src: string;
  popFrame: number;
  x: number; // left offset in 1080x1920
  y: number; // top offset in 1080x1920
  width: number;
  height: number;
  rotation: number;
  pinned?: boolean;
  views: string;
  zIndex: number;
  sfxSrc?: string;
}

interface SingleProofCardProps {
  card: ProofCardItem;
  index: number;
}

const SingleProofCard: React.FC<SingleProofCardProps> = ({ card, index }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  if (frame < card.popFrame) return null;

  const localFrame = frame - card.popFrame;

  // Snappy spring pop entrance with overshoot
  const scale = spring({
    frame: localFrame,
    fps,
    config: { damping: 11, stiffness: 240, mass: 0.75 },
    from: 0.35,
    to: 1.0,
  });

  // Dynamic rotation spring: starts with exaggerated tilt and settles
  const rotation = spring({
    frame: localFrame,
    fps,
    config: { damping: 12, stiffness: 220, mass: 0.75 },
    from: card.rotation * 2.2,
    to: card.rotation,
  });

  // Subtle organic float after landing
  const bob = Math.sin((localFrame + index * 18) * 0.08) * 4;

  return (
    <div
      style={{
        position: "absolute",
        left: card.x,
        top: card.y,
        width: card.width,
        height: card.height,
        borderRadius: 36,
        border: "3.5px solid rgba(255, 255, 255, 0.9)",
        overflow: "hidden",
        boxShadow:
          "0 22px 55px rgba(0, 0, 0, 0.8), 0 0 15px rgba(255, 255, 255, 0.08)",
        backgroundColor: "#111111",
        zIndex: card.zIndex,
        transformOrigin: "center center",
        transform: `translateY(${bob}px) rotate(${rotation}deg) scale(${scale})`,
      }}
    >
      {/* Video Content */}
      <OffthreadVideo
        src={card.src}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
        }}
        muted
      />

      {/* Pinned Badge (Top Left) */}
      {card.pinned && (
        <div
          style={{
            position: "absolute",
            top: 20,
            left: 20,
            background: "#E6004D",
            borderRadius: 8,
            padding: "5px 16px",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            boxShadow: "0 4px 12px rgba(230, 0, 77, 0.4)",
            zIndex: 10,
          }}
        >
          <span
            style={{
              fontFamily: "'Montserrat', 'Arial Black', sans-serif",
              fontSize: 24,
              fontWeight: 800,
              color: "#FFFFFF",
              letterSpacing: 0.5,
            }}
          >
            Pinned
          </span>
        </div>
      )}

      {/* Views Counter Overlay (Bottom Left) */}
      <div
        style={{
          position: "absolute",
          bottom: 22,
          left: 24,
          display: "flex",
          alignItems: "center",
          gap: 10,
          zIndex: 10,
          filter: "drop-shadow(0 2px 8px rgba(0,0,0,0.9))",
        }}
      >
        {/* Play triangle outline */}
        <svg width="26" height="26" viewBox="0 0 24 24" fill="none">
          <polygon
            points="6,3 20,12 6,21"
            stroke="#FFFFFF"
            strokeWidth="2.5"
            strokeLinejoin="round"
            fill="none"
          />
        </svg>
        <span
          style={{
            fontFamily: "'Montserrat', 'Arial Black', sans-serif",
            fontSize: 32,
            fontWeight: 900,
            color: "#FFFFFF",
            letterSpacing: 0.5,
          }}
        >
          {card.views}
        </span>
      </div>
    </div>
  );
};

export interface ProofCardsPopProps {
  cards?: ProofCardItem[];
}

export const defaultProofCards: ProofCardItem[] = [
  {
    src: staticFile("cards/proof_card_1.mp4"),
    popFrame: 68, // on word "THAT"
    x: 60,
    y: 160,
    width: 540,
    height: 690,
    rotation: -6.0,
    pinned: true,
    views: "1.3M",
    zIndex: 10,
    sfxSrc: staticFile("sfx/pop_card_1.wav"),
  },
  {
    src: staticFile("cards/proof_card_2.mp4"),
    popFrame: 78, // on word "GENERATING"
    x: 475,
    y: 470,
    width: 545,
    height: 695,
    rotation: 4.5,
    pinned: false,
    views: "981.9K",
    zIndex: 15,
    sfxSrc: staticFile("sfx/pop_card_2.wav"),
  },
  {
    src: staticFile("cards/proof_card_3.mp4"),
    popFrame: 89, // on word "MILLIONS"
    x: 95,
    y: 980,
    width: 540,
    height: 690,
    rotation: -3.5,
    pinned: true,
    views: "1.9M",
    zIndex: 20,
    sfxSrc: staticFile("sfx/pop_card_3.wav"),
  },
];

export const ProofCardsPop: React.FC<ProofCardsPopProps> = ({
  cards = defaultProofCards,
}) => {
  return (
    <>
      {/* SFX sequences for pop sound on each card pop frame */}
      {cards.map((card, i) =>
        card.sfxSrc ? (
          <Sequence
            key={`sfx-${i}`}
            from={card.popFrame}
            durationInFrames={15}
          >
            <Audio src={card.sfxSrc} volume={0.9} />
          </Sequence>
        ) : null
      )}

      {/* Proof cards rendering */}
      {cards.map((card, i) => (
        <SingleProofCard key={`card-${i}`} card={card} index={i} />
      ))}
    </>
  );
};
