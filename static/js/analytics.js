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

        const positionsMap = {};

        candidates.forEach(c => {
            const regSt = (c.registration_status || c.status || "").toLowerCase();
            const resSt = (c.resume_status || "").toLowerCase();

            if (regSt.includes("registered") || regSt.includes("processed") || regSt.includes("new")) {
                registered++;
            }
            if (resSt.includes("uploaded") || (c.resume && c.resume.length > 0)) {
                resumesUploaded++;
            } else {
                resumesPending++;
            }
            if (regSt.includes("processed") || resSt.includes("uploaded")) {
                processed++;
            }
            if (regSt.includes("fail") || resSt.includes("fail")) {
                failed++;
            }

            const pos = c.position || "Unspecified";
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

        // Render Charts
        renderStatusChart(registered, resumesPending, processed, failed);
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

        if (statusChart) statusChart.destroy();
        statusChart = new Chart(ctx, {
            type: "pie",
            data: {
                labels: ["Registered", "Resume Pending", "Processed", "Failed"],
                datasets: [{
                    data: [registered || 1, pending, processed, failed],
                    backgroundColor: ["#1d4ed8", "#2563eb", "#3b82f6", "#60a5fa"],
                    borderWidth: 2,
                    borderColor: "#ffffff"
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false
            }
        });
    }

    function renderResumeChart(uploaded, pending, failed) {
        const ctx = document.getElementById("resumeStatusChart");
        if (!ctx || typeof Chart === "undefined") return;

        if (resumeChart) resumeChart.destroy();
        resumeChart = new Chart(ctx, {
            type: "doughnut",
            data: {
                labels: ["Uploaded", "Pending", "Failed"],
                datasets: [{
                    data: [uploaded || 1, pending, failed],
                    backgroundColor: ["#1d4ed8", "#2563eb", "#60a5fa"],
                    borderWidth: 2,
                    borderColor: "#ffffff"
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false
            }
        });
    }

    function renderPositionChart(positionsMap) {
        const ctx = document.getElementById("positionsChart");
        if (!ctx || typeof Chart === "undefined") return;

        const labels = Object.keys(positionsMap).length ? Object.keys(positionsMap) : ["Python Developer", "Data Analyst", "DevOps Engineer"];
        const dataVals = Object.keys(positionsMap).length ? Object.values(positionsMap) : [5, 3, 2];

        if (positionChart) positionChart.destroy();
        positionChart = new Chart(ctx, {
            type: "bar",
            data: {
                labels: labels,
                datasets: [{
                    label: "Candidates",
                    data: dataVals,
                    backgroundColor: "#2563eb",
                    borderRadius: 8
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: { beginAtZero: true, ticks: { precision: 0 } }
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
