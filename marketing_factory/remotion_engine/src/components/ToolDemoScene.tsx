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

export interface ToolDemoSceneProps {
  videoSrc?: string;
}

export const ToolDemoScene: React.FC<ToolDemoSceneProps> = ({
  videoSrc = "hotshort_demo.mp4",
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // ─────────────────────────────────────────────────────────────
  // 1. DYNAMIC CAMERA PUNCH-INS ON PhoneMock CONTAINER (Spring, 1.0 -> 1.7)
  // Always scales the WHOLE PhoneMock container so bezel stays partly visible!
  // No full-bleed crops of the inner screen!
  // ─────────────────────────────────────────────────────────────
  // Punch-in 1 (frames 0 - 85, 0.0s - 2.83s): URL Input typing (1.0 -> 1.30)
  const punch1Spring = spring({
    frame: frame - 0,
    fps,
    config: { damping: 14, stiffness: 110 },
  });

  // Punch-in 2 (frames 85 - 115, 2.83s - 3.83s): Analyze Now button tap
  const punch2Spring = spring({
    frame: frame - 85,
    fps,
    config: { damping: 12, stiffness: 140 },
  });

  // Punch-in 3 (frames 115 - 155, 3.83s - 5.17s): Vibe selection (Center Crop TikTok)
  const punch3Spring = spring({
    frame: frame - 115,
    fps,
    config: { damping: 14, stiffness: 120 },
  });

  // Pull-back (frames 155 - 180, 5.17s - 6.00s): Smooth spring pull back to full phone view
  const pullBackSpring = spring({
    frame: frame - 155,
    fps,
    config: { damping: 16, stiffness: 90 },
  });

  // Compute camera scale and vertical translation on PhoneMock container
  let cameraScale = 1.0;
  let cameraTranslateY = 0;

  if (frame < 85) {
    // Zooming into URL input (scale 1.0 -> 1.30, translateY 0 -> 240px)
    // Scale 1.30 keeps PhoneMock width at 1092px (only 6px cropped at edges, bezel stays fully visible)
    // Centers the URL input target with ample margins and zero empty dark void at the top!
    cameraScale = interpolate(punch1Spring, [0, 1], [1.0, 1.30]);
    cameraTranslateY = interpolate(punch1Spring, [0, 1], [0, 240]);
  } else if (frame < 115) {
    // Subtle button-press punch bounce on Analyze Now tap
    const tapBounce = Math.sin((frame - 85) * 0.4) * 0.02;
    cameraScale = 1.30 + tapBounce;
    cameraTranslateY = interpolate(punch2Spring, [0, 1], [240, 200]);
  } else if (frame < 155) {
    // Focus on Vibe card (Center Crop TikTok)
    cameraScale = 1.30;
    cameraTranslateY = interpolate(punch3Spring, [0, 1], [200, 110]);
  } else if (frame < 185) {
    // Smooth cinematic spring pull back to 1.00 full phone view
    cameraScale = interpolate(pullBackSpring, [0, 1], [1.30, 1.0]);
    cameraTranslateY = interpolate(pullBackSpring, [0, 1], [110, 0]);
  } else {
    // Full view for Results & 4 Jump Cuts (PhoneMock width = ~80%, bezel fully visible)
    cameraScale = interpolate(frame, [185, 373], [1.0, 1.015], {
      extrapolateRight: "clamp",
    });
    cameraTranslateY = 0;
  }

  // ─────────────────────────────────────────────────────────────
  // 2. 6-FRAME WHIP-BLUR BETWEEN JUMP CUTS (Cut 1: f205, Cut 2: f241, Cut 3: f277)
  // ─────────────────────────────────────────────────────────────
  let whipBlur = 0;
  let whipX = 0;

  if (frame >= 202 && frame <= 208) {
    // Cut 1: Card 1 -> Card 2 (frame 205)
    whipBlur = interpolate(frame, [202, 205, 208], [0, 20, 0], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });
    whipX = interpolate(frame, [202, 205, 208], [0, -35, 0], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });
  } else if (frame >= 238 && frame <= 244) {
    // Cut 2: Card 2 -> Card 3 (frame 241)
    whipBlur = interpolate(frame, [238, 241, 244], [0, 20, 0], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });
    whipX = interpolate(frame, [238, 241, 244], [0, -35, 0], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });
  } else if (frame >= 274 && frame <= 280) {
    // Cut 3: Card 3 -> Card 4 (frame 277)
    whipBlur = interpolate(frame, [274, 277, 280], [0, 20, 0], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });
    whipX = interpolate(frame, [274, 277, 280], [0, -35, 0], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });
  }

  // ─────────────────────────────────────────────────────────────
  // 3. "34+ VIRAL SHORTS GENERATED" BADGE (OUTSIDE PhoneMock, ABOVE BEZEL)
  // ─────────────────────────────────────────────────────────────
  const badgeSpring = spring({
    frame: frame - 170,
    fps,
    config: { damping: 14, stiffness: 120 },
  });

  const badgeOpacity = interpolate(frame, [168, 180], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Animated clip counter badge from 1 to 34+
  const clipCount = Math.min(
    34,
    Math.max(1, Math.floor(interpolate(frame, [172, 230], [1, 34], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    })))
  );

  // ─────────────────────────────────────────────────────────────
  // 4. FAKE CURSOR (Synced to UI interaction inside PhoneMock screen)
  // ─────────────────────────────────────────────────────────────
  let cursorX = 320;
  let cursorY = 412;
  let cursorOpacity = 0;
  let cursorScale = 1.0;

  if (frame < 85) {
    // Typing in URL input box
    cursorX = interpolate(frame, [0, 75], [280, 500], { extrapolateRight: "clamp" });
    cursorY = 412;
    cursorOpacity = 1;
    cursorX += Math.sin(frame * 0.8) * 1.5;
  } else if (frame < 115) {
    // Move to "Analyze Now" button
    cursorX = interpolate(frame, [85, 93], [500, 320], { extrapolateRight: "clamp" });
    cursorY = interpolate(frame, [85, 93], [412, 485], { extrapolateRight: "clamp" });
    cursorOpacity = 1;
    if (frame >= 93 && frame <= 98) {
      cursorScale = 0.86; // Tap press
    }
  } else if (frame < 155) {
    // Move to "Center Crop" card in modal (x=440, y=720) then modal button
    cursorX = interpolate(frame, [115, 126, 138, 146], [320, 440, 440, 440], { extrapolateRight: "clamp" });
    cursorY = interpolate(frame, [115, 126, 138, 146], [485, 720, 720, 860], { extrapolateRight: "clamp" });
    cursorOpacity = 1;
    if ((frame >= 126 && frame <= 130) || (frame >= 146 && frame <= 150)) {
      cursorScale = 0.86;
    }
  } else {
    // Fade out as results page loads
    cursorOpacity = interpolate(frame, [155, 165], [1, 0], {
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

      {/* SFX: Typing mechanical clicks */}
      <Sequence from={5} durationInFrames={75}>
        <Audio src={staticFile("sfx/mouse_click.mp3")} volume={0.22} />
      </Sequence>

      {/* SFX: Analyze Now button tap */}
      <Sequence from={93} durationInFrames={15}>
        <Audio src={staticFile("sfx/mouse_click_mech.mp3")} volume={0.8} />
      </Sequence>

      {/* SFX: Vibe card selection tap */}
      <Sequence from={126} durationInFrames={15}>
        <Audio src={staticFile("sfx/pop_card_2.wav")} volume={0.75} />
      </Sequence>

      {/* SFX: Modal Analyze Now tap */}
      <Sequence from={146} durationInFrames={15}>
        <Audio src={staticFile("sfx/pop_click.mp3")} volume={0.7} />
      </Sequence>

      {/* SFX: Camera pull-back swoosh */}
      <Sequence from={155} durationInFrames={20}>
        <Audio src={staticFile("sfx/whoosh_fast.mp3")} volume={0.4} />
      </Sequence>

      {/* SFX: Results dopamine ching */}
      <Sequence from={170} durationInFrames={35}>
        <Audio src={staticFile("sfx/money_ching.mp3")} volume={0.85} />
      </Sequence>

      {/* SFX: 6-frame whip whoosh on Cut 1 */}
      <Sequence from={203} durationInFrames={12}>
        <Audio src={staticFile("sfx/whoosh_fast.mp3")} volume={0.5} />
      </Sequence>

      {/* SFX: 6-frame whip whoosh on Cut 2 */}
      <Sequence from={239} durationInFrames={12}>
        <Audio src={staticFile("sfx/whoosh_fast.mp3")} volume={0.5} />
      </Sequence>

      {/* SFX: 6-frame whip whoosh on Cut 3 */}
      <Sequence from={275} durationInFrames={12}>
        <Audio src={staticFile("sfx/whoosh_fast.mp3")} volume={0.5} />
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
                style={{
                  width: "100%",
                  height: "100%",
                  objectFit: "cover",
                }}
              />
            </div>

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
      {frame >= 325 && (() => {
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
    </div>
  );
};
