import React from "react";
import { Audio, Composition, Sequence, staticFile } from "remotion";
import { HookScene, HookSceneProps } from "./components/HookScene";
import {
  YouTubeBrowseScene,
} from "./components/YouTubeBrowseScene";
import { ToolDemoScene, ToolDemoSceneProps } from "./components/ToolDemoScene";
import { DmBubbleCta } from "./components/DmBubbleCta";
import { AdPlan, SceneConfig } from "./types/plan";
import defaultPlanJson from "../public/plan.json";

// ─────────────────────────────────────────────────────────────
// COMPONENT REGISTRY (Modular Lego Blocks)
// ─────────────────────────────────────────────────────────────
const SCENE_REGISTRY: Record<string, React.FC<any>> = {
  HOOK_CARD_FAN: (props) => {
    // Ensure staticFile wrapper on asset paths if passed as plain relative strings
    const resolvedCards = (props.cards || []).map((c: any) => ({
      ...c,
      src: c.src.startsWith("/") || c.src.startsWith("http") ? c.src : staticFile(c.src),
    }));
    const resolvedAudio = props.audioSrc && !props.audioSrc.startsWith("/") ? staticFile(props.audioSrc) : props.audioSrc;
    const resolvedAvatar = props.avatarVideoSrc && !props.avatarVideoSrc.startsWith("/") ? staticFile(props.avatarVideoSrc) : props.avatarVideoSrc;

    return (
      <HookScene
        {...props}
        cards={resolvedCards}
        audioSrc={resolvedAudio}
        avatarVideoSrc={resolvedAvatar}
      />
    );
  },
  PHONE_BROWSE: (props) => {
    const resolvedAudio = props.audioSrc && !props.audioSrc.startsWith("/") ? staticFile(props.audioSrc) : props.audioSrc;
    return (
      <YouTubeBrowseScene
        {...props}
        audioSrc={resolvedAudio}
      />
    );
  },
  TOOL_DEMO: (props) => {
    const resolvedAudio = props.audioSrc && !props.audioSrc.startsWith("/") ? staticFile(props.audioSrc) : props.audioSrc;
    return (
      <ToolDemoScene
        {...props}
        audioSrc={resolvedAudio}
      />
    );
  },
  DM_BUBBLE_CTA: (props) => {
    const resolvedAudio = props.audioSrc && !props.audioSrc.startsWith("/") ? staticFile(props.audioSrc) : props.audioSrc;
    const resolvedAvatar = props.avatarVideoSrc && !props.avatarVideoSrc.startsWith("/") ? staticFile(props.avatarVideoSrc) : props.avatarVideoSrc;
    return (
      <DmBubbleCta
        {...props}
        audioSrc={resolvedAudio}
        avatarVideoSrc={resolvedAvatar}
      />
    );
  },
};

// ─────────────────────────────────────────────────────────────
// DYNAMIC MASTER AD SEQUENCE (Driven by plan.json / props)
// ─────────────────────────────────────────────────────────────
export const DynamicAdSequence: React.FC<{ plan?: AdPlan; scenes?: SceneConfig[] }> = (props) => {
  const plan: AdPlan = (props.scenes ? (props as unknown as AdPlan) : props.plan) || (defaultPlanJson as AdPlan);
  let frameOffset = 0;

  return (
    <>
      {/* Background Music Bed */}
      {plan.bgMusic && (
        <Audio
          src={plan.bgMusic.src.startsWith("/") ? plan.bgMusic.src : staticFile(plan.bgMusic.src)}
          volume={plan.bgMusic.volume ?? 0.14}
          loop={plan.bgMusic.loop ?? true}
        />
      )}

      {/* Dynamic Scenes rendered sequentially based on plan.json */}
      {plan.scenes.map((scene: SceneConfig, index: number) => {
        const SceneComponent = SCENE_REGISTRY[scene.type];
        if (!SceneComponent) {
          console.warn(`Scene type ${scene.type} not found in SCENE_REGISTRY`);
          return null;
        }

        const fromFrame = frameOffset;
        frameOffset += scene.durationInFrames;

        return (
          <Sequence
            key={scene.id || index}
            from={fromFrame}
            durationInFrames={scene.durationInFrames}
          >
            <SceneComponent {...scene.props} />
          </Sequence>
        );
      })}
    </>
  );
};

// Backward-compatible default props for individual scene previews
const defaultHookProps: HookSceneProps = {
  words: [
    { text: "HERE'S", start: 0.0, end: 0.26 },
    { text: "HOW", start: 0.26, end: 0.34 },
    { text: "I", start: 0.34, end: 0.42 },
    { text: "MAKE", start: 0.42, end: 0.58 },
    { text: "THESE", start: 0.58, end: 0.82 },
    { text: "VIRAL", start: 0.82, end: 1.1 },
    { text: "STREAMER", start: 1.1, end: 1.46 },
    { text: "CLIPS", start: 1.46, end: 1.66 },
    { text: "THAT", start: 1.66, end: 1.86 },
    { text: "ARE", start: 1.86, end: 1.94 },
    { text: "GENERATING", start: 1.94, end: 2.3 },
    { text: "MILLIONS", start: 2.3, end: 2.62 },
    { text: "OF", start: 2.62, end: 2.88 },
    { text: "VIEWS", start: 2.88, end: 3.08 },
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

const defaultToolDemoProps: ToolDemoSceneProps = {
  videoSrc: "hotshort_demo.mp4",
};

// Full Master Viral Ad Sequence (Hook -> YouTube Search -> HotShort 34 Clips Glide Flex)
const FullAdSequence: React.FC = () => {
  return <DynamicAdSequence plan={defaultPlanJson as AdPlan} />;
};

export const MyComposition = () => {
  return (
    <>
      {/* 1. Fully Automated Data-Driven Master Ad Composition */}
      <Composition
        id="AutoAd"
        component={DynamicAdSequence}
        calculateMetadata={async ({ props }) => {
          const raw = props as any;
          const plan: AdPlan = (raw?.scenes ? raw : raw?.plan) || (defaultPlanJson as AdPlan);
          const totalFrames = (plan.scenes || []).reduce(
            (acc: number, s: SceneConfig) => acc + (s.durationInFrames || 0),
            0
          );
          return {
            durationInFrames: totalFrames || 583,
            fps: plan.fps || 30,
            width: plan.width || 1080,
            height: plan.height || 1920,
          };
        }}
        defaultProps={{
          plan: defaultPlanJson as AdPlan,
        }}
      />

      {/* 2. Full Combined Sequence (0 - 19.43s, 583 frames) */}
      <Composition
        id="FullAdPreview"
        component={FullAdSequence}
        durationInFrames={583}
        fps={30}
        width={1080}
        height={1920}
      />

      {/* 3. Individual Scene Previews for Fast Prototyping */}
      <Composition
        id="HookPreview"
        component={HookScene as any}
        durationInFrames={100}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={defaultHookProps}
      />

      <Composition
        id="YouTubeBrowse"
        component={YouTubeBrowseScene}
        durationInFrames={110}
        fps={30}
        width={1080}
        height={1920}
      />

      <Composition
        id="ToolDemo"
        component={ToolDemoScene as any}
        durationInFrames={373}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={defaultToolDemoProps}
      />
    </>
  );
};
