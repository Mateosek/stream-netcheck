"""
FastAPI Server & WebSocket Probing Gateway for stream-netcheck.
"""

import asyncio
import os
import time
from typing import List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from engine.qos import QoSEngine, PacketProbe, QoSMetrics
from engine.netbird import NetBirdInspector, NetBirdPeerInfo
from engine.classifier import SLAClassifier, SLARating

app = FastAPI(
    title="stream-netcheck",
    description="Real-Time Network QoS & Bufferbloat Diagnostic Engine for Cloud Gaming",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ProbeSubmissionItem(BaseModel):
    seq: int
    send_ts: float
    recv_ts: float
    rtt_ms: float


class DiagnosticRequest(BaseModel):
    total_sent: int
    probes: List[ProbeSubmissionItem]
    loaded_avg_rtt: Optional[float] = None
    throughput_mbps: Optional[float] = None
    client_ip_override: Optional[str] = None


@app.get("/")
def serve_index():
    """Serves the built-in diagnostic Web UI SPA."""
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return JSONResponse({"status": "stream-netcheck daemon online", "ui": "static/index.html not found"})


@app.websocket("/ws/probe")
async def websocket_probe(websocket: WebSocket):
    """
    Sub-millisecond WebSocket echo loop for high-frequency RTT and jitter measurement.
    """
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            # Immediately echo back with server timestamp
            server_ts = time.time()
            await websocket.send_json({
                "type": "pong",
                "seq": data.get("seq", 0),
                "client_ts": data.get("client_ts", 0),
                "server_ts": server_ts,
            })
    except WebSocketDisconnect:
        pass
    except Exception:
        try:
            await websocket.close()
        except Exception:
            pass


@app.get("/api/bandwidth/chunk")
def download_chunk(size_mb: float = Query(2.0, ge=0.5, le=10.0)):
    """
    Generates a deterministic raw binary chunk to measure client download throughput
    and induce network load for bufferbloat evaluation.
    """
    chunk_bytes = int(size_mb * 1024 * 1024)
    # Fast pseudo-random stream (repetition of a 64KB block to save server CPU)
    block = os.urandom(65536)
    full_payload = (block * (chunk_bytes // 65536 + 1))[:chunk_bytes]
    return Response(
        content=full_payload,
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Content-Length": str(len(full_payload)),
        }
    )


@app.post("/api/bandwidth/upload")
async def upload_chunk(request: Request):
    """
    Accepts client upload chunk to measure upstream bandwidth.
    """
    body = await request.body()
    return {"received_bytes": len(body), "status": "ok"}


@app.post("/api/evaluate")
def evaluate_network(req: DiagnosticRequest, request: Request):
    """
    Aggregates probe metrics, inspects NetBird mesh state, and returns full SLA verdict.
    """
    client_ip = req.client_ip_override
    if not client_ip:
        client_ip = request.client.host
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()

    # Convert incoming probe dicts to PacketProbe objects
    samples = [
        PacketProbe(
            seq=p.seq,
            send_ts=p.send_ts,
            recv_ts=p.recv_ts,
            rtt_ms=p.rtt_ms,
        )
        for p in req.probes
    ]

    metrics = QoSEngine.compute_metrics(
        sent_count=req.total_sent,
        probes=samples,
        loaded_avg_rtt=req.loaded_avg_rtt,
        throughput_mbps=req.throughput_mbps,
    )

    netbird_info = NetBirdInspector.inspect_peer(client_ip)
    rating = SLAClassifier.evaluate(metrics, netbird_info)

    return {
        "client_ip": client_ip,
        "metrics": {
            "total_sent": metrics.total_sent,
            "total_received": metrics.total_received,
            "packet_loss_pct": metrics.packet_loss_pct,
            "min_rtt_ms": metrics.min_rtt_ms,
            "max_rtt_ms": metrics.max_rtt_ms,
            "avg_rtt_ms": metrics.avg_rtt_ms,
            "median_rtt_ms": metrics.median_rtt_ms,
            "p95_rtt_ms": metrics.p95_rtt_ms,
            "std_dev_ms": metrics.std_dev_ms,
            "rfc3550_jitter_ms": metrics.rfc3550_jitter_ms,
            "bufferbloat_delta_ms": metrics.bufferbloat_delta_ms,
            "throughput_mbps": metrics.throughput_mbps,
        },
        "netbird": {
            "ip": netbird_info.ip,
            "connected": netbird_info.connected,
            "is_direct_p2p": netbird_info.is_direct_p2p,
            "connection_type": netbird_info.connection_type,
            "ice_candidate_type": netbird_info.ice_candidate_type,
            "reported_latency_ms": netbird_info.reported_latency_ms,
        },
        "sla": {
            "grade": rating.grade,
            "tier_name": rating.tier_name,
            "status_color": rating.status_color,
            "summary_pl": rating.summary_pl,
            "summary_en": rating.summary_en,
            "recommendations_pl": rating.recommendations_pl,
            "recommendations_en": rating.recommendations_en,
        }
    }
