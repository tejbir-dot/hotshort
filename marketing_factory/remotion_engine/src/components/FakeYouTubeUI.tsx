import React from "react";
import { Img, staticFile } from "remotion";

export interface YouTubeVideoItem {
  id: string;
  title: string;
  channel: string;
  views: string;
  timeAgo: string;
  duration: string;
  thumbnailSrc: string;
  channelAvatarSrc?: string;
  verified?: boolean;
}

export const defaultYouTubeVideos: YouTubeVideoItem[] = [
  {
    id: "vid_1",
    title: "IShowSpeed Travels To India & Meets Daler Mehndi (INSANE STREAM)",
    channel: "IShowSpeed",
    views: "18.4M views",
    timeAgo: "3 days ago",
    duration: "2:41:19",
    thumbnailSrc: staticFile("thumbs/thumb_speed.jpg"),
    channelAvatarSrc: staticFile("thumbs/thumb_speed.jpg"),
    verified: true,
  },
  {
    id: "vid_2",
    title: "Kai Cenat & Speed Diamond Sword Challenge",
    channel: "Kai Cenat",
    views: "34.8M views",
    timeAgo: "1 week ago",
    duration: "14:28",
    thumbnailSrc: staticFile("thumbs/thumb_stream.jpg"),
    channelAvatarSrc: staticFile("thumbs/thumb_stream.jpg"),
    verified: true,
  },
  {
    id: "vid_3",
    title: "How Streamers Make Millions From AI Shorts (Full Breakdown)",
    channel: "HotShort Studio",
    views: "1.2M views",
    timeAgo: "2 weeks ago",
    duration: "8:55",
    thumbnailSrc: staticFile("thumbs/thumb_crypto.jpg"),
    channelAvatarSrc: staticFile("thumbs/thumb_crypto.jpg"),
    verified: true,
  },
];

export interface FakeYouTubeUIProps {
  searchQuery?: string;
  videos?: YouTubeVideoItem[];
  scrollY?: number;
  isTargetClicked?: boolean;
  targetClickRippleScale?: number;
  targetClickRippleOpacity?: number;
  shareSheetProgress?: number; // 0 (hidden) to 1 (fully open)
  isCopyLinkClicked?: boolean;
  toastOpacity?: number;
}

export const FakeYouTubeUI: React.FC<FakeYouTubeUIProps> = ({
  searchQuery = "ishowspeed",
  videos = defaultYouTubeVideos,
  scrollY = 0,
  isTargetClicked = false,
  targetClickRippleScale = 0,
  targetClickRippleOpacity = 0,
  shareSheetProgress = 0,
  isCopyLinkClicked = false,
  toastOpacity = 0,
}) => {
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        backgroundColor: "#0f0f0f",
        color: "#ffffff",
        fontFamily:
          "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'SF Pro Display', sans-serif",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
      }}
    >
      {/* Fixed Top Section: Header + Filter Chips */}
      <div
        style={{
          paddingTop: 56, // below status bar
          backgroundColor: "#0f0f0f",
          zIndex: 80,
          borderBottom: "1px solid rgba(255,255,255,0.06)",
        }}
      >
        {/* Search Bar Row */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            padding: "8px 18px",
            gap: 12,
          }}
        >
          {/* Back Arrow */}
          <div style={{ fontSize: 26, color: "#f1f1f1", cursor: "pointer" }}>
            ←
          </div>

          {/* Search Input Box */}
          <div
            style={{
              flex: 1,
              height: 44,
              backgroundColor: "#272727",
              borderRadius: 22,
              display: "flex",
              alignItems: "center",
              padding: "0 16px",
              gap: 10,
            }}
          >
            <span style={{ fontSize: 18, color: "#888" }}>🔍</span>
            <span
              style={{
                flex: 1,
                fontSize: 18,
                color: "#ffffff",
                fontWeight: 500,
              }}
            >
              {searchQuery}
            </span>
            <span style={{ fontSize: 16, color: "#aaa" }}>✕</span>
          </div>

          {/* Mic Icon */}
          <div
            style={{
              width: 44,
              height: 44,
              borderRadius: "50%",
              backgroundColor: "#272727",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 20,
            }}
          >
            🎙
          </div>
        </div>

        {/* Filter Chips Horizontal Row */}
        <div
          style={{
            display: "flex",
            gap: 8,
            padding: "8px 18px 14px",
            overflowX: "hidden",
          }}
        >
          <div
            style={{
              background: "#ffffff",
              color: "#0f0f0f",
              padding: "7px 18px",
              borderRadius: 16,
              fontSize: 15,
              fontWeight: 700,
            }}
          >
            All
          </div>
          <div
            style={{
              background: "#272727",
              color: "#f1f1f1",
              padding: "7px 16px",
              borderRadius: 16,
              fontSize: 15,
              fontWeight: 500,
            }}
          >
            Shorts
          </div>
          <div
            style={{
              background: "#272727",
              color: "#f1f1f1",
              padding: "7px 16px",
              borderRadius: 16,
              fontSize: 15,
              fontWeight: 500,
            }}
          >
            Videos
          </div>
          <div
            style={{
              background: "#272727",
              color: "#f1f1f1",
              padding: "7px 16px",
              borderRadius: 16,
              fontSize: 15,
              fontWeight: 500,
            }}
          >
            Live
          </div>
          <div
            style={{
              background: "#272727",
              color: "#f1f1f1",
              padding: "7px 16px",
              borderRadius: 16,
              fontSize: 15,
              fontWeight: 500,
              whiteSpace: "nowrap",
            }}
          >
            Recently uploaded
          </div>
        </div>
      </div>

      {/* Scrollable Feed Container */}
      <div
        style={{
          flex: 1,
          position: "relative",
          transform: `translateY(${scrollY}px)`,
        }}
      >
        {videos.map((video, idx) => {
          const isTarget = idx === 1; // 2nd video is the tap target
          return (
            <div
              key={video.id}
              style={{
                position: "relative",
                marginBottom: 26,
                backgroundColor: "#0f0f0f",
              }}
            >
              {/* Thumbnail Container */}
              <div
                style={{
                  position: "relative",
                  width: "100%",
                  height: 440,
                  backgroundColor: "#181818",
                  overflow: "hidden",
                  filter: isTarget && isTargetClicked ? "brightness(0.92)" : "none",
                  transition: "filter 0.1s ease",
                }}
              >
                <Img
                  src={video.thumbnailSrc}
                  style={{
                    width: "100%",
                    height: "100%",
                    objectFit: "cover",
                  }}
                />

                {/* Duration Badge */}
                <div
                  style={{
                    position: "absolute",
                    bottom: 12,
                    right: 14,
                    backgroundColor: "rgba(0, 0, 0, 0.85)",
                    color: "#ffffff",
                    fontSize: 13,
                    fontWeight: 700,
                    padding: "3px 8px",
                    borderRadius: 6,
                    letterSpacing: 0.5,
                  }}
                >
                  {video.duration}
                </div>

                {/* Click Ripple on Target Video */}
                {isTarget && targetClickRippleOpacity > 0 && (
                  <div
                    style={{
                      position: "absolute",
                      left: "50%",
                      top: "50%",
                      width: 120,
                      height: 120,
                      borderRadius: "50%",
                      border: "4px solid rgba(255, 255, 255, 0.9)",
                      backgroundColor: "rgba(255, 255, 255, 0.2)",
                      transform: `translate(-50%, -50%) scale(${targetClickRippleScale})`,
                      opacity: targetClickRippleOpacity,
                      pointerEvents: "none",
                    }}
                  />
                )}
              </div>

              {/* Video Info Row */}
              <div
                style={{
                  display: "flex",
                  padding: "14px 18px 4px",
                  gap: 14,
                  alignItems: "flex-start",
                }}
              >
                {/* Channel Avatar */}
                <div
                  style={{
                    width: 44,
                    height: 44,
                    borderRadius: "50%",
                    overflow: "hidden",
                    backgroundColor: "#333",
                    flexShrink: 0,
                  }}
                >
                  {video.channelAvatarSrc && (
                    <Img
                      src={video.channelAvatarSrc}
                      style={{
                        width: "100%",
                        height: "100%",
                        objectFit: "cover",
                      }}
                    />
                  )}
                </div>

                {/* Title & Metadata */}
                <div style={{ flex: 1 }}>
                  <div
                    style={{
                      fontSize: 17,
                      fontWeight: 700,
                      lineHeight: 1.35,
                      color: "#f1f1f1",
                      marginBottom: 6,
                      display: "-webkit-box",
                      WebkitLineClamp: 2,
                      WebkitBoxOrient: "vertical",
                      overflow: "hidden",
                    }}
                  >
                    {video.title}
                  </div>
                  <div
                    style={{
                      fontSize: 14,
                      color: "#aaaaaa",
                      display: "flex",
                      alignItems: "center",
                      gap: 6,
                    }}
                  >
                    <span>{video.channel}</span>
                    {video.verified && (
                      <span
                        style={{
                          display: "inline-block",
                          width: 14,
                          height: 14,
                          background: "#717171",
                          color: "#0f0f0f",
                          borderRadius: "50%",
                          fontSize: 9,
                          textAlign: "center",
                          lineHeight: "14px",
                          fontWeight: 900,
                        }}
                      >
                        ✓
                      </span>
                    )}
                    <span>•</span>
                    <span>{video.views}</span>
                    <span>•</span>
                    <span>{video.timeAgo}</span>
                  </div>
                </div>

                {/* 3-dots Menu */}
                <div
                  style={{
                    fontSize: 22,
                    color: "#888888",
                    padding: "0 4px",
                    cursor: "pointer",
                  }}
                >
                  ⋮
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Share Sheet Modal Drawer (Slide-up) */}
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: "#212121",
          borderTopLeftRadius: 32,
          borderTopRightRadius: 32,
          padding: "16px 24px 44px",
          boxShadow: "0 -15px 50px rgba(0, 0, 0, 0.9)",
          borderTop: "1px solid rgba(255, 255, 255, 0.12)",
          transform: `translateY(${(1 - shareSheetProgress) * 105}%)`,
          zIndex: 120,
        }}
      >
        {/* Modal Handle Pill */}
        <div
          style={{
            width: 48,
            height: 5,
            backgroundColor: "#555",
            borderRadius: 3,
            margin: "0 auto 16px",
          }}
        />

        {/* Modal Title */}
        <div
          style={{
            fontSize: 18,
            fontWeight: 700,
            color: "#ffffff",
            marginBottom: 20,
          }}
        >
          Share this video
        </div>

        {/* Social Apps Row */}
        <div
          style={{
            display: "flex",
            gap: 20,
            overflowX: "hidden",
            marginBottom: 24,
          }}
        >
          {[
            { name: "WhatsApp", icon: "💬", bg: "#25D366" },
            { name: "Messages", icon: "✉️", bg: "#34C759" },
            { name: "X", icon: "𝕏", bg: "#000000" },
            { name: "Instagram", icon: "📷", bg: "#E1306C" },
            { name: "Create post", icon: "✏️", bg: "#333333" },
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
                  width: 58,
                  height: 58,
                  borderRadius: "50%",
                  backgroundColor: app.bg,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 24,
                  boxShadow: "0 4px 12px rgba(0,0,0,0.4)",
                  border: "1px solid rgba(255,255,255,0.15)",
                }}
              >
                {app.icon}
              </div>
              <span style={{ fontSize: 13, color: "#ccc", fontWeight: 500 }}>
                {app.name}
              </span>
            </div>
          ))}
        </div>

        {/* Primary Action: Copy Link Row */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            padding: "16px 20px",
            backgroundColor: isCopyLinkClicked
              ? "rgba(255, 255, 255, 0.22)"
              : "rgba(255, 255, 255, 0.08)",
            borderRadius: 18,
            gap: 16,
            cursor: "pointer",
            border: isCopyLinkClicked
              ? "1.5px solid #ffffff"
              : "1px solid rgba(255, 255, 255, 0.1)",
            transition: "all 0.15s ease",
          }}
        >
          <div
            style={{
              width: 44,
              height: 44,
              borderRadius: "50%",
              background: "linear-gradient(135deg, #ff0055, #ff5500)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 22,
              boxShadow: "0 0 16px rgba(255, 0, 85, 0.4)",
            }}
          >
            🔗
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 17, fontWeight: 700, color: "#ffffff" }}>
              Copy link
            </div>
            <div style={{ fontSize: 13, color: "#aaaaaa" }}>
              https://youtu.be/kAiCeNat_981
            </div>
          </div>
          <span style={{ fontSize: 20, color: "#fff" }}>›</span>
        </div>
      </div>

      {/* Link Copied Floating Toast Notification */}
      <div
        style={{
          position: "absolute",
          bottom: 330,
          left: "50%",
          transform: "translateX(-50%)",
          backgroundColor: "rgba(18, 18, 22, 0.96)",
          backdropFilter: "blur(20px)",
          border: "1.5px solid rgba(255, 215, 100, 0.75)",
          color: "#ffe071",
          padding: "14px 28px",
          borderRadius: 30,
          fontSize: 18,
          fontWeight: 800,
          boxShadow: "0 20px 60px rgba(0, 0, 0, 0.95), 0 0 30px rgba(255, 215, 100, 0.25)",
          opacity: toastOpacity,
          pointerEvents: "none",
          display: "flex",
          alignItems: "center",
          gap: 12,
          zIndex: 200,
          whiteSpace: "nowrap",
        }}
      >
        <span style={{ fontSize: 22, color: "#4ade80" }}>✓</span>
        <span>Link copied to clipboard</span>
      </div>
    </div>
  );
};
