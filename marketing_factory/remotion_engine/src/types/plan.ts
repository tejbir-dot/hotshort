// src/types/plan.ts - Reference Master Standardized Ad Plan Schema
export interface WordItem {
  text: string;
  start: number; // in seconds
  end: number;   // in seconds
  isEmphasis?: boolean;
}

export interface BgMusicConfig {
  src: string;
  volume: number;
  loop?: boolean;
}

export interface CardItem {
  src: string;
  viewCount?: number;
}

export interface ProofCardItemConfig {
  src: string;
  popFrame: number;
  x: number;
  y: number;
  width: number;
  height: number;
  rotation: number;
  pinned?: boolean;
  views: string;
  zIndex: number;
  sfxSrc?: string;
}

export interface SceneConfig {
  id?: string;
  type: "HOOK_CARD_FAN" | "PHONE_BROWSE" | "TOOL_DEMO" | string;
  durationInFrames: number;
  props: Record<string, any>;
}

export interface AdPlan {
  id?: string;
  title?: string;
  fps?: number;
  width?: number;
  height?: number;
  bgMusic?: BgMusicConfig;
  scenes: SceneConfig[];
}
