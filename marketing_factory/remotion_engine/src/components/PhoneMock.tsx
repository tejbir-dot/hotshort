import React from "react";

interface PhoneMockProps {
  children: React.ReactNode;
  width?: number; // 890px for accurate reference framing in 1080x1920
  bezelColor?: string;
  safeAreaTop?: number;
  safeAreaBottom?: number;
}

export const PhoneMock: React.FC<PhoneMockProps> = ({
  children,
  width = 780,
  bezelColor = "#b88a78", // Titanium Rose-Gold matching reference
  safeAreaTop = 56,
  safeAreaBottom = 22,
}) => {
  // Proportional iPhone 15 Pro dimensions (393 x 852 ratio = 2.168)
  const height = Math.round(width * 2.168); // Exact ratio verified in out_accurate_f85.png

  return (
    <div
      style={{
        position: "relative",
        width,
        height,
        borderRadius: 62,
        padding: 10,
        background: `linear-gradient(150deg, #dfb9a8 0%, ${bezelColor} 30%, #8c5d4b 75%, #dfb9a8 100%)`,
        boxShadow:
          "0 40px 100px rgba(0, 0, 0, 0.95), 0 0 45px rgba(223, 185, 168, 0.2), inset 0 2px 4px rgba(255, 255, 255, 0.45)",
        boxSizing: "border-box",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
      }}
    >
      {/* Outer Metallic Bezel Ring */}
      <div
        style={{
          position: "absolute",
          inset: 2,
          borderRadius: 58,
          border: "2px solid rgba(255, 255, 255, 0.28)",
          pointerEvents: "none",
        }}
      />

      {/* Side Button Accents (Left Volume Buttons & Right Power Button) */}
      <div
        style={{
          position: "absolute",
          left: -2,
          top: 240,
          width: 3,
          height: 60,
          background: "rgba(255, 255, 255, 0.35)",
          borderRadius: 2,
          pointerEvents: "none",
        }}
      />
      <div
        style={{
          position: "absolute",
          left: -2,
          top: 320,
          width: 3,
          height: 60,
          background: "rgba(255, 255, 255, 0.35)",
          borderRadius: 2,
          pointerEvents: "none",
        }}
      />
      <div
        style={{
          position: "absolute",
          right: -2,
          top: 280,
          width: 3,
          height: 90,
          background: "rgba(255, 255, 255, 0.35)",
          borderRadius: 2,
          pointerEvents: "none",
        }}
      />

      {/* Inner OLED Screen Display */}
      <div
        style={{
          position: "relative",
          width: "100%",
          height: "100%",
          backgroundColor: "#000000",
          borderRadius: 52,
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
        }}
      >
        {/* iOS Status Bar (Baked into Phone Frame) */}
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            right: 0,
            height: safeAreaTop,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "0 34px",
            zIndex: 150,
            pointerEvents: "none",
            background:
              "linear-gradient(180deg, rgba(0, 0, 0, 0.7) 0%, rgba(0, 0, 0, 0.2) 60%, rgba(0, 0, 0, 0) 100%)",
          }}
        >
          {/* Time & Location Arrow */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 4,
              fontFamily:
                "-apple-system, BlinkMacSystemFont, 'SF Pro Text', sans-serif",
              fontSize: 20,
              fontWeight: 700,
              color: "#FFFFFF",
              letterSpacing: -0.3,
            }}
          >
            <span>11:45</span>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="#FFFFFF">
              <path d="M2 12l20-9-9 20-3-8z" />
            </svg>
          </div>

          {/* Dynamic Island with Camera Sensor & Subtle Mic Dot */}
          <div
            style={{
              position: "absolute",
              left: "50%",
              top: 12,
              transform: "translateX(-50%)",
              width: 172,
              height: 36,
              backgroundColor: "#000000",
              borderRadius: 20,
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "0 12px",
              boxShadow: "0 0 10px rgba(0,0,0,0.9)",
              border: "1px solid rgba(255,255,255,0.06)",
            }}
          >
            {/* Camera sensor dot */}
            <div
              style={{
                width: 12,
                height: 12,
                borderRadius: "50%",
                background: "#080c18",
                border: "1.5px solid #1a2236",
              }}
            />
            {/* Orange Mic Indicator Dot (Exact reference detail) */}
            <div
              style={{
                width: 7,
                height: 7,
                borderRadius: "50%",
                background: "#ff9500",
                boxShadow: "0 0 6px #ff9500",
              }}
            />
          </div>

          {/* Right Status Icons (Signal, 5G, Wi-Fi, 91% Battery) */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 7,
              color: "#FFFFFF",
            }}
          >
            {/* Signal Bars */}
            <svg width="19" height="13" viewBox="0 0 17 12" fill="#FFFFFF">
              <rect x="0" y="9" width="3" height="3" rx="0.5" />
              <rect x="4.5" y="6" width="3" height="6" rx="0.5" />
              <rect x="9" y="3" width="3" height="9" rx="0.5" />
              <rect x="13.5" y="0" width="3" height="12" rx="0.5" />
            </svg>

            {/* 5G Text */}
            <span
              style={{
                fontSize: 14,
                fontWeight: 700,
                letterSpacing: -0.5,
              }}
            >
              5G
            </span>

            {/* Battery Icon with 91% charge */}
            <div
              style={{
                width: 28,
                height: 14,
                borderRadius: 4.5,
                border: "1.8px solid #FFFFFF",
                padding: 1.5,
                display: "flex",
                alignItems: "center",
                position: "relative",
              }}
            >
              <div
                style={{
                  width: "91%",
                  height: "100%",
                  background: "#FFFFFF",
                  borderRadius: 2,
                }}
              />
              <div
                style={{
                  position: "absolute",
                  right: -4,
                  top: 3.5,
                  width: 2.5,
                  height: 5,
                  background: "#FFFFFF",
                  borderTopRightRadius: 2,
                  borderBottomRightRadius: 2,
                }}
              />
            </div>
          </div>
        </div>

        {/* Dynamic Screen Content (YouTube UI / Screen Recording) */}
        <div
          style={{
            flex: 1,
            position: "relative",
            overflow: "hidden",
            paddingTop: safeAreaTop,
            paddingBottom: safeAreaBottom,
            boxSizing: "border-box",
            display: "flex",
            flexDirection: "column",
          }}
        >
          {children}
        </div>

        {/* iOS Home Indicator Bar */}
        <div
          style={{
            position: "absolute",
            bottom: 8,
            left: "50%",
            transform: "translateX(-50%)",
            width: 148,
            height: 5,
            backgroundColor: "rgba(255, 255, 255, 0.75)",
            borderRadius: 3,
            zIndex: 150,
            pointerEvents: "none",
          }}
        />
      </div>
    </div>
  );
};
