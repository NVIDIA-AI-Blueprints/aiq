// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Open external links in new tabs
document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("a[href]").forEach(function (link) {
        var href = link.getAttribute("href");
        if (href && (href.startsWith("http://") || href.startsWith("https://")) && !href.includes(window.location.hostname)) {
            link.setAttribute("target", "_blank");
            link.setAttribute("rel", "noopener noreferrer");
        }
    });
});

// Click-to-expand fullscreen for Mermaid diagrams
document.addEventListener("DOMContentLoaded", function () {
    // Wait for Mermaid to render (it runs async)
    setTimeout(function () {
        document.querySelectorAll(".mermaid").forEach(function (el) {
            el.addEventListener("click", function () {
                this.classList.toggle("fullscreen");
            });
        });

        // ESC key closes fullscreen
        document.addEventListener("keydown", function (e) {
            if (e.key === "Escape") {
                document.querySelectorAll(".mermaid.fullscreen").forEach(function (el) {
                    el.classList.remove("fullscreen");
                });
            }
        });
    }, 1000);
});
