/* ==========================================================================
   FORGOT PASSWORD & OTP INTERACTIVE SCRIPTS
   ========================================================================== */

document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("forgotPasswordForm");
    const verifyBtn = document.getElementById("verifyButton") || document.getElementById("candVerifyBtn");
    const otpInput = document.getElementById("otp_code");

    if (otpInput) {
        otpInput.addEventListener("input", (e) => {
            e.target.value = e.target.value.replace(/[^0-9]/g, "").slice(0, 6);
        });
    }

    if (form && verifyBtn) {
        form.addEventListener("submit", () => {
            verifyBtn.classList.add("loading");
            verifyBtn.disabled = true;
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
