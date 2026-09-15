import re

with open("scratch/orchestrator_legacy.py", "r", encoding="utf-16") as f:
    legacy_code = f.read()

legacy_func = ""
in_func = False
for line in legacy_code.splitlines(True):
    if line.startswith("def _run_arc_assembler("):
        in_func = True
    if in_func:
        if line.startswith("def _") and not line.startswith("def _run_arc_assembler(") and not line.startswith("    def _"):
            break
        legacy_func += line

with open("viral_finder/orchestrator.py", "r", encoding="utf-8") as f:
    orch_code = f.read()

# Rename current to v2
orch_code = orch_code.replace("def _run_arc_assembler(ctx: PipelineContext) -> None:", "def _run_arc_assembler_v2(ctx: PipelineContext) -> None:")

# Inject legacy before v2
orch_code = orch_code.replace("def _run_arc_assembler_v2(ctx: PipelineContext) -> None:", legacy_func + "\n\ndef _run_arc_assembler_v2(ctx: PipelineContext) -> None:")

with open("viral_finder/orchestrator.py", "w", encoding="utf-8") as f:
    f.write(orch_code)
