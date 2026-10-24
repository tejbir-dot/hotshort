import React from "react";
import { Composition, Sequence, staticFile } from "remotion";
import { HookScene, HookSceneProps } from "./components/HookScene";
import {
  YouTubeBrowseScene,
  YouTubeBrowseSceneProps,
} from "./components/YouTubeBrowseScene";
import { ToolDemoScene, ToolDemoSceneProps } from "./components/ToolDemoScene";

// Word list verified via Whisper word timestamps from ref_audio.mp3
const defaultHookProps: HookSceneProps = {
  words: [
    { text: "HERE'S", start: 0.0, end: 0.24 },
    { text: "HOW", start: 0.24, end: 0.34 },
    { text: "I", start: 0.34, end: 0.48 },
    { text: "MAKE", start: 0.48, end: 0.62 },
    { text: "THESE", start: 0.62, end: 0.92 },
    { text: "VIRAL", start: 0.92, end: 1.24 },
    { text: "STREAMER", start: 1.24, end: 1.7 },
    { text: "CLIPS", start: 1.7, end: 2.18 },
    { text: "THAT", start: 2.18, end: 2.58 },
    { text: "GENERATING", start: 2.58, end: 2.94 },
    { text: "MILLIONS", start: 2.94, end: 3.38 },
    { text: "VIEWS", start: 3.38, end: 3.7 },
  ],
  cards: [
    { src: staticFile("cards/card_left.mp4"), viewCount: 37700000 },
    { src: staticFile("cards/card_center.mp4"), viewCount: 34300000 },
    { src: staticFile("cards/card_right.mp4"), viewCount: 42700000 },
  ],
  cardPopFrames: [5, 17, 11],
  avatarSlideFrame: 3,
  avatarVideoSrc: staticFile("avatar_animated.webm"),
  audioSrc: staticFile("audio.mp3"),
};

const defaultYouTubeProps: YouTubeBrowseSceneProps = {
  searchQuery: "ishowspeed",
};

const defaultToolDemoProps: ToolDemoSceneProps = {
  videoSrc: "hotshort_demo.mp4",
};

// Full Master Viral Ad Sequence (Hook -> YouTube Search -> HotShort 34 Clips Glide Flex)
const FullAdSequence: React.FC = () => {
  return (
    <>
      {/* Scene 1: Hook (0 - 3.67s, frames 0 - 110) */}
      <Sequence from={0} durationInFrames={110}>
        <HookScene {...defaultHookProps} />
      </Sequence>

      {/* Scene 2: Real YouTube Search / Share (3.67s - 7.33s, frames 110 - 220) */}
      <Sequence from={110} durationInFrames={110}>
        <YouTubeBrowseScene />
      </Sequence>

      {/* Scene 3: HotShort Demo & 4 Jump Cuts (7.33s - 19.76s, frames 220 - 593) */}
      <Sequence from={220} durationInFrames={373}>
        <ToolDemoScene {...defaultToolDemoProps} />
      </Sequence>
    </>
  );
};

export const MyComposition = () => {
  return (
    <>
      {/* Scene 1: Hook (0 - 3.67s, 110 frames) */}
      <Composition
        id="HookPreview"
        component={HookScene as any}
        durationInFrames={110}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={defaultHookProps}
      />

      {/* Scene 2: YouTubeBrowse (0 - 3.67s, 110 frames) */}
      <Composition
        id="YouTubeBrowse"
        component={YouTubeBrowseScene}
        durationInFrames={110}
        fps={30}
        width={1080}
        height={1920}
      />

      {/* Scene 3: ToolDemo (HotShort Demo & 4 Jump Cuts, 373 frames = 12.43s) */}
      <Composition
        id="ToolDemo"
        component={ToolDemoScene as any}
        durationInFrames={373}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={defaultToolDemoProps}
      />

      {/* Full Combined Sequence (0 - 16.43s, 493 frames) */}
      <Composition
        id="FullAdPreview"
        component={FullAdSequence}
        durationInFrames={493}
        fps={30}
        width={1080}
        height={1920}
      />
    </>
  );
};
