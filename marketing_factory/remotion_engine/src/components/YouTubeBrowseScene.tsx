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

export interface YouTubeBrowseSceneProps {
  searchQuery?: string;
  videoSrc?: string;
  audioSrc?: string;
  words?: Array<{ text: string; start: number; end: number }>;
}

export const YouTubeBrowseScene: React.FC<YouTubeBrowseSceneProps> = ({
  searchQuery = "ishowspeed",
  videoSrc = "yt_search.mp4",
  audioSrc,
  words = [],
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // 1. Camera Punch-in Zoom & Pan (Matching Reference Video)
  // Frames 0-60: subtle 1.0 -> 1.03 scale
  // Frames 60-105: punch-in zoom onto Share sheet (scale up to 1.24x, translateY -70px)
  const cameraScale = interpolate(
    frame,
    [0, 50, 75, 102, 110],
    [1.0, 1.03, 1.10, 1.24, 1.30],
    { extrapolateRight: "clamp" }
  );

  const cameraY = interpolate(
    frame,
    [0, 50, 75, 102, 110],
    [0, -10, -35, -75, -85],
    { extrapolateRight: "clamp" }
  );

  // Whip-blur transition on final 6 frames (104 - 110)
  const whipBlur = interpolate(frame, [104, 110], [0, 18], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // 2. Accurate Cursor Path (Mapped to 870x1722 screen content space)
  let cursorX = 550;
  let cursorY = 750;
  let cursorOpacity = 1;
  let cursorScale = 1.0;

  if (frame < 18) {
    // Fly in towards search input
    cursorX = interpolate(frame, [0, 16], [640, 390], { extrapolateRight: "clamp" });
    cursorY = interpolate(frame, [0, 16], [850, 95], { extrapolateRight: "clamp" });
    cursorOpacity = interpolate(frame, [0, 4], [0, 1], { extrapolateRight: "clamp" });
  } else if (frame < 48) {
    // Touch swipe down / scroll motion
    cursorX = interpolate(frame, [18, 28, 45], [390, 440, 420], { extrapolateRight: "clamp" });
    cursorY = interpolate(frame, [18, 30, 45], [95, 540, 400], { extrapolateRight: "clamp" });
  } else if (frame < 62) {
    // Move to video card "BUYING THE NEW iPHONE DUO!" at (430, 350) and tap at frame 55
    cursorX = interpolate(frame, [48, 54], [420, 435], { extrapolateRight: "clamp" });
    cursorY = interpolate(frame, [48, 54], [400, 350], { extrapolateRight: "clamp" });
    if (frame >= 54 && frame <= 58) {
      cursorScale = interpolate(frame, [54, 55, 58], [1.0, 0.85, 1.0]);
    }
  } else if (frame < 78) {
    // Watch page loaded: move to Share curved arrow button (x: 625, y: 410) and tap at frame 75
    cursorX = interpolate(frame, [62, 74], [435, 625], { extrapolateRight: "clamp" });
    cursorY = interpolate(frame, [62, 74], [350, 410], { extrapolateRight: "clamp" });
    if (frame >= 74 && frame <= 77) {
      cursorScale = interpolate(frame, [74, 75, 77], [1.0, 0.85, 1.0]);
    }
  } else {
    // Share sheet open: move down to "Copy link" (x: 435, y: 1410) and tap at frame 85
    cursorX = interpolate(frame, [78, 84], [625, 435], { extrapolateRight: "clamp" });
    cursorY = interpolate(frame, [78, 84], [410, 1410], { extrapolateRight: "clamp" });
    if (frame >= 84 && frame <= 88) {
      cursorScale = interpolate(frame, [84, 85, 88], [1.0, 0.85, 1.0]);
    }
    if (frame > 96) {
      cursorOpacity = interpolate(frame, [96, 106], [1, 0.3]);
    }
  }

  // 3. Tap Ripples
  // Ripple 1: Video tap at frame 55 (at x: 435, y: 350)
  const ripple1Progress = spring({
    frame: frame - 55,
    fps,
    config: { damping: 14, stiffness: 120 },
  });
  const ripple1Scale = interpolate(ripple1Progress, [0, 1], [0.2, 1.8]);
  const ripple1Opacity = frame >= 55 ? interpolate(frame, [55, 63], [0.85, 0], { extrapolateRight: "clamp" }) : 0;

  // Ripple 2: Share button tap at frame 75 (at x: 625, y: 410)
  const ripple2Progress = spring({
    frame: frame - 75,
    fps,
    config: { damping: 14, stiffness: 120 },
  });
  const ripple2Scale = interpolate(ripple2Progress, [0, 1], [0.2, 1.6]);
  const ripple2Opacity = frame >= 75 ? interpolate(frame, [75, 82], [0.85, 0], { extrapolateRight: "clamp" }) : 0;

  // Ripple 3: Copy link tap at frame 85 (at x: 435, y: 1410)
  const ripple3Progress = spring({
    frame: frame - 85,
    fps,
    config: { damping: 14, stiffness: 120 },
  });
  const ripple3Scale = interpolate(ripple3Progress, [0, 1], [0.2, 1.8]);
  const ripple3Opacity = frame >= 85 ? interpolate(frame, [85, 93], [0.85, 0], { extrapolateRight: "clamp" }) : 0;

  // 4. Share Sheet Drawer Slide-Up (Matching exact YouTube iOS Share Sheet from reference)
  const shareSheetSpring = spring({
    frame: frame - 76,
    fps,
    config: { damping: 16, stiffness: 140 },
  });
  const shareSheetProgress = frame >= 76 ? Math.min(1, Math.max(0, shareSheetSpring)) : 0;

  // 5. Toast Notification "Link copied to clipboard"
  const toastSpring = spring({
    frame: frame - 86,
    fps,
    config: { damping: 13, stiffness: 140 },
  });
  const toastY = interpolate(toastSpring, [0, 1], [30, 0]);
  const toastOpacity = frame >= 86 ? interpolate(frame, [86, 90, 106, 110], [0, 1, 1, 0.6], { extrapolateRight: "clamp" }) : 0;

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        backgroundColor: "#000000",
        overflow: "hidden",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      {/* ── EXACT SYNCHRONIZED VOICEOVER & SFX ── */}
      {audioSrc ? (
        <Audio src={audioSrc.startsWith("/") ? audioSrc : staticFile(audioSrc)} volume={1.0} />
      ) : (
        <Sequence from={0} durationInFrames={110}>
          <Audio src={staticFile("vo/vo_scene2.mp3")} volume={1.0} />
        </Sequence>
      )}
      <Sequence from={55} durationInFrames={15}>
        <Audio src={staticFile("sfx/mouse_click_mech.mp3")} volume={0.7} />
      </Sequence>
      <Sequence from={75} durationInFrames={15}>
        <Audio src={staticFile("sfx/pop_click.mp3")} volume={0.6} />
      </Sequence>
      <Sequence from={85} durationInFrames={15}>
        <Audio src={staticFile("sfx/mouse_click_mech.mp3")} volume={0.8} />
      </Sequence>
      <Sequence from={86} durationInFrames={20}>
        <Audio src={staticFile("sfx/pop_bubble.mp3")} volume={0.75} />
      </Sequence>
      <Sequence from={104} durationInFrames={25}>
        <Audio src={staticFile("sfx/whoosh_fast.mp3")} volume={0.5} />
      </Sequence>
      {/* Subtle Studio Ambient Radial Glow behind phone */}
      <div
        style={{
          position: "absolute",
          width: 1200,
          height: 1200,
          borderRadius: "50%",
          background:
            "radial-gradient(circle, rgba(255, 70, 40, 0.09) 0%, rgba(30, 20, 25, 0.35) 50%, rgba(0,0,0,0) 80%)",
          filter: "blur(70px)",
          pointerEvents: "none",
        }}
      />

      {/* Main Camera Container with dynamic Zoom & Whip-blur */}
      <div
        style={{
          transform: `scale(${cameraScale}) translateY(${cameraY}px)`,
          filter: whipBlur > 0 ? `blur(${whipBlur}px)` : undefined,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          transformOrigin: "center 48%",
        }}
      >
        {/* Phone Container with 2-3% film-softness (blur 0.3px) */}
        <div
          style={{
            filter: "blur(0.3px)", // 2-3% film softness matching overlay & recording
            position: "relative",
          }}
        >
          <PhoneMock width={780} safeAreaTop={56} safeAreaBottom={22}>
            {/* Screen Inner Content Area */}
            <div
              style={{
                position: "relative",
                width: "100%",
                height: "100%",
                backgroundColor: "#0f0f0f",
                overflow: "hidden",
              }}
            >
              {/* 1. Real Screen Recording Video via <OffthreadVideo> */}
              <OffthreadVideo
                src={staticFile(videoSrc)}
                style={{
                  width: "100%",
                  height: "100%",
                  objectFit: "cover",
                }}
              />

              {/* 2. Tap Ripple 1 (Video Tap at f55) */}
              {ripple1Opacity > 0 && (
                <div
                  style={{
                    position: "absolute",
                    left: 435,
                    top: 288,
                    width: 110,
                    height: 110,
                    borderRadius: "50%",
                    border: "3.5px solid rgba(255, 255, 255, 0.95)",
                    backgroundColor: "rgba(255, 255, 255, 0.28)",
                    transform: `translate(-50%, -50%) scale(${ripple1Scale})`,
                    opacity: ripple1Opacity,
                    pointerEvents: "none",
                    zIndex: 220,
                  }}
                />
              )}

              {/* Tap Ripple 2 (Share Button Tap at f75) */}
              {ripple2Opacity > 0 && (
                <div
                  style={{
                    position: "absolute",
                    left: 625,
                    top: 348,
                    width: 90,
                    height: 90,
                    borderRadius: "50%",
                    border: "3.5px solid rgba(255, 255, 255, 0.95)",
                    backgroundColor: "rgba(255, 255, 255, 0.3)",
                    transform: `translate(-50%, -50%) scale(${ripple2Scale})`,
                    opacity: ripple2Opacity,
                    pointerEvents: "none",
                    zIndex: 220,
                  }}
                />
              )}

              {/* 3. Authentic YouTube / iOS Share Sheet Modal Drawer (Reference Exact) */}
              {shareSheetProgress > 0 && (
                <div
                  style={{
                    position: "absolute",
                    left: 0,
                    right: 0,
                    bottom: 0,
                    backgroundColor: "rgba(33, 33, 36, 0.98)",
                    backdropFilter: "blur(25px)",
                    borderTopLeftRadius: 28,
                    borderTopRightRadius: 28,
                    padding: "14px 26px 36px",
                    boxShadow: "0 -20px 60px rgba(0, 0, 0, 0.95)",
                    borderTop: "1px solid rgba(255, 255, 255, 0.14)",
                    transform: `translateY(${(1 - shareSheetProgress) * 105}%)`,
                    zIndex: 250,
                  }}
                >
                  {/* Handle Pill */}
                  <div
                    style={{
                      width: 44,
                      height: 4,
                      backgroundColor: "rgba(255, 255, 255, 0.4)",
                      borderRadius: 2,
                      margin: "0 auto 16px",
                    }}
                  />

                  {/* Header: "Share" */}
                  <div
                    style={{
                      fontSize: 22,
                      fontWeight: 700,
                      color: "#ffffff",
                      fontFamily: "-apple-system, BlinkMacSystemFont, 'SF Pro Display', sans-serif",
                      marginBottom: 20,
                    }}
                  >
                    Share
                  </div>

                  {/* Social Apps Row (WhatsApp, Messages, X, Gmail) */}
                  <div
                    style={{
                      display: "flex",
                      gap: 20,
                      overflowX: "hidden",
                      marginBottom: 24,
                      paddingBottom: 4,
                    }}
                  >
                    {[
                      { name: "WhatsApp", icon: "💬", bg: "#25D366" },
                      { name: "Messages", icon: "✉️", bg: "#34C759" },
                      { name: "X", icon: "𝕏", bg: "#000000" },
                      { name: "Gmail", icon: "✉️", bg: "#ffffff", color: "#EA4335" },
                    ].map((app) => (
                      <div
                        key={app.name}
                        style={{
                          display: "flex",
                          flexDirection: "column",
                          alignItems: "center",
                          gap: 8,
                          minWidth: 70,
                        }}
                      >
                        <div
                          style={{
                            width: 62,
                            height: 62,
                            borderRadius: "50%",
                            backgroundColor: app.bg,
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            fontSize: 26,
                            color: app.color || "#ffffff",
                            boxShadow: "0 6px 16px rgba(0,0,0,0.5)",
                            border: "1px solid rgba(255,255,255,0.15)",
                          }}
                        >
                          {app.icon}
                        </div>
                        <span
                          style={{
                            fontSize: 13,
                            color: "#cccccc",
                            fontWeight: 500,
                          }}
                        >
                          {app.name}
                        </span>
                      </div>
                    ))}
                  </div>

                  {/* Action 1: "Copy link" (Exact Reference Button) */}
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      padding: "16px 20px",
                      backgroundColor:
                        frame >= 85
                          ? "rgba(255, 255, 255, 0.18)"
                          : "rgba(255, 255, 255, 0.07)",
                      borderRadius: 18,
                      gap: 18,
                      marginBottom: 12,
                      border:
                        frame >= 85
                          ? "2px solid #ffffff"
                          : "1px solid rgba(255, 255, 255, 0.1)",
                      position: "relative",
                    }}
                  >
                    {/* Copy Link SVG Icon (Two overlapping rectangles) */}
                    <div
                      style={{
                        width: 44,
                        height: 44,
                        borderRadius: "50%",
                        backgroundColor: "rgba(255, 255, 255, 0.12)",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                      }}
                    >
                      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" strokeWidth="2">
                        <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                      </svg>
                    </div>

                    <div style={{ flex: 1 }}>
                      <div
                        style={{
                          fontSize: 18,
                          fontWeight: 700,
                          color: "#ffffff",
                        }}
                      >
                        Copy link
                      </div>
                    </div>

                    {/* Ripple 3 (Copy Link Tap at f85) */}
                    {ripple3Opacity > 0 && (
                      <div
                        style={{
                          position: "absolute",
                          left: "50%",
                          top: "50%",
                          width: 160,
                          height: 160,
                          borderRadius: "50%",
                          border: "4px solid rgba(255, 255, 255, 0.95)",
                          backgroundColor: "rgba(255, 255, 255, 0.3)",
                          transform: `translate(-50%, -50%) scale(${ripple3Scale})`,
                          opacity: ripple3Opacity,
                          pointerEvents: "none",
                        }}
                      />
                    )}
                  </div>

                  {/* Action 2: "Create post" */}
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      padding: "16px 20px",
                      backgroundColor: "rgba(255, 255, 255, 0.07)",
                      borderRadius: 18,
                      gap: 18,
                      border: "1px solid rgba(255, 255, 255, 0.1)",
                    }}
                  >
                    <div
                      style={{
                        width: 44,
                        height: 44,
                        borderRadius: "50%",
                        backgroundColor: "rgba(255, 255, 255, 0.12)",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                      }}
                    >
                      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" strokeWidth="2">
                        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                        <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                      </svg>
                    </div>

                    <div style={{ flex: 1 }}>
                      <div
                        style={{
                          fontSize: 18,
                          fontWeight: 600,
                          color: "#dddddd",
                        }}
                      >
                        Create post
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* 4. Link Copied Floating Toast Notification */}
              {toastOpacity > 0 && (
                <div
                  style={{
                    position: "absolute",
                    bottom: 340,
                    left: "50%",
                    transform: `translateX(-50%) translateY(${toastY}px)`,
                    backgroundColor: "rgba(18, 18, 22, 0.96)",
                    backdropFilter: "blur(20px)",
                    border: "1.5px solid rgba(255, 215, 100, 0.75)",
                    color: "#ffe071",
                    padding: "14px 28px",
                    borderRadius: 30,
                    fontSize: 18,
                    fontWeight: 800,
                    boxShadow:
                      "0 20px 60px rgba(0, 0, 0, 0.95), 0 0 30px rgba(255, 215, 100, 0.25)",
                    opacity: toastOpacity,
                    pointerEvents: "none",
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                    zIndex: 280,
                    whiteSpace: "nowrap",
                  }}
                >
                  <span style={{ fontSize: 22, color: "#4ade80" }}>✓</span>
                  <span>Link copied to clipboard</span>
                </div>
              )}

              {/* 5. Synchronized FakeCursor Pointer */}
              <FakeCursor
                x={cursorX}
                y={cursorY}
                scale={cursorScale}
                opacity={cursorOpacity}
              />
            </div>
          </PhoneMock>
        </div>
      </div>

      {/* Word Pop Captions overlay */}
      {words.length > 0 && (
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
