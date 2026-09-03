"""
Network Quality of Service (QoS) & Statistical Telemetry Engine.

Implements mathematical models from RFC 3550 (RTP Interarrival Jitter),
ITU-T Y.1540/Y.1541 IP Packet Transfer Delay, and Bufferbloat metrics.
"""

from dataclasses import dataclass
import math
from typing import List, Optional


@dataclass
class PacketProbe:
    seq: int
    send_ts: float  # Epoch timestamp in seconds (client-side)
    recv_ts: float  # Epoch timestamp in seconds (server-side, or echo receipt)
    rtt_ms: float


@dataclass
class QoSMetrics:
    total_sent: int
    total_received: int
    packet_loss_pct: float
    min_rtt_ms: float
    max_rtt_ms: float
    avg_rtt_ms: float
    median_rtt_ms: float
    p95_rtt_ms: float
    std_dev_ms: float
    rfc3550_jitter_ms: float
    bufferbloat_delta_ms: Optional[float] = None
    throughput_mbps: Optional[float] = None


class QoSEngine:
    """
    Computes statistical network characteristics and RFC 3550 jitter
    for real-time multimedia & game streaming streams.
    """

    @staticmethod
    def calculate_rfc3550_jitter(samples: List[PacketProbe]) -> float:
        """
        Calculates interarrival jitter using the RFC 3550 smoothing filter:
        D(i, j) = (R_j - S_j) - (R_i - S_i)
        J(i) = J(i-1) + (|D(i-1, i)| - J(i-1)) / 16

        Where S is send time and R is receive time.
        """
        if len(samples) < 2:
            return 0.0

        jitter = 0.0
        for idx in range(1, len(samples)):
            prev = samples[idx - 1]
            curr = samples[idx]

            # Transit time difference between consecutive packets in milliseconds
            d = abs((curr.recv_ts - curr.send_ts) - (prev.recv_ts - prev.send_ts)) * 1000.0
            jitter = jitter + (d - jitter) / 16.0

        return round(jitter, 3)

    @staticmethod
    def compute_metrics(
        sent_count: int,
        probes: List[PacketProbe],
        loaded_avg_rtt: Optional[float] = None,
        throughput_mbps: Optional[float] = None,
    ) -> QoSMetrics:
        """
        Aggregates packet probe measurements into comprehensive QoS telemetry.
        """
        recv_count = len(probes)
        loss_pct = 0.0
        if sent_count > 0:
            loss_pct = max(0.0, min(100.0, ((sent_count - recv_count) / sent_count) * 100.0))

        if recv_count == 0:
            return QoSMetrics(
                total_sent=sent_count,
                total_received=0,
                packet_loss_pct=100.0,
                min_rtt_ms=0.0,
                max_rtt_ms=0.0,
                avg_rtt_ms=0.0,
                median_rtt_ms=0.0,
                p95_rtt_ms=0.0,
                std_dev_ms=0.0,
                rfc3550_jitter_ms=0.0,
                bufferbloat_delta_ms=None,
                throughput_mbps=throughput_mbps,
            )

        rtts = sorted([p.rtt_ms for p in probes])
        min_rtt = rtts[0]
        max_rtt = rtts[-1]
        avg_rtt = sum(rtts) / recv_count

        # Median and 95th percentile
        median_idx = recv_count // 2
        median_rtt = (
            rtts[median_idx]
            if recv_count % 2 != 0
            else (rtts[median_idx - 1] + rtts[median_idx]) / 2.0
        )

        p95_idx = max(0, min(recv_count - 1, int(math.ceil(0.95 * recv_count)) - 1))
        p95_rtt = rtts[p95_idx]

        # Standard Deviation
        variance = sum((x - avg_rtt) ** 2 for x in rtts) / recv_count
        std_dev = math.sqrt(variance)

        # RFC 3550 Jitter
        rfc_jitter = QoSEngine.calculate_rfc3550_jitter(probes)

        # Bufferbloat Delta: difference between loaded and idle latency
        bufferbloat_delta = None
        if loaded_avg_rtt is not None and loaded_avg_rtt >= avg_rtt:
            bufferbloat_delta = round(loaded_avg_rtt - avg_rtt, 2)
        elif loaded_avg_rtt is not None:
            bufferbloat_delta = 0.0

        return QoSMetrics(
            total_sent=sent_count,
            total_received=recv_count,
            packet_loss_pct=round(loss_pct, 2),
            min_rtt_ms=round(min_rtt, 2),
            max_rtt_ms=round(max_rtt, 2),
            avg_rtt_ms=round(avg_rtt, 2),
            median_rtt_ms=round(median_rtt, 2),
            p95_rtt_ms=round(p95_rtt, 2),
            std_dev_ms=round(std_dev, 2),
            rfc3550_jitter_ms=rfc_jitter,
            bufferbloat_delta_ms=bufferbloat_delta,
            throughput_mbps=round(throughput_mbps, 2) if throughput_mbps else None,
        )
