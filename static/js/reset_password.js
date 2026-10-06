/* ==========================================================================
   RESET & CHANGE PASSWORD INTERACTIVE SCRIPTS
   ========================================================================== */

document.addEventListener("DOMContentLoaded", () => {
    const newPwInput = document.getElementById("new_password");
    const confirmPwInput = document.getElementById("confirm_password");
    const toggleNewPw = document.getElementById("toggleNewPassword");
    const toggleConfirmPw = document.getElementById("toggleConfirmPassword");
    const strengthText = document.getElementById("strengthText");
    const matchText = document.getElementById("passwordMessage") || document.getElementById("passwordMatch");
    const updateBtn = document.getElementById("resetButton") || document.getElementById("updateButton") || document.getElementById("savePasswordBtn");

    // Password visibility toggles
    if (toggleNewPw && newPwInput) {
        toggleNewPw.addEventListener("click", () => {
            const isPassword = newPwInput.type === "password";
            newPwInput.type = isPassword ? "text" : "password";
            toggleNewPw.querySelector("i").className = isPassword ? "fa-solid fa-eye-slash" : "fa-solid fa-eye";
        });
    }

    if (toggleConfirmPw && confirmPwInput) {
        toggleConfirmPw.addEventListener("click", () => {
            const isPassword = confirmPwInput.type === "password";
            confirmPwInput.type = isPassword ? "text" : "password";
            toggleConfirmPw.querySelector("i").className = isPassword ? "fa-solid fa-eye-slash" : "fa-solid fa-eye";
        });
    }

    // Live strength evaluation
    function checkStrength() {
        if (!newPwInput) return;
        const val = newPwInput.value;

        const hasLength = val.length >= 8;
        const hasUpper = /[A-Z]/.test(val) && /[a-z]/.test(val);
        const hasNumber = /[0-9]/.test(val);
        const hasSpecial = /[^A-Za-z0-9]/.test(val);

        if (reqLen) reqLen.className = hasLength ? "valid" : "";
        if (reqUpper) reqUpper.className = hasUpper ? "valid" : "";
        if (reqNum) reqNum.className = hasNumber ? "valid" : "";
        if (reqSpecial) reqSpecial.className = hasSpecial ? "valid" : "";

        let score = 0;
        if (hasLength) score++;
        if (hasUpper) score++;
        if (hasNumber) score++;
        if (hasSpecial) score++;

        const bars = [strBar1, strBar2, strBar3, strBar4];
        bars.forEach((bar, idx) => {
            if (bar) {
                bar.className = "";
                if (idx < score) {
                    if (score <= 2) bar.classList.add("weak");
                    else if (score === 3) bar.classList.add("medium");
                    else bar.classList.add("strong");
                }
            }
        });

        if (strengthText) {
            if (val.length === 0) strengthText.innerText = "Enter password";
            else if (score <= 2) strengthText.innerText = "Weak password";
            else if (score === 3) strengthText.innerText = "Medium strength password";
            else strengthText.innerText = "Strong password";
        }
    }

    function checkMatch() {
        if (!newPwInput || !confirmPwInput || !matchText) return;
        if (!confirmPwInput.value) {
            matchText.innerText = "";
            return;
        }
        if (newPwInput.value === confirmPwInput.value) {
            matchText.style.color = "#10b981";
            matchText.innerText = "Passwords match ✓";
        } else {
            matchText.style.color = "#ef4444";
            matchText.innerText = "Passwords do not match ✕";
        }
    }

    if (newPwInput) {
        newPwInput.addEventListener("input", () => {
            checkStrength();
            checkMatch();
        });
    }

    if (confirmPwInput) {
        confirmPwInput.addEventListener("input", checkMatch);
    }

    if (resetForm && updateBtn) {
        resetForm.addEventListener("submit", () => {
            updateBtn.classList.add("loading");
            updateBtn.disabled = true;
        });
    }

    /* 3D PARALLAX MOUSE TILT */
    const authCard = document.querySelector(".login-card-3d") || document.querySelector(".auth-card");
    const authPage = document.querySelector(".login-full-wrapper") || document.querySelector(".auth-page");

    if (authCard && authPage) {
        document.body.addEventListener("mousemove", (e) => {
            const rect = authPage.getBoundingClientRect();
            const x = e.clientX - rect.left - rect.width / 2;
            const y = e.clientY - rect.top - rect.height / 2;
            const rotateX = (y / (rect.height / 2)) * -6;
            const rotateY = (x / (rect.width / 2)) * 6;

            authCard.style.transform = `perspective(1000px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) translateY(-4px)`;
        });

        document.body.addEventListener("mouseleave", () => {
            authCard.style.transform = "perspective(1000px) rotateX(0deg) rotateY(0deg) translateY(0px)";
        });
    }
});
