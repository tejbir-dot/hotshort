import React from "react";
import {
  Audio,
  OffthreadVideo,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { PhoneMock } from "./PhoneMock";
import { FakeCursor } from "./FakeCursor";
import { WordPopSequence } from "./WordPop";

export interface ToolDemoSceneProps {
  videoSrc?: string;
  audioSrc?: string;
  words?: Array<{ text: string; start: number; end: number }>;
  videoStartFrom?: number;
  hideCtaModal?: boolean;
}

export const ToolDemoScene: React.FC<ToolDemoSceneProps> = ({
  videoSrc = "hotshort_demo.mp4",
  audioSrc,
  words = [],
  videoStartFrom,
  hideCtaModal = false,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // ─────────────────────────────────────────────────────────────
  // 1. DYNAMIC CAMERA PUNCH-INS ON PhoneMock CONTAINER (Spring, 1.0 -> 1.30)
  // Always scales the WHOLE PhoneMock container so bezel stays partly visible!
  // No full-bleed crops of the inner screen!
  // ─────────────────────────────────────────────────────────────
  // Punch-in 1 (frames 0 - 48): URL Input typing (1.0 -> 1.25, translateY 0 -> 60)
  const punch1Spring = spring({
    frame: frame - 0,
    fps,
    config: { damping: 14, stiffness: 110 },
  });

  // Punch-in 2 (frames 60 - 155): "Choose Your Vibe" sheet centered (1.25 -> 1.30, translateY 60 -> -140)
  const vibeSpring = spring({
    frame: frame - 60,
    fps,
    config: { damping: 15, stiffness: 120 },
  });

  // Pull-back (frames 155 - 180): Smooth spring pull back to full phone view
  const pullBackSpring = spring({
    frame: frame - 155,
    fps,
    config: { damping: 16, stiffness: 90 },
  });

  // Compute camera scale and vertical translation on PhoneMock container
  let cameraScale = 1.0;
  let cameraTranslateY = 0;

  if (videoStartFrom !== undefined && videoStartFrom > 0) {
    cameraScale = 1.0;
    cameraTranslateY = 0;
  } else if (frame < 57) {
    // Zooming into URL input (scale 1.0 -> 1.25, translateY 0 -> 60px)
    cameraScale = interpolate(punch1Spring, [0, 1], [1.0, 1.25]);
    cameraTranslateY = interpolate(punch1Spring, [0, 1], [0, 60]);
  } else if (frame < 65) {
    // Tactile button-press punch bounce on Analyze Now tap at frame 57
    const tapBounce = Math.sin((frame - 57) * 0.7) * 0.02;
    cameraScale = 1.25 + tapBounce;
    cameraTranslateY = 60;
  } else if (frame < 155) {
    // Focus on "Choose Your Vibe" sheet: translateY=-140 centers the sheet in canvas!
    // Eliminates the empty dark void at the top while keeping phone bezel visible
    cameraScale = interpolate(vibeSpring, [0, 1], [1.25, 1.30]);
    cameraTranslateY = interpolate(vibeSpring, [0, 1], [60, -140]);
  } else if (frame < 185) {
    // Smooth cinematic spring pull back to 1.00 full phone view
    cameraScale = interpolate(pullBackSpring, [0, 1], [1.30, 1.0]);
    cameraTranslateY = interpolate(pullBackSpring, [0, 1], [-140, 0]);
  } else {
    // Full view for Results & 4 Jump Cuts (PhoneMock width = ~80%, bezel fully visible)
    cameraScale = interpolate(frame, [185, 373], [1.0, 1.015], {
      extrapolateRight: "clamp",
    });
    cameraTranslateY = 0;
  }

  // ─────────────────────────────────────────────────────────────
  // 2. SMOOTH CONTINUOUS GLIDE ACROSS SPEED RUNNING CLIPS (Crystal clear, 0 blur)
  // ─────────────────────────────────────────────────────────────
  const whipBlur = 0;
  const whipX = 0;

  // ─────────────────────────────────────────────────────────────
  // 3. "34+ VIRAL SHORTS GENERATED" BADGE (OUTSIDE PhoneMock, ABOVE BEZEL)
  // ─────────────────────────────────────────────────────────────
  const badgeSpring = spring({
    frame: (videoStartFrom !== undefined && videoStartFrom > 0) ? frame : frame - 170,
    fps,
    config: { damping: 14, stiffness: 120 },
  });

  const badgeOpacity = (videoStartFrom !== undefined && videoStartFrom > 0)
    ? 1
    : interpolate(frame, [168, 180], [0, 1], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      });

  // Animated clip counter badge from 1 to 34+
  const clipCount = Math.min(
    34,
    Math.max(1, Math.floor(interpolate(
      (videoStartFrom !== undefined && videoStartFrom > 0) ? frame : frame,
      (videoStartFrom !== undefined && videoStartFrom > 0) ? [0, 35] : [172, 230],
      [1, 34],
      {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      }
    )))
  );

  // ─────────────────────────────────────────────────────────────
  // 4. FAKE CURSOR (Synced to UI interaction inside PhoneMock screen)
  // URL Input (f0-48) -> Analyze Now tap (f57) -> Center Crop tap (f102) -> Modal Submit (f130)
  // ─────────────────────────────────────────────────────────────
  let cursorX = 320;
  let cursorY = 503;
  let cursorOpacity = 0;
  let cursorScale = 1.0;
  let rippleScale = 0;
  let rippleOpacity = 0;
  let rippleX = 320;
  let rippleY = 570;

  if (videoStartFrom !== undefined && videoStartFrom > 0) {
    cursorOpacity = 0;
  } else if (frame < 48) {
    // Typing in URL input box (y=503)
    cursorX = interpolate(frame, [0, 46], [240, 480], { extrapolateRight: "clamp" });
    cursorY = 503;
    cursorOpacity = 1;
    cursorX += Math.sin(frame * 0.8) * 1.5;
  } else if (frame < 65) {
    // Glide to Analyze Now button center (x=320, y=570) and tap at frame 57
    cursorX = interpolate(frame, [48, 56], [480, 320], { extrapolateRight: "clamp" });
    cursorY = interpolate(frame, [48, 56], [503, 570], { extrapolateRight: "clamp" });
    cursorOpacity = 1;
    if (frame >= 57 && frame <= 62) {
      cursorScale = interpolate(frame, [57, 59, 63], [1.0, 0.78, 1.0], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      });
    }
    if (frame >= 57 && frame <= 65) {
      rippleX = 320;
      rippleY = 570;
      rippleScale = interpolate(frame, [57, 65], [0.5, 1.9], { extrapolateRight: "clamp" });
      rippleOpacity = interpolate(frame, [57, 60, 65], [0.85, 0.6, 0], { extrapolateRight: "clamp" });
    }
  } else if (frame < 98) {
    // Move up to "Center Crop (TikTok Ratio)" card (x=451, y=625) and tap at frame 88
    cursorX = interpolate(frame, [65, 85], [320, 451], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });
    cursorY = interpolate(frame, [65, 85], [570, 625], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });
    cursorOpacity = 1;
    if (frame >= 87 && frame <= 91) {
      cursorScale = interpolate(frame, [87, 89, 92], [1.0, 0.82, 1.0], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      });
    }
    if (frame >= 88 && frame <= 95) {
      rippleX = 451;
      rippleY = 625;
      rippleScale = interpolate(frame, [88, 95], [0.5, 1.8], { extrapolateRight: "clamp" });
      rippleOpacity = interpolate(frame, [88, 91, 95], [0.85, 0.5, 0], { extrapolateRight: "clamp" });
    }
  } else if (frame < 135) {
    // Move directly onto the golden "Analyze Now 🚀" button (x=474, y=984) and tap firmly at frame 116
    cursorX = interpolate(frame, [95, 114], [451, 474], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });
    cursorY = interpolate(frame, [95, 114], [625, 984], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });
    cursorOpacity = 1;
    if (frame >= 115 && frame <= 120) {
      cursorScale = interpolate(frame, [115, 117, 121], [1.0, 0.78, 1.0], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      });
    }
    if (frame >= 116 && frame <= 124) {
      rippleX = 474;
      rippleY = 984;
      rippleScale = interpolate(frame, [116, 124], [0.5, 1.9], { extrapolateRight: "clamp" });
      rippleOpacity = interpolate(frame, [116, 119, 124], [0.90, 0.5, 0], { extrapolateRight: "clamp" });
    }
  } else {
    // Smooth fade out as results page loads
    cursorOpacity = interpolate(frame, [125, 145], [1, 0], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });
  }

  return (
    <div
      style={{
        position: "relative",
        width: 1080,
        height: 1920,
        backgroundColor: "#070503",
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        fontFamily: "'Inter', -apple-system, sans-serif",
      }}
    >
      {/* ─────────────────────────────────────────────────────────────
          SYNCHRONIZED VOICEOVER & SFX TRACKS
          ───────────────────────────────────────────────────────────── */}
      {audioSrc ? (
        <Audio src={audioSrc.startsWith("/") ? audioSrc : staticFile(audioSrc)} volume={1.0} />
      ) : (
        <>
          {/* Voice 1: Step 1 (URL + Vibe): "Paste it into HotShort, choose your TikTok vibe, and tap Analyze." */}
          <Sequence from={5} durationInFrames={140}>
            <Audio src={staticFile("vo/vo_scene3_step1.mp3")} volume={1.0} />
          </Sequence>

          {/* Voice 2: 34 Clips: "In seconds, it generates over thirty viral shorts with auto-synced captions and face tracking!" */}
          <Sequence from={170} durationInFrames={150}>
            <Audio src={staticFile("vo/vo_scene3_glide.mp3")} volume={1.0} />
          </Sequence>

          {/* Voice 3: End CTA: "Comment AI below right now, and I will DM you the private link for free!" */}
          <Sequence from={325} durationInFrames={48}>
            <Audio src={staticFile("vo/vo_cta.mp3")} volume={1.0} />
          </Sequence>
        </>
      )}

      {/* SFX: only when running full flow without manual audio */}
      {!audioSrc && (
        <>
          <Sequence from={5} durationInFrames={44}>
            <Audio src={staticFile("sfx/mouse_click.mp3")} volume={0.22} />
          </Sequence>
          <Sequence from={57} durationInFrames={15}>
            <Audio src={staticFile("sfx/mouse_click_mech.mp3")} volume={0.95} />
          </Sequence>
          <Sequence from={88} durationInFrames={15}>
            <Audio src={staticFile("sfx/pop_card_2.wav")} volume={0.8} />
          </Sequence>
          <Sequence from={116} durationInFrames={15}>
            <Audio src={staticFile("sfx/mouse_click_mech.mp3")} volume={0.95} />
          </Sequence>
        </>
      )}

      {/* SFX: Analyze Now button tap - EXACTLY SYNCED AT FRAME 57 */}
      <Sequence from={57} durationInFrames={15}>
        <Audio src={staticFile("sfx/mouse_click_mech.mp3")} volume={0.95} />
      </Sequence>

      {/* SFX: Vibe card selection tap - EXACTLY SYNCED AT FRAME 88 */}
      <Sequence from={88} durationInFrames={15}>
        <Audio src={staticFile("sfx/pop_card_2.wav")} volume={0.8} />
      </Sequence>

      {/* SFX: Modal Analyze Now tap - EXACTLY SYNCED AT FRAME 116 */}
      <Sequence from={116} durationInFrames={15}>
        <Audio src={staticFile("sfx/mouse_click_mech.mp3")} volume={0.95} />
      </Sequence>

      {/* SFX: Camera pull-back swoosh */}
      <Sequence from={155} durationInFrames={20}>
        <Audio src={staticFile("sfx/whoosh_fast.mp3")} volume={0.4} />
      </Sequence>

      {/* SFX: Results dopamine ching */}
      <Sequence from={170} durationInFrames={35}>
        <Audio src={staticFile("sfx/money_ching.mp3")} volume={0.85} />
      </Sequence>

      {/* SFX: Silky reel glide swipe as carousel smooth scrolls */}
      <Sequence from={205} durationInFrames={20}>
        <Audio src={staticFile("sfx/whoosh_fast.mp3")} volume={0.4} />
      </Sequence>

      {/* SFX: CTA Card pop on frame 325 */}
      <Sequence from={325} durationInFrames={20}>
        <Audio src={staticFile("sfx/pop_bubble.mp3")} volume={0.75} />
      </Sequence>
      <Sequence from={330} durationInFrames={35}>
        <Audio src={staticFile("sfx/money_ching.mp3")} volume={0.55} />
      </Sequence>

      {/* Warm Ambient Studio Background Glow */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background:
            "radial-gradient(circle at 50% 40%, rgba(255, 175, 55, 0.18) 0%, rgba(18, 12, 6, 0.90) 55%, #050403 100%)",
          zIndex: 1,
        }}
      />

      {/* Floating Sparkles */}
      <div
        style={{
          position: "absolute",
          top: "10%",
          left: "10%",
          width: 6,
          height: 6,
          borderRadius: "50%",
          backgroundColor: "#ffc864",
          boxShadow: "0 0 16px #ffc864",
          opacity: 0.6 + Math.sin(frame * 0.1) * 0.3,
          zIndex: 2,
        }}
      />
      <div
        style={{
          position: "absolute",
          top: "18%",
          right: "12%",
          width: 8,
          height: 8,
          borderRadius: "50%",
          backgroundColor: "#ff9000",
          boxShadow: "0 0 20px #ff9000",
          opacity: 0.5 + Math.cos(frame * 0.08) * 0.3,
          zIndex: 2,
        }}
      />

      {/* ─────────────────────────────────────────────────────────────
          FLOATING TOP FLEX BADGE: "34+ VIRAL SHORTS GENERATED"
          Positioned at top: 14px — 100% ABOVE the PhoneMock (PhoneMock top is at 82px)
          NEVER overlaps the phone bezel, status bar, or UI!
          ───────────────────────────────────────────────────────────── */}
      {frame >= 168 && (
        <div
          style={{
            position: "absolute",
            top: 14,
            zIndex: 120,
            display: "flex",
            alignItems: "center",
            gap: 12,
            padding: "8px 24px",
            background: "linear-gradient(135deg, rgba(30, 22, 12, 0.96), rgba(14, 9, 5, 0.98))",
            border: "1.5px solid rgba(255, 200, 100, 0.75)",
            borderRadius: 999,
            boxShadow:
              "0 12px 30px rgba(0, 0, 0, 0.9), 0 0 35px rgba(255, 180, 50, 0.4), inset 0 1px 2px rgba(255, 255, 255, 0.5)",
            transform: `scale(${badgeSpring})`,
            opacity: badgeOpacity,
            backdropFilter: "blur(20px)",
          }}
        >
          <span style={{ fontSize: 22 }}>⚡</span>
          <div style={{ display: "flex", flexDirection: "column" }}>
            <span
              style={{
                fontFamily: "'Inter', sans-serif",
                fontSize: 18,
                fontWeight: 900,
                letterSpacing: -0.3,
                background: "linear-gradient(90deg, #fff4cc, #ffb347, #ffcf80)",
                WebkitBackgroundClip: "text",
                WebkitTextFillColor: "transparent",
                textTransform: "uppercase",
              }}
            >
              {clipCount}+ VIRAL SHORTS GENERATED
            </span>
            <span
              style={{
                fontFamily: "'Inter', sans-serif",
                fontSize: 11,
                fontWeight: 700,
                color: "rgba(255, 230, 200, 0.85)",
                letterSpacing: 0.2,
              }}
            >
              1 Long Stream → 30+ Ready-To-Post Clips
            </span>
          </div>
        </div>
      )}

      {/* ─────────────────────────────────────────────────────────────
          PHONE MOCK WITH SPRING CAMERA PUNCH-IN (1.0 -> 1.7)
          Requirement 1 & 2:
          - Never remove PhoneMock
          - Width is constant at 840px (~80% of 1080 canvas)
          - All zooms = transform scale/translate on the whole PhoneMock container
          - Top bezel curve stays partly visible at the top edge during zooms!
          - Bottom bezel sits with ~20px margin when at scale 1.0!
          ───────────────────────────────────────────────────────────── */}
      <div
        style={{
          position: "absolute",
          top: 82,
          zIndex: 10,
          transform: `translateY(${cameraTranslateY}px) scale(${cameraScale})`,
          transformOrigin: "50% 50%",
          transition: "transform 0.05s linear",
        }}
      >
        <PhoneMock width={840} bezelColor="#b88a78" safeAreaTop={56} safeAreaBottom={24}>
          <div
            style={{
              position: "relative",
              width: "100%",
              height: "100%",
              backgroundColor: "#0b0b0b",
              overflow: "hidden",
            }}
          >
            {/* The Real High-Bitrate Screen Recording with 6-frame whip-blur on cuts */}
            <div
              style={{
                width: "100%",
                height: "100%",
                filter: whipBlur > 0 ? `blur(${whipBlur}px)` : "none",
                transform: whipX !== 0 ? `translateX(${whipX}px)` : "none",
                transition: "filter 0.03s linear, transform 0.03s linear",
              }}
            >
              <OffthreadVideo
                src={staticFile(videoSrc)}
                startFrom={videoStartFrom || 0}
                style={{
                  width: "100%",
                  height: "100%",
                  objectFit: "cover",
                }}
              />
            </div>

            {/* Tactile Touch Click Ripple */}
            {rippleOpacity > 0 && (
              <div
                style={{
                  position: "absolute",
                  left: (rippleX / 640) * 820 - 36,
                  top: (rippleY / 1386) * 1801 - 36,
                  width: 72,
                  height: 72,
                  borderRadius: "50%",
                  border: "2.5px solid rgba(255, 205, 80, 0.95)",
                  backgroundColor: "rgba(255, 185, 45, 0.30)",
                  transform: `scale(${rippleScale})`,
                  opacity: rippleOpacity,
                  pointerEvents: "none",
                  zIndex: 195,
                  boxShadow: "0 0 25px rgba(255, 190, 50, 0.75)",
                }}
              />
            )}

            {/* Synchronized Fake Cursor Overlay inside phone screen */}
            {cursorOpacity > 0 && (
              <div
                style={{
                  position: "absolute",
                  left: (cursorX / 640) * 820,
                  top: (cursorY / 1386) * 1801,
                  opacity: cursorOpacity,
                  transform: `scale(${cursorScale}) translate(-15%, -15%)`,
                  pointerEvents: "none",
                  zIndex: 200,
                  filter: "drop-shadow(0 4px 10px rgba(0,0,0,0.65))",
                }}
              >
                <FakeCursor />
              </div>
            )}
          </div>
        </PhoneMock>
      </div>

      {/* ─────────────────────────────────────────────────────────────
          END CALL-TO-ACTION (CTA) POPUP: "COMMENT 'AI' FOR LINK"
          Appears at frame >= 325 with spring animation & glassmorphism
          ───────────────────────────────────────────────────────────── */}
      {!hideCtaModal && frame >= 325 && (() => {
        // Snappy 6-frame spring punch-in (0.2s)
        const ctaSpring = spring({
          frame: frame - 325,
          fps,
          config: { damping: 11, stiffness: 220 },
        });

        const pulseScale = 1 + Math.sin((frame - 325) * 0.15) * 0.03;

        return (
          <div
            style={{
              position: "absolute",
              inset: 0,
              zIndex: 300,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              backgroundColor: "rgba(5, 3, 2, 0.78)",
              backdropFilter: "blur(14px)",
              opacity: interpolate(frame, [325, 331], [0, 1], {
                extrapolateLeft: "clamp",
                extrapolateRight: "clamp",
              }),
            }}
          >
            {/* Ambient Gold Radial Flare */}
            <div
              style={{
                position: "absolute",
                width: 820,
                height: 820,
                borderRadius: "50%",
                background:
                  "radial-gradient(circle, rgba(255, 190, 50, 0.35) 0%, rgba(255, 110, 20, 0.12) 50%, transparent 75%)",
                filter: "blur(60px)",
                pointerEvents: "none",
              }}
            />

            {/* Main CTA Modal Card: 30% Larger (940px wide) & High-Luminance Contrast */}
            <div
              style={{
                position: "relative",
                width: 940,
                padding: "52px 46px",
                background:
                  "linear-gradient(160deg, rgba(50, 36, 22, 0.99) 0%, rgba(28, 19, 12, 0.99) 100%)",
                border: "3.5px solid #ffca48",
                borderRadius: 42,
                boxShadow:
                  "0 35px 100px rgba(0, 0, 0, 0.98), 0 0 110px rgba(255, 185, 45, 0.75), inset 0 2px 6px rgba(255, 255, 255, 0.6)",
                transform: `scale(${ctaSpring})`,
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                textAlign: "center",
                gap: 22,
              }}
            >
              {/* Top VIP Access Badge */}
              <div
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 10,
                  padding: "10px 28px",
                  background: "rgba(255, 210, 0, 0.20)",
                  border: "1.8px solid rgba(255, 224, 66, 0.75)",
                  borderRadius: 999,
                  fontSize: 18,
                  fontWeight: 900,
                  letterSpacing: 1.5,
                  textTransform: "uppercase",
                  boxShadow: "0 0 25px rgba(255, 210, 0, 0.4)",
                }}
              >
                <span style={{ fontSize: 22 }}>⚡</span>
                <span style={{ color: "#ffe042", textShadow: "0 0 14px rgba(255, 224, 66, 0.85)" }}>
                  FREE
                </span>
                <span style={{ color: "#ffffff" }}>VIP BETA INVITE</span>
              </div>

              {/* Huge Bold Headline with Yellow "AI" */}
              <div
                style={{
                  fontSize: 62,
                  fontWeight: 900,
                  lineHeight: 1.05,
                  letterSpacing: -1,
                  color: "#ffffff",
                  textTransform: "uppercase",
                }}
              >
                COMMENT <span style={{ color: "#ffe042", textShadow: "0 0 40px rgba(255, 224, 66, 0.95)" }}>"AI"</span>
              </div>

              {/* Sub-headline with Yellow "FREE" */}
              <div
                style={{
                  fontSize: 26,
                  fontWeight: 700,
                  color: "rgba(255, 245, 230, 0.96)",
                  lineHeight: 1.35,
                  maxWidth: 820,
                }}
              >
                I'll DM you the private VIP link to test HotShort 3.0 for{" "}
                <span
                  style={{
                    color: "#ffe042",
                    fontWeight: 900,
                    textDecoration: "underline",
                    textShadow: "0 0 16px rgba(255, 224, 66, 0.8)",
                  }}
                >
                  FREE
                </span>
                ! 📩
              </div>

              {/* Mock Direct Message Notification Card */}
              <div
                style={{
                  width: "100%",
                  padding: "20px 26px",
                  background: "rgba(255, 255, 255, 0.08)",
                  border: "1.5px solid rgba(255, 255, 255, 0.20)",
                  borderRadius: 22,
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 18,
                  textAlign: "left",
                  marginTop: 4,
                  boxShadow: "0 10px 25px rgba(0,0,0,0.4)",
                }}
              >
                <div
                  style={{
                    width: 58,
                    height: 58,
                    borderRadius: "50%",
                    background: "linear-gradient(135deg, #ff9000, #ff4500)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: 30,
                    boxShadow: "0 6px 18px rgba(255, 100, 0, 0.5)",
                    flexShrink: 0,
                  }}
                >
                  🔥
                </div>
                <div style={{ flex: 1 }}>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      marginBottom: 4,
                    }}
                  >
                    <span
                      style={{
                        fontSize: 20,
                        fontWeight: 800,
                        color: "#ffffff",
                      }}
                    >
                      HotShort AI
                    </span>
                    <span style={{ fontSize: 16, color: "#60a5fa" }}>✓</span>
                    <span
                      style={{
                        fontSize: 14,
                        color: "rgba(255,255,255,0.55)",
                        marginLeft: "auto",
                      }}
                    >
                      Just now
                    </span>
                  </div>
                  <div
                    style={{
                      fontSize: 17,
                      color: "rgba(255, 240, 225, 0.95)",
                      lineHeight: 1.45,
                    }}
                  >
                    "Hey! 🚀 Here is your private VIP link to turn any YouTube stream into 34 viral shorts:{" "}
                    <span style={{ color: "#ffe042", fontWeight: 800 }}>hotshort.ai/invite</span>"
                  </div>
                </div>
              </div>

              {/* Pulsing Interactive Button Prompt */}
              <div
                style={{
                  marginTop: 6,
                  padding: "18px 48px",
                  background:
                    "linear-gradient(90deg, #ff9000, #ff5e00, #ff9000)",
                  backgroundSize: "200% auto",
                  borderRadius: 999,
                  fontSize: 24,
                  fontWeight: 900,
                  color: "#ffffff",
                  letterSpacing: 0.5,
                  boxShadow:
                    "0 14px 40px rgba(255, 100, 0, 0.6), 0 0 30px rgba(255, 180, 50, 0.5)",
                  transform: `scale(${pulseScale})`,
                  display: "flex",
                  alignItems: "center",
                  gap: 12,
                }}
              >
                <span>💬</span>
                <span>
                  DROP <span style={{ color: "#ffe042" }}>"AI"</span> IN COMMENTS
                </span>
                <span>👇</span>
              </div>
            </div>
          </div>
        );
      })()}

      {/* Word Pop Captions overlay */}
      {words && words.length > 0 && (
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            pointerEvents: "none",
            zIndex: 400,
          }}
        >
          <WordPopSequence
            words={words.map((w) => ({
              text: w.text,
              startFrame: Math.round(w.start * fps),
              endFrame: Math.round(w.end * fps),
            }))}
            forceWhite={true}
          />
        </div>
      )}
    </div>
  );
};
