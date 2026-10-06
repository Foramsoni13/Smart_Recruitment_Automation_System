/**
 * SMART RECRUITMENT AUTOMATION SYSTEM - RESUME SCANNER JAVASCRIPT
 */

document.addEventListener("DOMContentLoaded", function () {
    const dropZone = document.getElementById("dropZone");
    const resumeFileInput = document.getElementById("resumeFileInput");
    const uploadSection = document.getElementById("uploadSection");
    const progressSection = document.getElementById("progressSection");
    const resultSection = document.getElementById("resultSection");
    const scanAgainBtn = document.getElementById("scanAgainBtn");
    
    const scannerErrorBanner = document.getElementById("scannerErrorBanner");
    const errorMessage = document.getElementById("errorMessage");
    const closeErrorBanner = document.getElementById("closeErrorBanner");

    // Drag and Drop Events
    if (dropZone) {
        ['dragenter', 'dragover'].forEach(eventName => {
            dropZone.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
                dropZone.classList.add('dragover');
            }, false);
        });

        ['dragleave', 'drop'].forEach(eventName => {
            dropZone.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
                dropZone.classList.remove('dragover');
            }, false);
        });

        dropZone.addEventListener('drop', (e) => {
            const dt = e.dataTransfer;
            const files = dt.files;
            if (files && files.length > 0) {
                handleResumeUpload(files[0]);
            }
        });

        dropZone.addEventListener('click', (e) => {
            if (e.target !== resumeFileInput && !e.target.closest('.btn-choose-file')) {
                if (resumeFileInput) resumeFileInput.click();
            }
        });
    }

    if (resumeFileInput) {
        resumeFileInput.addEventListener('change', function () {
            if (this.files && this.files.length > 0) {
                handleResumeUpload(this.files[0]);
            }
        });
    }

    if (closeErrorBanner) {
        closeErrorBanner.addEventListener('click', () => {
            if (scannerErrorBanner) scannerErrorBanner.classList.add('hidden');
        });
    }

    if (scanAgainBtn) {
        scanAgainBtn.addEventListener('click', resetScannerUI);
    }

    function handleResumeUpload(file) {
        if (!file) return;

        const validTypes = ['.pdf', '.doc', '.docx'];
        const fileName = file.name.toLowerCase();
        const isValid = validTypes.some(ext => fileName.endsWith(ext));

        if (!isValid) {
            showError("Unsupported resume format. Please upload PDF, DOC, or DOCX file.");
            return;
        }

        hideError();

        // Show progress view
        if (uploadSection) uploadSection.classList.add('hidden');
        if (resultSection) resultSection.classList.add('hidden');
        if (progressSection) progressSection.classList.remove('hidden');

        // FormData upload
        const formData = new FormData();
        formData.append('resume', file);

        // Tracker animation step 1
        setTrackerStep('stepUpload', true);

        fetch('/api/resume-scanner/upload', {
            method: 'POST',
            body: formData
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                setTrackerStep('stepProcess', true);
                setTimeout(() => {
                    setTrackerStep('stepExtract', true);
                    setTimeout(() => {
                        renderExtractedCandidate(data.candidate);
                    }, 400);
                }, 400);
            } else {
                showError(data.message || "Failed to process resume file.");
                resetScannerUI();
            }
        })
        .catch(err => {
            console.error("Resume upload error:", err);
            showError("An unexpected error occurred during resume parsing.");
            resetScannerUI();
        });
    }

    function renderExtractedCandidate(cand) {
        if (!cand) return;

        if (progressSection) progressSection.classList.add('hidden');
        if (resultSection) resultSection.classList.remove('hidden');

        setText('resCandidateName', cand.name || 'Candidate Name');
        setText('resCandidatePosition', cand.position || 'Software Engineer');
        setText('resCandidateEmail', cand.email || '-');
        setText('resCandidatePhone', cand.phone || '-');
        setText('resCandidateExperience', cand.experience || 'Not detected');
        setText('resCandidateEducation', cand.education || 'Not detected');
        setText('resCandidateFilename', cand.resume_filename || 'resume.pdf');

        const viewBtn = document.getElementById('resViewResumeBtn');
        if (viewBtn) {
            if (cand.resume_url) {
                viewBtn.href = cand.resume_url;
                viewBtn.style.display = 'inline-flex';
            } else {
                viewBtn.style.display = 'none';
            }
        }

        const skillsContainer = document.getElementById('resCandidateSkills');
        if (skillsContainer) {
            skillsContainer.innerHTML = '';
            let skillsList = cand.skills;
            if (typeof skillsList === 'string') {
                skillsList = skillsList.split(',').map(s => s.trim()).filter(Boolean);
            }
            if (!skillsList || skillsList.length === 0) {
                skillsList = (cand.skills_str || '').split(',').map(s => s.trim()).filter(Boolean);
            }
            if (!skillsList || skillsList.length === 0) {
                skillsList = ['Parsed Entity'];
            }

            skillsList.forEach(skill => {
                const pill = document.createElement('span');
                pill.className = 'skill-pill';
                pill.textContent = skill;
                skillsContainer.appendChild(pill);
            });
        }
    }

    function resetScannerUI() {
        if (resultSection) resultSection.classList.add('hidden');
        if (progressSection) progressSection.classList.add('hidden');
        if (uploadSection) uploadSection.classList.remove('hidden');
        if (resumeFileInput) resumeFileInput.value = '';
    }

    function setTrackerStep(stepId, isActive) {
        const el = document.getElementById(stepId);
        if (el) {
            if (isActive) {
                el.classList.add('step-active');
            } else {
                el.classList.remove('step-active');
            }
        }
    }

    function showError(msg) {
        if (errorMessage) errorMessage.textContent = msg;
        if (scannerErrorBanner) scannerErrorBanner.classList.remove('hidden');
    }

    function hideError() {
        if (scannerErrorBanner) scannerErrorBanner.classList.add('hidden');
    }

    function setText(id, val) {
        const el = document.getElementById(id);
        if (el) el.textContent = val;
    }
});
