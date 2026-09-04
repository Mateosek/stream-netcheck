import pytest
from engine.advisor import evaluate_moonlight_config
from engine.classifier import classify_sla


def test_scenario_a_baseline():
    """Scenariusz A: 65 Mbps, RTT 24ms, Bloat +4.2ms, Jitter 1.9ms, Loss 0.0%"""
    cfg = evaluate_moonlight_config(
        throughput_mbps=65.0, rtt_ms=24.0, jitter_ms=1.9,
        packet_loss_pct=0.0, bufferbloat_ms=4.2
    )
    assert cfg.cinematic_profile.target_bitrate_mbps == 45
    assert cfg.cinematic_profile.resolution == "1440p (2560x1440) @ 60 FPS"
    assert cfg.cinematic_profile.score == pytest.approx(0.873, abs=1e-3)
    
    assert cfg.fallback_hevc.resolution == "1440p (2560x1440) @ 60 FPS"
    assert cfg.fallback_hevc.score == pytest.approx(0.740, abs=1e-3)
    
    assert cfg.competitive_profile is not None
    assert cfg.competitive_profile.resolution == "1080p (1920x1080) @ 120 FPS"
    assert cfg.competitive_profile.score == pytest.approx(0.747, abs=1e-3)
    
    assert cfg.recommended_fec_percentage == 0
    assert cfg.frame_pacing is False
    assert cfg.confidence_level == "HIGH"
    assert classify_sla(24.0, 1.9, 0.0, 4.2) == "Grade A: Ultra-Low Latency"


def test_scenario_b_fiber():
    """Scenariusz B: 120 Mbps, RTT 12ms, Bloat +2.0ms, Jitter 0.8ms, Loss 0.0%"""
    cfg = evaluate_moonlight_config(
        throughput_mbps=120.0, rtt_ms=12.0, jitter_ms=0.8,
        packet_loss_pct=0.0, bufferbloat_ms=2.0
    )
    assert cfg.cinematic_profile.target_bitrate_mbps == 95
    assert cfg.cinematic_profile.resolution == "4K (3840x2160) @ 60 FPS"
    assert cfg.cinematic_profile.score == pytest.approx(0.934, abs=1e-3)
    
    assert cfg.fallback_hevc.resolution == "4K (3840x2160) @ 60 FPS"
    assert cfg.fallback_hevc.score == pytest.approx(0.810, abs=1e-3)
    
    assert cfg.competitive_profile is not None
    assert cfg.competitive_profile.resolution == "1440p (2560x1440) @ 120 FPS"
    assert cfg.competitive_profile.score == pytest.approx(0.917, abs=1e-3)
    assert cfg.frame_pacing is False
    assert classify_sla(12.0, 0.8, 0.0, 2.0) == "Grade A: Ultra-Low Latency"


def test_scenario_c_degradation():
    """Scenariusz C: 65 Mbps, RTT 35ms, Bloat +42ms, Jitter 4.5ms, Loss 1.5%"""
    cfg = evaluate_moonlight_config(
        throughput_mbps=65.0, rtt_ms=35.0, jitter_ms=4.5,
        packet_loss_pct=1.5, bufferbloat_ms=42.0
    )
    assert cfg.cinematic_profile.target_bitrate_mbps == 25
    assert cfg.cinematic_profile.resolution == "1080p (1920x1080) @ 60 FPS"
    # Poprawna suma pośrednich 0.1750 + 0.6282 = 0.8032:
    assert cfg.cinematic_profile.score == pytest.approx(0.803, abs=1e-3)
    
    assert cfg.fallback_hevc.resolution == "1080p (1920x1080) @ 60 FPS"
    assert cfg.fallback_hevc.score == pytest.approx(0.672, abs=1e-3)
    
    # RTT 35 ms > 30 ms -> brak trybu competitive
    assert cfg.competitive_profile is None
    
    assert cfg.recommended_fec_percentage == 20
    assert cfg.frame_pacing is True
    assert classify_sla(35.0, 4.5, 1.5, 42.0) == "Grade C: Functional / High Latency"


def test_scenario_d_narrow_band():
    """Scenariusz D: 15 Mbps, RTT 40ms, Bloat +12ms, Jitter 2.1ms, Loss 0.0%"""
    cfg = evaluate_moonlight_config(
        throughput_mbps=15.0, rtt_ms=40.0, jitter_ms=2.1,
        packet_loss_pct=0.0, bufferbloat_ms=12.0
    )
    assert cfg.cinematic_profile.target_bitrate_mbps == 10
    assert cfg.cinematic_profile.resolution == "720p (1280x720) @ 60 FPS"
    assert cfg.cinematic_profile.score == pytest.approx(0.656, abs=1e-3)
    assert cfg.fallback_hevc.score == pytest.approx(0.538, abs=1e-3)
    assert cfg.competitive_profile is None
    assert cfg.recommended_fec_percentage == 0
    assert classify_sla(40.0, 2.1, 0.0, 12.0) == "Grade B: Stable Interactive"


def test_scenario_e_distant_p2p():
    """Scenariusz E: 80 Mbps, RTT 60ms, Bloat +5.0ms, Jitter 1.8ms, Loss 0.0%"""
    cfg = evaluate_moonlight_config(
        throughput_mbps=80.0, rtt_ms=60.0, jitter_ms=1.8,
        packet_loss_pct=0.0, bufferbloat_ms=5.0
    )
    assert cfg.cinematic_profile.target_bitrate_mbps == 55
    assert cfg.cinematic_profile.resolution == "1440p (2560x1440) @ 60 FPS"
    assert cfg.cinematic_profile.score == pytest.approx(0.883, abs=1e-3)
    
    # Nasycenie BPPF_eff sprawia, że HEVC ma identyczny score (0.883)
    assert cfg.fallback_hevc.resolution == "1440p (2560x1440) @ 60 FPS"
    assert cfg.fallback_hevc.score == pytest.approx(0.883, abs=1e-3)
    assert cfg.competitive_profile is None
    
    # Szczelny catch-all dla stabilnego łącza z wysokim RTT
    assert classify_sla(60.0, 1.8, 0.0, 5.0) == "Grade C: Functional / High Latency"
