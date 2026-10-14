/**
 * SMART RECRUITMENT AUTOMATION SYSTEM - HR ANALYTICS DASHBOARD JS
 */

document.addEventListener("DOMContentLoaded", function () {
    let statusChart = null;
    let resumeChart = null;
    let positionChart = null;

    const refreshBtn = document.getElementById("refreshAnalyticsBtn");
    const retryBtn = document.getElementById("retryAnalyticsBtn");
    const errorBanner = document.getElementById("analyticsErrorBanner");

    if (refreshBtn) {
        refreshBtn.addEventListener("click", function () {
            const icon = refreshBtn.querySelector("i");
            if (icon) icon.classList.add("fa-spin");
            fetchAnalyticsData().finally(() => {
                if (icon) icon.classList.remove("fa-spin");
            });
        });
    }

    if (retryBtn) {
        retryBtn.addEventListener("click", function () {
            if (errorBanner) errorBanner.classList.add("hidden");
            fetchAnalyticsData();
        });
    }

    // Initial Load
    fetchAnalyticsData();

    function fetchAnalyticsData() {
        return fetch("/api/candidates")
            .then(res => {
                if (!res.ok) throw new Error("Network response error");
                return res.json();
            })
            .then(data => {
                if (errorBanner) errorBanner.classList.add("hidden");
                const candidates = data.candidates || data || [];
                renderAnalytics(candidates);
            })
            .catch(err => {
                console.warn("Notice fetching analytics from /api/candidates, retrying /api/analytics:", err);
                return fetch("/api/analytics")
                    .then(res => res.json())
                    .then(data => {
                        if (errorBanner) errorBanner.classList.add("hidden");
                        const candidates = data.candidates || [];
                        renderAnalytics(candidates);
                    })
                    .catch(e => {
                        console.error("Analytics fetch error:", e);
                        if (errorBanner) errorBanner.classList.remove("hidden");
                    });
            });
    }

    function renderAnalytics(candidates) {
        const total = candidates.length;
        let registered = 0;
        let resumesUploaded = 0;
        let resumesPending = 0;
        let processed = 0;
        let failed = 0;

        let statusRegistered = 0;
        let statusPending = 0;
        let statusProcessed = 0;
        let statusFailed = 0;

        const positionsMap = {};

        candidates.forEach(c => {
            const regSt = (c.registration_status || "").toLowerCase();
            const st = (c.status || "").toLowerCase();
            const autoSt = (c.automation_status || "").toLowerCase();
            const resSt = (c.resume_status || "").toLowerCase();

            // Resume metric
            if (resSt.includes("uploaded") || (c.resume && c.resume.length > 0)) {
                resumesUploaded++;
            } else {
                resumesPending++;
            }

            // High-level KPI counts
            if (regSt.includes("registered") || st.includes("registered") || regSt.includes("processed") || st.includes("processed") || regSt.includes("new") || st.includes("new") || !regSt) {
                registered++;
            }
            if (st.includes("process") || autoSt.includes("process") || regSt.includes("process")) {
                processed++;
            }
            if (st.includes("fail") || regSt.includes("fail") || autoSt.includes("fail") || resSt.includes("fail")) {
                failed++;
            }

            // Mutually exclusive distribution for Status Chart:
            if (st.includes("fail") || regSt.includes("fail") || autoSt.includes("fail")) {
                statusFailed++;
            } else if (st.includes("process") || autoSt.includes("process") || regSt.includes("process")) {
                statusProcessed++;
            } else if (st.includes("pend") || regSt.includes("pend") || autoSt.includes("pend") || st.includes("new")) {
                statusPending++;
            } else {
                statusRegistered++;
            }

            const pos = (c.position && c.position.trim()) ? c.position.trim() : "Software Engineer";
            positionsMap[pos] = (positionsMap[pos] || 0) + 1;
        });

        // Update KPIs
        setText("kpiTotal", total);
        setText("kpiRegistered", registered);
        setText("kpiRegisteredPct", total > 0 ? `${Math.round((registered / total) * 100)}% of total` : "0% of total");
        setText("kpiResumesUploaded", resumesUploaded);
        setText("kpiUploadedPct", total > 0 ? `${Math.round((resumesUploaded / total) * 100)}% verified` : "0% verified");
        setText("kpiResumesPending", resumesPending);
        setText("kpiProcessed", processed);
        setText("kpiFailed", failed);

        // Render Pipeline Funnel
        renderPipeline(total, registered, resumesUploaded, processed);

        // Render Charts with balanced data
        renderStatusChart(statusRegistered, statusPending, statusProcessed, statusFailed);
        renderResumeChart(resumesUploaded, resumesPending, failed);
        renderPositionChart(positionsMap);

        // Render Recent Table & Activity
        renderRecentTable(candidates.slice(0, 5));
        renderActivityTimeline(candidates.slice(0, 4));
    }

    function setText(id, text) {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    }

    function renderPipeline(total, registered, uploaded, processed) {
        const funnel = document.getElementById("pipelineFunnel");
        if (!funnel) return;

        funnel.innerHTML = `
            <div class="pipeline-stage">
                <h4>1. Total Sourced</h4>
                <div class="stage-count">${total}</div>
            </div>
            <div class="pipeline-stage">
                <h4>2. Registered</h4>
                <div class="stage-count">${registered}</div>
            </div>
            <div class="pipeline-stage">
                <h4>3. Resume Linked</h4>
                <div class="stage-count">${uploaded}</div>
            </div>
            <div class="pipeline-stage">
                <h4>4. Processed</h4>
                <div class="stage-count">${processed}</div>
            </div>
        `;
    }

    function renderStatusChart(registered, pending, processed, failed) {
        const ctx = document.getElementById("candidateStatusChart");
        if (!ctx || typeof Chart === "undefined") return;

        const total = (registered || 0) + (pending || 0) + (processed || 0) + (failed || 0);
        const labels = ["Registered", "Pending", "Processed", "Failed"];
        const dataVals = total > 0
            ? [registered, pending, processed, failed]
            : [1, 0, 0, 0];
        const bgColors = ["#2563eb", "#60a5fa", "#1e40af", "#94a3b8"];

        if (statusChart) statusChart.destroy();
        statusChart = new Chart(ctx, {
            type: "doughnut",
            data: {
                labels: labels,
                datasets: [{
                    data: dataVals,
                    backgroundColor: bgColors,
                    borderWidth: 3,
                    borderColor: "#ffffff",
                    hoverOffset: 6
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: "62%",
                layout: {
                    padding: { top: 10, bottom: 10, left: 10, right: 10 }
                },
                plugins: {
                    legend: {
                        position: "bottom",
                        labels: {
                            padding: 16,
                            usePointStyle: true,
                            pointStyle: "circle",
                            boxWidth: 10,
                            font: {
                                family: "'Plus Jakarta Sans', sans-serif",
                                size: 12,
                                weight: "600"
                            },
                            color: "#334155"
                        }
                    },
                    tooltip: {
                        backgroundColor: "#0f172a",
                        titleFont: { family: "'Plus Jakarta Sans', sans-serif", size: 13, weight: "700" },
                        bodyFont: { family: "'Plus Jakarta Sans', sans-serif", size: 12 },
                        padding: 12,
                        cornerRadius: 10,
                        callbacks: {
                            label: function(context) {
                                const sum = context.dataset.data.reduce((a, b) => a + b, 0);
                                const val = context.parsed;
                                const pct = sum > 0 ? Math.round((val / sum) * 100) : 0;
                                return ` ${context.label}: ${val} (${pct}%)`;
                            }
                        }
                    }
                }
            }
        });
    }

    function renderResumeChart(uploaded, pending, failed) {
        const ctx = document.getElementById("resumeStatusChart");
        if (!ctx || typeof Chart === "undefined") return;

        const total = (uploaded || 0) + (pending || 0) + (failed || 0);
        const labels = ["Uploaded", "Pending", "Failed"];
        const dataVals = total > 0
            ? [uploaded, pending, failed]
            : [1, 0, 0];
        const bgColors = ["#2563eb", "#60a5fa", "#94a3b8"];

        if (resumeChart) resumeChart.destroy();
        resumeChart = new Chart(ctx, {
            type: "doughnut",
            data: {
                labels: labels,
                datasets: [{
                    data: dataVals,
                    backgroundColor: bgColors,
                    borderWidth: 3,
                    borderColor: "#ffffff",
                    hoverOffset: 6
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: "62%",
                layout: {
                    padding: { top: 10, bottom: 10, left: 10, right: 10 }
                },
                plugins: {
                    legend: {
                        position: "bottom",
                        labels: {
                            padding: 16,
                            usePointStyle: true,
                            pointStyle: "circle",
                            boxWidth: 10,
                            font: {
                                family: "'Plus Jakarta Sans', sans-serif",
                                size: 12,
                                weight: "600"
                            },
                            color: "#334155"
                        }
                    },
                    tooltip: {
                        backgroundColor: "#0f172a",
                        titleFont: { family: "'Plus Jakarta Sans', sans-serif", size: 13, weight: "700" },
                        bodyFont: { family: "'Plus Jakarta Sans', sans-serif", size: 12 },
                        padding: 12,
                        cornerRadius: 10,
                        callbacks: {
                            label: function(context) {
                                const sum = context.dataset.data.reduce((a, b) => a + b, 0);
                                const val = context.parsed;
                                const pct = sum > 0 ? Math.round((val / sum) * 100) : 0;
                                return ` ${context.label}: ${val} (${pct}%)`;
                            }
                        }
                    }
                }
            }
        });
    }

    function renderPositionChart(positionsMap) {
        const ctx = document.getElementById("positionsChart");
        if (!ctx || typeof Chart === "undefined") return;

        const rawLabels = Object.keys(positionsMap).filter(k => k && k.trim());
        const labels = rawLabels.length ? rawLabels : ["Software Engineer"];
        const dataVals = rawLabels.length ? rawLabels.map(k => positionsMap[k]) : [1];

        const maxVal = Math.max(...dataVals, 1);
        const yMax = maxVal < 5 ? maxVal + 1 : Math.ceil(maxVal * 1.25);

        if (positionChart) positionChart.destroy();
        positionChart = new Chart(ctx, {
            type: "bar",
            data: {
                labels: labels,
                datasets: [{
                    label: "Candidates",
                    data: dataVals,
                    backgroundColor: "#2563eb",
                    hoverBackgroundColor: "#1d4ed8",
                    borderRadius: 8,
                    borderSkipped: false,
                    maxBarThickness: 52,
                    barPercentage: 0.6,
                    categoryPercentage: labels.length === 1 ? 0.35 : 0.7
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                layout: {
                    padding: { top: 20, bottom: 8, left: 15, right: 15 }
                },
                plugins: {
                    legend: {
                        display: false
                    },
                    tooltip: {
                        backgroundColor: "#0f172a",
                        titleFont: { family: "'Plus Jakarta Sans', sans-serif", size: 13, weight: "700" },
                        bodyFont: { family: "'Plus Jakarta Sans', sans-serif", size: 12 },
                        padding: 12,
                        cornerRadius: 10,
                        displayColors: false,
                        callbacks: {
                            label: function(context) {
                                const val = context.parsed.y;
                                return `${val} Candidate${val === 1 ? '' : 's'}`;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { display: false, drawBorder: false },
                        ticks: {
                            color: "#0f172a",
                            font: {
                                family: "'Plus Jakarta Sans', sans-serif",
                                size: 12,
                                weight: "700"
                            },
                            padding: 8
                        }
                    },
                    y: {
                        beginAtZero: true,
                        suggestedMax: yMax,
                        grid: {
                            color: "#f1f5f9",
                            drawBorder: false
                        },
                        ticks: {
                            precision: 0,
                            stepSize: 1,
                            color: "#64748b",
                            font: {
                                family: "'Plus Jakarta Sans', sans-serif",
                                size: 11,
                                weight: "600"
                            },
                            padding: 8
                        }
                    }
                }
            }
        });
    }

    function renderRecentTable(recentCandidates) {
        const tbody = document.getElementById("recentCandidatesBody");
        if (!tbody) return;

        if (!recentCandidates.length) {
            tbody.innerHTML = `<tr><td colspan="4" class="text-center py-3 text-muted">No candidates found in database.</td></tr>`;
            return;
        }

        tbody.innerHTML = recentCandidates.map(c => `
            <tr>
                <td><strong>${escapeHtml(c.name)}</strong></td>
                <td>${escapeHtml(c.position)}</td>
                <td><span class="badge" style="background-color: #eff6ff; color: #1d4ed8; border: 1.5px solid #bfdbfe;"><i class="fa-solid fa-check me-1"></i> ${escapeHtml(c.registration_status || c.status || 'Registered')}</span></td>
                <td><span class="badge" style="background-color: #eff6ff; color: #2563eb; border: 1.5px solid #bfdbfe;"><i class="fa-solid fa-file me-1"></i> ${c.resume ? 'Uploaded' : (c.resume_status || 'Pending')}</span></td>
            </tr>
        `).join("");
    }

    function renderActivityTimeline(recent) {
        const timeline = document.getElementById("activityTimeline");
        if (!timeline) return;

        if (!recent.length) {
            timeline.innerHTML = `<div class="text-muted p-2">No recent system activity recorded.</div>`;
            return;
        }

        timeline.innerHTML = recent.map(c => `
            <div style="padding: 0.6rem 0; border-bottom: 1px solid #f1f5f9; display: flex; align-items: center; justify-content: space-between;">
                <div>
                    <strong>${escapeHtml(c.name)}</strong> registered for <em>${escapeHtml(c.position)}</em>
                </div>
                <small style="color: #64748b;">${c.created_at ? new Date(c.created_at).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}) : 'Recently'}</small>
            </div>
        `).join("");
    }

    function escapeHtml(str) {
        if (!str) return "";
        return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }
});
