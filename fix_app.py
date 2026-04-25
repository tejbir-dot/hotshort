import os
import re

def fix_app_py():
    with open('app.py', 'r', encoding='utf-8') as f:
        content = f.read()
        
    # 1. Update api_runpod_download try block (add runpod_start_time)
    target_1 = """    pod_started = False
    try:
        if RUNPOD_MODE == "pod" and RUNPOD_AVAILABLE and os.environ.get("RUNPOD_API_KEY") and os.environ.get("RUNPOD_POD_ID"):
            try:
                log.info("[RUNPOD] Starting GPU pod for download api...")
                start_pod()"""
    
    replace_1 = """    pod_started = False
    runpod_start_time = None
    try:
        if RUNPOD_MODE == "pod" and RUNPOD_AVAILABLE and os.environ.get("RUNPOD_API_KEY") and os.environ.get("RUNPOD_POD_ID"):
            try:
                log.info("[RUNPOD] Starting GPU pod for download api...")
                runpod_start_time = time.time()
                start_pod()"""
                
    content = content.replace(target_1, replace_1)
    
    # 2. Update api_runpod_download finally block (add cost)
    target_2 = """    finally:
        if RUNPOD_MODE == "pod" and pod_started and RUNPOD_AVAILABLE and os.environ.get("RUNPOD_API_KEY") and os.environ.get("RUNPOD_POD_ID"):
            try:
                log.info("[RUNPOD] Stopping GPU pod after api_runpod_download...")
                stop_pod()
            except Exception as e:
                log.warning("[RUNPOD] Failed to stop pod in finalizer: %s", e)"""
                
    replace_2 = """    finally:
        if RUNPOD_MODE == "pod" and pod_started and RUNPOD_AVAILABLE and os.environ.get("RUNPOD_API_KEY") and os.environ.get("RUNPOD_POD_ID"):
            try:
                if runpod_start_time:
                    duration = time.time() - runpod_start_time
                    cost = duration * (0.44 / 3600)
                    log.info(f"[RUNPOD_COST] user={getattr(current_user, 'id', 'anonymous')} time={duration:.2f}s cost=${cost:.5f}")
                log.info("[RUNPOD] Stopping GPU pod after api_runpod_download...")
                stop_pod()
            except Exception as e:
                log.warning("[RUNPOD] Failed to stop pod in finalizer: %s", e)"""
                
    content = content.replace(target_2, replace_2)

    # 3. Add moments logic & runpod_start_time to /analyze logic
    target_3 = """        pod_started = False

        def _ensure_runpod_ready() -> bool:
            nonlocal pod_started
            if not (RUNPOD_MODE == "pod" and RUNPOD_AVAILABLE and os.environ.get("RUNPOD_API_KEY") and os.environ.get("RUNPOD_POD_ID")):
                return False
            if pod_started:
                return True
            try:
                log.info("[RUNPOD] Starting GPU pod for fallback...")
                start_pod()
                pod_started = True"""
                
    replace_3 = """        pod_started = False
        runpod_start_time = None
        moments = []

        def _ensure_runpod_ready() -> bool:
            nonlocal pod_started, runpod_start_time
            if not (RUNPOD_MODE == "pod" and RUNPOD_AVAILABLE and os.environ.get("RUNPOD_API_KEY") and os.environ.get("RUNPOD_POD_ID")):
                return False
            if pod_started:
                return True
            try:
                log.info("[RUNPOD] Starting GPU pod for fallback...")
                runpod_start_time = time.time()
                start_pod()
                pod_started = True"""
                
    content = content.replace(target_3, replace_3)

    # 4. Clean out old stop_pod() blocks in the transcribe & analyze excepts to prevent double logging
    target_stop_1 = """            # Stop pod before returning error (pod mode only)
            if RUNPOD_MODE == "pod" and RUNPOD_AVAILABLE and os.environ.get("RUNPOD_API_KEY") and os.environ.get("RUNPOD_POD_ID"):
                try:
                    log.info("[RUNPOD] Stopping GPU pod due to error...")
                    stop_pod()
                except Exception as pod_err:
                    log.warning("[RUNPOD] Failed to stop pod: %s", pod_err)"""
    content = content.replace(target_stop_1, "")

    target_stop_2 = """            # Stop pod before returning error
                if pod_started and RUNPOD_AVAILABLE and os.environ.get("RUNPOD_API_KEY") and os.environ.get("RUNPOD_POD_ID"):
                    try:
                        log.info("[RUNPOD] Stopping GPU pod due to error...")
                        stop_pod()
                    except Exception as pod_err:
                        log.warning("[RUNPOD] Failed to stop pod: %s", pod_err)"""
    content = content.replace(target_stop_2, "")
    
    target_stop_3 = """        # --------------------------------------------------
        # Stop GPU pod after GPU work is complete (pod mode only)
        # --------------------------------------------------
        if pod_started and RUNPOD_MODE == "pod" and RUNPOD_AVAILABLE and os.environ.get("RUNPOD_API_KEY") and os.environ.get("RUNPOD_POD_ID"):
            try:
                log.info("[RUNPOD] Stopping GPU pod after analysis complete...")
                stop_pod()
            except Exception as e:
                log.warning("[RUNPOD] Failed to stop pod: %s", e)"""
    content = content.replace(target_stop_3, "")

    # 5. Instead of re-indenting 180 lines which could break python ast or diff formatters,
    # let's just make the final wrap.
    # The try block starts right before `# Precompute transcript...`
    # and ends after `log.info("[TIMING] stage=orchestrate...`
    
    # Let's split lines and find indices to inject try/finally and indent
    lines = content.splitlines(True) # keep ends
    start_idx = -1
    end_idx = -1
    
    for i, line in enumerate(lines):
        if line.startswith("        # Precompute transcript on clean wav and seed cache for orchestrator"):
            start_idx = i
        elif line.startswith("        log.info(\"[TIMING] stage=orchestrate wall=%.2fs moments=%d\", (time.time() - stage_t0), len(moments or []))"):
            end_idx = i
            
    if start_idx != -1 and end_idx != -1:
        # indent from start_idx to end_idx
        for i in range(start_idx, end_idx + 1):
            lines[i] = "    " + lines[i]
            
        # insert try before start_idx
        lines.insert(start_idx, "        try:\n")
        
        # insert finally after end_idx (which is now end_idx + 1)
        finally_block = [
            "        finally:\n",
            "            if pod_started and RUNPOD_MODE == \"pod\" and RUNPOD_AVAILABLE and os.environ.get(\"RUNPOD_API_KEY\") and os.environ.get(\"RUNPOD_POD_ID\"):\n",
            "                try:\n",
            "                    if runpod_start_time:\n",
            "                        duration = time.time() - runpod_start_time\n",
            "                        cost = duration * (0.44 / 3600)\n",
            "                        log.info(f\"[RUNPOD_COST] user={getattr(current_user, 'id', 'anonymous')} time={duration:.2f}s cost=${cost:.5f}\")\n",
            "                    log.info(\"[RUNPOD] Stopping GPU pod...\")\n",
            "                    stop_pod()\n",
            "                except Exception as e:\n",
            "                    log.warning(\"[RUNPOD] Failed to stop pod: %s\", e)\n"
        ]
        
        insert_pos = end_idx + 2
        for line in reversed(finally_block):
            lines.insert(insert_pos, line)
            
        with open('app.py', 'w', encoding='utf-8') as f:
            f.writelines(lines)
        print("Successfully applied modifications to app.py")
    else:
        print(f"Failed to find block. start={start_idx}, end={end_idx}")

if __name__ == '__main__':
    fix_app_py()
