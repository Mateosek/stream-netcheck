"""
stream-netcheck CLI Terminal Interface.

Allows automated or headless evaluation of network Quality of Service (QoS),
bufferbloat, and mesh connectivity.
"""

import argparse
import asyncio
import json
import sys
import time
import urllib.request
import websockets

def print_banner():
    print("\033[1;38;5;208m")
    banner = [
        r"  ___ _                     _  _     _   ___ _            _   ",
        r" / __| |_ _ _ ___ __ _ _ __| \| |___| |_/ __| |_  ___  __| |__",
        r" \__ \  _| '_/ -_) _` | '  \ .` / -_)  _| (__| ' \/ -_)/ _| / /",
        r" |___/\__|_| \___|__,_|_|_|_|\_|\___|\__|\___|_||_\___|\__|_\_\\",
    ]
    for line in banner:
        print(line)

    print("\033[0m")
    print(" RFC 3550 QoS, Bufferbloat & WireGuard Mesh Telemetry Engine\n")

async def run_cli_diagnostic(host: str, probe_count: int = 30, output_json: bool = False):
    ws_url = f"ws://{host}/ws/probe"
    http_url = f"http://{host}"

    if not output_json:
        print(f"[*] Connecting to probe gateway at {ws_url}...")

    probes = []
    try:
        async with websockets.connect(ws_url, open_timeout=5) as ws:
            if not output_json:
                print(f"[*] Running Idle Latency & Jitter probe ({probe_count} samples)...")

            for seq in range(probe_count):
                send_ts = time.time()
                await ws.send(json.dumps({"seq": seq, "client_ts": send_ts}))
                resp = await ws.recv()
                recv_ts = time.time()
                data = json.loads(resp)
                rtt_ms = (recv_ts - send_ts) * 1000.0
                probes.append({
                    "seq": seq,
                    "send_ts": send_ts,
                    "recv_ts": data.get("server_ts", recv_ts),
                    "rtt_ms": rtt_ms
                })
                await asyncio.sleep(0.05)

            # Measure loaded latency & throughput
            if not output_json:
                print("[*] Running Bandwidth & Bufferbloat test...")
            
            loaded_probes = []
            async def background_loaded_ping():
                for s in range(8):
                    st = time.time()
                    try:
                        await ws.send(json.dumps({"seq": s, "client_ts": st}))
                        resp = await ws.recv()
                        rt = time.time()
                        loaded_probes.append((rt - st) * 1000.0)
                        await asyncio.sleep(0.1)
                    except Exception:
                        break

            ping_task = asyncio.create_task(background_loaded_ping())
            
            # Download 8MB chunk
            start_dl = time.time()
            chunk_url = f"{http_url}/api/bandwidth/chunk?size_mb=8.0&t={time.time()}"
            speed_mbps = None
            try:
                req = urllib.request.Request(chunk_url)
                with urllib.request.urlopen(req, timeout=10) as response:
                    content = response.read()
                    duration = time.time() - start_dl
                    speed_mbps = round(((len(content) * 8.0) / duration) / (1024 * 1024), 2)
            except Exception as e:
                if not output_json:
                    print(f"[!] Bandwidth probe error: {e}")

            await ping_task
            loaded_avg = (sum(loaded_probes) / len(loaded_probes)) if loaded_probes else None

    except Exception as e:
        print(f"Error: Connection to {host} failed: {e}", file=sys.stderr)
        sys.exit(1)

    # Submit evaluation
    eval_url = f"{http_url}/api/evaluate"
    eval_payload = {
        "total_sent": probe_count,
        "probes": probes,
        "loaded_avg_rtt": loaded_avg,
        "throughput_mbps": speed_mbps
    }

    try:
        req = urllib.request.Request(
            eval_url,
            data=json.dumps(eval_payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"Error: Failed to evaluate SLA: {e}", file=sys.stderr)
        sys.exit(1)

    if output_json:
        print(json.dumps(result, indent=2))
        return

    m = result["metrics"]
    sla = result["sla"]
    nb = result["netbird"]

    color_code = "\033[1;32m" if sla["status_color"] == "green" else ("\033[1;33m" if sla["status_color"] == "yellow" else "\033[1;31m")
    reset_code = "\033[0m"

    print("\n" + "=" * 64)
    print(f" SLA VERDICT: {color_code}GRADE {sla['grade']} - {sla['tier_name']}{reset_code}")
    print("=" * 64)
    print(f" Summary: {sla['summary_en']}")
    print("-" * 64)
    print(f" • Round-Trip Time (RTT):   Avg: {m['avg_rtt_ms']} ms | Min: {m['min_rtt_ms']} ms | Max: {m['max_rtt_ms']} ms")
    print(f" • RFC 3550 Jitter:         {m['rfc3550_jitter_ms']} ms (StdDev: {m['std_dev_ms']} ms)")
    print(f" • Packet Loss Ratio:       {m['packet_loss_pct']}% ({m['total_received']}/{m['total_sent']} packets)")
    b_str = f"+{m['bufferbloat_delta_ms']} ms" if m['bufferbloat_delta_ms'] is not None else "N/A"
    print(f" • Bufferbloat (Loaded Δ):  {b_str}")
    sp_str = f"{m['throughput_mbps']} Mbps" if m['throughput_mbps'] is not None else "N/A"
    print(f" • Estimated Throughput:    {sp_str}")
    nb_mode = "Direct P2P (WireGuard)" if nb['is_direct_p2p'] else nb['connection_type']
    print(f" • NetBird Mesh Route:      {nb_mode}")

    if "moonlight_config" in result and result["moonlight_config"]:
        cfg = result["moonlight_config"]
        cp = cfg["cinematic_profile"]
        print("-" * 64)
        print(" MOONLIGHT / SUNSHINE CONFIGURATION ADVISOR")
        print("-" * 64)
        print(f" • Recommended Resolution:  {cp['resolution']}")
        print(f" • Target Bitrate Slider:    {cp['target_bitrate_mbps']} Mbps (Range: {cp['safe_bitrate_range']})")
        print(f" • Recommended Codec:        {cp['codec']} (Quality Score: {cp['score']})")
        if cfg.get("competitive_profile"):
            comp = cfg["competitive_profile"]
            print(f" • Competitive Mode (120Hz): {comp['resolution']} ({comp['codec']})")
        else:
            print(" • Competitive Mode (120Hz): Disabled (RTT > 30 ms)")
        print(f" • Forward Error Corr (FEC): {cfg['recommended_fec_percentage']}%")
        print(f" • Frame Pacing (Smooth):    {'ENABLED' if cfg['frame_pacing'] else 'OFF'}")
        print(f" • Confidence Level:         {cfg['confidence_level']}")
        print(f" • Hardware Notice:          {cfg['hardware_note']}")

    print("-" * 64)
    print(" Recommendations:")
    for r in sla['recommendations_en']:
        print(f"   - {r}")
    print("=" * 64 + "\n")


def main():
    parser = argparse.ArgumentParser(description="stream-netcheck network diagnostic CLI tool")
    parser.add_argument("--host", default="127.0.0.1:8055", help="Target stream-netcheck server host:port (default: 127.0.0.1:8055)")
    parser.add_argument("--count", type=int, default=30, help="Number of probe packets (default: 30)")
    parser.add_argument("--json", action="store_true", help="Output results in raw JSON format")
    args = parser.parse_args()

    if not args.json:
        print_banner()

    asyncio.run(run_cli_diagnostic(host=args.host, probe_count=args.count, output_json=args.json))


if __name__ == "__main__":
    main()
