/**
 * SMART RECRUITMENT AUTOMATION SYSTEM - CANDIDATES PAGE JAVASCRIPT
 */

document.addEventListener("DOMContentLoaded", function () {
    let candidatesData = [];
    let currentFilter = "all";
    let activeJobId = null;
    let activeUploadId = null;
    let pollTimer = null;
    let selectedCandidateId = null;
    let selectedCandidateIds = new Set();
    let isBatchDeleting = false;

    // Core Controls & File Pickers
    const candidateFile = document.getElementById("candidateFile");
    const resumeFiles = document.getElementById("resumeFiles");
    const excelFileName = document.getElementById("excelFileName");
    const resumeFileName = document.getElementById("resumeFileName");
    const startAutomationBtn = document.getElementById("startAutomationButton");
    const cancelAutomationBtn = document.getElementById("cancelAutomationButton");
    const candidatesBody = document.getElementById("candidateTableBody") || document.querySelector(".candidate-table tbody");
    const refreshBtn = document.getElementById("refreshCandidates");
    const searchInput = document.getElementById("candidateSearch");
    const statusFilterSelect = document.getElementById("statusFilter");

    // Modal elements (matched to candidates.html IDs)
    const candidateModal = document.getElementById("candidateModal");
    const closeCandidateModalBtn = document.getElementById("closeCandidateModal") || document.getElementById("closeModal");
    const deleteModal = document.getElementById("deleteModal") || document.getElementById("deleteConfirmModal");
    const cancelDeleteBtn = document.getElementById("cancelDelete");
    const confirmDeleteBtn = document.getElementById("confirmDelete");

    // Error card elements
    const retryAutomationBtn = document.getElementById("retryAutomationBtn");
    const viewErrorLogsBtn = document.getElementById("viewErrorLogsBtn");
    const clearLogsBtn = document.getElementById("clearLogsBtn");

    // File pickers feedback
    if (candidateFile) {
        candidateFile.addEventListener("change", function () {
            if (this.files && this.files.length > 0) {
                if (excelFileName) excelFileName.textContent = this.files[0].name;
            }
        });
    }

    if (resumeFiles) {
        resumeFiles.addEventListener("change", function () {
            if (this.files && this.files.length > 0) {
                if (resumeFileName) resumeFileName.textContent = `${this.files.length} resume(s) selected`;
            }
        });
    }

    // Filter Pills Listener
    document.querySelectorAll(".btn-filter").forEach(btn => {
        btn.addEventListener("click", function() {
            document.querySelectorAll(".btn-filter").forEach(b => b.classList.remove("active"));
            this.classList.add("active");
            currentFilter = this.getAttribute("data-filter").toLowerCase().trim();
            if (statusFilterSelect) statusFilterSelect.value = currentFilter;
            filterAndRenderCandidates();
        });
    });

    if (statusFilterSelect) {
        statusFilterSelect.addEventListener("change", function () {
            currentFilter = this.value.toLowerCase().trim();
            document.querySelectorAll(".btn-filter").forEach(b => {
                if (b.getAttribute("data-filter").toLowerCase() === currentFilter) {
                    b.classList.add("active");
                } else {
                    b.classList.remove("active");
                }
            });
            filterAndRenderCandidates();
        });
    }

    // Refresh & Search & Filters
    if (refreshBtn) {
        refreshBtn.addEventListener("click", fetchCandidates);
    }

    if (searchInput) {
        searchInput.addEventListener("input", filterAndRenderCandidates);
    }

    // Automation Buttons
    if (startAutomationBtn) {
        startAutomationBtn.addEventListener("click", startAutomationJob);
    }

    if (cancelAutomationBtn) {
        cancelAutomationBtn.addEventListener("click", cancelAutomationJob);
    }

    if (retryAutomationBtn) {
        retryAutomationBtn.addEventListener("click", function() {
            const errCard = document.getElementById("automationErrorCard");
            if (errCard) errCard.classList.add("hidden");
            startAutomationJob();
        });
    }

    if (viewErrorLogsBtn) {
        viewErrorLogsBtn.addEventListener("click", function() {
            const progressSec = document.getElementById("automationProgress");
            if (progressSec) {
                progressSec.classList.remove("hidden");
                progressSec.scrollIntoView({ behavior: "smooth" });
            }
        });
    }

    if (clearLogsBtn) {
        clearLogsBtn.addEventListener("click", function() {
            const logBox = document.getElementById("automationLog");
            if (logBox) logBox.innerHTML = '<div class="text-muted">Terminal view cleared.</div>';
        });
    }

    // Modal Handlers
    if (closeCandidateModalBtn && candidateModal) {
        closeCandidateModalBtn.addEventListener("click", () => candidateModal.classList.add("hidden"));
    }

    const modalOverlay = candidateModal ? candidateModal.querySelector(".candidate-modal-overlay") : null;
    if (modalOverlay && candidateModal) {
        modalOverlay.addEventListener("click", () => candidateModal.classList.add("hidden"));
    }

    if (cancelDeleteBtn && deleteModal) {
        cancelDeleteBtn.addEventListener("click", () => deleteModal.classList.add("hidden"));
    }

    const deleteOverlay = deleteModal ? deleteModal.querySelector(".candidate-modal-overlay") : null;
    if (deleteOverlay && deleteModal) {
        deleteOverlay.addEventListener("click", () => deleteModal.classList.add("hidden"));
    }

    if (confirmDeleteBtn) {
        confirmDeleteBtn.addEventListener("click", executeDeleteCandidate);
    }
    enforceBlueDeleteModal();

    // Initial load
    fetchCandidates();
    const loadCandidates = fetchCandidates;

    // Fetch Candidates API
    function fetchCandidates() {
        let url = "/api/candidates?all=true";

        fetch(url)
            .then(res => {
                if (!res.ok) {
                    throw new Error(`HTTP ${res.status}: ${res.statusText}`);
                }
                return res.json();
            })
            .then(data => {
                candidatesData = data.candidates || (Array.isArray(data) ? data : []);
                updateStats(candidatesData);
                filterAndRenderCandidates();
            })
            .catch(err => {
                console.error("Error loading candidates:", err);
                if (candidatesBody) {
                    candidatesBody.innerHTML = `<tr><td colspan="11" style="text-align: center; color: #ef4444; padding: 2rem;"><i class="fa-solid fa-triangle-exclamation me-2"></i>Error loading candidates database. Please refresh.</td></tr>`;
                }
            });
    }

    function getStatusBadgeClass(status) {
        if (!status) return "badge-pending";
        const st = String(status).toLowerCase();
        if (st.includes("register") || st.includes("success") || st.includes("complete") || st.includes("pass")) {
            return "badge-registered";
        }
        if (st.includes("fail") || st.includes("error")) {
            return "badge-failed";
        }
        return "badge-pending";
    }

    function openCandidateModal(candidateId) {
        if (!candidateModal) return;
        const c = candidatesData.find(item => String(item.id) === String(candidateId));
        if (!c) return;

        setText("modalCandidateName", c.name || "Candidate");
        setText("modalCandidateEmail", c.email || "-");
        setText("modalCandidatePhone", c.phone || "-");
        setText("modalCandidatePosition", c.position || c.job_title || "-");
        setText("modalCandidateStatus", c.registration_status || c.status || "Registered");
        setText("modalCandidateResume", c.resume ? "Uploaded" : (c.resume_status || "Not Uploaded"));
        setText("modalCandidateExam", c.exam_name || "No Exam Assigned");

        const modalScore = document.getElementById("modalCandidateScore");
        if (modalScore) modalScore.textContent = c.score_formatted || "-";

        const modalResult = document.getElementById("modalCandidateResult");
        if (modalResult) modalResult.textContent = c.result_status || "-";

        candidateModal.classList.remove("hidden");
    }

    function updateStats(list) {
        const total = list.length;
        let excelCount = 0;
        let resumeCount = 0;

        list.forEach(c => {
            const regSt = (c.registration_status || c.status || "").toLowerCase();
            const resSt = (c.resume_status || "").toLowerCase();
            if (regSt.includes("registered") || regSt.includes("processed") || regSt.includes("new")) excelCount++;
            if (resSt.includes("uploaded") || (c.resume && c.resume.length > 0)) resumeCount++;
        });

        setText("totalCandidates", total);
        setText("excelCandidates", excelCount || total);
        setText("resumeCandidates", resumeCount);
        setText("candidateCount", total);
    }

    function filterAndRenderCandidates() {
        if (!candidatesBody) return;

        const q = searchInput ? searchInput.value.toLowerCase().trim() : "";
        const cleanQ = q.replace(/^#/, "");

        let filtered = candidatesData.filter(c => {
            const idStr = String(c.id || "");
            const nameStr = (c.name || "").toLowerCase();
            const emailStr = (c.email || "").toLowerCase();
            const phoneStr = (c.phone || "").toLowerCase();
            const posStr = (c.position || c.job_title || "").toLowerCase();
            const examName = (c.exam_name || "").toLowerCase();
            const examStatus = (c.exam_status || "").toLowerCase();
            const resultStatus = (c.result_status || "").toLowerCase();
            const regStatus = (c.registration_status || c.status || "").toLowerCase();
            const resStatus = (c.resume_status || (c.resume ? "uploaded" : "")).toLowerCase();
            const scoreStr = (c.score_formatted || "").toLowerCase();
            const jobIdStr = (c.job_id || c.upload_id || "").toLowerCase();

            const matchesQuery = !q ||
                nameStr.includes(q) ||
                emailStr.includes(q) ||
                phoneStr.includes(q) ||
                posStr.includes(q) ||
                examName.includes(q) ||
                examStatus.includes(q) ||
                resultStatus.includes(q) ||
                regStatus.includes(q) ||
                resStatus.includes(q) ||
                scoreStr.includes(q) ||
                jobIdStr.includes(q) ||
                idStr === cleanQ ||
                `#${idStr}` === q ||
                (cleanQ.length > 0 && idStr.includes(cleanQ));

            let matchesFilter = true;
            if (currentFilter === "all" || currentFilter === "") {
                matchesFilter = true;
            } else if (currentFilter === "exam_assigned" || currentFilter === "exam assigned") {
                matchesFilter = examName !== "no exam assigned" && Boolean(c.exam_name);
            } else if (currentFilter === "not_started" || currentFilter === "not started") {
                matchesFilter = examStatus.includes("not started");
            } else if (currentFilter === "in_progress" || currentFilter === "in progress") {
                matchesFilter = examStatus.includes("in progress") || resultStatus.includes("in progress");
            } else if (currentFilter === "completed") {
                matchesFilter = examStatus.includes("completed") || examStatus.includes("auto submitted");
            } else if (currentFilter === "passed") {
                matchesFilter = resultStatus.includes("passed");
            } else if (currentFilter === "failed") {
                matchesFilter = resultStatus.includes("failed");
            } else if (currentFilter === "registered") {
                matchesFilter = regStatus.includes("registered");
            } else if (currentFilter === "uploaded" || currentFilter === "resume uploaded") {
                matchesFilter = resStatus.includes("uploaded") || Boolean(c.resume);
            } else {
                matchesFilter = regStatus.includes(currentFilter) || resStatus.includes(currentFilter) || examStatus.includes(currentFilter) || resultStatus.includes(currentFilter);
            }

            return matchesQuery && matchesFilter;
        });

        if (!filtered.length) {
            candidatesBody.innerHTML = `<tr><td colspan="11" style="text-align: center; padding: 2.5rem; color: #64748b;">No candidates match the selected filters.</td></tr>`;
            updateBulkDeleteUI(0);
            return;
        }

        candidatesBody.innerHTML = filtered.map(c => {
            const isChecked = selectedCandidateIds.has(String(c.id));
            const exName = c.exam_name || "No Exam Assigned";
            const exStatus = c.exam_status || "—";
            const scoreStr = c.score_formatted || "—";
            const resStatus = c.result_status || "—";

            // Exam status badge HTML
            let exStatusBadge = '<span class="text-muted">—</span>';
            if (exStatus === "Completed") {
                exStatusBadge = '<span class="badge" style="background-color: #eff6ff; color: #1d4ed8; border: 1px solid #bfdbfe;"><i class="fa-solid fa-circle-check me-1"></i> Completed</span>';
            } else if (exStatus === "Auto Submitted") {
                exStatusBadge = '<span class="badge" style="background-color: #f1f5f9; color: #475569; border: 1px solid #cbd5e1;"><i class="fa-solid fa-clock-rotate-left me-1"></i> Auto Submitted</span>';
            } else if (exStatus === "In Progress") {
                exStatusBadge = '<span class="badge" style="background-color: #eff6ff; color: #2563eb; border: 1px solid #bfdbfe;"><i class="fa-solid fa-spinner fa-spin me-1"></i> In Progress</span>';
            } else if (exStatus === "Not Started") {
                exStatusBadge = '<span class="badge" style="background-color: #f1f5f9; color: #475569; border: 1px solid #cbd5e1;"><i class="fa-solid fa-hourglass-start me-1"></i> Not Started</span>';
            }

            // Result badge HTML
            let resBadge = '<span class="text-muted">—</span>';
            if (resStatus === "Passed") {
                resBadge = '<span class="badge" style="background-color: #eff6ff; color: #1d4ed8; border: 1.5px solid #bfdbfe;"><i class="fa-solid fa-check me-1"></i> Passed</span>';
            } else if (resStatus === "Failed") {
                resBadge = '<span class="badge badge-result-failed" style="background-color: #eff6ff; color: #2563eb; border: 1.5px solid #bfdbfe; backdrop-filter: blur(4px); -webkit-backdrop-filter: blur(4px); filter: blur(0.3px);"><i class="fa-solid fa-xmark me-1"></i> Failed</span>';
            } else if (resStatus === "In Progress") {
                resBadge = '<span class="badge" style="background-color: #eff6ff; color: #2563eb; border: 1.5px solid #bfdbfe;"><i class="fa-solid fa-spinner fa-spin me-1"></i> In Progress</span>';
            } else if (resStatus === "Pending") {
                resBadge = '<span class="badge" style="background-color: #f1f5f9; color: #475569; border: 1.5px solid #cbd5e1;"><i class="fa-solid fa-clock me-1"></i> Pending</span>';
            }

            // Score text styling
            let scoreDisplay = '<span class="text-muted">—</span>';
            if (scoreStr !== "—") {
                scoreDisplay = `<span class="fw-bold" style="color: #000000;">${escapeHtml(scoreStr)}</span>`;
            }

            return `
                <tr>
                    <td style="text-align: center;">
                        <input type="checkbox" class="candidate-row-cb" data-id="${c.id}" ${isChecked ? 'checked' : ''} style="width: 18px; height: 18px; cursor: pointer;">
                    </td>

                    <!-- 1. Candidate -->
                    <td>
                        <div style="font-weight: 700; color: #0f172a;">${escapeHtml(c.name)}</div>
                        <small class="text-muted">#${c.id}</small>
                    </td>

                    <!-- 2. Email -->
                    <td>${escapeHtml(c.email)}</td>

                    <!-- 3. Job/Position -->
                    <td>${escapeHtml(c.position || c.job_title || '-')}</td>

                    <!-- 4. Registration Status -->
                    <td>
                        <span class="badge ${getStatusBadgeClass(c.registration_status || c.status)}">
                            ${escapeHtml(c.registration_status || c.status || 'Registered')}
                        </span>
                    </td>

                    <!-- 5. Resume Status -->
                    <td>
                        <span class="badge ${c.resume ? 'badge-uploaded' : 'badge-pending'}">
                            ${c.resume ? 'Uploaded' : (c.resume_status || 'Not Uploaded')}
                        </span>
                    </td>

                    <!-- 6. Exam -->
                    <td>
                        <span class="fw-semibold text-dark">${escapeHtml(exName)}</span>
                    </td>

                    <!-- 7. Exam Status -->
                    <td>${exStatusBadge}</td>

                    <!-- 8. Score -->
                    <td>${scoreDisplay}</td>

                    <!-- 9. Result -->
                    <td>${resBadge}</td>

                    <!-- 10. Actions -->
                    <td>
                        <div class="d-flex align-items-center gap-2">
                            <button type="button" class="btn-action-blue view-btn" data-id="${c.id}" title="View Details">
                                <i class="fa-solid fa-eye me-1"></i> View
                            </button>
                            ${c.attempt_id ? `
                                <a href="/hr/exams/attempt/${c.attempt_id}" target="_blank" class="btn-action-sky audit-btn" title="View Exam Audit">
                                    <i class="fa-solid fa-chart-line me-1"></i> Audit
                                </a>
                            ` : ''}
                            <button type="button" class="btn-action-red delete-btn" data-id="${c.id}" title="Delete Candidate">
                                <i class="fa-solid fa-trash me-1"></i> Delete
                            </button>
                        </div>
                    </td>
                </tr>
            `;
        }).join("");

        // Row Checkbox Listeners
        const rowCbs = candidatesBody.querySelectorAll(".candidate-row-cb");
        rowCbs.forEach(cb => {
            cb.addEventListener("change", () => {
                const id = String(cb.getAttribute("data-id"));
                if (cb.checked) {
                    selectedCandidateIds.add(id);
                } else {
                    selectedCandidateIds.delete(id);
                }
                updateBulkDeleteUI(rowCbs.length);
            });
        });

        updateBulkDeleteUI(rowCbs.length);

        // Action Listeners
        candidatesBody.querySelectorAll(".view-btn").forEach(btn => {
            btn.addEventListener("click", () => openCandidateModal(btn.getAttribute("data-id")));
        });

        candidatesBody.querySelectorAll(".delete-btn").forEach(btn => {
            btn.addEventListener("click", () => promptDeleteCandidate(btn.getAttribute("data-id")));
        });
    }

    function updateBulkDeleteUI(totalVisibleRows) {
        const bulkContainer = document.getElementById("bulkActionsContainer");
        const countBadge = document.getElementById("selectedCountBadge");
        const selectAllCb = document.getElementById("selectAllCandidates");
        const count = selectedCandidateIds.size;

        if (bulkContainer) {
            if (count > 0) {
                bulkContainer.style.display = "inline-flex";
                bulkContainer.classList.remove("hidden");
            } else {
                bulkContainer.style.display = "none";
                bulkContainer.classList.add("hidden");
            }
        }

        if (countBadge) {
            countBadge.textContent = `${count} selected`;
        }

        if (selectAllCb) {
            if (totalVisibleRows > 0 && count >= totalVisibleRows) {
                selectAllCb.checked = true;
                selectAllCb.indeterminate = false;
            } else if (count > 0) {
                selectAllCb.checked = false;
                selectAllCb.indeterminate = true;
            } else {
                selectAllCb.checked = false;
                selectAllCb.indeterminate = false;
            }
        }
    }

    const selectAllCb = document.getElementById("selectAllCandidates");
    if (selectAllCb) {
        selectAllCb.addEventListener("change", () => {
            const rowCbs = candidatesBody ? candidatesBody.querySelectorAll(".candidate-row-cb") : [];
            rowCbs.forEach(cb => {
                const id = String(cb.getAttribute("data-id"));
                cb.checked = selectAllCb.checked;
                if (selectAllCb.checked) {
                    selectedCandidateIds.add(id);
                } else {
                    selectedCandidateIds.delete(id);
                }
            });
            updateBulkDeleteUI(rowCbs.length);
        });
    }

    let isBatchDeleteTarget = false;

    function showInlineNotification(type, title, detailsHtml = "") {
        const banner = document.getElementById("candidateNotificationBanner");
        if (!banner) return;

        let bgStyle = "background: #ecfdf5; color: #047857; border: 1px solid #a7f3d0;";
        let iconClass = "fa-solid fa-circle-check text-success";

        if (type === "warning") {
            bgStyle = "background: #fffbeb; color: #b45309; border: 1px solid #fde68a;";
            iconClass = "fa-solid fa-triangle-exclamation text-warning";
        } else if (type === "danger" || type === "error") {
            bgStyle = "background: #fef2f2; color: #b91c1c; border: 1px solid #fecaca;";
            iconClass = "fa-solid fa-circle-exclamation text-danger";
        }

        banner.style.cssText = `display: block; ${bgStyle} padding: 1rem 1.25rem; border-radius: 12px; font-size: 0.9rem; box-shadow: 0 4px 12px rgba(0,0,0,0.05); transition: all 0.3s ease;`;

        banner.innerHTML = `
            <div class="d-flex align-items-start justify-content-between">
                <div style="flex: 1;">
                    <div class="d-flex align-items-center gap-2" style="font-weight: 700; font-size: 0.95rem;">
                        <i class="${iconClass}" style="font-size: 1.1rem;"></i>
                        <span>${title}</span>
                    </div>
                    ${detailsHtml ? `<div class="mt-2 pt-2 border-top" style="font-weight: 500; opacity: 0.95;">${detailsHtml}</div>` : ''}
                </div>
                <button type="button" class="btn-close ms-3" aria-label="Close" onclick="document.getElementById('candidateNotificationBanner').style.display='none'" style="font-size: 0.8rem; cursor: pointer; opacity: 0.7;"></button>
            </div>
        `;

        banner.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }

    const deleteSelectedBtn = document.getElementById("deleteSelectedBtn");
    if (deleteSelectedBtn) {
        deleteSelectedBtn.addEventListener("click", promptBatchDeleteCandidates);
    }

    function enforceBlueDeleteModal() {
        if (!deleteModal) return;
        const iconBox = deleteModal.querySelector(".delete-icon");
        if (iconBox) {
            iconBox.style.setProperty("background-color", "#eff6ff", "important");
            iconBox.style.setProperty("border-color", "#bfdbfe", "important");
            iconBox.style.setProperty("color", "#2563eb", "important");
            const iconI = iconBox.querySelector("i");
            if (iconI) iconI.style.setProperty("color", "#2563eb", "important");
        }
        const confirmBtn = document.getElementById("confirmDelete");
        if (confirmBtn) {
            confirmBtn.style.setProperty("background-color", "#2563eb", "important");
            confirmBtn.style.setProperty("border-color", "#1d4ed8", "important");
            confirmBtn.style.setProperty("color", "#ffffff", "important");
            confirmBtn.style.setProperty("box-shadow", "0 4px 12px rgba(37, 99, 235, 0.25)", "important");
        }
    }

    function promptDeleteCandidate(id) {
        selectedCandidateId = id;
        isBatchDeleteTarget = false;
        enforceBlueDeleteModal();
        const title = deleteModal ? deleteModal.querySelector("h2") : null;
        const msg = deleteModal ? deleteModal.querySelector("p") : null;
        if (title) title.textContent = "Delete Candidate?";
        if (msg) msg.textContent = "Are you sure you want to delete this candidate? Associated test attempts and interview records will be permanently removed.";
        if (deleteModal) deleteModal.classList.remove("hidden");
    }

    function promptBatchDeleteCandidates() {
        if (isBatchDeleting) return;
        const count = selectedCandidateIds.size;
        if (count === 0) return;

        isBatchDeleteTarget = true;
        enforceBlueDeleteModal();
        const title = deleteModal ? deleteModal.querySelector("h2") : null;
        const msg = deleteModal ? deleteModal.querySelector("p") : null;
        if (title) title.textContent = "Delete Selected Candidates?";
        if (msg) msg.textContent = `Are you sure you want to delete ${count} selected candidate${count > 1 ? 's' : ''}? Associated test attempts and interview records will be permanently removed.`;
        if (deleteModal) deleteModal.classList.remove("hidden");
    }

    function executeDeleteCandidate() {
        if (deleteModal) deleteModal.classList.add("hidden");

        if (isBatchDeleteTarget) {
            executeBatchDeleteCandidates();
        } else {
            executeSingleDeleteCandidate();
        }
    }

    function executeSingleDeleteCandidate() {
        if (!selectedCandidateId) return;

        const targetId = selectedCandidateId;
        const candObj = candidatesData.find(c => String(c.id) === String(targetId));
        const candName = candObj ? candObj.name : `#${targetId}`;

        fetch(`/api/candidate/delete/${targetId}`, { method: "DELETE" })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    showInlineNotification("success", `✓ Candidate ${escapeHtml(candName)} deleted successfully.`);
                } else {
                    showInlineNotification("danger", `⚠ Unable to delete candidate ${escapeHtml(candName)}.`, escapeHtml(data.message || "Operation failed."));
                }
                loadCandidates();
            })
            .catch(err => {
                console.error("Single delete error:", err);
                showInlineNotification("danger", "⚠ Candidate Deletion Failed", "An unexpected error occurred while communicating with the server.");
                loadCandidates();
            });
    }

    function executeBatchDeleteCandidates() {
        if (isBatchDeleting) return;
        const count = selectedCandidateIds.size;
        if (count === 0) return;

        isBatchDeleting = true;
        const deleteBtn = document.getElementById("deleteSelectedBtn");
        if (deleteBtn) {
            deleteBtn.disabled = true;
            deleteBtn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Deleting (${count})...`;
        }

        fetch("/api/candidates/delete-batch", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ candidate_ids: Array.from(selectedCandidateIds) })
        })
        .then(res => res.json())
        .then(data => {
            isBatchDeleting = false;
            if (deleteBtn) {
                deleteBtn.disabled = false;
                deleteBtn.innerHTML = `<i class="fa-solid fa-trash-can"></i> Delete Selected`;
            }

            if (data.success) {
                const deleted = data.deleted || [];
                const failed = data.failed || [];
                const deletedCount = deleted.length;
                const failedCount = failed.length;

                selectedCandidateIds.clear();
                const selectAllCb = document.getElementById("selectAllCandidates");
                if (selectAllCb) selectAllCb.checked = false;

                if (failedCount === 0) {
                    showInlineNotification("success", `✓ ${deletedCount} candidate${deletedCount > 1 ? 's' : ''} deleted successfully.`);
                } else {
                    let failListHtml = `<div class="mb-1 fw-bold"><i class="fa-solid fa-triangle-exclamation me-1"></i> ${failedCount} candidate${failedCount > 1 ? 's' : ''} could not be deleted:</div><ul class="mb-0 ps-3">`;
                    failed.forEach(f => {
                        failListHtml += `<li>Candidate <strong>${escapeHtml(f.name || '#' + f.id)}</strong>: ${escapeHtml(f.reason || 'Failed to delete')}</li>`;
                    });
                    failListHtml += `</ul>`;

                    if (deletedCount > 0) {
                        showInlineNotification("warning", `✓ ${deletedCount} candidate${deletedCount > 1 ? 's' : ''} deleted successfully.`, failListHtml);
                    } else {
                        showInlineNotification("danger", `⚠ 0 candidates deleted. Batch deletion failed for ${failedCount} candidate${failedCount > 1 ? 's' : ''}.`, failListHtml);
                    }
                }

                loadCandidates();
            } else {
                showInlineNotification("danger", "⚠ Batch Deletion Request Failed", escapeHtml(data.message || "Failed to process batch deletion request."));
            }
        })
        .catch(err => {
            isBatchDeleting = false;
            if (deleteBtn) {
                deleteBtn.disabled = false;
                deleteBtn.innerHTML = `<i class="fa-solid fa-trash-can"></i> Delete Selected`;
            }
            console.error("Batch delete error:", err);
            showInlineNotification("danger", "⚠ Batch Deletion Error", "An unexpected error occurred while executing the batch deletion request.");
        });
    }

    // RPA Automation Trigger & Polling
    function startAutomationJob() {
        const modeInput = document.querySelector('input[name="browserMode"]:checked');
        const browserMode = modeInput ? modeInput.value : "headless";

        const hasCandidateFile = candidateFile && candidateFile.files && candidateFile.files.length > 0;
        const currentJobId = activeJobId || localStorage.getItem("activeJobId") || "";

        // If no file is chosen and there is no active job, show a helpful alert instead of triggering an invalid run
        if (!hasCandidateFile && !currentJobId) {
            showInlineNotification("warning", "File Required", "Please click 'Choose Excel' to select your candidate Excel (.xlsx) or CSV file before starting automation.");
            const fileLabel = document.querySelector('label[for="candidateFile"]');
            if (fileLabel) {
                fileLabel.style.transition = "transform 0.2s, box-shadow 0.2s";
                fileLabel.style.transform = "scale(1.05)";
                fileLabel.style.boxShadow = "0 0 12px rgba(59, 130, 246, 0.5)";
                setTimeout(() => {
                    fileLabel.style.transform = "";
                    fileLabel.style.boxShadow = "";
                }, 1200);
            }
            return;
        }

        const progressSection = document.getElementById("automationProgress");
        if (progressSection) progressSection.classList.remove("hidden");

        const errCard = document.getElementById("automationErrorCard");
        if (errCard) errCard.classList.add("hidden");

        if (startAutomationBtn) startAutomationBtn.classList.add("hidden");
        if (cancelAutomationBtn) cancelAutomationBtn.classList.remove("hidden");

        const bar = document.getElementById("automationProgressBar");
        const percentText = document.getElementById("automationPercent");
        const msgText = document.getElementById("automationMessage");

        const triggerAutomationEngine = (jobId, uploadId, excelPath) => {
            if (msgText) msgText.textContent = "Starting Robot Framework & Selenium automation engine...";
            if (bar) bar.style.width = "40%";
            if (percentText) percentText.textContent = "40%";

            fetch("/api/automation/start", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    job_id: jobId,
                    upload_id: uploadId,
                    excel_file: excelPath,
                    browser_mode: browserMode
                })
            })
            .then(res => res.json())
            .then(data => {
                if (data.success && data.job_id) {
                    activeJobId = data.job_id;
                    localStorage.setItem("activeJobId", activeJobId);
                    if (data.upload_id) {
                        activeUploadId = data.upload_id;
                        localStorage.setItem("activeUploadId", data.upload_id);
                    }
                    pollAutomationStatus(activeJobId);
                } else {
                    updateAutomationUIError(data.message || data.failure_reason || data.reason || "Could not start automation", data);
                }
            })
            .catch(err => {
                updateAutomationUIError(err.message || "Failed to trigger automation API");
            });
        };

        if (hasCandidateFile) {
            if (msgText) msgText.textContent = "Uploading candidate spreadsheet and resumes to server...";
            if (bar) bar.style.width = "15%";
            if (percentText) percentText.textContent = "15%";

            const formData = new FormData();
            formData.append("candidate_file", candidateFile.files[0]);

            if (resumeFiles && resumeFiles.files && resumeFiles.files.length > 0) {
                for (let i = 0; i < resumeFiles.files.length; i++) {
                    formData.append("resumes", resumeFiles.files[i]);
                }
            }

            fetch("/api/automation/upload", {
                method: "POST",
                body: formData
            })
            .then(res => res.json())
            .then(uploadData => {
                if (!uploadData.success) {
                    throw new Error(uploadData.message || "Candidate file upload failed");
                }

                const newJobId = uploadData.job_id || "";
                const newUploadId = uploadData.upload_id || "";
                const uploadedFilePath = uploadData.uploaded_file || ((uploadData.uploaded_files && uploadData.uploaded_files.length > 0) ? uploadData.uploaded_files[0] : "");

                activeJobId = newJobId;
                activeUploadId = newUploadId;
                if (newJobId) localStorage.setItem("activeJobId", newJobId);
                if (newUploadId) localStorage.setItem("activeUploadId", newUploadId);

                // Update candidate list and stats immediately
                fetchCandidates();

                // Kick off automation execution
                triggerAutomationEngine(newJobId, newUploadId, uploadedFilePath);
            })
            .catch(err => {
                console.error("Upload error before automation:", err);
                updateAutomationUIError(err.message || "Failed to upload candidate file before starting automation");
            });
        } else {
            triggerAutomationEngine(currentJobId, activeUploadId || localStorage.getItem("activeUploadId") || "", "");
        }
    }

    function pollAutomationStatus(jobId) {
        if (pollTimer) clearInterval(pollTimer);

        pollTimer = setInterval(() => {
            fetch(`/api/automation/status/${jobId}`)
                .then(res => res.json())
                .then(data => {
                    updateAutomationProgressUI(data);

                    if (data.status === "SUCCESS" || data.status === "FAILED" || data.status === "CANCELLED") {
                        clearInterval(pollTimer);
                        if (cancelAutomationBtn) cancelAutomationBtn.classList.add("hidden");
                        if (startAutomationBtn) startAutomationBtn.classList.remove("hidden");
                        fetchCandidates();

                        if (data.status === "FAILED") {
                            updateAutomationUIError(data.error || data.reason || data.message || "Automated recruitment task encountered an error.", data);
                        }
                    }
                })
                .catch(err => console.error("Status polling error:", err));
        }, 2000);
    }

    function cancelAutomationJob() {
        if (!activeJobId) return;

        fetch(`/api/automation/cancel/${activeJobId}`, { method: "POST" })
            .then(res => res.json())
            .then(() => {
                if (pollTimer) clearInterval(pollTimer);
                if (cancelAutomationBtn) cancelAutomationBtn.classList.add("hidden");
                if (startAutomationBtn) startAutomationBtn.classList.remove("hidden");
            });
    }

    function updateAutomationProgressUI(data) {
        if (!data) return;

        const bar = document.getElementById("automationProgressBar");
        const percentText = document.getElementById("automationPercent");
        const msgText = document.getElementById("automationMessage");
        const logBox = document.getElementById("automationLog");

        if (data.job_id && data.job_id !== "-") {
            activeJobId = data.job_id;
            setText("metaJobId", `Job: ${data.job_id}`);
            setText("errJobId", data.job_id);
            setText("jobIdDisplay", data.job_id);
        }
        if (data.stage) {
            setText("metaStage", `Stage: ${data.stage}`);
            setText("errStage", data.stage);
        }
        if (data.last_successful_step) setText("errLastStep", data.last_successful_step);

        if (data.total_candidates !== undefined) {
            setText("metaCandidateCount", `Candidates: ${data.current_candidate || 0} / ${data.total_candidates}`);
        }

        if (data.status) {
            const eyebrow = document.getElementById("progressEyebrow");
            if (eyebrow) {
                if (data.status === "SUCCESS") {
                    eyebrow.textContent = "AUTOMATION COMPLETED";
                    eyebrow.className = "progress-eyebrow success";
                } else if (data.status === "FAILED") {
                    eyebrow.textContent = "AUTOMATION FAILED";
                    eyebrow.className = "progress-eyebrow failed";
                } else {
                    eyebrow.textContent = "AUTOMATION ACTIVE";
                    eyebrow.className = "progress-eyebrow";
                }
            }
        }

        if (bar && data.progress !== undefined) bar.style.width = `${data.progress}%`;
        if (percentText && data.progress !== undefined) percentText.textContent = `${data.progress}%`;
        if (msgText && data.message) msgText.textContent = data.message;

        if (logBox && data.output && Array.isArray(data.output)) {
            logBox.innerHTML = data.output.map(line => {
                const escaped = escapeHtml(line);
                let lineCls = "log-line";
                if (line.includes("SUCCESS") || line.includes("PASS") || line.includes("File exists: YES") || line.includes("exists=True")) {
                    lineCls += " log-success";
                } else if (line.includes("FAIL") || line.includes("ERROR")) {
                    lineCls += " log-error";
                } else if (line.includes("STAGE:") || line.includes("CANDIDATE:") || line.includes("JOB OVERALL") || line.includes("RPA Execution")) {
                    lineCls += " log-highlight";
                } else if (line.includes("LAST_STEP:") || line.includes("Parsing candidate") || line.includes("Connecting")) {
                    lineCls += " log-warning";
                }
                return `<div class="${lineCls}">${escaped}</div>`;
            }).join("");
            logBox.scrollTop = logBox.scrollHeight;
        }
    }

    function updateAutomationUIError(errMsg, data) {
        const errCard = document.getElementById("automationErrorCard");
        const errReason = document.getElementById("errReason");
        if (errReason) errReason.textContent = errMsg;

        if (data) {
            const jId = data.job_id || data.jobId || data.job_code;
            if (jId && jId !== "-") {
                activeJobId = jId;
                setText("errJobId", jId);
                setText("jobIdDisplay", jId);
            }
            if (data.stage && data.stage !== "-") setText("errStage", data.stage);
            if (data.last_successful_step) setText("errLastStep", data.last_successful_step);
            if (data.robot_status) setText("errRobotStatus", data.robot_status);
            if (data.browser_status) setText("errSeleniumStatus", data.browser_status);
        }

        if (errCard) errCard.classList.remove("hidden");
        if (cancelAutomationBtn) cancelAutomationBtn.classList.add("hidden");
        if (startAutomationBtn) startAutomationBtn.classList.remove("hidden");
    }

    function setText(id, val) {
        const el = document.getElementById(id);
        if (el) el.textContent = val;
    }

    function escapeHtml(str) {
        if (!str) return "";
        return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }
});
