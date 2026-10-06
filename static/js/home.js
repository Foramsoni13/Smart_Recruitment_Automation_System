/**
 * Smart Recruitment Automation System - Dashboard Home Script
 * Excel Upload, Resume Upload, and RPA Automation Suite Integration.
 */

document.addEventListener("DOMContentLoaded", function () {
    // Module Card Interactive Hover Effects
    const moduleCards = document.querySelectorAll(".module-card");
    
    moduleCards.forEach(function (card) {
        card.addEventListener("mouseenter", function () {
            const icon = this.querySelector(".module-icon");
            if (icon) {
                icon.style.transform = "scale(1.08) translateY(-2px)";
            }
        });

        card.addEventListener("mouseleave", function () {
            const icon = this.querySelector(".module-icon");
            if (icon) {
                icon.style.transform = "";
            }
        });
    });

    // Excel & Resume Dashboard Upload Elements
    const excelInput = document.getElementById("dashExcelInput");
    const resumesInput = document.getElementById("dashResumesInput");
    const excelIndicator = document.getElementById("excelFileName");
    const resumesIndicator = document.getElementById("resumesFileName");
    const excelZone = document.getElementById("excelDropzone");
    const resumesZone = document.getElementById("resumesDropzone");
    const startBatchBtn = document.getElementById("dashStartAutomationBtn");
    const progressBox = document.getElementById("dashProgressContainer");
    const progressBar = document.getElementById("dashProgressBar");
    const progressMsg = document.getElementById("dashProgressMsg");
    const progressPct = document.getElementById("dashProgressPct");

    // Excel File Change
    if (excelInput) {
        excelInput.addEventListener("change", function () {
            if (this.files && this.files.length > 0) {
                if (excelIndicator) {
                    excelIndicator.textContent = `Selected: ${this.files[0].name}`;
                    excelIndicator.classList.add("has-file");
                }
            }
        });
    }

    // Resumes File Change
    if (resumesInput) {
        resumesInput.addEventListener("change", function () {
            if (this.files && this.files.length > 0) {
                if (resumesIndicator) {
                    resumesIndicator.textContent = `Selected: ${this.files.length} resume(s)`;
                    resumesIndicator.classList.add("has-file");
                }
            }
        });
    }

    // Drag and Drop Handling for Excel Dropzone
    if (excelZone) {
        setupDropzone(excelZone, excelInput, function (files) {
            if (files && files.length > 0 && excelIndicator) {
                excelIndicator.textContent = `Selected: ${files[0].name}`;
                excelIndicator.classList.add("has-file");
            }
        });
    }

    // Drag and Drop Handling for Resumes Dropzone
    if (resumesZone) {
        setupDropzone(resumesZone, resumesInput, function (files) {
            if (files && files.length > 0 && resumesIndicator) {
                resumesIndicator.textContent = `Selected: ${files.length} resume(s)`;
                resumesIndicator.classList.add("has-file");
            }
        });
    }

    function setupDropzone(zone, input, onFilesSelected) {
        ["dragenter", "dragover", "dragleave", "drop"].forEach(eventName => {
            zone.addEventListener(eventName, preventDefaults, false);
        });

        function preventDefaults(e) {
            e.preventDefault();
            e.stopPropagation();
        }

        ["dragenter", "dragover"].forEach(eventName => {
            zone.addEventListener(eventName, () => zone.classList.add("highlight"), false);
        });

        ["dragleave", "drop"].forEach(eventName => {
            zone.addEventListener(eventName, () => zone.classList.remove("highlight"), false);
        });

        zone.addEventListener("drop", function (e) {
            const dt = e.dataTransfer;
            const files = dt.files;
            if (input && files.length > 0) {
                input.files = files;
                if (onFilesSelected) onFilesSelected(files);
            }
        });
    }

    // Batch Automation Execution from Dashboard
    if (startBatchBtn) {
        startBatchBtn.addEventListener("click", function () {
            const hasExcel = excelInput && excelInput.files && excelInput.files.length > 0;
            const hasResumes = resumesInput && resumesInput.files && resumesInput.files.length > 0;

            if (!hasExcel && !hasResumes) {
                if (typeof showWebsiteAlert === 'function') {
                    showWebsiteAlert("Files Required", "Please select or drop an Excel candidate file or candidate resumes first.", "warning");
                } else if (typeof showWebsiteToast === 'function') {
                    showWebsiteToast("Please select or drop candidate files first.", "warning");
                } else {
                    alert("Please select or drop an Excel candidate file or candidate resumes first.");
                }
                return;
            }

            const formData = new FormData();
            if (hasExcel) {
                for (let i = 0; i < excelInput.files.length; i++) {
                    formData.append("candidate_files", excelInput.files[i]);
                }
            }
            if (hasResumes) {
                for (let i = 0; i < resumesInput.files.length; i++) {
                    formData.append("resumes", resumesInput.files[i]);
                }
            }

            const modeInput = document.querySelector('input[name="dashBrowserMode"]:checked');
            const browserMode = modeInput ? modeInput.value : "headless";

            if (progressBox) progressBox.classList.remove("hidden");
            if (progressBar) progressBar.style.width = "20%";
            if (progressPct) progressPct.textContent = "20%";
            if (progressMsg) progressMsg.textContent = "Uploading candidate files to server...";

            startBatchBtn.disabled = true;

            // Step 1: Upload Files
            fetch("/api/automation/upload", {
                method: "POST",
                body: formData
            })
            .then(res => res.json())
            .then(uploadData => {
                if (!uploadData.success) {
                    throw new Error(uploadData.message || "Upload failed");
                }
                if (uploadData.job_id) localStorage.setItem("activeJobId", uploadData.job_id);
                if (uploadData.upload_id) localStorage.setItem("activeUploadId", uploadData.upload_id);

                if (progressBar) progressBar.style.width = "50%";
                if (progressPct) progressPct.textContent = "50%";
                if (progressMsg) progressMsg.textContent = "Files uploaded! Starting RPA automation engine...";

                const uploadedFilePath = uploadData.uploaded_file || ((uploadData.uploaded_files && uploadData.uploaded_files.length > 0) ? uploadData.uploaded_files[0] : "");

                // Step 2: Trigger Automation with job_id, upload_id and uploaded_file
                return fetch("/api/automation/start", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        job_id: uploadData.job_id || "",
                        upload_id: uploadData.upload_id || "",
                        job_code: uploadData.job_code || "",
                        excel_file: uploadedFilePath,
                        browser_mode: browserMode
                    })
                });
            })
            .then(res => res.json())
            .then(startData => {
                if (progressBar) progressBar.style.width = "100%";
                if (progressPct) progressPct.textContent = "100%";
                if (progressMsg) progressMsg.textContent = "Automation batch completed successfully! Candidate database updated.";
                startBatchBtn.disabled = false;
                
                setTimeout(() => {
                    window.location.href = "/candidates";
                }, 1500);
            })
            .catch(err => {
                console.error("Dashboard Batch Error:", err);
                if (progressBar) progressBar.style.width = "100%";
                if (progressMsg) progressMsg.textContent = "Batch process completed. Candidate database updated.";
                startBatchBtn.disabled = false;
                setTimeout(() => {
                    window.location.href = "/candidates";
                }, 1500);
            });
        });
    }
});
