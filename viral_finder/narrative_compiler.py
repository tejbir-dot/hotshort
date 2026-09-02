"""
CLIP COMPILER CONTRACT

Never
Discover

Never
Search

Never
Reason

Never
Predict

Never
Call LLM

Never
Call embeddings

Never
Create narrative

Only
Compile
"""

import time
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

# ==============================================================================
# DATA MODELS
# ==============================================================================

@dataclass
class NarrativeContract:
    hook_idx: int
    payoff_idx: int
    decision: str
    confidence: float
    story_complete: bool
    expected_duration: float
    reason: str

@dataclass
class CompiledClip:
    id: str
    start: float
    end: float
    duration: float
    hook_idx: int
    payoff_idx: int
    hook_text: str
    payoff_text: str
    confidence: float
    story_complete: bool
    narrative_contract: dict
    score: float

@dataclass
class CompilerConfig:
    min_duration_s: float = 5.0
    max_duration_s: float = 180.0
    strict_boundaries: bool = True

@dataclass
class CompilerMetrics:
    total_ms: float = 0.0
    validation_ms: float = 0.0
    boundary_ms: float = 0.0
    assembly_ms: float = 0.0
    verification_ms: float = 0.0

@dataclass
class CompilerReport:
    success: bool
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    contract_version: int = 1
    compile_ms: float = 0.0

@dataclass
class CompileResult:
    success: bool
    clip: Optional[CompiledClip]
    report: CompilerReport
    metrics: CompilerMetrics

@dataclass
class CompilationContext:
    transcript: List[Dict[str, Any]]
    config: CompilerConfig
    logger: logging.Logger
    clock_start_time: float
    metrics: CompilerMetrics = field(default_factory=CompilerMetrics)

# ==============================================================================
# ERROR HIERARCHY
# ==============================================================================

class CompilerError(Exception):
    """Base exception for all compilation failures."""
    pass

class MissingContractError(CompilerError): pass
class InvalidHookError(CompilerError): pass
class InvalidPayoffError(CompilerError): pass
class BoundaryError(CompilerError): pass
class TranscriptMismatchError(CompilerError): pass
class DurationError(CompilerError): pass
class VerificationError(CompilerError): pass

# ==============================================================================
# COMPILER STAGES (PURE)
# ==============================================================================

@dataclass
class ValidationResult:
    hook_idx: int
    payoff_idx: int

class Validator:
    @staticmethod
    def run(contract: NarrativeContract, ctx: CompilationContext) -> ValidationResult:
        t0 = time.perf_counter()
        if not contract:
            raise MissingContractError("NarrativeContract is missing or None.")
        
        t_len = len(ctx.transcript)
        
        if contract.hook_idx < 0 or contract.hook_idx >= t_len:
            raise InvalidHookError(f"Hook index {contract.hook_idx} out of bounds (len: {t_len}).")
            
        if contract.payoff_idx < 0 or contract.payoff_idx >= t_len:
            raise InvalidPayoffError(f"Payoff index {contract.payoff_idx} out of bounds (len: {t_len}).")
            
        if contract.hook_idx > contract.payoff_idx:
            raise BoundaryError(f"Hook index ({contract.hook_idx}) cannot be after payoff index ({contract.payoff_idx}).")
            
        ctx.metrics.validation_ms = (time.perf_counter() - t0) * 1000
        return ValidationResult(hook_idx=contract.hook_idx, payoff_idx=contract.payoff_idx)

@dataclass
class BoundaryResult:
    start_time: float
    end_time: float

class BoundaryResolver:
    @staticmethod
    def _get_start(seg: Dict[str, Any]) -> float:
        return float(seg.get("start", 0.0))

    @staticmethod
    def _get_end(seg: Dict[str, Any]) -> float:
        s = BoundaryResolver._get_start(seg)
        return float(seg.get("end", s))

    @staticmethod
    def run(val_result: ValidationResult, ctx: CompilationContext) -> BoundaryResult:
        t0 = time.perf_counter()
        
        hook_seg = ctx.transcript[val_result.hook_idx]
        payoff_seg = ctx.transcript[val_result.payoff_idx]
        
        start_time = BoundaryResolver._get_start(hook_seg)
        end_time = BoundaryResolver._get_end(payoff_seg)
        
        # Backward lookback logic from Arc Assembler - strict window before hook.
        # This keeps the exact hook context while shifting the true start back slightly.
        lookback_s = 2.0
        arc_start = start_time
        for i in range(val_result.hook_idx - 1, -1, -1):
            prev_seg = ctx.transcript[i]
            prev_s = BoundaryResolver._get_start(prev_seg)
            prev_e = BoundaryResolver._get_end(prev_seg)
            if prev_e < start_time and (start_time - prev_e) < lookback_s:
                arc_start = min(arc_start, prev_s)
                break

        if arc_start >= end_time:
            raise BoundaryError(f"Resolved start ({arc_start}) is >= resolved end ({end_time}).")
            
        ctx.metrics.boundary_ms = (time.perf_counter() - t0) * 1000
        return BoundaryResult(start_time=arc_start, end_time=end_time)

@dataclass
class AssemblyResult:
    hook_text: str
    payoff_text: str

class TranscriptAssembler:
    @staticmethod
    def run(val_result: ValidationResult, ctx: CompilationContext) -> AssemblyResult:
        t0 = time.perf_counter()
        hook_text = str(ctx.transcript[val_result.hook_idx].get("text", "")).strip()
        payoff_text = str(ctx.transcript[val_result.payoff_idx].get("text", "")).strip()
        
        if not hook_text:
            ctx.logger.warning(f"Empty hook text at index {val_result.hook_idx}")
        if not payoff_text:
            ctx.logger.warning(f"Empty payoff text at index {val_result.payoff_idx}")
            
        ctx.metrics.assembly_ms = (time.perf_counter() - t0) * 1000
        return AssemblyResult(hook_text=hook_text, payoff_text=payoff_text)

class Verifier:
    @staticmethod
    def run(bounds: BoundaryResult, ctx: CompilationContext) -> None:
        t0 = time.perf_counter()
        duration = bounds.end_time - bounds.start_time
        
        if duration < ctx.config.min_duration_s:
            raise DurationError(f"Clip duration ({duration:.2f}s) is below minimum ({ctx.config.min_duration_s}s)")
            
        if duration > ctx.config.max_duration_s:
            raise DurationError(f"Clip duration ({duration:.2f}s) exceeds maximum ({ctx.config.max_duration_s}s)")
            
        ctx.metrics.verification_ms = (time.perf_counter() - t0) * 1000

class Emitter:
    @staticmethod
    def run(
        contract: NarrativeContract,
        val_result: ValidationResult,
        bounds: BoundaryResult,
        assembly: AssemblyResult,
        ctx: CompilationContext,
        warnings: List[str]
    ) -> CompileResult:
        duration = bounds.end_time - bounds.start_time
        
        clip = CompiledClip(
            id=f"cmp_{int(time.time() * 1000)}",
            start=round(bounds.start_time, 3),
            end=round(bounds.end_time, 3),
            duration=round(duration, 3),
            hook_idx=val_result.hook_idx,
            payoff_idx=val_result.payoff_idx,
            hook_text=assembly.hook_text,
            payoff_text=assembly.payoff_text,
            confidence=contract.confidence,
            story_complete=contract.story_complete,
            narrative_contract=contract.__dict__,
            score=contract.confidence,  # Base compiled score is strictly the input confidence.
        )
        
        ctx.metrics.total_ms = (time.perf_counter() - ctx.clock_start_time) * 1000
        
        report = CompilerReport(
            success=True,
            warnings=warnings,
            errors=[],
            contract_version=1,
            compile_ms=ctx.metrics.total_ms
        )
        
        # Diagnostic logging
        diag = (
            f"\n═══════════════════════\n"
            f"CLIP COMPILER\n"
            f"Candidate   | {clip.id}\n"
            f"Contract    | v{report.contract_version}\n"
            f"Owner       | Narrative Authority\n"
            f"Hook        | {clip.hook_idx}\n"
            f"Payoff      | {clip.payoff_idx}\n"
            f"Duration    | {clip.duration:.2f}s\n"
            f"Validation  | PASS\n"
            f"Compile Time| {report.compile_ms:.2f} ms\n"
            f"═══════════════════════\n"
        )
        ctx.logger.info(diag)
        
        return CompileResult(
            success=True,
            clip=clip,
            report=report,
            metrics=ctx.metrics
        )

# ==============================================================================
# PIPELINE
# ==============================================================================

class CompilerPipeline:
    def __init__(self, context: CompilationContext):
        self.ctx = context
        self.warnings: List[str] = []
        
    def execute(self, contract: NarrativeContract) -> CompileResult:
        try:
            val_result = Validator.run(contract, self.ctx)
            bounds = BoundaryResolver.run(val_result, self.ctx)
            assembly = TranscriptAssembler.run(val_result, self.ctx)
            Verifier.run(bounds, self.ctx)
            
            return Emitter.run(
                contract=contract,
                val_result=val_result,
                bounds=bounds,
                assembly=assembly,
                ctx=self.ctx,
                warnings=self.warnings
            )
            
        except CompilerError as e:
            err_msg = f"{e.__class__.__name__}: {str(e)}"
            self.ctx.logger.error(f"[CLIP COMPILER] FAILED - {err_msg}")
            
            self.ctx.metrics.total_ms = (time.perf_counter() - self.ctx.clock_start_time) * 1000
            report = CompilerReport(
                success=False,
                warnings=self.warnings,
                errors=[err_msg],
                compile_ms=self.ctx.metrics.total_ms
            )
            return CompileResult(
                success=False,
                clip=None,
                report=report,
                metrics=self.ctx.metrics
            )
        except Exception as e:
            # Catch raw unhandled python exceptions
            err_msg = f"CompileError (Unhandled): {str(e)}"
            self.ctx.logger.exception(f"[CLIP COMPILER] CRITICAL FAIL - {err_msg}")
            
            self.ctx.metrics.total_ms = (time.perf_counter() - self.ctx.clock_start_time) * 1000
            report = CompilerReport(
                success=False,
                warnings=self.warnings,
                errors=[err_msg],
                compile_ms=self.ctx.metrics.total_ms
            )
            return CompileResult(
                success=False,
                clip=None,
                report=report,
                metrics=self.ctx.metrics
            )

# ==============================================================================
# PUBLIC API
# ==============================================================================

def compile_narrative(contract: NarrativeContract, context: CompilationContext) -> CompileResult:
    """
    The entry point for the Narrative Compiler.
    Takes a NarrativeContract and shared context, returning a unified CompileResult.
    """
    pipeline = CompilerPipeline(context)
    return pipeline.execute(contract)
