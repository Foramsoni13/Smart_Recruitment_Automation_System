/* ==========================================================================
   REGISTER INTERACTIVE SCRIPTS
   ========================================================================== */

document.addEventListener("DOMContentLoaded", () => {
    const pwInput = document.getElementById("password");
    const confirmInput = document.getElementById("confirmPassword");
    const togglePw = document.getElementById("togglePassword");
    const toggleConfirmPw = document.getElementById("toggleConfirmPassword");

    const strBar1 = document.getElementById("strBar1");
    const strBar2 = document.getElementById("strBar2");
    const strBar3 = document.getElementById("strBar3");
    const strBar4 = document.getElementById("strBar4");
    const strText = document.getElementById("strengthText");
    const pwMsg = document.getElementById("passwordMessage");
    const regForm = document.getElementById("registerForm");
    const regBtn = document.getElementById("registerButton");

    if (togglePw && pwInput) {
        togglePw.addEventListener("click", () => {
            const isPassword = pwInput.type === "password";
            pwInput.type = isPassword ? "text" : "password";
            togglePw.querySelector("i").className = isPassword ? "fa-solid fa-eye-slash" : "fa-solid fa-eye";
        });
    }

    if (toggleConfirmPw && confirmInput) {
        toggleConfirmPw.addEventListener("click", () => {
            const isPassword = confirmInput.type === "password";
            confirmInput.type = isPassword ? "text" : "password";
            toggleConfirmPw.querySelector("i").className = isPassword ? "fa-solid fa-eye-slash" : "fa-solid fa-eye";
        });
    }

    function checkStrength() {
        if (!pwInput) return;
        const val = pwInput.value;

        const hasLength = val.length >= 8;
        const hasUpper = /[A-Z]/.test(val) && /[a-z]/.test(val);
        const hasNumber = /[0-9]/.test(val);
        const hasSpecial = /[^A-Za-z0-9]/.test(val);

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

        if (strText) {
            if (val.length === 0) strText.innerText = "Enter password";
            else if (score <= 2) strText.innerText = "Weak password";
            else if (score === 3) strText.innerText = "Medium strength password";
            else strText.innerText = "Strong password";
        }
    }

    function checkMatch() {
        if (!pwInput || !confirmInput || !pwMsg) return;
        if (!confirmInput.value) {
            pwMsg.innerText = "";
            return;
        }
        if (pwInput.value === confirmInput.value) {
            pwMsg.style.color = "#10b981";
            pwMsg.innerText = "Passwords match ✓";
        } else {
            pwMsg.style.color = "#ef4444";
            pwMsg.innerText = "Passwords do not match ✕";
        }
    }

    if (pwInput) {
        pwInput.addEventListener("input", () => {
            checkStrength();
            checkMatch();
        });
    }

    if (confirmInput) {
        confirmInput.addEventListener("input", checkMatch);
    }

    if (regForm && regBtn) {
        regForm.addEventListener("submit", () => {
            regBtn.classList.add("loading");
            regBtn.disabled = true;
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
