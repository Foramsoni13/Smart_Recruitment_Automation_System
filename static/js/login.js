document.addEventListener("DOMContentLoaded", function () {

    // Clean up stale session jobs and upload identifiers across different logins
    try {
        localStorage.removeItem("activeJobId");
        localStorage.removeItem("activeUploadId");
        sessionStorage.clear();
    } catch (e) {
        console.warn("Storage cleanup error:", e);
    }

    /* =====================================================
       PASSWORD SHOW / HIDE
    ===================================================== */
    const password = document.getElementById("password");
    const togglePassword = document.getElementById("togglePassword");

    if (password && togglePassword) {
        togglePassword.addEventListener("click", function () {
            const icon = togglePassword.querySelector("i");

            if (password.type === "password") {
                password.type = "text";
                if (icon) {
                    icon.classList.remove("fa-eye");
                    icon.classList.add("fa-eye-slash");
                }
                togglePassword.setAttribute("aria-label", "Hide password");
            } else {
                password.type = "password";
                if (icon) {
                    icon.classList.remove("fa-eye-slash");
                    icon.classList.add("fa-eye");
                }
                togglePassword.setAttribute("aria-label", "Show password");
            }
        });
    }

    /* =====================================================
       INPUT FOCUS ANIMATION
    ===================================================== */
    const inputs = document.querySelectorAll(".custom-input input");

    inputs.forEach(function (input) {
        input.addEventListener("focus", function () {
            const parent = input.closest(".custom-input");
            if (parent) {
                parent.style.transform = "translateY(-2px)";
            }
        });

        input.addEventListener("blur", function () {
            const parent = input.closest(".custom-input");
            if (parent) {
                parent.style.transform = "translateY(0)";
            }
        });
    });

    /* =====================================================
       LOGIN FORM SUBMISSION
       DO NOT CALL preventDefault() ON VALID FORM!
       Flask route /login-user receives standard POST submission.
    ===================================================== */
    const loginForm = document.getElementById("loginForm");
    const loginButton = document.getElementById("loginButton");

    if (loginForm) {
        loginForm.addEventListener("submit", function (event) {
            const username = document.getElementById("username");
            const passwordInput = document.getElementById("password");

            // Username validation
            if (!username || !username.value.trim()) {
                event.preventDefault();
                if (username) username.focus();
                return;
            }

            // Password validation
            if (!passwordInput || !passwordInput.value) {
                event.preventDefault();
                if (passwordInput) passwordInput.focus();
                return;
            }

            // Valid submission: Allow standard browser submit to Flask
            if (loginButton) {
                loginButton.classList.add("loading");
            }
        });
    }

    // Restore state on pageshow (e.g. back button navigation)
    window.addEventListener("pageshow", function () {
        if (loginButton) {
            loginButton.classList.remove("loading");
            loginButton.disabled = false;
        }
    });

    /* =====================================================
       INTERACTIVE 3D PARALLAX MOUSE TILT ON IMAGE & CARD
    ===================================================== */
    const card3D = document.querySelector(".login-card-3d");
    const container3D = document.querySelector(".login-full-wrapper");
    const bgFloatingLayer = document.querySelector(".bg-3d-floating-layer");

    if (container3D) {
        container3D.addEventListener("mousemove", function (e) {
            const rect = container3D.getBoundingClientRect();
            const x = e.clientX - rect.left - rect.width / 2;
            const y = e.clientY - rect.top - rect.height / 2;

            if (card3D) {
                const rotateX = (y / (rect.height / 2)) * -8;
                const rotateY = (x / (rect.width / 2)) * 8;
                card3D.style.transform = `perspective(1000px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) translateY(-4px)`;
            }

            if (bgFloatingLayer) {
                const shiftX = (x / (rect.width / 2)) * -15;
                const shiftY = (y / (rect.height / 2)) * -15;
                bgFloatingLayer.style.transform = `translate3d(${shiftX}px, ${shiftY}px, 0)`;
            }
        });

        container3D.addEventListener("mouseleave", function () {
            if (card3D) {
                card3D.style.transform = "perspective(1000px) rotateX(0deg) rotateY(0deg) translateY(0px)";
            }
            if (bgFloatingLayer) {
                bgFloatingLayer.style.transform = "translate3d(0, 0, 0)";
            }
        });
    }

});