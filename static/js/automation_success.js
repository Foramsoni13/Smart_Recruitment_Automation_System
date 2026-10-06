/**
 * SMART RECRUITMENT AUTOMATION SYSTEM - AUTOMATION SUCCESS JAVASCRIPT
 */

document.addEventListener("DOMContentLoaded", function () {
    let candidatesData = [];

    const searchInput = document.getElementById("candidateSearchInput");
    const resumeFilter = document.getElementById("resumeFilter");
    const tableBody = document.getElementById("candidatesTableBody");
    const emptyState = document.getElementById("emptyState");

    // Modal Elements
    const candidateModal = document.getElementById("candidateModal");
    const modalCloseBtn = document.getElementById("modalCloseBtn");
    const modalFooterCloseBtn = document.getElementById("modalFooterCloseBtn");

    if (searchInput) {
        searchInput.addEventListener("input", filterAndRender);
    }

    if (resumeFilter) {
        resumeFilter.addEventListener("change", filterAndRender);
    }

    if (modalCloseBtn && candidateModal) {
        modalCloseBtn.addEventListener("click", () => candidateModal.classList.add("hidden"));
    }

    if (modalFooterCloseBtn && candidateModal) {
        modalFooterCloseBtn.addEventListener("click", () => candidateModal.classList.add("hidden"));
    }

    if (candidateModal) {
        candidateModal.addEventListener("click", function (e) {
            if (e.target === candidateModal) {
                candidateModal.classList.add("hidden");
            }
        });
    }

    // Fetch Candidates
    fetchCandidates();

    function fetchCandidates() {
        const urlParams = new URLSearchParams(window.location.search);
        const jobId = urlParams.get("job_id") || localStorage.getItem("activeJobId") || "";
        const uploadId = urlParams.get("upload_id") || localStorage.getItem("activeUploadId") || "";

        let apiUrl = "/api/candidates?all=true";
        if (jobId) {
            apiUrl += `&job_id=${encodeURIComponent(jobId)}`;
        } else if (uploadId) {
            apiUrl += `&upload_id=${encodeURIComponent(uploadId)}`;
        }

        fetch(apiUrl)
            .then(res => res.json())
            .then(data => {
                candidatesData = data.candidates || (Array.isArray(data) ? data : []);
                filterAndRender();
            })
            .catch(err => {
                console.error("Error fetching automation results:", err);
                if (tableBody) {
                    tableBody.innerHTML = `<tr><td colspan="9" class="text-center text-danger p-4">Failed to load automation results. Please try refreshing.</td></tr>`;
                }
            });
    }

    function filterAndRender() {
        if (!tableBody) return;

        const q = searchInput ? searchInput.value.toLowerCase().trim() : "";
        const cleanQ = q.replace(/^#/, "");
        const filterVal = resumeFilter ? resumeFilter.value : "all";

        const filtered = candidatesData.filter(c => {
            const idStr = String(c.id || "");
            const nameStr = (c.name || "").toLowerCase();
            const emailStr = (c.email || "").toLowerCase();
            const phoneStr = (c.phone || "").toLowerCase();
            const posStr = (c.position || c.job_title || "").toLowerCase();
            const regStatus = (c.registration_status || c.status || "").toLowerCase();
            const resStatus = (c.resume_status || (c.resume ? "uploaded" : "")).toLowerCase();
            const jobIdStr = (c.job_id || c.upload_id || "").toLowerCase();

            const matchesQuery = !q ||
                nameStr.includes(q) ||
                emailStr.includes(q) ||
                phoneStr.includes(q) ||
                posStr.includes(q) ||
                regStatus.includes(q) ||
                resStatus.includes(q) ||
                jobIdStr.includes(q) ||
                idStr === cleanQ ||
                `#${idStr}` === q ||
                (cleanQ.length > 0 && idStr.includes(cleanQ));

            let matchesResume = true;
            if (filterVal === "Uploaded") {
                matchesResume = resStatus.includes("uploaded") || Boolean(c.resume);
            } else if (filterVal === "Not Uploaded") {
                matchesResume = resStatus.includes("not uploaded") || (!c.resume && !resStatus.includes("failed"));
            } else if (filterVal === "Upload Failed") {
                matchesResume = resStatus.includes("failed") || resStatus.includes("error");
            }

            return matchesQuery && matchesResume;
        });

        if (filtered.length === 0) {
            tableBody.innerHTML = "";
            if (emptyState) emptyState.classList.remove("hidden");
            return;
        }

        if (emptyState) emptyState.classList.add("hidden");

        tableBody.innerHTML = filtered.map(c => {
            const resStatusHtml = c.resume || (c.resume_status && c.resume_status.toLowerCase().includes("uploaded"))
                ? `<span class="badge bg-success-subtle text-success border border-success-subtle px-2 py-1"><i class="fa-solid fa-check me-1"></i> Uploaded</span>`
                : `<span class="badge bg-secondary-subtle text-secondary border px-2 py-1"><i class="fa-solid fa-clock me-1"></i> ${escapeHtml(c.resume_status || 'Not Uploaded')}</span>`;

            const regStatusHtml = `<span class="badge bg-primary-subtle text-primary border border-primary-subtle px-2 py-1">${escapeHtml(c.registration_status || c.status || 'Registered')}</span>`;

            return `
                <tr>
                    <td class="fw-bold">#${c.id}</td>
                    <td>
                        <div class="fw-semibold text-dark">${escapeHtml(c.name || 'Unknown')}</div>
                    </td>
                    <td>${escapeHtml(c.email || '-')}</td>
                    <td>${escapeHtml(c.phone || '-')}</td>
                    <td>${escapeHtml(c.position || c.job_title || '-')}</td>
                    <td>${regStatusHtml}</td>
                    <td>${resStatusHtml}</td>
                    <td><small class="text-muted">${escapeHtml(c.processed_at_formatted || c.created_at || '-')}</small></td>
                    <td class="text-end">
                        <button type="button" class="btn btn-sm btn-outline-primary view-details-btn" data-id="${c.id}">
                            <i class="fa-solid fa-eye me-1"></i> View Details
                        </button>
                    </td>
                </tr>
            `;
        }).join("");

        tableBody.querySelectorAll(".view-details-btn").forEach(btn => {
            btn.addEventListener("click", () => openModal(btn.getAttribute("data-id")));
        });
    }

    function openModal(candidateId) {
        const candidate = candidatesData.find(c => String(c.id) === String(candidateId));
        if (!candidate || !candidateModal) return;

        setText("modalName", candidate.name || "Candidate Details");
        setText("modalPosition", candidate.position || candidate.job_title || "Applicant");
        setText("modalCandidateId", `#${candidate.id}`);
        setText("modalEmail", candidate.email || "-");
        setText("modalPhone", candidate.phone || "-");
        setText("modalAppliedPosition", candidate.position || candidate.job_title || "-");
        setText("modalRegistrationStatus", candidate.registration_status || candidate.status || "Registered");
        setText("modalResumeStatus", candidate.resume_status || (candidate.resume ? "Uploaded" : "Not Uploaded"));
        setText("modalResumeFilename", candidate.resume_filename || candidate.resume || "None");
        setText("modalProcessedTime", candidate.processed_at_formatted || candidate.created_at || "-");

        const modalResumeAction = document.getElementById("modalResumeAction");
        if (modalResumeAction) {
            if (candidate.resume_url) {
                modalResumeAction.innerHTML = `
                    <a href="${candidate.resume_url}" target="_blank" class="btn btn-primary">
                        <i class="fa-solid fa-file-pdf me-1"></i> View Resume PDF
                    </a>
                `;
            } else {
                modalResumeAction.innerHTML = `
                    <span class="badge bg-secondary p-2">Resume File Not Uploaded</span>
                `;
            }
        }

        candidateModal.classList.remove("hidden");
    }

    function setText(id, text) {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    }

    function escapeHtml(str) {
        if (!str) return "";
        return String(str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }
});
