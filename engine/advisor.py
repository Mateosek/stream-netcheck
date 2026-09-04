"""
Intelligent Moonlight / Sunshine Configuration Advisor Engine.

Evaluates network QoS telemetry, bandwidth headroom, FEC overhead, and codec efficiency
to synthesize optimal streaming presets for Moonlight / Sunshine game streaming.
"""

from dataclasses import dataclass, asdict
from typing import Optional, List, Tuple


@dataclass
class CodecProfile:
    codec: str                      # "AV1", "HEVC" or "H.264"
    resolution: str                 # e.g. "1440p (2560x1440) @ 60 FPS"
    width: int                      # e.g. 2560
    height: int                     # e.g. 1440
    fps: int                        # 60 or 120
    target_bitrate_mbps: int        # e.g. 45
    safe_bitrate_range: str         # e.g. "40 - 45 Mbps"
    bppf_effective: float           # e.g. 0.346
    score: float                    # e.g. 0.873 (rounded to 3 decimal places)


@dataclass
class MoonlightConfig:
    cinematic_profile: CodecProfile            # Primary quality recommendation (60 FPS, preferred AV1)
    competitive_profile: Optional[CodecProfile]# Esports recommendation (120 FPS, None if RTT > 30 ms)
    fallback_hevc: Optional[CodecProfile]      # Best HEVC profile for Cinematic mode
    fallback_h264: Optional[CodecProfile]      # Best H.264 profile for Cinematic mode
    recommended_fec_percentage: int            # 0, 10 or 20%
    frame_pacing: bool                         # True if jitter > 3.0 ms or bloat > 15.0 ms
    confidence_level: str                      # "HIGH", "MEDIUM", "LOW"
    hardware_note: str                         # Hardware decoding notice
    reasoning_pl: str                          # Polish technical explanation
    reasoning_en: str                          # English technical explanation

    def to_dict(self) -> dict:
        return {
            "cinematic_profile": asdict(self.cinematic_profile),
            "competitive_profile": asdict(self.competitive_profile) if self.competitive_profile else None,
            "fallback_hevc": asdict(self.fallback_hevc) if self.fallback_hevc else None,
            "fallback_h264": asdict(self.fallback_h264) if self.fallback_h264 else None,
            "recommended_fec_percentage": self.recommended_fec_percentage,
            "frame_pacing": self.frame_pacing,
            "confidence_level": self.confidence_level,
            "hardware_note": self.hardware_note,
            "reasoning_pl": self.reasoning_pl,
            "reasoning_en": self.reasoning_en,
        }


def calculate_safe_bitrate(
    throughput_mbps: float,
    bufferbloat_ms: float,
    packet_loss_pct: float
) -> Tuple[int, str, int]:
    """
    Computes safe target video bitrate taking into account adaptive headroom,
    FEC overhead, packet loss penalties, and bufferbloat degradation.

    Returns:
        (target_bitrate_mbps, safe_bitrate_range, recommended_fec_pct)
    """
    # 1. Adaptive Headroom
    if bufferbloat_ms <= 3.0:
        headroom = 0.80
    elif bufferbloat_ms <= 12.0:
        headroom = 0.70
    else:
        headroom = 0.60

    # 2. Forward Error Correction (FEC) Overhead
    if packet_loss_pct < 0.2:
        fec_pct = 0
    elif packet_loss_pct <= 1.0:
        fec_pct = 10
    else:
        fec_pct = 20

    factor_fec = 1.0 / (1.0 + fec_pct / 100.0)

    # 3. Multiplicative Penalties
    penalty_loss = 0.85 if packet_loss_pct > 1.0 else 1.0
    penalty_bloat = 0.90 if bufferbloat_ms > 35.0 else 1.0

    # 4. Calculation & Safety Floor
    bitrate_raw = (throughput_mbps * headroom) * factor_fec * penalty_loss * penalty_bloat
    bitrate_safe = max(3.0, max(throughput_mbps * 0.25, bitrate_raw))

    # 5. Slider Quantization
    if bitrate_safe < 20.0:
        target = int(round(bitrate_safe))
    else:
        target = int(round(bitrate_safe / 5.0) * 5)

    # 6. Safe Bitrate Range String
    if target < 20:
        safe_range = f"{max(3, target - 2)} - {target} Mbps"
    else:
        safe_range = f"{max(3, target - 5)} - {target} Mbps"

    return target, safe_range, fec_pct


def evaluate_moonlight_config(
    throughput_mbps: float,
    rtt_ms: float,
    jitter_ms: float,
    packet_loss_pct: float,
    bufferbloat_ms: float,
    is_relayed: bool = False,
    has_netbird_context: bool = True
) -> MoonlightConfig:
    """
    Main evaluation pipeline: derives safe video bitrate, tests candidate resolution/FPS profiles,
    computes BPPF and composite psychovisual scores, and produces a complete MoonlightConfig.
    """
    target_bitrate, safe_range, fec_pct = calculate_safe_bitrate(
        throughput_mbps=throughput_mbps,
        bufferbloat_ms=bufferbloat_ms,
        packet_loss_pct=packet_loss_pct
    )

    codec_multipliers = {
        "AV1": 1.70,
        "HEVC": 1.45,
        "H.264": 1.00,
    }

    bitrate_bps = target_bitrate * 1_000_000

    def compute_profile(w: int, h: int, fps: int, label: str, codec_name: str, is_competitive: bool) -> Optional[CodecProfile]:
        pixels_per_second = w * h * fps
        bppf_raw = bitrate_bps / pixels_per_second
        multiplier = codec_multipliers[codec_name]
        bppf_eff = bppf_raw * multiplier

        if bppf_eff < 0.10:
            return None

        score_res = h / 2160.0
        score_quality = min(1.0, max(0.0, (bppf_eff - 0.10) / 0.25))

        if is_competitive:
            comp_res = round(0.25 * score_res, 4)
            comp_qual = round(0.75 * score_quality, 4)
            raw_score = round(comp_res + comp_qual, 3)
        else:
            cin_res = round(0.35 * score_res, 4)
            cin_qual = round(0.65 * score_quality, 4)
            raw_score = round(cin_res + cin_qual, 3)


        return CodecProfile(
            codec=codec_name,
            resolution=label,
            width=w,
            height=h,
            fps=fps,
            target_bitrate_mbps=target_bitrate,
            safe_bitrate_range=safe_range,
            bppf_effective=round(bppf_eff, 3),
            score=round(raw_score, 3)
        )

    # 1. Cinematic Mode: evaluates 60 FPS candidates first (4K, 1440p, 1080p, 720p)
    cinematic_60_specs = [
        (3840, 2160, 60, "4K (3840x2160) @ 60 FPS"),
        (2560, 1440, 60, "1440p (2560x1440) @ 60 FPS"),
        (1920, 1080, 60, "1080p (1920x1080) @ 60 FPS"),
        (1280, 720, 60, "720p (1280x720) @ 60 FPS"),
    ]

    cinematic_candidates_av1: List[Tuple[int, int, int, str, CodecProfile]] = []
    for w, h, fps, label in cinematic_60_specs:
        prof = compute_profile(w, h, fps, label, "AV1", is_competitive=False)
        if prof is not None:
            cinematic_candidates_av1.append((w, h, fps, label, prof))

    # Fallback to 720p @ 30 FPS if all 60 FPS candidates fail BPPF floor
    if not cinematic_candidates_av1:
        prof_30 = compute_profile(1280, 720, 30, "720p (1280x720) @ 30 FPS", "AV1", is_competitive=False)
        if prof_30 is not None:
            cinematic_candidates_av1.append((1280, 720, 30, "720p (1280x720) @ 30 FPS", prof_30))

    if cinematic_candidates_av1:
        best_spec = max(cinematic_candidates_av1, key=lambda x: (x[4].score, x[0] * x[1]))
        win_w, win_h, win_fps, win_label, win_av1_profile = best_spec
    else:
        # Ultimate fallback
        win_w, win_h, win_fps, win_label = 1280, 720, 30, "720p (1280x720) @ 30 FPS"
        win_av1_profile = CodecProfile(
            codec="AV1",
            resolution=win_label,
            width=win_w,
            height=win_h,
            fps=win_fps,
            target_bitrate_mbps=target_bitrate,
            safe_bitrate_range=safe_range,
            bppf_effective=0.10,
            score=0.333
        )

    cinematic_profile = win_av1_profile
    fallback_hevc = compute_profile(win_w, win_h, win_fps, win_label, "HEVC", is_competitive=False)
    fallback_h264 = compute_profile(win_w, win_h, win_fps, win_label, "H.264", is_competitive=False)

    # 2. Competitive Mode (120 FPS): strictly if RTT <= 30.0 ms
    competitive_profile = None
    if rtt_ms <= 30.0:
        competitive_specs = [
            (2560, 1440, 120, "1440p (2560x1440) @ 120 FPS"),
            (1920, 1080, 120, "1080p (1920x1080) @ 120 FPS"),
        ]
        comp_candidates = []
        for w, h, fps, label in competitive_specs:
            for c_name in ["AV1", "HEVC", "H.264"]:
                cp = compute_profile(w, h, fps, label, c_name, is_competitive=True)
                if cp is not None:
                    comp_candidates.append(cp)

        if comp_candidates:
            codec_priority = {"AV1": 3, "HEVC": 2, "H.264": 1}
            competitive_profile = max(
                comp_candidates,
                key=lambda p: (p.score, codec_priority.get(p.codec, 0), p.height, p.bppf_effective)
            )

    # 3. Auxiliary Metadata
    frame_pacing = (jitter_ms > 3.0 or bufferbloat_ms > 15.0)

    if packet_loss_pct < 0.2 and jitter_ms < 3.0 and bufferbloat_ms < 10.0:
        confidence_level = "HIGH"
    elif packet_loss_pct <= 1.0 and jitter_ms <= 7.0 and bufferbloat_ms <= 25.0:
        confidence_level = "MEDIUM"
    else:
        confidence_level = "LOW"

    hardware_note = (
        "Rekomendowany profil AV1 wymaga karty graficznej lub układu SoC z obsługą sprzętowego dekodowania "
        "AV1 na urządzeniu klienckim. W przypadku braku wsparcia przełącz na profil HEVC."
    )

    reasoning_pl = (
        f"Dla przepustowości {throughput_mbps:.1f} Mbps obliczono bezpieczny limit wideo {target_bitrate} Mbps "
        f"(zakres: {safe_range}) przy uwzględnieniu bufora na piki entropii sceny oraz {fec_pct}% narzutu FEC. "
        f"Główna rekomendacja: {cinematic_profile.resolution} z kodekiem {cinematic_profile.codec} "
        f"(bppf: {cinematic_profile.bppf_effective:.3f}, jakość: {cinematic_profile.score:.3f}). "
    )
    if competitive_profile:
        reasoning_pl += (
            f"W trybie e-sportowym (RTT {rtt_ms:.1f} ms <= 30 ms) rekomendowane: "
            f"{competitive_profile.resolution} ({competitive_profile.codec}, wynik: {competitive_profile.score:.3f})."
        )
    else:
        reasoning_pl += f"Tryb e-sportowy (120 FPS) nie jest rekomendowany z powodu opóźnienia RTT ({rtt_ms:.1f} ms > 30 ms)."

    reasoning_en = (
        f"For {throughput_mbps:.1f} Mbps throughput, safe video bitrate is calculated at {target_bitrate} Mbps "
        f"(range: {safe_range}) factoring in scene entropy headroom and {fec_pct}% FEC overhead. "
        f"Primary recommendation: {cinematic_profile.resolution} using {cinematic_profile.codec} "
        f"(bppf: {cinematic_profile.bppf_effective:.3f}, score: {cinematic_profile.score:.3f}). "
    )
    if competitive_profile:
        reasoning_en += f"Competitive 120 FPS mode approved (RTT {rtt_ms:.1f} ms <= 30 ms): {competitive_profile.resolution}."
    else:
        reasoning_en += f"Competitive 120 FPS mode unavailable due to latency (RTT {rtt_ms:.1f} ms > 30 ms)."

    return MoonlightConfig(
        cinematic_profile=cinematic_profile,
        competitive_profile=competitive_profile,
        fallback_hevc=fallback_hevc,
        fallback_h264=fallback_h264,
        recommended_fec_percentage=fec_pct,
        frame_pacing=frame_pacing,
        confidence_level=confidence_level,
        hardware_note=hardware_note,
        reasoning_pl=reasoning_pl,
        reasoning_en=reasoning_en
    )
