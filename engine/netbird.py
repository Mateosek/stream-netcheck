"""
NetBird & WireGuard Mesh Overlay Topology Resolver.

Inspects the local NetBird daemon to ascertain whether a peer connection
is established directly via peer-to-peer WireGuard (P2P) or fell back
to an intermediate relay (TURN/DERP), which adds latency penalty.
"""

from dataclasses import dataclass
import json
import shutil
import subprocess
from typing import Optional, Dict, Any


@dataclass
class NetBirdPeerInfo:
    ip: str
    connected: bool
    is_direct_p2p: bool
    connection_type: str  # "P2P", "Relayed", or "Unknown"
    ice_candidate_type: Optional[str] = None
    reported_latency_ms: Optional[float] = None
    raw_info: Optional[str] = None


class NetBirdInspector:
    """
    Interrogates the local NetBird client daemon via CLI.
    """

    @staticmethod
    def is_netbird_available() -> bool:
        """Returns True if the netbird CLI is accessible on the host."""
        return shutil.which("netbird") is not None

    @staticmethod
    def inspect_peer(target_ip: str) -> NetBirdPeerInfo:
        """
        Determines the connection state of a specific NetBird peer IP.
        """
        if not NetBirdInspector.is_netbird_available():
            return NetBirdPeerInfo(
                ip=target_ip,
                connected=False,
                is_direct_p2p=False,
                connection_type="Not Installed",
                raw_info="NetBird CLI not available on this host."
            )

        # Try JSON output first
        try:
            res = subprocess.run(
                ["netbird", "status", "--json"],
                capture_output=True,
                text=True,
                timeout=3
            )
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout)
                peers = data.get("peers", {}).get("details", [])
                for peer in peers:
                    peer_ip = peer.get("netbirdIp", "")
                    if target_ip in peer_ip or target_ip == peer.get("ip"):
                        conn_type = peer.get("connectionType", "")
                        is_p2p = conn_type.lower() in ("p2p", "direct")
                        latency = peer.get("latency")
                        return NetBirdPeerInfo(
                            ip=target_ip,
                            connected=peer.get("status", "").lower() == "connected",
                            is_direct_p2p=is_p2p,
                            connection_type="P2P" if is_p2p else "Relayed",
                            ice_candidate_type=peer.get("iceCandidateType"),
                            reported_latency_ms=float(latency) if latency is not None else None,
                            raw_info=f"Peer: {peer.get('fqdn', '')}, ICE: {peer.get('iceCandidateType', '')}"
                        )
        except Exception:
            pass

        # Fallback to text parsing
        try:
            res = subprocess.run(
                ["netbird", "status"],
                capture_output=True,
                text=True,
                timeout=3
            )
            if res.returncode == 0 and res.stdout:
                lines = res.stdout.splitlines()
                for line in lines:
                    if target_ip in line:
                        lower_line = line.lower()
                        is_p2p = "p2p" in lower_line or "direct" in lower_line
                        is_relayed = "relay" in lower_line
                        return NetBirdPeerInfo(
                            ip=target_ip,
                            connected=True,
                            is_direct_p2p=is_p2p,
                            connection_type="P2P" if is_p2p else ("Relayed" if is_relayed else "Connected"),
                            raw_info=line.strip()
                        )
        except Exception as e:
            return NetBirdPeerInfo(
                ip=target_ip,
                connected=False,
                is_direct_p2p=False,
                connection_type="Error",
                raw_info=str(e)
            )

        return NetBirdPeerInfo(
            ip=target_ip,
            connected=False,
            is_direct_p2p=False,
            connection_type="Peer Not Found",
            raw_info="Peer not present in NetBird active routing table."
        )
