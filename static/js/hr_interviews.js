/**
 * HR Interview Management & Interactive Calendar JS
 * Includes:
 * 1. Searchable Candidate Select Dropdown (with live search filter inside dropdown)
 * 2. Searchable Interviewer Select Dropdown
 * 3. In-page Website Popups, Custom Modals & Toasts (Zero browser alert/confirm)
 */

let currentView = 'month';
let currentDate = new Date();
let allInterviews = [];
let filteredInterviews = [];
let activeInterview = null;

// Candidates & Interviewers master datasets for search
let candidatesMaster = [];
let interviewersMaster = [];

document.addEventListener('DOMContentLoaded', () => {
    loadInterviews();
    loadCandidatesMaster();
    loadInterviewersMaster();

    // Close search dropdowns when clicking outside
    document.addEventListener('click', (e) => {
        if (!e.target.closest('#candidateDropdownMenu') && !e.target.closest('#candidateSelectBtn')) {
            hideCandidateDropdown();
        }
        if (!e.target.closest('#interviewerDropdownMenu') && !e.target.closest('#formInterviewerName')) {
            hideInterviewerDropdown();
        }
    });

    // Keyboard navigation for candidate search input
    const candSearchInput = document.getElementById('candidateSearchInput');
    if (candSearchInput) {
        candSearchInput.addEventListener('keydown', (e) => {
            const listEl = document.getElementById('candidateDropdownList');
            if (!listEl) return;
            const items = Array.from(listEl.querySelectorAll('.search-dropdown-item'));
            if (!items.length) return;

            let activeIdx = items.findIndex(el => el.classList.contains('active-focus'));

            if (e.key === 'ArrowDown') {
                e.preventDefault();
                activeIdx = (activeIdx + 1) % items.length;
                items.forEach((el, idx) => el.classList.toggle('active-focus', idx === activeIdx));
                items[activeIdx].scrollIntoView({ block: 'nearest' });
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                activeIdx = (activeIdx - 1 + items.length) % items.length;
                items.forEach((el, idx) => el.classList.toggle('active-focus', idx === activeIdx));
                items[activeIdx].scrollIntoView({ block: 'nearest' });
            } else if (e.key === 'Enter') {
                e.preventDefault();
                if (activeIdx >= 0 && items[activeIdx]) {
                    items[activeIdx].click();
                } else if (items.length > 0) {
                    items[0].click();
                }
            } else if (e.key === 'Escape') {
                hideCandidateDropdown();
            }
        });
    }
});

// -------------------------------------------------------------
// API DATA LOADERS
// -------------------------------------------------------------
function loadInterviews() {
    fetch('/api/interviews/list')
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                allInterviews = data.interviews || [];
                filterInterviews();
            } else {
                console.error("Error loading interviews:", data.message);
            }
        })
        .catch(err => console.error("API error:", err));
}

function loadCandidatesMaster() {
    // Try dedicated candidates endpoint first, fallback to general candidates endpoint
    fetch('/api/interviews/candidates')
        .then(res => res.json())
        .then(data => {
            if (data.success && data.candidates && data.candidates.length > 0) {
                processCandidatesList(data.candidates);
            } else {
                fallbackLoadCandidates();
            }
        })
        .catch(() => fallbackLoadCandidates());
}

function fallbackLoadCandidates() {
    fetch('/api/candidates?all=true')
        .then(res => res.json())
        .then(data => {
            const list = data.candidates || (Array.isArray(data) ? data : []);
            processCandidatesList(list);
        })
        .catch(err => console.error("Error loading candidates master:", err));
}

function processCandidatesList(list) {
    candidatesMaster = list.map(c => ({
        id: c.id,
        name: c.name || 'Candidate',
        email: c.email || '',
        phone: c.phone || '',
        position: c.position || c.job_title || 'Applicant',
        job_id: c.job_id || '',
        status: c.status || c.registration_status || 'Active'
    }));

    // Populate the dropdown list immediately
    renderCandidateDropdownList(candidatesMaster);
}

function loadInterviewersMaster() {
    fetch('/api/interviews/interviewers')
        .then(res => res.json())
        .then(data => {
            if (data.success && data.interviewers) {
                interviewersMaster = data.interviewers;
                renderInterviewerDropdownList(interviewersMaster);
            }
        })
        .catch(err => console.error("Error loading interviewers:", err));
}

function filterInterviews() {
    const search = (document.getElementById('interviewSearchInput')?.value || '').toLowerCase().trim();
    const status = document.getElementById('statusFilterSelect')?.value || 'ALL';

    filteredInterviews = allInterviews.filter(item => {
        const matchesStatus = (status === 'ALL' || item.status === status);
        const matchesSearch = !search || (
            (item.candidate_name && item.candidate_name.toLowerCase().includes(search)) ||
            (item.interviewer_name && item.interviewer_name.toLowerCase().includes(search)) ||
            (item.interview_type && item.interview_type.toLowerCase().includes(search)) ||
            (item.candidate_email && item.candidate_email.toLowerCase().includes(search)) ||
            (item.candidate_id && String(item.candidate_id) === search)
        );
        return matchesStatus && matchesSearch;
    });

    renderCalendar();
}

function renderCalendar() {
    updateTitleHeader();

    if (currentView === 'month') {
        renderMonthView();
    } else if (currentView === 'week') {
        renderWeekView();
    } else if (currentView === 'day') {
        renderDayView();
    } else if (currentView === 'list') {
        renderListView();
    }
}

// -------------------------------------------------------------
// SEARCHABLE CANDIDATE SELECT DROPDOWN
// -------------------------------------------------------------
function toggleCandidateDropdown() {
    const menu = document.getElementById('candidateDropdownMenu');
    if (menu) {
        if (menu.classList.contains('d-none')) {
            showCandidateDropdown();
        } else {
            hideCandidateDropdown();
        }
    }
}

function showCandidateDropdown() {
    filterCandidateDropdown();
    document.getElementById('candidateDropdownMenu')?.classList.remove('d-none');
    setTimeout(() => {
        document.getElementById('candidateSearchInput')?.focus();
    }, 50);
}

function hideCandidateDropdown() {
    document.getElementById('candidateDropdownMenu')?.classList.add('d-none');
}

function clearCandidateSearch() {
    const input = document.getElementById('candidateSearchInput');
    if (input) {
        input.value = '';
        filterCandidateDropdown();
        input.focus();
    }
}

function filterCandidateDropdown() {
    const query = (document.getElementById('candidateSearchInput')?.value || '').toLowerCase().trim();
    const cleanQ = query.replace(/^#/, '');

    const matches = candidatesMaster.filter(c => {
        if (!query) return true;
        const nameMatch = c.name && c.name.toLowerCase().includes(query);
        const emailMatch = c.email && c.email.toLowerCase().includes(query);
        const phoneMatch = c.phone && c.phone.toLowerCase().includes(query);
        const posMatch = (c.position || '').toLowerCase().includes(query);
        const jobMatch = (c.job_id || '').toLowerCase().includes(query);
        const idMatch = c.id && (String(c.id) === cleanQ || `#${c.id}` === query || String(c.id).includes(cleanQ));
        return nameMatch || emailMatch || phoneMatch || posMatch || jobMatch || idMatch;
    });

    const countEl = document.getElementById('candidateMatchCount');
    if (countEl) {
        countEl.textContent = query 
            ? `${matches.length} candidate${matches.length === 1 ? '' : 's'} found`
            : `${candidatesMaster.length} candidate${candidatesMaster.length === 1 ? '' : 's'} available`;
    }

    renderCandidateDropdownList(matches, query);
}

function renderCandidateDropdownList(matches, query = '') {
    const listEl = document.getElementById('candidateDropdownList');
    if (!listEl) return;

    listEl.innerHTML = '';
    const selectedId = document.getElementById('formCandidateId')?.value;

    if (matches.length === 0) {
        listEl.innerHTML = `
            <div class="p-3 text-center text-muted small">
                <i class="fa-solid fa-user-slash fs-4 d-block mb-1 text-secondary opacity-50"></i>
                No candidate found matching "<strong>${escapeHtml(query)}</strong>"
            </div>
        `;
        return;
    }

    matches.forEach(cand => {
        const isSelected = selectedId && String(selectedId) === String(cand.id);
        const initials = getInitials(cand.name);

        const item = document.createElement('div');
        item.className = `search-dropdown-item d-flex justify-content-between align-items-center ${isSelected ? 'active' : ''}`;
        item.innerHTML = `
            <div class="d-flex align-items-center gap-2 overflow-hidden">
                <div class="candidate-avatar-badge">${initials}</div>
                <div class="overflow-hidden">
                    <strong class="text-dark d-block text-truncate">${escapeHtml(cand.name)} <span class="badge bg-secondary ms-1">#${cand.id}</span></strong>
                    <small class="text-muted d-block text-truncate"><i class="fa-solid fa-envelope me-1"></i>${escapeHtml(cand.email)}</small>
                </div>
            </div>
            <div class="text-end ms-2 flex-shrink-0">
                <span class="badge bg-light text-primary border d-block">${escapeHtml(cand.position || 'Applicant')}</span>
                ${isSelected ? '<i class="fa-solid fa-check text-success small mt-1"></i>' : ''}
            </div>
        `;

        item.addEventListener('click', () => {
            selectCandidate(cand);
        });

        listEl.appendChild(item);
    });
}

function selectCandidate(cand) {
    document.getElementById('formCandidateId').value = cand.id;
    
    // Update button text
    const btnText = document.getElementById('candidateSelectBtnText');
    if (btnText) {
        btnText.innerHTML = `<strong class="text-dark">${escapeHtml(cand.name)}</strong> <span class="text-muted ms-1">(#${cand.id})</span>`;
    }
    
    // Show clear cross icon on trigger button
    document.getElementById('clearCandBtnIcon')?.classList.remove('d-none');

    // Update details card
    document.getElementById('selectedCandNameText').textContent = `${cand.name} (#${cand.id})`;
    document.getElementById('selectedCandEmailText').textContent = cand.email || 'No email provided';
    document.getElementById('selectedCandPositionText').textContent = cand.position || 'Applicant';
    
    const initialsEl = document.getElementById('candAvatarInitials');
    if (initialsEl) initialsEl.textContent = getInitials(cand.name);

    document.getElementById('selectedCandidateBadge').classList.remove('d-none');

    hideCandidateDropdown();
    checkLiveConflict();
}

function clearCandidateSelection() {
    document.getElementById('formCandidateId').value = '';
    
    const btnText = document.getElementById('candidateSelectBtnText');
    if (btnText) {
        btnText.innerHTML = `<span class="text-muted"><i class="fa-solid fa-user me-2"></i>-- Choose Candidate or Search --</span>`;
    }
    
    document.getElementById('clearCandBtnIcon')?.classList.add('d-none');
    document.getElementById('selectedCandidateBadge')?.classList.add('d-none');

    const searchInput = document.getElementById('candidateSearchInput');
    if (searchInput) searchInput.value = '';

    filterCandidateDropdown();
    checkLiveConflict();
}

// -------------------------------------------------------------
// SEARCHABLE INTERVIEWER SELECT DROPDOWN
// -------------------------------------------------------------
function toggleInterviewerDropdown() {
    const menu = document.getElementById('interviewerDropdownMenu');
    if (menu) {
        if (menu.classList.contains('d-none')) {
            showInterviewerDropdown();
        } else {
            hideInterviewerDropdown();
        }
    }
}

function showInterviewerDropdown() {
    filterInterviewerDropdown();
    document.getElementById('interviewerDropdownMenu')?.classList.remove('d-none');
}

function hideInterviewerDropdown() {
    document.getElementById('interviewerDropdownMenu')?.classList.add('d-none');
}

function filterInterviewerDropdown() {
    const query = (document.getElementById('formInterviewerName')?.value || '').toLowerCase().trim();
    const listEl = document.getElementById('interviewerDropdownList');
    if (!listEl) return;

    listEl.innerHTML = '';

    const matches = interviewersMaster.filter(i => {
        if (!query) return true;
        const nameMatch = i.name && i.name.toLowerCase().includes(query);
        const emailMatch = i.email && i.email.toLowerCase().includes(query);
        return nameMatch || emailMatch;
    });

    if (matches.length === 0) {
        if (query) {
            listEl.innerHTML = `
                <div class="search-dropdown-item text-primary small" onclick="selectTypedInterviewer('${escapeHtml(query)}')">
                    <i class="fa-solid fa-plus me-1"></i> Use custom interviewer: "<strong>${escapeHtml(query)}</strong>"
                </div>
            `;
        } else {
            listEl.innerHTML = `<div class="p-2 text-center text-muted small">Type name or email to search interviewer...</div>`;
        }
        return;
    }

    renderInterviewerDropdownList(matches);
}

function renderInterviewerDropdownList(matches) {
    const listEl = document.getElementById('interviewerDropdownList');
    if (!listEl) return;

    listEl.innerHTML = '';

    matches.forEach(intv => {
        const item = document.createElement('div');
        item.className = 'search-dropdown-item d-flex justify-content-between align-items-center';
        item.innerHTML = `
            <div>
                <strong class="text-dark d-block">${escapeHtml(intv.name)}</strong>
                <small class="text-muted"><i class="fa-solid fa-envelope me-1"></i>${escapeHtml(intv.email || 'No email')}</small>
            </div>
            <span class="badge bg-light text-secondary border">Interviewer</span>
        `;
        item.addEventListener('click', () => {
            selectInterviewer(intv);
        });
        listEl.appendChild(item);
    });
}

function selectInterviewer(intv) {
    document.getElementById('formInterviewerName').value = intv.name;
    if (intv.email) {
        document.getElementById('formInterviewerEmail').value = intv.email;
    }
    hideInterviewerDropdown();
    checkLiveConflict();
}

function selectTypedInterviewer(name) {
    document.getElementById('formInterviewerName').value = name;
    hideInterviewerDropdown();
    checkLiveConflict();
}

// -------------------------------------------------------------
// LIVE CONFLICT CHECK
// -------------------------------------------------------------
function checkLiveConflict() {
    const interviewerName = document.getElementById('formInterviewerName')?.value?.trim();
    const date = document.getElementById('formInterviewDate')?.value;
    const startTime = document.getElementById('formStartTime')?.value;
    const endTime = document.getElementById('formEndTime')?.value;
    const interviewId = document.getElementById('formInterviewId')?.value;
    const noticeBox = document.getElementById('liveConflictNotice');

    if (!interviewerName || !date || !startTime || !endTime) {
        noticeBox?.classList.add('d-none');
        return;
    }

    fetch('/api/interviews/check-conflict', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            interviewer_name: interviewerName,
            interview_date: date,
            start_time: startTime,
            end_time: endTime,
            exclude_id: interviewId ? parseInt(interviewId) : null
        })
    })
    .then(res => res.json())
    .then(data => {
        if (data.has_conflict) {
            document.getElementById('liveConflictText').textContent = 
                `${data.conflict.interviewer_name} already has an interview with ${data.conflict.candidate_name} on ${data.conflict.interview_date} (${data.conflict.start_time} - ${data.conflict.end_time}).`;
            noticeBox?.classList.remove('d-none');
            noticeBox?.classList.add('d-flex');
        } else {
            noticeBox?.classList.add('d-none');
            noticeBox?.classList.remove('d-flex');
        }
    })
    .catch(err => console.error("Conflict check error:", err));
}

// -------------------------------------------------------------
// FORM SUBMIT HANDLER
// -------------------------------------------------------------
function handleInterviewFormSubmit(e) {
    e.preventDefault();

    const interviewId = document.getElementById('formInterviewId').value;
    const candidateId = document.getElementById('formCandidateId').value;
    const interviewerName = document.getElementById('formInterviewerName').value.trim();
    const interviewerEmail = document.getElementById('formInterviewerEmail').value.trim();
    const date = document.getElementById('formInterviewDate').value;
    const startTime = document.getElementById('formStartTime').value;
    const endTime = document.getElementById('formEndTime').value;
    const interviewType = document.getElementById('formInterviewType').value;
    const locationLink = document.getElementById('formLocationLink').value.trim();
    const status = document.getElementById('formStatus').value;
    const notes = document.getElementById('formNotes').value.trim();

    if (!candidateId) {
        showWebsiteAlert("Candidate Required", "Please select a candidate from the candidate list before scheduling.", "warning");
        return;
    }

    if (startTime >= endTime) {
        showWebsiteAlert("Invalid Time Range", "Start time must be strictly before end time.", "warning");
        return;
    }

    const payload = {
        candidate_id: candidateId,
        interviewer_name: interviewerName,
        interviewer_email: interviewerEmail,
        interview_date: date,
        start_time: startTime,
        end_time: endTime,
        interview_type: interviewType,
        location_link: locationLink,
        status: status,
        notes: notes
    };

    const endpoint = interviewId ? `/api/interviews/update/${interviewId}` : '/api/interviews/schedule';

    const saveBtn = document.getElementById('submitScheduleBtn');
    if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin me-1"></i> Saving...';
    }

    fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    })
    .then(res => res.json())
    .then(data => {
        if (saveBtn) {
            saveBtn.disabled = false;
            saveBtn.innerHTML = '<i class="fa-solid fa-floppy-disk me-1"></i> Save Interview';
        }

        if (data.success) {
            const modalEl = document.getElementById('scheduleModal');
            const bsModal = bootstrap.Modal.getInstance(modalEl);
            if (bsModal) bsModal.hide();

            loadInterviews();
            showWebsiteToast(data.message || "Interview saved successfully!", 'success');
        } else if (data.has_conflict) {
            showConflictWarningModal(data.conflict);
        } else {
            showWebsiteAlert("Unable to Save Interview", data.message || "Error saving interview.", "danger");
        }
    })
    .catch(err => {
        if (saveBtn) {
            saveBtn.disabled = false;
            saveBtn.innerHTML = '<i class="fa-solid fa-floppy-disk me-1"></i> Save Interview';
        }
        console.error("Save interview error:", err);
        showWebsiteAlert("Server Error", "An error occurred while communicating with the server. Please try again.", "danger");
    });
}

function showConflictWarningModal(conflict) {
    document.getElementById('conflictCandidateName').textContent = conflict.candidate_name || '-';
    document.getElementById('conflictDate').textContent = conflict.interview_date || '-';
    document.getElementById('conflictTimeSlot').textContent = `${conflict.start_time} - ${conflict.end_time}`;
    document.getElementById('conflictInterviewerName').textContent = conflict.interviewer_name || '-';
    document.getElementById('conflictStatus').textContent = conflict.status || 'Scheduled';

    const modalEl = document.getElementById('conflictWarningModal');
    const modal = new bootstrap.Modal(modalEl);
    modal.show();
}

// -------------------------------------------------------------
// MODAL CONTROLLERS
// -------------------------------------------------------------
function openScheduleModal(item = null, defaultDate = null) {
    document.getElementById('scheduleInterviewForm').reset();
    document.getElementById('liveConflictNotice').classList.add('d-none');
    clearCandidateSelection();

    if (item) {
        document.getElementById('modalHeaderTitle').textContent = "Edit / Reschedule Interview";
        document.getElementById('formInterviewId').value = item.id;
        
        // Find and select candidate in searchable dropdown
        const cand = candidatesMaster.find(c => c.id === item.candidate_id) || {
            id: item.candidate_id,
            name: item.candidate_name,
            email: item.candidate_email,
            position: 'Applicant'
        };
        selectCandidate(cand);

        document.getElementById('formInterviewerName').value = item.interviewer_name || '';
        document.getElementById('formInterviewerEmail').value = item.interviewer_email || '';
        document.getElementById('formInterviewDate').value = item.interview_date || '';
        document.getElementById('formStartTime').value = item.start_time || '';
        document.getElementById('formEndTime').value = item.end_time || '';
        document.getElementById('formInterviewType').value = item.interview_type || 'Technical';
        document.getElementById('formLocationLink').value = item.location_link || '';
        document.getElementById('formStatus').value = item.status || 'Scheduled';
        document.getElementById('formNotes').value = item.notes || '';
    } else {
        document.getElementById('modalHeaderTitle').textContent = "Schedule Interview";
        document.getElementById('formInterviewId').value = "";
        
        if (defaultDate) {
            document.getElementById('formInterviewDate').value = defaultDate;
        } else {
            document.getElementById('formInterviewDate').value = formatDateYMD(new Date());
        }
        document.getElementById('formStartTime').value = "10:00";
        document.getElementById('formEndTime').value = "11:00";
    }

    const modalEl = document.getElementById('scheduleModal');
    const bsModal = new bootstrap.Modal(modalEl);
    bsModal.show();
}

function openDetailModal(item) {
    activeInterview = item;

    const statusNorm = (item.status || 'Scheduled');
    const statusClass = statusNorm.toLowerCase().replace(/\s+/g, '-');
    document.getElementById('detailTypeBadge').textContent = item.interview_type || 'Technical';
    document.getElementById('detailStatusBadge').textContent = statusNorm;
    document.getElementById('detailStatusBadge').className = `badge status-${statusClass} fs-6`;

    document.getElementById('detailCandidateName').textContent = item.candidate_name || 'Candidate';
    document.getElementById('detailCandidateEmail').textContent = `${item.candidate_email || ''} (ID: #${item.candidate_id})`;

    document.getElementById('detailDateText').textContent = item.interview_date || '-';
    document.getElementById('detailTimeText').textContent = `${item.start_time} - ${item.end_time}`;
    document.getElementById('detailInterviewerText').textContent = `${item.interviewer_name} (${item.interviewer_email || 'No Email'})`;
    
    const locEl = document.getElementById('detailLocationText');
    if (item.location_link && item.location_link.startsWith('http')) {
        locEl.innerHTML = `<a href="${escapeHtml(item.location_link)}" target="_blank" class="text-primary fw-bold">${escapeHtml(item.location_link)} <i class="fa-solid fa-arrow-up-right-from-square small"></i></a>`;
    } else {
        locEl.textContent = item.location_link || 'In-Person / To be shared';
    }

    document.getElementById('detailNotesText').textContent = item.notes || 'No additional notes provided.';
    document.getElementById('detailUpdatedAt').textContent = item.updated_at_formatted || item.created_at_formatted || '-';

    // Candidate Reschedule Alert Check
    const candAlert = document.getElementById('detailCandRescheduleAlert');
    if (candAlert) {
        if (item.status === 'Reschedule Requested' || item.candidate_reschedule_reason) {
            candAlert.classList.remove('d-none');
            document.getElementById('detailCandReqReason').textContent = item.candidate_reschedule_reason || 'Schedule adjustment requested';
            document.getElementById('detailCandReqPreferred').textContent = (item.candidate_preferred_date || 'Flexible Date') + ' (' + (item.candidate_preferred_time || 'Flexible Time') + ')';
            document.getElementById('detailCandReqMessage').textContent = item.candidate_reschedule_message ? item.candidate_reschedule_message : 'No additional message provided by candidate.';
            document.getElementById('detailCandReqTime').textContent = item.reschedule_requested_at_formatted || 'Recently';
        } else {
            candAlert.classList.add('d-none');
        }
    }

    const modalEl = document.getElementById('detailModal');
    const modal = new bootstrap.Modal(modalEl);
    modal.show();
}

function openDetailModalById(id) {
    const item = allInterviews.find(i => i.id === id);
    if (item) openDetailModal(item);
}

function openEditModalById(id) {
    const item = allInterviews.find(i => i.id === id);
    if (item) openScheduleModal(item);
}

function openEditModalFromDetail() {
    if (!activeInterview) return;
    
    const detailModalEl = document.getElementById('detailModal');
    const bsDetailModal = bootstrap.Modal.getInstance(detailModalEl);
    if (bsDetailModal) bsDetailModal.hide();

    openScheduleModal(activeInterview);
}

function openDeclineRescheduleModalFromDetail() {
    if (!activeInterview) return;

    const detailModalEl = document.getElementById('detailModal');
    const bsDetail = bootstrap.Modal.getInstance(detailModalEl);
    if (bsDetail) bsDetail.hide();

    document.getElementById('declineCandName').textContent = activeInterview.candidate_name || 'Candidate';
    document.getElementById('declineReasonText').value = '';

    const modalEl = document.getElementById('declineRescheduleModal');
    const modal = new bootstrap.Modal(modalEl);
    modal.show();
}

function confirmDeclineCandidateReschedule() {
    if (!activeInterview) return;

    const interviewId = activeInterview.id;
    const declineReason = document.getElementById('declineReasonText').value.trim();

    const btn = document.getElementById('confirmDeclineBtn');
    const spinner = document.getElementById('confirmDeclineSpinner');
    btn.disabled = true;
    spinner.classList.remove('d-none');

    fetch(`/api/hr/interview/decline-reschedule/${interviewId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decline_note: declineReason })
    })
    .then(res => res.json())
    .then(data => {
        btn.disabled = false;
        spinner.classList.add('d-none');

        if (data.success) {
            const modalEl = document.getElementById('declineRescheduleModal');
            const modal = bootstrap.Modal.getInstance(modalEl);
            if (modal) modal.hide();

            showWebsiteToast(data.message || "Candidate reschedule request declined.", "info", 3500);
            loadInterviews();
        } else {
            showWebsiteToast(data.message || "Failed to decline reschedule request.", "error");
        }
    })
    .catch(err => {
        btn.disabled = false;
        spinner.classList.add('d-none');
        console.error("Decline reschedule error:", err);
        showWebsiteToast("An error occurred while declining request.", "error");
    });
}

// -------------------------------------------------------------
// DEDICATED RESCHEDULE EXPERIENCE CONTROLLERS
// -------------------------------------------------------------

function openRescheduleModal(item) {
    if (!item) return;

    activeInterview = item;

    // Reset Form
    document.getElementById('rescheduleInterviewForm').reset();
    document.getElementById('rescheduleConflictAlert').classList.add('d-none');
    document.getElementById('customReasonContainer').classList.add('d-none');

    // Populate Hidden & Header fields
    document.getElementById('rescheduleInterviewId').value = item.id;
    document.getElementById('rescheduleCandidateEmail').value = item.candidate_email || '';
    document.getElementById('rescheduleCandidateName').value = item.candidate_name || '';
    document.getElementById('rescheduleInterviewerName').value = item.interviewer_name || '';
    document.getElementById('rescheduleInterviewType').value = item.interview_type || 'Technical';
    
    const oldScheduleStr = `${item.interview_date} from ${item.start_time} to ${item.end_time}`;
    document.getElementById('rescheduleOldScheduleStr').value = oldScheduleStr;

    // Populate Overview Card
    document.getElementById('rescheduleTypePill').textContent = `${item.interview_type || 'Technical'} Round`;
    document.getElementById('rescheduleCurrentCandText').textContent = `${item.candidate_name} (${item.candidate_email || 'No email'})`;
    document.getElementById('rescheduleCurrentInterviewerText').textContent = `${item.interviewer_name} (${item.interviewer_email || 'HR Team'})`;
    document.getElementById('rescheduleCurrentDateText').innerHTML = `<i class="fa-regular fa-calendar-xmark me-1"></i> ${item.interview_date} &bull; ${item.start_time} - ${item.end_time}`;

    // Candidate prompt banner check
    const candPromptBanner = document.getElementById('rescheduleCandidatePromptBanner');
    const candPromptDetails = document.getElementById('rescheduleCandidatePromptDetails');
    const hasCandidateReq = (item.status === 'Reschedule Requested' || item.candidate_preferred_date || item.candidate_reschedule_reason);

    if (candPromptBanner && candPromptDetails && hasCandidateReq) {
        candPromptBanner.classList.remove('d-none');
        candPromptDetails.innerHTML = `Candidate <strong>${escapeHtml(item.candidate_name)}</strong> requested: <strong>📅 ${item.candidate_preferred_date || 'Flexible Date'}</strong> (${escapeHtml(item.candidate_preferred_time || 'Flexible Time')})<br>Reason: <span class="text-danger fw-semibold">${escapeHtml(item.candidate_reschedule_reason || 'Candidate requested a change')}</span>${item.candidate_reschedule_message ? `<br>Note: <em>"${escapeHtml(item.candidate_reschedule_message)}"</em>` : ''}`;
    } else if (candPromptBanner) {
        candPromptBanner.classList.add('d-none');
    }

    // Set Default New Date: if candidate provided preferred_date, use that! Else +1 day
    if (item.candidate_preferred_date) {
        document.getElementById('rescheduleNewDate').value = item.candidate_preferred_date;
    } else {
        const currentD = new Date(item.interview_date);
        const defaultNewD = isNaN(currentD.getTime()) ? new Date() : currentD;
        defaultNewD.setDate(defaultNewD.getDate() + 1);
        document.getElementById('rescheduleNewDate').value = formatDateYMD(defaultNewD);
    }

    document.getElementById('rescheduleNewStartTime').value = item.start_time || '10:00';
    document.getElementById('rescheduleNewEndTime').value = item.end_time || '11:00';
    document.getElementById('rescheduleLocationLink').value = item.location_link || '';

    if (hasCandidateReq) {
        document.getElementById('rescheduleReasonSelect').value = 'Candidate requested a change';
        document.getElementById('rescheduleNotes').value = item.candidate_reschedule_message ? `Candidate Note: ${item.candidate_reschedule_message}` : (item.notes || '');
    } else {
        document.getElementById('rescheduleReasonSelect').value = 'Interviewer unavailable';
        document.getElementById('rescheduleNotes').value = item.notes || '';
    }

    document.getElementById('rescheduleSendEmail').checked = true;

    // Update diff summary & preview
    updateRescheduleSummaryDiff();
    updateLiveEmailPreview();

    const modalEl = document.getElementById('rescheduleModal');
    const modal = new bootstrap.Modal(modalEl);
    modal.show();
}

function openRescheduleModalById(id) {
    const item = allInterviews.find(i => i.id === id);
    if (item) openRescheduleModal(item);
}

function openRescheduleModalFromDetail() {
    if (!activeInterview) return;

    const detailModalEl = document.getElementById('detailModal');
    const bsDetailModal = bootstrap.Modal.getInstance(detailModalEl);
    if (bsDetailModal) bsDetailModal.hide();

    openRescheduleModal(activeInterview);
}

function handleRescheduleReasonChange() {
    const reasonSelect = document.getElementById('rescheduleReasonSelect');
    const customContainer = document.getElementById('customReasonContainer');
    
    if (reasonSelect.value === 'Other') {
        customContainer.classList.remove('d-none');
        document.getElementById('rescheduleCustomReason').focus();
    } else {
        customContainer.classList.add('d-none');
    }

    updateRescheduleSummaryDiff();
    updateLiveEmailPreview();
}

function setRescheduleDatePreset(daysAhead) {
    const d = new Date();
    d.setDate(d.getDate() + daysAhead);
    document.getElementById('rescheduleNewDate').value = formatDateYMD(d);
    onRescheduleScheduleChange();
}

function setRescheduleTimeSlot(start, end) {
    document.getElementById('rescheduleNewStartTime').value = start;
    document.getElementById('rescheduleNewEndTime').value = end;
    onRescheduleScheduleChange();
}

function onRescheduleScheduleChange() {
    updateRescheduleSummaryDiff();
    checkRescheduleLiveConflict();
    updateLiveEmailPreview();
}

function updateRescheduleSummaryDiff() {
    const oldStr = document.getElementById('rescheduleOldScheduleStr').value || '-';
    const newDate = document.getElementById('rescheduleNewDate').value || '-';
    const newStart = document.getElementById('rescheduleNewStartTime').value || '';
    const newEnd = document.getElementById('rescheduleNewEndTime').value || '';
    
    const reasonSelect = document.getElementById('rescheduleReasonSelect');
    let reasonText = reasonSelect ? reasonSelect.value : 'Interviewer unavailable';
    if (reasonText === 'Other') {
        const custom = document.getElementById('rescheduleCustomReason')?.value.trim();
        reasonText = custom ? `Other (${custom})` : 'Other';
    }

    document.getElementById('summaryPrevSchedule').textContent = oldStr;
    document.getElementById('summaryNewSchedule').textContent = `${newDate} from ${newStart} to ${newEnd}`;
    document.getElementById('summaryReasonText').textContent = reasonText;
}

function checkRescheduleLiveConflict() {
    const interviewerName = document.getElementById('rescheduleInterviewerName').value;
    const date = document.getElementById('rescheduleNewDate').value;
    const start = document.getElementById('rescheduleNewStartTime').value;
    const end = document.getElementById('rescheduleNewEndTime').value;
    const interviewId = document.getElementById('rescheduleInterviewId').value;
    const alertBox = document.getElementById('rescheduleConflictAlert');
    const alertText = document.getElementById('rescheduleConflictText');

    if (!interviewerName || !date || !start || !end || start >= end) {
        alertBox?.classList.add('d-none');
        return;
    }

    fetch('/api/interviews/check-conflict', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            interviewer_name: interviewerName,
            interview_date: date,
            start_time: start,
            end_time: end,
            exclude_id: interviewId
        })
    })
    .then(res => res.json())
    .then(data => {
        if (data.has_conflict && data.conflict) {
            alertText.textContent = `Conflict Detected: ${interviewerName} has another interview with ${data.conflict.candidate_name} from ${data.conflict.start_time} to ${data.conflict.end_time}.`;
            alertBox.classList.remove('d-none');
        } else {
            alertBox.classList.add('d-none');
        }
    })
    .catch(() => alertBox?.classList.add('d-none'));
}

function toggleEmailPreviewVisibility() {
    const checkbox = document.getElementById('rescheduleSendEmail');
    const previewBox = document.getElementById('emailPreviewBox');
    if (!checkbox.checked && previewBox) {
        previewBox.classList.add('d-none');
    }
}

function toggleEmailPreviewAccordion() {
    const previewBox = document.getElementById('emailPreviewBox');
    const toggleText = document.getElementById('emailPreviewToggleText');
    if (!previewBox) return;

    if (previewBox.classList.contains('d-none')) {
        previewBox.classList.remove('d-none');
        if (toggleText) toggleText.textContent = 'Hide Preview';
        updateLiveEmailPreview();
    } else {
        previewBox.classList.add('d-none');
        if (toggleText) toggleText.textContent = 'Preview Email';
    }
}

let previewDebounceTimer = null;
function updateLiveEmailPreview() {
    clearTimeout(previewDebounceTimer);
    previewDebounceTimer = setTimeout(() => {
        const candidateName = document.getElementById('rescheduleCandidateName').value || 'Candidate';
        const candidateEmail = document.getElementById('rescheduleCandidateEmail').value || 'candidate@example.com';
        const interviewType = document.getElementById('rescheduleInterviewType').value || 'Technical';
        const oldSchedule = document.getElementById('rescheduleOldScheduleStr').value || 'Previous Date & Time';
        const newDate = document.getElementById('rescheduleNewDate').value || 'New Date';
        const newStart = document.getElementById('rescheduleNewStartTime').value || '10:00';
        const newEnd = document.getElementById('rescheduleNewEndTime').value || '11:00';
        const interviewerName = document.getElementById('rescheduleInterviewerName').value || 'Interviewer';
        const locationLink = document.getElementById('rescheduleLocationLink').value || '';
        const notes = document.getElementById('rescheduleNotes').value || '';
        
        let reason = document.getElementById('rescheduleReasonSelect')?.value || 'Interviewer unavailable';
        if (reason === 'Other') {
            const custom = document.getElementById('rescheduleCustomReason')?.value.trim();
            reason = custom ? `Other: ${custom}` : 'Other';
        }

        const recipientBadge = document.getElementById('emailPreviewRecipient');
        if (recipientBadge) recipientBadge.textContent = `To: ${candidateEmail}`;

        fetch('/api/interviews/preview-email', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                candidate_name: candidateName,
                interview_type: interviewType,
                old_schedule: oldSchedule,
                new_date: newDate,
                new_start: newStart,
                new_end: newEnd,
                interviewer_name: interviewerName,
                location_link: locationLink,
                reason: reason,
                notes: notes
            })
        })
        .then(res => res.json())
        .then(data => {
            if (data.success && data.html) {
                const container = document.getElementById('renderedEmailPreviewContainer');
                if (container) {
                    container.innerHTML = `
                        <div class="mb-2 p-2 bg-white rounded border small">
                            <strong class="text-secondary">Subject:</strong> <span class="text-dark fw-bold">${escapeHtml(data.subject)}</span>
                        </div>
                        <div class="bg-white rounded border p-2" style="transform: scale(0.96); transform-origin: top left; width: 104%;">
                            ${data.html}
                        </div>
                    `;
                }
            }
        })
        .catch(err => console.log("Preview email notice:", err));
    }, 200);
}

function handleRescheduleFormSubmit(e) {
    e.preventDefault();

    const interviewId = document.getElementById('rescheduleInterviewId').value;
    const newDate = document.getElementById('rescheduleNewDate').value;
    const newStart = document.getElementById('rescheduleNewStartTime').value;
    const newEnd = document.getElementById('rescheduleNewEndTime').value;
    const reason = document.getElementById('rescheduleReasonSelect').value;
    const customReason = document.getElementById('rescheduleCustomReason').value.trim();
    const sendEmail = document.getElementById('rescheduleSendEmail').checked;
    const locationLink = document.getElementById('rescheduleLocationLink').value.trim();
    const notes = document.getElementById('rescheduleNotes').value.trim();

    if (!newDate || !newStart || !newEnd) {
        showWebsiteAlert("Missing Information", "Please specify the new interview date and time.", "warning");
        return;
    }

    if (newStart >= newEnd) {
        showWebsiteAlert("Invalid Time Slot", "Start time must be strictly before end time.", "warning");
        return;
    }

    if (reason === 'Other' && !customReason) {
        showWebsiteAlert("Reason Details Required", "Please specify the details for the 'Other' rescheduling reason.", "warning");
        return;
    }

    const submitBtn = document.getElementById('btnSubmitReschedule');
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.querySelector('.btn-text')?.classList.add('d-none');
        submitBtn.querySelector('.btn-spinner')?.classList.remove('d-none');
    }

    const payload = {
        new_date: newDate,
        new_start: newStart,
        new_end: newEnd,
        reason: reason,
        custom_reason: customReason,
        send_email: sendEmail,
        location_link: locationLink,
        notes: notes
    };

    fetch(`/api/interviews/reschedule/${interviewId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    })
    .then(res => res.json())
    .then(data => {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.querySelector('.btn-text')?.classList.remove('d-none');
            submitBtn.querySelector('.btn-spinner')?.classList.add('d-none');
        }

        if (data.success) {
            const modalEl = document.getElementById('rescheduleModal');
            const bsModal = bootstrap.Modal.getInstance(modalEl);
            if (bsModal) bsModal.hide();

            loadInterviews();
            if (window.loadGlobalNotifications) window.loadGlobalNotifications();

            const toastMsg = data.email_sent 
                ? `${data.message} Email notification dispatched to candidate.`
                : data.message;
            showWebsiteToast(toastMsg, 'success', 5000);
        } else if (data.has_conflict) {
            showConflictWarningModal(data.conflict);
        } else {
            showWebsiteAlert("Unable to Reschedule", data.message || "Failed to reschedule interview.", "danger");
        }
    })
    .catch(err => {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.querySelector('.btn-text')?.classList.remove('d-none');
            submitBtn.querySelector('.btn-spinner')?.classList.add('d-none');
        }
        console.error("Reschedule error:", err);
        showWebsiteAlert("Server Communication Error", "Could not connect to the server to update the interview schedule.", "danger");
    });
}

function cancelCurrentInterview() {
    if (!activeInterview) return;

    showWebsiteConfirm(
        "Cancel Interview?",
        `Are you sure you want to cancel the scheduled interview for ${activeInterview.candidate_name}?`,
        () => {
            fetch(`/api/interviews/cancel/${activeInterview.id}`, { method: 'POST' })
                .then(res => res.json())
                .then(data => {
                    if (data.success) {
                        const detailModalEl = document.getElementById('detailModal');
                        const bsDetailModal = bootstrap.Modal.getInstance(detailModalEl);
                        if (bsDetailModal) bsDetailModal.hide();

                        loadInterviews();
                        showWebsiteToast("Interview cancelled successfully.", "info");
                    } else {
                        showWebsiteAlert("Failed", data.message || "Failed to cancel interview.", "danger");
                    }
                })
                .catch(err => {
                    console.error("Cancel error:", err);
                    showWebsiteAlert("Error", "Error connecting to server.", "danger");
                });
        },
        "Yes, Cancel Interview",
        "danger"
    );
}

// -------------------------------------------------------------
// CALENDAR VIEW RENDERERS
// -------------------------------------------------------------
function switchView(viewName) {
    currentView = viewName;

    ['month', 'week', 'day', 'list'].forEach(v => {
        document.getElementById(`viewBtn${capitalize(v)}`)?.classList.remove('active');
        document.getElementById(`${v}ViewContainer`)?.classList.add('d-none');
    });

    document.getElementById(`viewBtn${capitalize(viewName)}`)?.classList.add('active');
    document.getElementById(`${viewName}ViewContainer`)?.classList.remove('d-none');

    renderCalendar();
}

function navigateDate(delta) {
    if (currentView === 'month') {
        currentDate.setMonth(currentDate.getMonth() + delta);
    } else if (currentView === 'week') {
        currentDate.setDate(currentDate.getDate() + (delta * 7));
    } else if (currentView === 'day') {
        currentDate.setDate(currentDate.getDate() + delta);
    }
    renderCalendar();
}

function goToToday() {
    currentDate = new Date();
    renderCalendar();
}

function updateTitleHeader() {
    const titleEl = document.getElementById('currentCalendarTitle');
    if (!titleEl) return;

    const monthNames = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
    
    if (currentView === 'month') {
        titleEl.textContent = `${monthNames[currentDate.getMonth()]} ${currentDate.getFullYear()}`;
    } else if (currentView === 'week') {
        const start = getStartOfWeek(currentDate);
        const end = new Date(start);
        end.setDate(end.getDate() + 6);
        titleEl.textContent = `${monthNames[start.getMonth()].substring(0, 3)} ${start.getDate()} - ${monthNames[end.getMonth()].substring(0, 3)} ${end.getDate()}, ${end.getFullYear()}`;
    } else if (currentView === 'day') {
        titleEl.textContent = `${monthNames[currentDate.getMonth()]} ${currentDate.getDate()}, ${currentDate.getFullYear()}`;
    } else if (currentView === 'list') {
        titleEl.textContent = "All Scheduled Interviews";
    }
}

// Month View
function renderMonthView() {
    const grid = document.getElementById('monthGridDays');
    if (!grid) return;
    grid.innerHTML = '';

    const year = currentDate.getFullYear();
    const month = currentDate.getMonth();

    const firstDay = new Date(year, month, 1);
    const lastDay = new Date(year, month + 1, 0);

    const startOffset = firstDay.getDay();
    const totalDays = lastDay.getDate();

    const prevMonthLastDay = new Date(year, month, 0).getDate();
    const todayStr = formatDateYMD(new Date());

    // Previous month filler days
    for (let i = startOffset - 1; i >= 0; i--) {
        const dayNum = prevMonthLastDay - i;
        const cell = document.createElement('div');
        cell.className = 'calendar-day-cell other-month';
        cell.innerHTML = `<div class="day-number">${dayNum}</div>`;
        grid.appendChild(cell);
    }

    // Current month days
    for (let day = 1; day <= totalDays; day++) {
        const dateObj = new Date(year, month, day);
        const dateStr = formatDateYMD(dateObj);
        const isToday = (dateStr === todayStr);

        const cell = document.createElement('div');
        cell.className = `calendar-day-cell ${isToday ? 'today-cell' : ''}`;
        
        let headerHtml = `<div class="day-number">
            <span>${day}</span>
            ${isToday ? '<span class="today-badge">Today</span>' : ''}
        </div>`;
        cell.innerHTML = headerHtml;

        // Add Interview chips
        const dayInterviews = filteredInterviews.filter(i => i.interview_date === dateStr);
        dayInterviews.forEach(item => {
            const statusClass = (item.status || 'scheduled').toLowerCase().replace(/\s+/g, '-');
            const isReq = (item.status === 'Reschedule Requested');
            const chip = document.createElement('div');
            chip.className = `interview-chip status-${statusClass}`;
            chip.title = `${item.start_time} - ${item.candidate_name} (${item.interview_type}) [${item.status}]`;
            chip.innerHTML = `
                <i class="fa-solid ${isReq ? 'fa-hourglass-half text-warning' : 'fa-circle small'}" style="font-size: ${isReq ? '0.65rem' : '0.45rem'};"></i>
                <span class="fw-bold">${item.start_time}</span>
                <span>${escapeHtml(item.candidate_name)}</span>
            `;
            chip.onclick = (e) => {
                e.stopPropagation();
                openDetailModal(item);
            };
            cell.appendChild(chip);
        });

        // Click cell to schedule on that day
        cell.onclick = () => openScheduleModal(null, dateStr);
        grid.appendChild(cell);
    }

    // Next month filler days to complete 7-col grid
    const totalRendered = startOffset + totalDays;
    const remaining = (7 - (totalRendered % 7)) % 7;
    for (let j = 1; j <= remaining; j++) {
        const cell = document.createElement('div');
        cell.className = 'calendar-day-cell other-month';
        cell.innerHTML = `<div class="day-number">${j}</div>`;
        grid.appendChild(cell);
    }
}

// Week View
function renderWeekView() {
    const container = document.getElementById('weekViewGrid');
    if (!container) return;
    container.innerHTML = '';

    const startOfWeek = getStartOfWeek(currentDate);
    const dayNames = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
    const todayStr = formatDateYMD(new Date());

    let headerHtml = `<div class="d-flex bg-light border-bottom">
        <div style="width: 80px; flex-shrink: 0;" class="p-2 fw-bold text-muted small text-center border-end">Time</div>`;
    
    for (let d = 0; d < 7; d++) {
        const dObj = new Date(startOfWeek);
        dObj.setDate(dObj.getDate() + d);
        const dStr = formatDateYMD(dObj);
        const isToday = (dStr === todayStr);

        headerHtml += `
            <div class="flex-grow-1 p-2 text-center border-end ${isToday ? 'bg-primary text-white' : 'text-dark'}" style="min-width: 120px;">
                <div class="fw-bold fs-6">${dayNames[d]}</div>
                <div class="small">${dObj.getDate()}</div>
            </div>
        `;
    }
    headerHtml += `</div>`;
    container.innerHTML = headerHtml;

    // Time Slots 08:00 to 19:00
    for (let hour = 8; hour <= 19; hour++) {
        const timeStr = `${String(hour).padStart(2, '0')}:00`;
        let slotRow = document.createElement('div');
        slotRow.className = 'time-slot-row';
        slotRow.innerHTML = `<div class="time-label text-center">${timeStr}</div>`;

        for (let d = 0; d < 7; d++) {
            const dObj = new Date(startOfWeek);
            dObj.setDate(dObj.getDate() + d);
            const dStr = formatDateYMD(dObj);

            const dayCell = document.createElement('div');
            dayCell.className = 'flex-grow-1 border-end time-slot-content';
            dayCell.style.minWidth = '120px';

            const slotInterviews = filteredInterviews.filter(i => {
                if (i.interview_date !== dStr) return false;
                const slotHour = parseInt(i.start_time.split(':')[0]);
                return slotHour === hour;
            });

            slotInterviews.forEach(item => {
                const statusClass = (item.status || 'scheduled').toLowerCase().replace(/\s+/g, '-');
                const isReq = (item.status === 'Reschedule Requested');
                const chip = document.createElement('div');
                chip.className = `interview-chip status-${statusClass}`;
                chip.innerHTML = `${isReq ? '<i class="fa-solid fa-hourglass-half text-warning me-1"></i>' : ''}<strong>${item.start_time}</strong> ${escapeHtml(item.candidate_name)}`;
                chip.onclick = (e) => {
                    e.stopPropagation();
                    openDetailModal(item);
                };
                dayCell.appendChild(chip);
            });

            dayCell.onclick = () => openScheduleModal(null, dStr);
            slotRow.appendChild(dayCell);
        }

        container.appendChild(slotRow);
    }
}

// Day View
function renderDayView() {
    const container = document.getElementById('dayViewTimeline');
    if (!container) return;
    container.innerHTML = '';

    const dStr = formatDateYMD(currentDate);

    for (let hour = 8; hour <= 20; hour++) {
        const timeStr = `${String(hour).padStart(2, '0')}:00`;
        const nextTimeStr = `${String(hour + 1).padStart(2, '0')}:00`;

        const row = document.createElement('div');
        row.className = 'time-slot-row';
        row.innerHTML = `<div class="time-label">${timeStr}</div>`;

        const content = document.createElement('div');
        content.className = 'time-slot-content';

        const slotInterviews = filteredInterviews.filter(i => {
            if (i.interview_date !== dStr) return false;
            const slotHour = parseInt(i.start_time.split(':')[0]);
            return slotHour === hour;
        });

        slotInterviews.forEach(item => {
            const statusClass = (item.status || 'scheduled').toLowerCase().replace(/\s+/g, '-');
            const card = document.createElement('div');
            card.className = `p-2 rounded-2 border d-flex justify-content-between align-items-center status-${statusClass}`;
            card.style.cursor = 'pointer';
            card.innerHTML = `
                <div>
                    <strong class="d-block">${escapeHtml(item.candidate_name)} (${item.interview_type})</strong>
                    <small class="text-muted"><i class="fa-solid fa-clock me-1"></i>${item.start_time} - ${item.end_time} &bull; <i class="fa-solid fa-user-tie me-1"></i>${escapeHtml(item.interviewer_name)}</small>
                </div>
                ${getStatusBadgeHtml(item.status)}
            `;
            card.onclick = () => openDetailModal(item);
            content.appendChild(card);
        });

        content.onclick = (e) => {
            if (e.target === content) openScheduleModal(null, dStr);
        };

        row.appendChild(content);
        container.appendChild(row);
    }
}

// List View
function renderListView() {
    const tbody = document.getElementById('interviewTableBody');
    if (!tbody) return;
    tbody.innerHTML = '';

    if (filteredInterviews.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="7" class="text-center py-5 text-muted">
                    <i class="fa-solid fa-calendar-xmark fs-2 mb-2 d-block text-secondary opacity-50"></i>
                    No interviews found matching your criteria.
                </td>
            </tr>
        `;
        return;
    }

    filteredInterviews.forEach(item => {
        const isReq = (item.status === 'Reschedule Requested');
        const tr = document.createElement('tr');
        if (isReq) tr.style.background = '#f8fafc';
        tr.innerHTML = `
            <td>
                <strong class="text-dark d-block">${escapeHtml(item.candidate_name)}</strong>
                <small class="text-muted">${escapeHtml(item.candidate_email || '')} (ID: #${item.candidate_id})</small>
            </td>
            <td>
                <div class="fw-semibold text-dark"><i class="fa-regular fa-calendar text-primary me-1"></i> ${item.interview_date}</div>
                <small class="text-muted"><i class="fa-regular fa-clock text-secondary me-1"></i> ${item.start_time} - ${item.end_time}</small>
            </td>
            <td><span class="badge bg-light text-dark border">${escapeHtml(item.interview_type || 'Technical')}</span></td>
            <td>
                <div class="fw-semibold text-dark">${escapeHtml(item.interviewer_name)}</div>
                <small class="text-muted">${escapeHtml(item.interviewer_email || '-')}</small>
            </td>
            <td>
                ${item.location_link && item.location_link.startsWith('http') 
                    ? `<a href="${escapeHtml(item.location_link)}" target="_blank" class="btn btn-sm btn-outline-primary py-0 px-2"><i class="fa-solid fa-video me-1"></i> Meeting Link</a>` 
                    : `<span class="small text-muted">${escapeHtml(item.location_link || 'In-Person')}</span>`}
            </td>
            <td>${getStatusBadgeHtml(item.status)}</td>
            <td class="text-end">
                <div class="btn-group btn-group-sm">
                    ${isReq ? `
                        <button class="btn btn-primary btn-sm fw-bold px-2.5" onclick="openDetailModalById(${item.id})" title="Review Reschedule Request"><i class="fa-solid fa-clock-rotate-left me-1"></i> Review Request</button>
                        <button class="btn btn-outline-primary btn-sm" onclick="openRescheduleModalById(${item.id})" title="Set New Schedule"><i class="fa-solid fa-calendar-check"></i></button>
                    ` : `
                        <button class="btn btn-outline-secondary" onclick="openDetailModalById(${item.id})" title="View Details"><i class="fa-solid fa-eye"></i></button>
                        <button class="btn btn-outline-primary" onclick="openRescheduleModalById(${item.id})" title="Reschedule Interview"><i class="fa-solid fa-calendar-rotate-left"></i></button>
                        <button class="btn btn-outline-secondary" onclick="openEditModalById(${item.id})" title="Edit Details"><i class="fa-solid fa-pen"></i></button>
                    `}
                </div>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

// -------------------------------------------------------------
// IN-PAGE WEBSITE POPUPS, TOASTS & MODALS (Zero browser alert/confirm)
// -------------------------------------------------------------
function showWebsiteToast(msg, type = 'info', duration = 3500) {
    const container = document.getElementById('websiteToastContainer');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `custom-toast toast-${type}`;

    let iconClass = 'fa-circle-info text-primary';
    if (type === 'success') iconClass = 'fa-circle-check text-success';
    else if (type === 'error' || type === 'danger') iconClass = 'fa-circle-exclamation text-danger';
    else if (type === 'warning') iconClass = 'fa-triangle-exclamation text-warning';

    toast.innerHTML = `
        <i class="fa-solid ${iconClass} fs-5 flex-shrink-0"></i>
        <div class="flex-grow-1 text-dark small fw-semibold">${escapeHtml(msg)}</div>
        <button type="button" class="btn-close btn-sm ms-2" aria-label="Close"></button>
    `;

    const closeBtn = toast.querySelector('.btn-close');
    closeBtn.onclick = () => removeToast(toast);

    container.appendChild(toast);

    setTimeout(() => {
        removeToast(toast);
    }, duration);
}

function removeToast(toast) {
    toast.style.animation = 'toastSlideOut 0.25s forwards';
    setTimeout(() => {
        toast.remove();
    }, 250);
}

function showWebsiteAlert(title, message, type = 'info') {
    const titleEl = document.getElementById('websiteAlertTitle');
    const msgEl = document.getElementById('websiteAlertMessage');
    const iconBox = document.getElementById('websiteAlertIconBox');
    const iconEl = document.getElementById('websiteAlertIcon');

    if (titleEl) titleEl.textContent = title;
    if (msgEl) msgEl.textContent = message;

    if (iconBox && iconEl) {
        if (type === 'danger' || type === 'error') {
            iconBox.style.background = '#fee2e2';
            iconBox.style.color = '#ef4444';
            iconEl.className = 'fa-solid fa-circle-exclamation';
        } else if (type === 'warning') {
            iconBox.style.background = '#fef3c7';
            iconBox.style.color = '#d97706';
            iconEl.className = 'fa-solid fa-triangle-exclamation';
        } else if (type === 'success') {
            iconBox.style.background = '#dcfce7';
            iconBox.style.color = '#16a34a';
            iconEl.className = 'fa-solid fa-circle-check';
        } else {
            iconBox.style.background = '#eff6ff';
            iconBox.style.color = '#2563eb';
            iconEl.className = 'fa-solid fa-circle-info';
        }
    }

    const modalEl = document.getElementById('websiteAlertModal');
    if (modalEl) {
        const bsModal = new bootstrap.Modal(modalEl);
        bsModal.show();
    }
}

function showWebsiteConfirm(titleOrOptions, message, onConfirm, okText = 'Confirm', type = 'danger') {
    let title = 'Confirm Action';
    if (typeof titleOrOptions === 'object' && titleOrOptions !== null) {
        title = titleOrOptions.title || title;
        message = titleOrOptions.message || '';
        onConfirm = titleOrOptions.onConfirm;
        okText = titleOrOptions.confirmText || titleOrOptions.okText || 'Confirm';
        type = titleOrOptions.type || (titleOrOptions.confirmBtnClass && titleOrOptions.confirmBtnClass.includes('primary') ? 'primary' : 'danger');
    } else {
        title = titleOrOptions || title;
    }

    const titleEl = document.getElementById('websiteConfirmTitle');
    const msgEl = document.getElementById('websiteConfirmMessage');
    const okBtn = document.getElementById('websiteConfirmOkBtn');
    const iconBox = document.getElementById('websiteConfirmIconBox');
    const iconEl = document.getElementById('websiteConfirmIcon');

    if (titleEl) titleEl.textContent = title;
    if (msgEl) msgEl.textContent = message;

    if (okBtn) {
        okBtn.textContent = okText;
        okBtn.className = `btn btn-primary px-3 fw-bold`;
        okBtn.style.backgroundColor = '#2563eb';
        okBtn.style.borderColor = '#1d4ed8';
        okBtn.style.color = '#ffffff';
    }

    if (iconBox && iconEl) {
        iconBox.style.background = '#eff6ff';
        iconBox.style.color = '#2563eb';
        iconBox.style.border = '1.5px solid #bfdbfe';
        iconEl.className = 'fa-solid fa-circle-question';
    }

    const modalEl = document.getElementById('websiteConfirmModal');
    if (!modalEl) return;

    const bsModal = new bootstrap.Modal(modalEl);

    // Set one-time click listener on confirm button
    const handleOk = () => {
        okBtn.removeEventListener('click', handleOk);
        bsModal.hide();
        if (typeof onConfirm === 'function') {
            onConfirm();
        }
    };

    // Clean old listeners by cloning
    const newOkBtn = okBtn.cloneNode(true);
    okBtn.parentNode.replaceChild(newOkBtn, okBtn);
    newOkBtn.addEventListener('click', handleOk);

    bsModal.show();
}

// -------------------------------------------------------------
// UTILS & HELPERS
// -------------------------------------------------------------
function formatDateYMD(d) {
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

function getStartOfWeek(d) {
    const date = new Date(d);
    const day = date.getDay();
    const diff = date.getDate() - day;
    return new Date(date.setDate(diff));
}

function getStatusBadgeHtml(status) {
    const rawStatus = (status || 'Scheduled').trim();
    const st = rawStatus.toLowerCase().replace(/\s+/g, '-');
    let icon = 'fa-calendar-check';
    if (st === 'rescheduled') icon = 'fa-arrows-rotate';
    else if (st === 'reschedule-requested') icon = 'fa-hourglass-half';
    else if (st === 'completed') icon = 'fa-circle-check';
    else if (st === 'cancelled') icon = 'fa-ban';
    else if (st === 'pending') icon = 'fa-clock';

    return `<span class="badge status-${st}"><i class="fa-solid ${icon} me-1"></i> ${escapeHtml(rawStatus)}</span>`;
}

function getInitials(name) {
    if (!name) return 'C';
    const parts = name.trim().split(/\s+/);
    if (parts.length >= 2) {
        return (parts[0][0] + parts[1][0]).toUpperCase();
    }
    return name.substring(0, 2).toUpperCase();
}

function capitalize(str) {
    if (!str) return '';
    return str.charAt(0).toUpperCase() + str.slice(1);
}

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}
