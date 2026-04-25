import os

def apply_watchdog():
    # 1. Update runpod_controller.py to accept force=True
    with open("runpod_controller.py", "r", encoding="utf-8") as f:
        content = f.read()
    
    target_controller = """def stop_pod():
    \"\"\"Stop the RunPod GPU pod.\"\"\"
    query = \"\"\"
    mutation {"""
    
    replace_controller = """def stop_pod(force=False):
    \"\"\"Stop the RunPod GPU pod. (force parameter included for API compatibility / watchdog)\"\"\"
    if force:
        print("[WATCHDOG] Force stopping pod...")
    
    query = \"\"\"
    mutation {"""
    if target_controller in content:
        content = content.replace(target_controller, replace_controller)
        with open("runpod_controller.py", "w", encoding="utf-8") as f:
            f.write(content)
        print("Updated runpod_controller.py successfully")
    else:
        print("Could not find target block in runpod_controller.py")

    # 2. Update app.py
    with open("app.py", "r", encoding="utf-8") as f:
        content = f.read()
        
    target_api = """                    log.info(f"[RUNPOD_COST] user={getattr(current_user, 'id', 'anonymous')} time={duration:.2f}s cost=${cost:.5f}")
                log.info("[RUNPOD] Stopping GPU pod after api_runpod_download...")
                stop_pod()"""
                
    replace_api = """                    log.info(f"[RUNPOD_COST] user={getattr(current_user, 'id', 'anonymous')} time={duration:.2f}s cost=${cost:.5f}")
                    MAX_GPU_RUNTIME = 300
                    if duration > MAX_GPU_RUNTIME:
                        log.warning("[WATCHDOG] GPU runtime exceeded safe window")
                        stop_pod(force=True)
                    else:
                        log.info("[RUNPOD] Stopping GPU pod after api_runpod_download...")
                        stop_pod()
                else:
                    log.info("[RUNPOD] Stopping GPU pod after api_runpod_download...")
                    stop_pod()"""
    if target_api in content:
        content = content.replace(target_api, replace_api)
        print("Updated app.py (api) successfully")
    else:
        print("Could not find app.py api block")
        
    target_analyze = """                    log.info(f"[RUNPOD_COST] user={getattr(current_user, 'id', 'anonymous')} time={duration:.2f}s cost=${cost:.5f}")
                    log.info("[RUNPOD] Stopping GPU pod...")
                    stop_pod()"""
                    
    replace_analyze = """                    log.info(f"[RUNPOD_COST] user={getattr(current_user, 'id', 'anonymous')} time={duration:.2f}s cost=${cost:.5f}")
                        MAX_GPU_RUNTIME = 300
                        if duration > MAX_GPU_RUNTIME:
                            log.warning("[WATCHDOG] GPU runtime exceeded safe window")
                            stop_pod(force=True)
                        else:
                            log.info("[RUNPOD] Stopping GPU pod...")
                            stop_pod()
                    else:
                        log.info("[RUNPOD] Stopping GPU pod...")
                        stop_pod()"""
                        
    if target_analyze in content:
        content = content.replace(target_analyze, replace_analyze)
        print("Updated app.py (analyze) successfully")
    else:
        print("Could not find app.py analyze block")

    with open("app.py", "w", encoding="utf-8") as f:
        f.write(content)

if __name__ == "__main__":
    apply_watchdog()
