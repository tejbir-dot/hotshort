import sys

with open('viral_finder/groq_cortex.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add import
if 'from viral_finder.cognition import Evidence, IntelligenceArtifact' not in content:
    content = content.replace('import time', 'import time\nfrom viral_finder.cognition import Evidence, IntelligenceArtifact')

# 2. Update merge_groq_results_with_candidates
old_code = '''        # Attach Groq specific fields
        new_cand["cortex_enabled"] = True
        raw_score = float(v_clip.get("viral_score", 0))
        # Normalise 0-100 to 0.0-1.0 to match pipeline convention
        cortex_score = raw_score / 100.0 if raw_score > 1.0 else raw_score
        new_cand["cortex_score"] = round(cortex_score, 4)
        # Override viral score to ensure ranking
        new_cand["viral_score"] = new_cand["cortex_score"]
        
        new_cand["title"] = v_clip.get("title", "")'''

new_code = '''        # Attach Groq specific fields
        new_cand["cortex_enabled"] = True
        
        # Instantiate Intelligence Artifact if it doesn't exist
        artifact = new_cand.get("intelligence")
        if not artifact:
            artifact = IntelligenceArtifact()
            new_cand["intelligence"] = artifact
            
        raw_score = float(v_clip.get("viral_score", 0))
        cortex_score = raw_score / 100.0 if raw_score > 1.0 else raw_score
        
        # We no longer overwrite viral_score! We emit Evidence.
        artifact.evidence_stream.extend([
            Evidence(type="stop_scroll", value=cortex_score, producer="groq_trigger", confidence=0.95),
            Evidence(type="memorability", value=float(v_clip.get("insight_strength", 0) or 0) / 100.0, producer="groq_trigger"),
            Evidence(type="usefulness", value=float(v_clip.get("usefulness", 0) or 0) / 100.0, producer="groq_trigger"),
            Evidence(type="completeness", value=float(v_clip.get("completeness_score", 0) or 0) / 100.0, producer="groq_trigger"),
        ])
        
        new_cand["title"] = v_clip.get("title", "")'''

content = content.replace(old_code, new_code)

with open('viral_finder/groq_cortex.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated groq_cortex.py")
