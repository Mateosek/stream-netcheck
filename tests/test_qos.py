import pytest
from engine.qos import QoSEngine, PacketProbe, QoSMetrics
from engine.classifier import SLAClassifier
from engine.netbird import NetBirdPeerInfo


def test_rfc3550_jitter_zero_variance():
    # Perfectly spaced packets should have 0 jitter
    samples = [
        PacketProbe(seq=0, send_ts=100.00, recv_ts=100.02, rtt_ms=20.0),
        PacketProbe(seq=1, send_ts=100.05, recv_ts=100.07, rtt_ms=20.0),
        PacketProbe(seq=2, send_ts=100.10, recv_ts=100.12, rtt_ms=20.0),
    ]
    jitter = QoSEngine.calculate_rfc3550_jitter(samples)
    assert jitter == 0.0


def test_rfc3550_jitter_varying_delay():
    # Transit time variations: 20ms -> 30ms -> 10ms
    samples = [
        PacketProbe(seq=0, send_ts=100.00, recv_ts=100.02, rtt_ms=20.0),
        PacketProbe(seq=1, send_ts=100.05, recv_ts=100.08, rtt_ms=30.0),
        PacketProbe(seq=2, send_ts=100.10, recv_ts=100.11, rtt_ms=10.0),
    ]
    jitter = QoSEngine.calculate_rfc3550_jitter(samples)
    assert jitter > 0.0


def test_qos_metrics_aggregation():
    samples = [
        PacketProbe(seq=0, send_ts=0, recv_ts=0.010, rtt_ms=10.0),
        PacketProbe(seq=1, send_ts=0, recv_ts=0.020, rtt_ms=20.0),
        PacketProbe(seq=2, send_ts=0, recv_ts=0.030, rtt_ms=30.0),
    ]
    metrics = QoSEngine.compute_metrics(
        sent_count=4,  # 1 dropped packet
        probes=samples,
        loaded_avg_rtt=45.0,
        throughput_mbps=85.5
    )

    assert metrics.total_sent == 4
    assert metrics.total_received == 3
    assert metrics.packet_loss_pct == 25.0
    assert metrics.min_rtt_ms == 10.0
    assert metrics.max_rtt_ms == 30.0
    assert metrics.avg_rtt_ms == 20.0
    assert metrics.median_rtt_ms == 20.0
    assert metrics.bufferbloat_delta_ms == 25.0
    assert metrics.throughput_mbps == 85.5


def test_sla_grade_a():
    metrics = QoSMetrics(
        total_sent=30,
        total_received=30,
        packet_loss_pct=0.0,
        min_rtt_ms=12.0,
        max_rtt_ms=18.0,
        avg_rtt_ms=15.0,
        median_rtt_ms=15.0,
        p95_rtt_ms=17.0,
        std_dev_ms=1.2,
        rfc3550_jitter_ms=1.1,
        bufferbloat_delta_ms=5.0,
        throughput_mbps=120.0
    )
    nb = NetBirdPeerInfo(
        ip="100.64.0.1",
        connected=True,
        is_direct_p2p=True,
        connection_type="P2P"
    )
    rating = SLAClassifier.evaluate(metrics, nb)
    assert rating.grade == "A"
    assert rating.status_color == "green"


def test_sla_grade_f_due_to_relay():
    # Fast ping, but relayed via cloud TURN server
    metrics = QoSMetrics(
        total_sent=30,
        total_received=30,
        packet_loss_pct=0.0,
        min_rtt_ms=15.0,
        max_rtt_ms=25.0,
        avg_rtt_ms=20.0,
        median_rtt_ms=20.0,
        p95_rtt_ms=23.0,
        std_dev_ms=2.0,
        rfc3550_jitter_ms=2.0,
        bufferbloat_delta_ms=10.0,
        throughput_mbps=50.0
    )
    nb = NetBirdPeerInfo(
        ip="100.64.0.1",
        connected=True,
        is_direct_p2p=False,
        connection_type="Relayed"
    )
    rating = SLAClassifier.evaluate(metrics, nb)
    assert rating.grade == "F"
    assert rating.status_color == "red"
    assert any("Relay" in tip for tip in rating.recommendations_pl)


def test_sla_bufferbloat_detection():
    metrics = QoSMetrics(
        total_sent=30,
        total_received=30,
        packet_loss_pct=0.0,
        min_rtt_ms=15.0,
        max_rtt_ms=25.0,
        avg_rtt_ms=20.0,
        median_rtt_ms=20.0,
        p95_rtt_ms=23.0,
        std_dev_ms=2.0,
        rfc3550_jitter_ms=2.0,
        bufferbloat_delta_ms=95.0,  # Massive bufferbloat
        throughput_mbps=50.0
    )
    rating = SLAClassifier.evaluate(metrics)
    assert any("bufferbloat" in tip.lower() for tip in rating.recommendations_pl)



def test_sla_wifi_spike_detection():
    # Low average and jitter, but periodic severe Wi-Fi spikes (Max 240ms vs Min 15ms)
    metrics = QoSMetrics(
        total_sent=60,
        total_received=60,
        packet_loss_pct=0.0,
        min_rtt_ms=15.0,
        max_rtt_ms=240.0,
        avg_rtt_ms=22.0,
        median_rtt_ms=16.0,
        p95_rtt_ms=45.0,
        std_dev_ms=8.0,
        rfc3550_jitter_ms=2.5,
        bufferbloat_delta_ms=5.0,
        throughput_mbps=80.0
    )
    rating = SLAClassifier.evaluate(metrics)
    assert any("skoki opóźnień" in tip for tip in rating.recommendations_pl)
    assert rating.grade not in ("A", "B")
