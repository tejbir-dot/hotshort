// WordPop.tsx - One word at a time, high-impact spring punch
import React from "react";
import { useCurrentFrame, spring, useVideoConfig } from "remotion";

interface WordPopProps {
  word: string;
  startFrame: number;
  endFrame: number;
  isEmphasis?: boolean;
  forceWhite?: boolean;
  top?: string | number;
}

export const WordPop: React.FC<WordPopProps> = ({
  word,
  startFrame,
  endFrame,
  isEmphasis = false,
  forceWhite = true, // Hook words are ALL white per rule 4
  top = "50%",
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  if (frame < startFrame || frame >= endFrame) return null;

  const localFrame = frame - startFrame;

  // Spring punch: overshoot from 0.7 to 1.15 then settle to 1.0
  const scale = spring({
    frame: localFrame,
    fps,
    config: { damping: 10, stiffness: 240, mass: 0.7 },
    from: 0.7,
    to: 1.0,
  });

  // Color: ALL white for hook words; if forceWhite is false, can use yellow for result-captions
  const textColor = forceWhite ? "#FFFFFF" : isEmphasis ? "#FFE600" : "#FFFFFF";

  // Dynamic font sizing for maximum visual punch without clipping
  const getFontSize = (w: string) => {
    const len = w.length;
    if (len <= 4) return 170;
    if (len <= 6) return 150;
    if (len <= 8) return 138;
    return 115;
  };

  const fontSize = getFontSize(word);

  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        top: top,
        transform: `translateY(-50%) scale(${scale})`,
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        zIndex: 100,
        pointerEvents: "none",
      }}
    >
      <span
        style={{
          fontFamily: "'Montserrat', 'Arial Black', 'Impact', sans-serif",
          fontWeight: 900, // 900 bold
          fontSize: fontSize,
          color: textColor,
          WebkitTextStroke: "12px #000000", // 12px black stroke
          textAlign: "center",
          lineHeight: 1.05,
          letterSpacing: "-0.01em", // tight viral typography per user spec
          textShadow: "0 14px 40px rgba(0,0,0,0.95), 0 0 25px rgba(0,0,0,0.9)",
          whiteSpace: "nowrap",
          userSelect: "none",
        }}
      >
        {word.toUpperCase()}
      </span>
    </div>
  );
};

export interface WordTimestamp {
  text: string;
  startFrame: number;
  endFrame: number;
  isEmphasis?: boolean;
  top?: string | number;
}

interface WordPopSequenceProps {
  words: WordTimestamp[];
  forceWhite?: boolean;
  top?: string | number;
}

export const WordPopSequence: React.FC<WordPopSequenceProps> = ({
  words,
  forceWhite = true,
  top,
}) => {
  const frame = useCurrentFrame();
  const activeWords = words.filter((w) => frame >= w.startFrame && frame < w.endFrame);
  const activeWord = activeWords.length > 0 ? activeWords[activeWords.length - 1] : undefined;
  if (!activeWord) return null;
  return (
    <WordPop
      word={activeWord.text}
      startFrame={activeWord.startFrame}
      endFrame={activeWord.endFrame}
      isEmphasis={activeWord.isEmphasis}
      forceWhite={forceWhite}
      top={activeWord.top || top || "50%"}
    />
  );
};
