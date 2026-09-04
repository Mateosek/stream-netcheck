"""
ITU-T Y.1541 QoS SLA Classifier & Root Cause Analysis (RCA) Engine.

Categorizes network telemetry into ITU-T QoS tiers tailored for low-latency
interactive streaming (Moonlight / Sunshine / GeForce NOW) and provides
actionable root-cause diagnosis.
"""

from dataclasses import dataclass, asdict
from typing import List, Optional
from engine.qos import QoSMetrics
from engine.netbird import NetBirdPeerInfo
from engine.advisor import MoonlightConfig, evaluate_moonlight_config


def classify_sla(
    rtt_ms: float,
    jitter_ms: float,
    packet_loss_pct: float,
    bufferbloat_ms: float,
    is_relayed: bool = False,
    has_netbird_context: bool = True
) -> str:
    """
    Classifies network health into defined SLA grades based on latency, jitter, loss, and bloat.
    """
    relayed_cond = is_relayed if has_netbird_context else False
    if relayed_cond or packet_loss_pct > 2.5 or jitter_ms > 12.0 or bufferbloat_ms > 60.0:
        return "Grade D: Degraded / Relayed"

    if (rtt_ms <= 25.0 and jitter_ms <= 3.5 and 
        packet_loss_pct == 0.0 and bufferbloat_ms <= 15.0):
        return "Grade A: Ultra-Low Latency"

    if (rtt_ms <= 45.0 and jitter_ms <= 6.0 and 
        packet_loss_pct <= 0.5 and bufferbloat_ms <= 30.0):
        return "Grade B: Stable Interactive"

    return "Grade C: Functional / High Latency"


@dataclass
class SLARating:
    grade: str            # "A", "B", "C", or "F"
    tier_name: str        # e.g. "Ultra-Low Latency", "Stable Interactive"
    status_color: str     # "green", "yellow", "red"
    summary_pl: str
    summary_en: str
    recommendations_pl: List[str]
    recommendations_en: List[str]
    moonlight_config: Optional[MoonlightConfig] = None

    def to_dict(self) -> dict:
        data = asdict(self)
        return data


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

        # Root Cause Analysis (RCA)
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
            rec_pl.append(f"Wykryto bufferbloat na routerze (+{bufferbloat} ms pod obciążeniem). Obniż bitrate w Moonlight, aby nie zapychać kolejki routera.")
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

        # Evaluate Moonlight preset advisor
        moonlight_cfg = evaluate_moonlight_config(
            throughput_mbps=metrics.throughput_mbps or 50.0,
            rtt_ms=metrics.avg_rtt_ms,
            jitter_ms=metrics.rfc3550_jitter_ms,
            packet_loss_pct=metrics.packet_loss_pct,
            bufferbloat_ms=bufferbloat,
            is_relayed=is_relayed,
            has_netbird_context=(netbird_info is not None)
        )

        # Standard SLA classification string
        sla_class = classify_sla(
            rtt_ms=metrics.avg_rtt_ms,
            jitter_ms=metrics.rfc3550_jitter_ms,
            packet_loss_pct=metrics.packet_loss_pct,
            bufferbloat_ms=bufferbloat,
            is_relayed=is_relayed,
            has_netbird_context=(netbird_info is not None)
        )

        # If Wi-Fi spikes detected, ensure grade is not A or B
        if has_wifi_spikes and "Grade A" in sla_class or "Grade B" in sla_class:
            sla_class = "Grade C: Functional / High Latency"

        # Map to SLARating
        if "Grade A" in sla_class:
            return SLARating(
                grade="A",
                tier_name="Ultra-Low Latency",
                status_color="green",
                summary_pl="Świetne połączenie. Znakomite warunki do gamingu z minimalnym opóźnieniem wejściowym.",
                summary_en="Optimal telecommunication parameters. Flawless cloud gaming with ultra-low latency.",
                recommendations_pl=rec_pl or ["Łącze jest w pełni stabilne."],
                recommendations_en=rec_en or ["Network is fully stable."],
                moonlight_config=moonlight_cfg
            )
        elif "Grade B" in sla_class:
            return SLARating(
                grade="B",
                tier_name="Stable Interactive",
                status_color="green",
                summary_pl="Dobre i stabilne połączenie. Płynna rozgrywka interaktywna.",
                summary_en="Good and stable connection. Smooth interactive gameplay expected.",
                recommendations_pl=rec_pl or ["Dobra stabilność łącza."],
                recommendations_en=rec_en or ["Good overall connection stability."],
                moonlight_config=moonlight_cfg
            )
        elif "Grade C" in sla_class:
            return SLARating(
                grade="C",
                tier_name="Functional / High Latency",
                status_color="yellow",
                summary_pl="Umiarkowane parametry. W grach dynamicznych/FPS może być wyczuwalny lekki input lag.",
                summary_en="Moderate connection quality. Action/FPS titles might feel latency delay.",
                recommendations_pl=rec_pl or ["Zalecane dostosowanie ustawień."],
                recommendations_en=rec_en or ["Adjust streaming settings to compensate for latency."],
                moonlight_config=moonlight_cfg
            )
        else:
            return SLARating(
                grade="F",
                tier_name="Degraded / Relayed",
                status_color="red",
                summary_pl="Niestabilne połączenie lub trasa przez serwer pośredniczący (Relay). Oczekiwany wysoki input lag.",
                summary_en="Degraded connection or routed via cloud Relay/TURN. Expect high input lag or stutter.",
                recommendations_pl=rec_pl or ["Sprawdź stan tunelu NetBird lub połączenie Wi-Fi."],
                recommendations_en=rec_en or ["Check NetBird tunnel status or local network link."],
                moonlight_config=moonlight_cfg
            )
