/**
 * stream-netcheck Web Probing Engine
 * Supports Quick (4s) & Full Stability (30s Live Chart) modes.
 */

let activeMode = "quick";
let socket = null;
let idleProbes = [];
let loadedProbes = [];
let chartPoints = [];

function setProgress(pct, status, ticker) {
    document.getElementById("progress-fill").style.width = pct + "%";
    document.getElementById("progress-pct").innerText = Math.round(pct) + "%";
    if (status) document.getElementById("progress-status").innerText = status;
    if (ticker) document.getElementById("live-ticker").innerText = ticker;
}

function resetTest() {
    document.getElementById("results-panel").classList.add("hidden");
    document.getElementById("progress-panel").classList.add("hidden");
    document.getElementById("chart-container").style.display = "none";
    document.getElementById("action-panel").classList.remove("hidden");
    idleProbes = [];
    loadedProbes = [];
    chartPoints = [];
}

async function startDiagnostic(mode = "quick") {
    activeMode = mode;
    document.getElementById("action-panel").classList.add("hidden");
    document.getElementById("results-panel").classList.add("hidden");
    document.getElementById("progress-panel").classList.remove("hidden");

    if (activeMode === "full") {
        document.getElementById("chart-container").style.display = "block";
        initCanvasChart();
    } else {
        document.getElementById("chart-container").style.display = "none";
    }

    setProgress(5, "Łączenie z serwerem diagnostycznym...", "Otwieranie kanału WebSocket...");

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws/probe`;

    try {
        socket = new WebSocket(wsUrl);
    } catch (e) {
        alert("Błąd połączenia z serwerem WebSocket: " + e);
        resetTest();
        return;
    }

    socket.onopen = async () => {
        try {
            // Phase 1: Idle Latency Probe
            await runIdleProbePhase();

            // Phase 2: Bandwidth & Bufferbloat Probe
            const bandwidthResult = await runBandwidthAndBufferbloatPhase();

            // Phase 3: Evaluation & Verdict
            await submitForEvaluation(bandwidthResult);
        } catch (err) {
            console.error(err);
            alert("Błąd podczas pomiaru: " + err);
            resetTest();
        } finally {
            if (socket && socket.readyState === WebSocket.OPEN) {
                socket.close();
            }
        }
    };

    socket.onerror = (e) => {
        console.error("WS error:", e);
    };
}

function initCanvasChart() {
    const canvas = document.getElementById("live-chart");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    chartPoints = [];
    document.getElementById("live-rtt-now").innerText = "-- ms";
}

function drawLiveChart(maxExpectedProbes) {
    const canvas = document.getElementById("live-chart");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const w = canvas.width;
    const h = canvas.height;

    ctx.clearRect(0, 0, w, h);

    if (chartPoints.length < 2) return;

    // Determine scale (min 60ms, or highest observed spike + 20ms)
    const maxVal = Math.max(60, Math.max(...chartPoints.map(p => p.rtt)) * 1.15);

    // Draw background threshold lines
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);

    // 30ms line (optimal)
    const y30 = h - (30 / maxVal) * (h - 20) - 10;
    if (y30 > 0 && y30 < h) {
        ctx.strokeStyle = "rgba(34, 197, 94, 0.25)";
        ctx.beginPath();
        ctx.moveTo(0, y30);
        ctx.lineTo(w, y30);
        ctx.stroke();
    }

    // 100ms line (jitter warning)
    const y100 = h - (100 / maxVal) * (h - 20) - 10;
    if (y100 > 0 && y100 < h) {
        ctx.strokeStyle = "rgba(239, 68, 68, 0.25)";
        ctx.beginPath();
        ctx.moveTo(0, y100);
        ctx.lineTo(w, y100);
        ctx.stroke();
    }

    ctx.setLineDash([]);

    // Draw filled area under curve
    ctx.beginPath();
    const xStep = w / Math.max(maxExpectedProbes, chartPoints.length);

    chartPoints.forEach((p, idx) => {
        const x = idx * xStep;
        const y = h - (p.rtt / maxVal) * (h - 20) - 10;
        if (idx === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    });

    const lastX = (chartPoints.length - 1) * xStep;
    ctx.lineTo(lastX, h);
    ctx.lineTo(0, h);
    ctx.closePath();

    const gradient = ctx.createLinearGradient(0, 0, 0, h);
    gradient.addColorStop(0, "rgba(249, 115, 22, 0.35)");
    gradient.addColorStop(1, "rgba(249, 115, 22, 0.0)");
    ctx.fillStyle = gradient;
    ctx.fill();

    // Draw main RTT line with conditional colors
    ctx.lineWidth = 2;
    ctx.beginPath();
    chartPoints.forEach((p, idx) => {
        const x = idx * xStep;
        const y = h - (p.rtt / maxVal) * (h - 20) - 10;
        if (idx === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = "#f97316";
    ctx.stroke();

    // Draw spikes as highlight dots
    chartPoints.forEach((p, idx) => {
        if (p.rtt > 80) {
            const x = idx * xStep;
            const y = h - (p.rtt / maxVal) * (h - 20) - 10;
            ctx.fillStyle = "#ef4444";
            ctx.beginPath();
            ctx.arc(x, y, 4, 0, Math.PI * 2);
            ctx.fill();
        }
    });
}

function runIdleProbePhase() {
    return new Promise((resolve) => {
        idleProbes = [];
        let seq = 0;

        const probeCount = activeMode === "full" ? 180 : 30;
        const intervalMs = activeMode === "full" ? 150 : 50; // 180 * 150ms = 27 seconds for full test

        const title = activeMode === "full" 
            ? "Faza 1/2: Pełny test stabilności (30s) — wykrywanie retransmisji i skoków Wi-Fi..." 
            : "Faza 1/2: Szybki pomiar opóźnienia i jittera...";
        setProgress(10, title, "Wysyłanie pakietów ICMP/WS...");




        const interval = setInterval(() => {
            if (seq >= probeCount) {
                clearInterval(interval);
                setTimeout(resolve, 300);
                return;
            }

            const sendTs = performance.now() / 1000.0;
            const payload = { seq: seq, client_ts: sendTs };
            socket.send(JSON.stringify(payload));
            seq++;

            const pct = 10 + Math.round((seq / probeCount) * 55);
            const remainingSecs = Math.max(1, Math.round(((probeCount - seq) * intervalMs) / 1000.0));
            const ticker = activeMode === "full" 
                ? `Próbka ${seq}/${probeCount} (Pozostało ok. ${remainingSecs}s)...` 
                : `Pakiet ${seq}/${probeCount} przesłany`;
            setProgress(pct, null, ticker);
        }, intervalMs);

        socket.onmessage = (event) => {
            const now = performance.now() / 1000.0;
            try {
                const data = JSON.parse(event.data);
                const rtt = Math.max(0.1, (now - data.client_ts) * 1000.0);
                idleProbes.push({
                    seq: data.seq,
                    send_ts: data.client_ts,
                    recv_ts: data.server_ts || now,
                    rtt_ms: rtt
                });

                if (activeMode === "full") {
                    chartPoints.push({ seq: data.seq, rtt: rtt });
                    document.getElementById("live-rtt-now").innerText = `${rtt.toFixed(1)} ms`;
                    drawLiveChart(probeCount);
                }
            } catch (e) {}
        };
    });
}

async function runBandwidthAndBufferbloatPhase() {
    setProgress(70, "Faza 2/2: Test pod obciążeniem i wykrywanie bufferbloatu...", "Pobieranie strumienia pomiarowego (8 MB)...");
    loadedProbes = [];




    // Firing concurrent loaded probes over WebSocket
    let loadedSeq = 0;
    const loadedInterval = setInterval(() => {
        if (loadedSeq >= 10 || !socket || socket.readyState !== WebSocket.OPEN) {
            clearInterval(loadedInterval);
            return;
        }
        const sendTs = performance.now() / 1000.0;
        socket.send(JSON.stringify({ seq: loadedSeq, client_ts: sendTs }));
        loadedSeq++;
    }, 100);

    socket.onmessage = (event) => {
        const now = performance.now() / 1000.0;
        try {
            const data = JSON.parse(event.data);
            const rtt = Math.max(0.1, (now - data.client_ts) * 1000.0);
            loadedProbes.push({
                seq: data.seq,
                send_ts: data.client_ts,
                recv_ts: data.server_ts || now,
                rtt_ms: rtt
            });
        } catch (e) {}
    };

    const startDownload = performance.now();
    let speedMbps = null;

    try {
        const res = await fetch(`/api/bandwidth/chunk?size_mb=8.0&t=${Date.now()}`, { cache: "no-store" });
        const blob = await res.blob();
        const durationSec = (performance.now() - startDownload) / 1000.0;
        const bitsLoaded = blob.size * 8.0;
        speedMbps = (bitsLoaded / durationSec) / (1024 * 1024);
    } catch (e) {
        console.warn("Bandwidth probe failed:", e);
    }


    clearInterval(loadedInterval);
    setProgress(92, "Klasyfikacja SLA i analiza przyczyn...", "Obliczanie parametrów RFC 3550 i ITU-T Y.1541...");
    await new Promise(r => setTimeout(r, 200));


    let loadedAvgRtt = null;
    if (loadedProbes.length > 0) {
        loadedAvgRtt = loadedProbes.reduce((a, b) => a + b.rtt_ms, 0) / loadedProbes.length;
    }

    return {
        speedMbps: speedMbps ? Math.round(speedMbps * 10) / 10 : null,
        loadedAvgRtt: loadedAvgRtt
    };
}

async function submitForEvaluation(bandwidthData) {
    setProgress(98, "Generowanie raportu końcowego...", "Gotowe!");

    const probeCount = activeMode === "full" ? 180 : 30;
    const payload = {
        total_sent: probeCount,
        probes: idleProbes,
        loaded_avg_rtt: bandwidthData.loadedAvgRtt,
        throughput_mbps: bandwidthData.speedMbps
    };

    const resp = await fetch("/api/evaluate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
    });

    const report = await resp.json();
    renderReport(report);
}

function renderReport(report) {
    document.getElementById("progress-panel").classList.add("hidden");
    document.getElementById("results-panel").classList.remove("hidden");

    const m = report.metrics;
    const sla = report.sla;
    const nb = report.netbird;

    // Badge and Verdict
    const badge = document.getElementById("grade-badge");
    badge.innerText = sla.grade;
    badge.className = `grade-badge grade-${sla.grade}`;

    const card = document.getElementById("verdict-card");
    if (sla.status_color === "red") {
        card.style.borderLeftColor = "var(--red)";
    } else if (sla.status_color === "yellow") {
        card.style.borderLeftColor = "var(--yellow)";
    } else {
        card.style.borderLeftColor = "var(--green)";
    }

    document.getElementById("tier-name").innerText = sla.tier_name;
    document.getElementById("verdict-summary").innerText = sla.summary_pl;

    // Recommendations list
    const recList = document.getElementById("rec-list");
    recList.innerHTML = "";
    sla.recommendations_pl.forEach(tip => {
        const li = document.createElement("li");
        li.innerText = tip;
        recList.appendChild(li);
    });

    // Metrics
    document.getElementById("m-avg-rtt").innerText = m.avg_rtt_ms;
    document.getElementById("m-min-rtt").innerText = m.min_rtt_ms;
    document.getElementById("m-max-rtt").innerText = m.max_rtt_ms;

    document.getElementById("m-jitter").innerText = m.rfc3550_jitter_ms;
    document.getElementById("m-std-dev").innerText = m.std_dev_ms;

    document.getElementById("m-loss").innerText = m.packet_loss_pct;
    document.getElementById("m-rec-count").innerText = m.total_received;
    document.getElementById("m-sent-count").innerText = m.total_sent;

    const bDelta = m.bufferbloat_delta_ms !== null ? `+${m.bufferbloat_delta_ms}` : "0.0";
    document.getElementById("m-bufferbloat").innerText = bDelta;

    document.getElementById("m-speed").innerText = m.throughput_mbps !== null ? m.throughput_mbps : "--";

    const nbModeEl = document.getElementById("m-netbird-mode");
    const nbSubEl = document.getElementById("m-netbird-sub");
    if (nb.is_direct_p2p) {
        nbModeEl.innerText = "Direct P2P";
        nbModeEl.style.color = "var(--green)";
        nbSubEl.innerText = "WireGuard Tunnel OK";
    } else if (nb.connection_type && nb.connection_type.toLowerCase() === "relayed") {
        nbModeEl.innerText = "Relayed (TURN)";
        nbModeEl.style.color = "var(--red)";
        nbSubEl.innerText = "Sztuczne opóźnienie";
    } else {
        nbModeEl.innerText = nb.connection_type || "LAN / Direct";
        nbModeEl.style.color = "var(--text-main)";
        nbSubEl.innerText = nb.connected ? "Połączony" : "Bezpośrednie IP";
    }

    // Moonlight / Sunshine Configuration Advisor
    if (report.moonlight_config) {
        renderMoonlightAdvisor(report.moonlight_config);
    }
}

let currentMoonlightConfig = null;
let activeCinematicCodec = "AV1";

function renderMoonlightAdvisor(cfg) {
    currentMoonlightConfig = cfg;
    activeCinematicCodec = "AV1";

    const mlCard = document.getElementById("moonlight-card");
    if (!mlCard) return;
    mlCard.classList.remove("hidden");

    // Badges
    const confBadge = document.getElementById("m-badge-confidence");
    if (confBadge) {
        confBadge.className = `m-badge badge-confidence-${cfg.confidence_level.toLowerCase()}`;
        confBadge.innerText = `WIARYGODNOŚĆ: ${cfg.confidence_level === "HIGH" ? "WYSOKA" : (cfg.confidence_level === "MEDIUM" ? "ŚREDNIA" : "NISKA")}`;
    }

    const fecBadge = document.getElementById("m-badge-fec");
    if (fecBadge) {
        fecBadge.innerText = `FEC: ${cfg.recommended_fec_percentage}%`;
    }

    const pacingBadge = document.getElementById("m-badge-pacing");
    if (pacingBadge) {
        pacingBadge.innerText = `PACING: ${cfg.frame_pacing ? "WŁ (SMOOTH)" : "WYŁ"}`;
        pacingBadge.style.borderColor = cfg.frame_pacing ? "var(--yellow)" : "var(--border)";
    }

    // Hardware Note & Reasoning
    const hwNote = document.getElementById("preset-hardware-note");
    if (hwNote) hwNote.innerText = cfg.hardware_note;

    const reasoning = document.getElementById("preset-reasoning");
    if (reasoning) reasoning.innerText = cfg.reasoning_pl;

    // Render Cinematic & Competitive
    updateCinematicDisplay();

    // Competitive Mode tab setup
    const compTabBtn = document.getElementById("tab-btn-competitive");
    const compGrid = document.getElementById("comp-grid");
    const compNote = document.getElementById("comp-status-note");

    if (cfg.competitive_profile) {
        if (compTabBtn) compTabBtn.style.display = "block";
        if (compGrid) compGrid.classList.remove("hidden");
        document.getElementById("preset-comp-res").innerText = cfg.competitive_profile.resolution;
        document.getElementById("preset-comp-bitrate").innerText = cfg.competitive_profile.target_bitrate_mbps;
        document.getElementById("preset-comp-codec").innerText = `${cfg.competitive_profile.codec} (${cfg.competitive_profile.safe_bitrate_range})`;
        if (compNote) {
            compNote.innerText = "Tryb e-sportowy (120 FPS) aktywny. Twoje opóźnienie RTT pozwala na responsywną rozgrywkę z wysokim odświeżaniem.";
            compNote.style.borderLeftColor = "var(--green)";
        }
    } else {
        if (compGrid) compGrid.classList.add("hidden");
        if (compNote) {
            compNote.innerText = "Niedostępny (RTT > 30 ms). Opóźnienie łącza jest zbyt wysokie na sensowną rozgrywkę w 120 FPS.";
            compNote.style.borderLeftColor = "var(--yellow)";
        }
    }
}

function updateCinematicDisplay() {
    if (!currentMoonlightConfig) return;
    const cfg = currentMoonlightConfig;

    let profile = cfg.cinematic_profile;
    if (activeCinematicCodec === "HEVC" && cfg.fallback_hevc) {
        profile = cfg.fallback_hevc;
    } else if (activeCinematicCodec === "H.264" && cfg.fallback_h264) {
        profile = cfg.fallback_h264;
    }

    document.getElementById("preset-cinematic-res").innerText = profile.resolution;
    document.getElementById("preset-cinematic-bitrate").innerText = profile.target_bitrate_mbps;
    document.getElementById("preset-cinematic-range").innerText = profile.safe_bitrate_range;

    // Toggle button active classes
    ["av1", "hevc", "h264"].forEach(c => {
        const btn = document.getElementById(`codec-btn-${c}`);
        if (btn) {
            btn.classList.toggle("active", c.toUpperCase() === activeCinematicCodec.toUpperCase());
        }
    });
}

window.selectCinematicCodec = function(codec) {
    activeCinematicCodec = codec;
    updateCinematicDisplay();
};

window.switchMoonlightTab = function(tabName) {
    const isCinematic = (tabName === "cinematic");
    document.getElementById("tab-btn-cinematic").classList.toggle("active", isCinematic);
    document.getElementById("tab-btn-competitive").classList.toggle("active", !isCinematic);

    document.getElementById("tab-content-cinematic").classList.toggle("hidden", !isCinematic);
    document.getElementById("tab-content-competitive").classList.toggle("hidden", isCinematic);
};

