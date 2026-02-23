/**
 * Aspect Ratio Selector Component
 * Provides UI for selecting video aspect ratios for different platforms
 */

const ASPECT_RATIOS = {
    "native": {
        label: "Native (Original)",
        description: "Keep original video aspect ratio",
        icon: "📹"
    },
    "16:9": {
        label: "YouTube/Desktop",
        description: "16:9 Horizontal - YouTube, Desktop",
        icon: "📺",
        platforms: ["YouTube", "Desktop"]
    },
    "9:16": {
        label: "TikTok/Reels/Shorts",
        description: "9:16 Vertical - TikTok, Instagram Reels, YouTube Shorts",
        icon: "📱",
        platforms: ["TikTok", "Instagram Reels", "YouTube Shorts"]
    },
    "1:1": {
        label: "Instagram Feed",
        description: "1:1 Square - Instagram Feed, Twitter, Pinterest",
        icon: "⬜",
        platforms: ["Instagram Feed", "Twitter", "Pinterest"]
    },
    "4:3": {
        label: "Classic Format",
        description: "4:3 - Older video formats",
        icon: "📽️",
        platforms: ["Legacy"]
    },
    "21:9": {
        label: "Ultra-wide",
        description: "21:9 Cinematic - Ultra-wide displays",
        icon: "🎬",
        platforms: ["Cinematic", "Ultra-wide"]
    }
};

const PADDING_COLORS = {
    "black": "Black (Professional)",
    "white": "White (Clean)",
    "blur": "Blur (Smart)",
    "transparent": "Transparent"
};

/**
 * Render aspect ratio selector UI
 */
function createAspectRatioSelector() {
    const container = document.createElement("div");
    container.className = "aspect-ratio-selector";
    container.innerHTML = `
        <div class="ratio-section">
            <h3>📐 Video Format</h3>
            <div class="ratio-buttons">
                ${Object.entries(ASPECT_RATIOS).map(([key, config]) => `
                    <button 
                        class="ratio-btn ${key === '16:9' ? 'active' : ''}" 
                        data-ratio="${key}"
                        title="${config.description}"
                    >
                        <span class="ratio-icon">${config.icon}</span>
                        <span class="ratio-label">${config.label}</span>
                    </button>
                `).join('')}
            </div>
        </div>
        
        <div class="padding-section">
            <h3>🎨 Padding Color</h3>
            <select id="paddingColor" class="padding-select">
                ${Object.entries(PADDING_COLORS).map(([key, label]) => `
                    <option value="${key}" ${key === 'black' ? 'selected' : ''}>${label}</option>
                `).join('')}
            </select>
        </div>
        
        <div class="preview-section">
            <h3>👁️ Preview</h3>
            <div class="ratio-preview" id="ratioPreview">
                <div class="preview-box" style="aspect-ratio: 16/9;">
                    <span>16:9 Preview</span>
                </div>
            </div>
        </div>
    `;
    
    // Add event listeners
    container.querySelectorAll(".ratio-btn").forEach(btn => {
        btn.addEventListener("click", (e) => {
            container.querySelectorAll(".ratio-btn").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            updatePreview(btn.dataset.ratio, container);
        });
    });
    
    return container;
}

/**
 * Update preview based on selected ratio
 */
function updatePreview(ratio, container) {
    const previewBox = container.querySelector(".preview-box");
    const config = ASPECT_RATIOS[ratio];
    
    if (ratio === "native") {
        previewBox.style.aspectRatio = "16/9"; // Default
    } else {
        // Convert ratio string to decimal
        const [w, h] = ratio.split(":").map(Number);
        previewBox.style.aspectRatio = `${w}/${h}`;
    }
    
    previewBox.innerHTML = `<span>${config.label}</span>`;
}

/**
 * Get selected aspect ratio and padding color
 */
function getAspectRatioSettings() {
    const selectedBtn = document.querySelector(".ratio-btn.active");
    const paddingColor = document.getElementById("paddingColor")?.value || "black";
    
    return {
        ratio: selectedBtn?.dataset.ratio || "16:9",
        paddingColor: paddingColor
    };
}

/**
 * Update form before submission
 */
function injectAspectRatioToForm(form) {
    const settings = getAspectRatioSettings();
    
    // Add hidden inputs to form
    const ratioInput = document.createElement("input");
    ratioInput.type = "hidden";
    ratioInput.name = "ratio";
    ratioInput.value = settings.ratio;
    form.appendChild(ratioInput);
    
    const paddingInput = document.createElement("input");
    paddingInput.type = "hidden";
    paddingInput.name = "padding_color";
    paddingInput.value = settings.paddingColor;
    form.appendChild(paddingInput);
}

// Auto-inject CSS styles
function addAspectRatioStyles() {
    const style = document.createElement("style");
    style.textContent = `
        .aspect-ratio-selector {
            padding: 20px;
            background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
            border-radius: 12px;
            margin: 20px 0;
        }
        
        .ratio-section, .padding-section, .preview-section {
            margin-bottom: 20px;
        }
        
        .ratio-section h3, .padding-section h3, .preview-section h3 {
            margin: 0 0 12px 0;
            font-size: 16px;
            font-weight: 600;
            color: #333;
        }
        
        .ratio-buttons {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 10px;
        }
        
        .ratio-btn {
            padding: 12px 16px;
            border: 2px solid #ddd;
            border-radius: 8px;
            background: white;
            cursor: pointer;
            transition: all 0.3s ease;
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 8px;
            font-size: 13px;
            font-weight: 500;
            color: #666;
        }
        
        .ratio-btn:hover {
            border-color: #4CAF50;
            background: #f0f8f0;
            transform: translateY(-2px);
        }
        
        .ratio-btn.active {
            border-color: #4CAF50;
            background: #4CAF50;
            color: white;
            box-shadow: 0 4px 8px rgba(76, 175, 80, 0.3);
        }
        
        .ratio-icon {
            font-size: 24px;
        }
        
        .ratio-label {
            display: block;
            text-align: center;
            line-height: 1.2;
        }
        
        .padding-select {
            padding: 10px 12px;
            border: 2px solid #ddd;
            border-radius: 8px;
            font-size: 14px;
            cursor: pointer;
            transition: border-color 0.3s ease;
            background: white;
        }
        
        .padding-select:hover {
            border-color: #4CAF50;
        }
        
        .padding-select:focus {
            outline: none;
            border-color: #4CAF50;
            box-shadow: 0 0 0 3px rgba(76, 175, 80, 0.1);
        }
        
        .preview-section {
            text-align: center;
        }
        
        .ratio-preview {
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
            background: rgba(0, 0, 0, 0.05);
            border-radius: 8px;
        }
        
        .preview-box {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: 600;
            font-size: 14px;
            width: 100%;
            max-width: 300px;
        }
        
        @media (max-width: 768px) {
            .ratio-buttons {
                grid-template-columns: repeat(2, 1fr);
            }
        }
    `;
    document.head.appendChild(style);
}

// Initialize when DOM is ready
document.addEventListener("DOMContentLoaded", addAspectRatioStyles);

// Export for use in forms
window.AspectRatioSelector = {
    create: createAspectRatioSelector,
    getSettings: getAspectRatioSettings,
    injectToForm: injectAspectRatioToForm
};
