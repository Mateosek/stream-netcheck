"""
ITU-T Y.1541 QoS SLA Classifier & Root Cause Analysis (RCA) Engine.

Categorizes network telemetry into ITU-T QoS tiers tailored for low-latency
interactive streaming (Moonlight / Sunshine / GeForce NOW) and provides
actionable root-cause diagnosis.
"""

from dataclasses import dataclass
from typing import List, Optional
from engine.qos import QoSMetrics
from engine.netbird import NetBirdPeerInfo


@dataclass
class SLARating:
    grade: str            # "A", "B", "C", or "F"
    tier_name: str        # "Optimal (4K/60)", "Good (1080p/60)", "Playable (720p)", "Degraded"
    status_color: str     # "green", "yellow", "red"
    summary_pl: str
    summary_en: str
    recommendations_pl: List[str]
    recommendations_en: List[str]


class SLAClassifier:
    """
    Evaluates QoS telemetry against ITU-T Y.1540 / Y.1541 telecommunication
    standards and Cloud Gaming SLA thresholds.
    """

    @staticmethod
    def evaluate(
        metrics: QoSMetrics,
        netbird_info: Optional[NetBirdPeerInfo] = None
    ) -> SLARating:
        rec_pl = []
        rec_en = []

        is_relayed = netbird_info is not None and netbird_info.connection_type.lower() == "relayed"
        bufferbloat = metrics.bufferbloat_delta_ms or 0.0

        # Detect specific Root Causes
        if metrics.packet_loss_pct > 1.5:
            rec_pl.append(f"Wykryto utratę pakietów ({metrics.packet_loss_pct}%). Może powodować zacięcia obrazu i artefakty.")
            rec_en.append(f"Significant packet loss detected ({metrics.packet_loss_pct}%). Video stream will suffer artifacts.")

        if metrics.rfc3550_jitter_ms > 12.0:
            rec_pl.append(f"Wysoki jitter ({metrics.rfc3550_jitter_ms} ms) wskazuje na niestabilność Wi-Fi lub zakłócenia radiowe. Zalecane przejście na kabel Ethernet.")
            rec_en.append(f"High jitter ({metrics.rfc3550_jitter_ms} ms) suggests Wi-Fi instability or radio interference. Switch to wired Ethernet.")
        elif metrics.rfc3550_jitter_ms > 6.0:
            rec_pl.append(f"Umiarkowany jitter ({metrics.rfc3550_jitter_ms} ms). Jeśli używasz Wi-Fi, podejdź bliżej routera (pasmo 5 GHz).")
            rec_en.append(f"Moderate jitter ({metrics.rfc3550_jitter_ms} ms). Ensure you are connected to a 5 GHz Wi-Fi band near the router.")

        if bufferbloat > 40.0:
            rec_pl.append(f"Wykryto bufferbloat na routerze (+{bufferbloat} ms pod obciążeniem). Obniż bitrate w Moonlight (np. do 25 Mbps), aby nie zapychać kolejki routera.")
            rec_en.append(f"Bufferbloat detected on the local router (+{bufferbloat} ms loaded delta). Lower the Moonlight bitrate to avoid buffer congestion.")


        # Detect Weak Wi-Fi / Low RSSI frame retries & intermittent spikes
        rtt_spread = metrics.max_rtt_ms - metrics.min_rtt_ms
        has_wifi_spikes = rtt_spread > 80.0 and metrics.max_rtt_ms > 140.0
        if has_wifi_spikes:
            rec_pl.append(f"Wykryto drastyczne skoki opóźnień (Maks: {metrics.max_rtt_ms} ms vs Min: {metrics.min_rtt_ms} ms). Jest to typowy objaw słabego zasięgu Wi-Fi (retransmisje radiowe przy niskim poziomie sygnału RSSI) lub skanowania sieci w tle. Zalecane zbliżenie się do routera lub kabel.")
            rec_en.append(f"Severe latency spikes observed (Max: {metrics.max_rtt_ms} ms vs Min: {metrics.min_rtt_ms} ms). Indicative of 802.11 MAC frame retransmissions due to weak Wi-Fi RSSI or background channel scanning.")

        if is_relayed:
            rec_pl.append("Połączenie NetBird korzysta z serwera pośredniczącego (Relay/TURN), a nie bezpośredniego P2P. Dodaje to sztuczne opóźnienie.")
            rec_en.append("NetBird is using a cloud Relay (TURN) rather than direct WireGuard P2P. Check NAT/firewall settings to allow direct UDP.")


        # If relayed, the connection is degraded by definition due to intermediate hops
        if is_relayed:
            return SLARating(
                grade="F",
                tier_name="Degraded (Relay Fallback)",
                status_color="red",
                summary_pl="Połączenie nie osiąga bezpośredniej trasy P2P i leci przez serwer pośredniczący (Relay). Oczekiwany wysoki input lag.",
                summary_en="Connection failed to establish direct WireGuard P2P and fell back to cloud Relay/TURN.",
                recommendations_pl=rec_pl or ["Sprawdź czy router nie blokuje portów UDP WireGuarda lub zrestartuj klienta NetBird."],
                recommendations_en=rec_en or ["Ensure router allows direct UDP hole punching or restart NetBird daemon."],
            )

        # GRADE A: RTT < 25ms, Jitter < 3.5ms, Loss == 0%, Bufferbloat < 20ms, No Spikes
        if (
            metrics.avg_rtt_ms < 25.0
            and metrics.rfc3550_jitter_ms < 3.5
            and metrics.packet_loss_pct == 0.0
            and bufferbloat < 20.0
            and not has_wifi_spikes
        ):
            return SLARating(
                grade="A",
                tier_name="Optimal (4K @ 60 FPS)",
                status_color="green",
                summary_pl="Świetne połączenie. Idealne warunki do grania w 4K przy 60 FPS z minimalnym opóźnieniem.",
                summary_en="Optimal telecommunication parameters. Flawless 4K/60FPS streaming with ultra-low latency.",
                recommendations_pl=rec_pl or ["Łącze jest w pełni stabilne. Możesz grać na najwyższych ustawieniach bitrate."],
                recommendations_en=rec_en or ["Network is fully stable. Safe to stream at maximum bitrate settings."],
            )

        # GRADE B: RTT < 45ms, Jitter < 8ms, Loss < 0.5%, Bufferbloat < 50ms, No Spikes
        if (
            metrics.avg_rtt_ms < 45.0
            and metrics.rfc3550_jitter_ms < 8.0
            and metrics.packet_loss_pct <= 0.5
            and bufferbloat < 50.0
            and not has_wifi_spikes
        ):

            return SLARating(
                grade="B",
                tier_name="Good (1080p @ 60 FPS)",
                status_color="green",
                summary_pl="Dobre i stabilne połączenie. Płynna rozgrywka w 1080p przy 60 FPS.",
                summary_en="Good and stable connection. Smooth gameplay expected at 1080p/60FPS.",
                recommendations_pl=rec_pl or ["Standardowa jakość streamingowa. Rekomendowany bitrate: 30-40 Mbps."],
                recommendations_en=rec_en or ["Standard streaming quality. Recommended bitrate: 30-40 Mbps."],
            )

        # GRADE C: RTT < 75ms, Jitter < 15ms, Loss < 2.0%
        if (
            metrics.avg_rtt_ms < 75.0
            and metrics.rfc3550_jitter_ms < 15.0
            and metrics.packet_loss_pct <= 2.0
        ):
            return SLARating(
                grade="C",
                tier_name="Playable (720p / Turn-based)",
                status_color="yellow",
                summary_pl="Umiarkowane połączenie. Gry zręcznościowe/FPS mogą odczuwać lekki input lag. Dobre dla gier RPG i turowych.",
                summary_en="Moderate connection quality. Action/FPS titles might feel input delay. Suitable for RPG or turn-based titles.",
                recommendations_pl=rec_pl or ["Zalecane obniżenie rozdzielczości do 720p lub ograniczenie bitrate do 15-20 Mbps."],
                recommendations_en=rec_en or ["Lower resolution to 720p or cap bitrate to 15-20 Mbps."],
            )

        # GRADE F: Degraded
        return SLARating(
            grade="F",
            tier_name="Degraded (Unstable)",
            status_color="red",
            summary_pl="Krytyczna niestabilność łącza. Rozgrywka będzie rwać, wystąpi wysoki input lag lub widoczne artefakty.",
            summary_en="Degraded connection. Gameplay will suffer stuttering, high input lag, and severe frame drops.",
            recommendations_pl=rec_pl or ["Sprawdź połączenie Wi-Fi, zrestartuj router lub sprawdź status tunelu NetBird."],
            recommendations_en=rec_en or ["Check Wi-Fi connection, reboot gateway router, or inspect NetBird tunnel status."],
        )
