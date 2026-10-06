/* ==========================================================================
   SENIOR FRONTEND 3D ATS HERO ANIMATION ENGINE
   ========================================================================== */

(function () {
    'use strict';

    // Respect user reduced-motion preference
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    document.addEventListener('DOMContentLoaded', () => {
        initHero3DEngine();
    });

    function initHero3DEngine() {
        const heroSection = document.querySelector('.login-full-wrapper') || document.querySelector('.splash-full-wrapper') || document.querySelector('.auth-page') || document.querySelector('#dashboard-page') || document.querySelector('.dashboard-welcome');
        const screenOverlay = document.querySelector('.ats-screen-overlay-container');

        if (!heroSection) return;

        // 1. Create interactive Canvas for 3D Node Network & Floating Orbs
        const canvas = document.createElement('canvas');
        canvas.className = 'hero-3d-canvas';
        canvas.style.position = 'absolute';
        canvas.style.top = '0';
        canvas.style.left = '0';
        canvas.style.width = '100%';
        canvas.style.height = '100%';
        canvas.style.pointerEvents = 'none';
        canvas.style.zIndex = '1';
        
        if (screenOverlay) {
            screenOverlay.appendChild(canvas);
        } else {
            heroSection.appendChild(canvas);
        }

        const ctx = canvas.getContext('2d');
        let width = 0;
        let height = 0;

        function resizeCanvas() {
            const container = canvas.parentElement;
            if (!container) return;
            width = container.clientWidth || window.innerWidth;
            height = container.clientHeight || window.innerHeight;
            const dpr = window.devicePixelRatio || 1;
            canvas.width = width * dpr;
            canvas.height = height * dpr;
            ctx.setTransform(1, 0, 0, 1, 0, 0); // Reset transform matrix to prevent scale multiplier accumulation
            ctx.scale(dpr, dpr);
        }

        window.addEventListener('resize', resizeCanvas);
        resizeCanvas();

        // 2. Dynamic Floating Nodes & Particle Network Model
        const nodes = [
            { x: 0.12, y: 0.70, radius: 7, color: '#3b82f6', vx: 0.0003, vy: -0.0002 },
            { x: 0.50, y: 0.45, radius: 11, color: '#2563eb', pulse: 0, vx: 0, vy: 0 }, // Central AI Node
            { x: 0.88, y: 0.22, radius: 7, color: '#60a5fa', vx: -0.0002, vy: 0.0003 },
            { x: 0.82, y: 0.75, radius: 6, color: '#93c5fd', vx: -0.0003, vy: -0.0003 },
            { x: 0.18, y: 0.20, radius: 6, color: '#3b82f6', vx: 0.0002, vy: 0.0002 },
            { x: 0.35, y: 0.82, radius: 5, color: '#38bdf8', vx: 0.0004, vy: -0.0003 },
            { x: 0.68, y: 0.15, radius: 5, color: '#818cf8', vx: -0.0003, vy: 0.0002 }
        ];

        // Animated Traveling Data Particles
        class DataParticle {
            constructor(startIdx, endIdx, speed) {
                this.startIdx = startIdx;
                this.endIdx = endIdx;
                this.progress = Math.random();
                this.speed = speed;
                this.radius = Math.random() * 3 + 2.5;
                this.color = Math.random() > 0.4 ? '#ffffff' : '#60a5fa';
            }

            update() {
                this.progress += this.speed;
                if (this.progress >= 1) {
                    this.progress = 0;
                    this.startIdx = Math.floor(Math.random() * nodes.length);
                    this.endIdx = Math.floor(Math.random() * nodes.length);
                    if (this.startIdx === this.endIdx) {
                        this.endIdx = (this.startIdx + 1) % nodes.length;
                    }
                }
            }

            draw() {
                const n1 = nodes[this.startIdx];
                const n2 = nodes[this.endIdx];
                if (!n1 || !n2) return;

                const x1 = n1.x * width;
                const y1 = n1.y * height;
                const x2 = n2.x * width;
                const y2 = n2.y * height;

                const cx = (x1 + x2) / 2 + Math.sin(this.progress * Math.PI) * 30;
                const cy = (y1 + y2) / 2 - Math.cos(this.progress * Math.PI) * 30;

                const t = this.progress;
                const px = (1 - t) * (1 - t) * x1 + 2 * (1 - t) * t * cx + t * t * x2;
                const py = (1 - t) * (1 - t) * y1 + 2 * (1 - t) * t * cy + t * t * y2;

                ctx.beginPath();
                ctx.arc(px, py, this.radius, 0, Math.PI * 2);
                ctx.fillStyle = this.color;
                ctx.shadowColor = '#3b82f6';
                ctx.shadowBlur = 12;
                ctx.fill();
                ctx.shadowBlur = 0;
            }
        }

        const particles = [
            new DataParticle(0, 1, 0.006),
            new DataParticle(1, 2, 0.005),
            new DataParticle(4, 1, 0.007),
            new DataParticle(1, 3, 0.006),
            new DataParticle(5, 1, 0.008),
            new DataParticle(1, 6, 0.005)
        ];

        // 3. Smooth Continuous Render Loop
        function render() {
            requestAnimationFrame(render);
            ctx.clearRect(0, 0, width, height);

            // Update node floating positions slightly
            nodes.forEach((n, idx) => {
                if (idx !== 1) { // Move peripheral nodes gently
                    n.x += n.vx;
                    n.y += n.vy;
                    if (n.x < 0.08 || n.x > 0.92) n.vx *= -1;
                    if (n.y < 0.08 || n.y > 0.92) n.vy *= -1;
                }
            });

            // Draw curved glowing network connections
            const connections = [[0, 1], [1, 2], [4, 1], [1, 3], [5, 1], [1, 6], [0, 4], [3, 2]];
            connections.forEach(([i, j]) => {
                const n1 = nodes[i];
                const n2 = nodes[j];
                if (!n1 || !n2) return;

                const x1 = n1.x * width;
                const y1 = n1.y * height;
                const x2 = n2.x * width;
                const y2 = n2.y * height;

                ctx.strokeStyle = 'rgba(147, 197, 253, 0.35)';
                ctx.lineWidth = 1.5;
                ctx.beginPath();
                ctx.moveTo(x1, y1);
                ctx.quadraticCurveTo((x1 + x2) / 2, (y1 + y2) / 2 - 25, x2, y2);
                ctx.stroke();
            });

            // Update & render data particles
            particles.forEach(p => {
                p.update();
                p.draw();
            });

            // Draw nodes with pulsating aura
            nodes.forEach((n, idx) => {
                const nx = n.x * width;
                const ny = n.y * height;

                if (idx === 1) { // Central Processing Node
                    n.pulse += 0.04;
                    const pulseRadius = n.radius + Math.sin(n.pulse) * 4;

                    // Multi-layer glowing aura
                    ctx.beginPath();
                    ctx.arc(nx, ny, pulseRadius + 12, 0, Math.PI * 2);
                    ctx.fillStyle = 'rgba(59, 130, 246, 0.15)';
                    ctx.fill();

                    ctx.beginPath();
                    ctx.arc(nx, ny, pulseRadius + 6, 0, Math.PI * 2);
                    ctx.fillStyle = 'rgba(37, 99, 235, 0.3)';
                    ctx.fill();

                    ctx.beginPath();
                    ctx.arc(nx, ny, pulseRadius, 0, Math.PI * 2);
                    ctx.fillStyle = '#2563eb';
                    ctx.shadowColor = '#3b82f6';
                    ctx.shadowBlur = 15;
                    ctx.fill();
                    ctx.shadowBlur = 0;
                } else {
                    ctx.beginPath();
                    ctx.arc(nx, ny, n.radius, 0, Math.PI * 2);
                    ctx.fillStyle = n.color;
                    ctx.shadowColor = n.color;
                    ctx.shadowBlur = 10;
                    ctx.fill();
                    ctx.shadowBlur = 0;
                }
            });
        }

        render();

        // 4. Webflow 3D Laptop Refresh Animation & Dynamic Count-Up Engine
        const laptopContainers = document.querySelectorAll('.ats-laptop-screen-animator, .ats-screen-overlay-container');
        const refreshBtns = document.querySelectorAll('.js-refresh-ats-laptop');

        function triggerWebflow3DRefresh() {
            laptopContainers.forEach(container => {
                container.classList.remove('refreshing');
                // Force reflow
                void container.offsetWidth;
                container.style.animation = 'none';
                void container.offsetWidth;
                container.style.animation = 'webflowLaptop3DRefreshReveal 1.4s cubic-bezier(0.16, 1, 0.3, 1) forwards';
            });

            // Animate Stats Count-Up
            animateStatsCounter();
        }

        function animateStatsCounter() {
            const statsBars = document.querySelectorAll('.ats-screen-stats-bar');
            statsBars.forEach(bar => {
                const spans = bar.querySelectorAll('span strong');
                if (spans.length >= 3) {
                    const resumesEl = spans[0];
                    const accuracyEl = spans[1];
                    const speedEl = spans[2];

                    let start = 0;
                    const duration = 1200;
                    const startTime = performance.now();

                    function updateNumbers(now) {
                        const elapsed = now - startTime;
                        const progress = Math.min(elapsed / duration, 1);
                        const easeProgress = 1 - Math.pow(1 - progress, 3); // cubic ease-out

                        const currentResumes = Math.floor(easeProgress * 1420);
                        const currentAccuracy = (easeProgress * 98.4).toFixed(1);
                        const currentSpeed = (0.8 - easeProgress * 0.6).toFixed(1);

                        resumesEl.textContent = currentResumes.toLocaleString();
                        accuracyEl.textContent = currentAccuracy + '%';
                        if (speedEl.querySelector('i')) {
                            speedEl.innerHTML = `<i class="fa-solid fa-bolt text-warning"></i> ${currentSpeed}s`;
                        } else {
                            speedEl.textContent = currentSpeed + 's';
                        }

                        if (progress < 1) {
                            requestAnimationFrame(updateNumbers);
                        }
                    }
                    requestAnimationFrame(updateNumbers);
                }
            });
        }

        // Run count-up on load
        setTimeout(animateStatsCounter, 300);

        // Refresh button click listener
        refreshBtns.forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                triggerWebflow3DRefresh();
            });
        });

        // 5. Interactive 3D Parallax Perspective Tilt Effect
        heroSection.addEventListener('mousemove', (e) => {
            if (prefersReducedMotion) return;
            const rect = heroSection.getBoundingClientRect();
            const x = e.clientX - rect.left - rect.width / 2;
            const y = e.clientY - rect.top - rect.height / 2;

            const rotateX = (y / (rect.height / 2)) * -8 + 5; // Base 5deg offset
            const rotateY = (x / (rect.width / 2)) * 8 - 12; // Base -12deg offset

            laptopContainers.forEach(container => {
                container.style.transform = `perspective(900px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) rotateZ(-1deg) scale(1.02)`;
                container.style.transition = 'transform 0.1s ease-out';
            });
        });

        heroSection.addEventListener('mouseleave', () => {
            laptopContainers.forEach(container => {
                container.style.transform = 'perspective(900px) rotateY(-12deg) rotateX(5deg) rotateZ(-1deg) scale(1)';
                container.style.transition = 'transform 0.5s cubic-bezier(0.16, 1, 0.3, 1)';
            });
        });
    }

})();
