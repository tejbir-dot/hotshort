#!/usr/bin/env python3
"""
QUICK COMPARISON: Single Pass vs Dual Pass Configuration

This shows what changes when you disable the relaxed pass in the analysis pipeline.

Setup:
1. Single Pass (Strict Only):
   - HS_SELECTOR_RELAX_CURIO_DELTA=0.0
   - HS_SELECTOR_RELAX_PUNCH_DELTA=0.0
   - Result: Only strict quality clips selected

2. Dual Pass (Strict + Relaxed):
   - HS_SELECTOR_RELAX_CURIO_DELTA=0.08 (default)
   - HS_SELECTOR_RELAX_PUNCH_DELTA=0.08 (default)
   - Result: Strict clips + additional lower-quality clips if needed
"""

import os
import subprocess
import json
from dotenv import load_dotenv, dotenv_values

load_dotenv()

CURRENT_ENV_FILE = '.env'
BACKUP_ENV_FILE = '.env.backup'

def show_current_config():
    """Display current pass configuration."""
    current = dotenv_values(CURRENT_ENV_FILE)
    print("\n📋 CURRENT CONFIGURATION:")
    print("-" * 70)
    print(f"HS_SELECTOR_RELAX_CURIO_DELTA   = {current.get('HS_SELECTOR_RELAX_CURIO_DELTA', 'not set')}")
    print(f"HS_SELECTOR_RELAX_PUNCH_DELTA   = {current.get('HS_SELECTOR_RELAX_PUNCH_DELTA', 'not set')}")
    print(f"HS_SELECTOR_RELAX_SEM_FLOOR     = {current.get('HS_SELECTOR_RELAX_SEM_FLOOR', 'not set')}")
    print(f"HS_DIVERSITY_STRICT_PASS_WEIGHT = {current.get('HS_DIVERSITY_STRICT_PASS_WEIGHT', 'not set (default 1.0)')}")
    print(f"HS_DIVERSITY_RELAX_PASS_WEIGHT  = {current.get('HS_DIVERSITY_RELAX_PASS_WEIGHT', 'not set (default 0.85)')}")
    print("-" * 70)

def backup_env():
    """Backup current .env file."""
    if os.path.exists(CURRENT_ENV_FILE) and not os.path.exists(BACKUP_ENV_FILE):
        os.system(f'copy "{CURRENT_ENV_FILE}" "{BACKUP_ENV_FILE}"')
        print(f"✅ Backed up: {BACKUP_ENV_FILE}")

def set_single_pass():
    """Configure for single pass (strict only)."""
    print("\n🔴 CONFIGURING FOR SINGLE PASS (Strict Only)...")
    os.system(f'powershell -Command "(gc {CURRENT_ENV_FILE}) -replace "HS_SELECTOR_RELAX_CURIO_DELTA=.*", "HS_SELECTOR_RELAX_CURIO_DELTA=0.0" | sc {CURRENT_ENV_FILE}"')
    os.system(f'powershell -Command "(gc {CURRENT_ENV_FILE}) -replace "HS_SELECTOR_RELAX_PUNCH_DELTA=.*", "HS_SELECTOR_RELAX_PUNCH_DELTA=0.0" | sc {CURRENT_ENV_FILE}"')
    print("✅ Set: CURIO_DELTA=0.0, PUNCH_DELTA=0.0")
    print("   → This disables the relaxed pass")
    show_current_config()

def set_dual_pass():
    """Configure for dual pass (strict + relaxed)."""
    print("\n🟢 CONFIGURING FOR DUAL PASS (Strict + Relaxed)...")
    os.system(f'powershell -Command "(gc {CURRENT_ENV_FILE}) -replace "HS_SELECTOR_RELAX_CURIO_DELTA=.*", "HS_SELECTOR_RELAX_CURIO_DELTA=0.08" | sc {CURRENT_ENV_FILE}"')
    os.system(f'powershell -Command "(gc {CURRENT_ENV_FILE}) -replace "HS_SELECTOR_RELAX_PUNCH_DELTA=.*", "HS_SELECTOR_RELAX_PUNCH_DELTA=0.08" | sc {CURRENT_ENV_FILE}"')
    print("✅ Set: CURIO_DELTA=0.08, PUNCH_DELTA=0.08")
    print("   → This enables the relaxed pass")
    show_current_config()

def restore_env():
    """Restore original .env file."""
    if os.path.exists(BACKUP_ENV_FILE):
        os.system(f'copy "{BACKUP_ENV_FILE}" "{CURRENT_ENV_FILE}"')
        print(f"\n✅ Restored: {CURRENT_ENV_FILE}")

def show_pass_differences():
    """Display the key differences between single and dual pass."""
    print("\n" + "="*70)
    print("📊 PASS COMPARISON TABLE")
    print("="*70)
    print()
    print("┌─ CRITERIA ────────────────────┬─────────────────┬─────────────────┐")
    print("│                               │  STRICT ONLY    │ STRICT+RELAXED  │")
    print("├─────────────────────────────┼─────────────────┼─────────────────┤")
    print("│ Curiosity Cutoff Threshold  │ Full (baseline) │ Reduced by 0.08 │")
    print("│ Punch Confidence Threshold  │ Full (baseline) │ Reduced by 0.08 │")
    print("│ Semantic Quality Floor      │ 0.52            │ 0.45            │")
    print("│ Score Weight Multiplier     │ 1.0x            │ 0.85x           │")
    print("├─────────────────────────────┼─────────────────┼─────────────────┤")
    print("│ Clips Found (typical)       │ 3-5             │ 5-8             │")
    print("│ Average Quality             │ HIGH ⭐⭐⭐     │ MEDIUM ⭐⭐    │")
    print("│ Processing Time             │ FAST ⚡         │ FAST + Time ⚡⚡ │")
    print("│ User Experience             │ Fewer but best  │ More options    │")
    print("└─────────────────────────────┴─────────────────┴─────────────────┘")
    print()
    print("🔑 KEY DIFFERENCES:")
    print("   • Relaxed pass activates when strict pass finds < target clips")
    print("   • Relaxes 3 quality thresholds (curiosity, punch, semantic)")
    print("   • Applies 0.85x weight to relaxed clips (slight quality reduction)")
    print("   • Time overhead: Usually <5% (depends on video length)")
    print()

def main():
    """Main test workflow."""
    print("="*70)
    print("🧪 SINGLE PASS vs DUAL PASS ANALYSIS TEST")
    print("="*70)
    
    backup_env()
    show_current_config()
    show_pass_differences()
    
    print("\n" + "="*70)
    print("🚀 HOW TO TEST:")
    print("="*70)
    print()
    print("OPTION 1: Manual Configuration")
    print("-" * 70)
    print("1. Set single pass:")
    print("   python test_single_vs_dual_pass.py --single-pass")
    print("   ↳ Then upload video via dashboard and check results")
    print()
    print("2. Set dual pass:")
    print("   python test_single_vs_dual_pass.py --dual-pass")
    print("   ↳ Upload same video and compare")
    print()
    print("OPTION 2: View the Configuration")
    print("-" * 70)
    print("   python test_single_vs_dual_pass.py --show-config")
    print()
    print("OPTION 3: Restore Original")
    print("-" * 70)
    print("   python test_single_vs_dual_pass.py --restore")
    print()
    print("="*70)
    print()
    print("📝 WHAT TO COMPARE:")
    print("   ✓ Number of clips found")
    print("   ✓ Quality of clips (as shown in UI)")
    print("   ✓ Time taken to analyze")
    print("   ✓ Confidence scores of clips")
    print()
    print("💡 TIP: Use Chrome DevTools Network tab to see timing!")
    print()

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        if cmd == "--single-pass":
            backup_env()
            set_single_pass()
            print("\n✅ Ready for test. Upload video and check clip results.")
            print("   (Strict high-quality clips only)")
        elif cmd == "--dual-pass":
            set_dual_pass()
            print("\n✅ Ready for test. Upload same video and compare.")
            print("   (Should get more clips including relaxed selections)")
        elif cmd == "--restore":
            restore_env()
        elif cmd == "--show-config":
            show_current_config()
            show_pass_differences()
        else:
            print(f"Unknown option: {cmd}")
    else:
        main()
