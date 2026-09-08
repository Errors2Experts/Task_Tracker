/*
 * Task Tracker — UI behavior (vanilla JS, no dependencies)
 * Handles:
 * - Desktop sidebar collapse (persisted)
 * - Logo click to collapse/expand sidebar
 * - Mobile off-canvas sidebar
 * - Backdrop + escape-to-close
 * - Auto-dismissing alert banners
 * - Profile dropdown
 * - Password show/hide
 * - Complete task popup
 */

(function () {
    "use strict";

    var STORAGE_KEY = "tt-sidebar-collapsed";

    function initializeSidebar() {

        // Prevent this script from initializing twice
        if (window.__taskTrackerSidebarInitialized) {
            return;
        }

        var shell = document.querySelector("[data-app-shell]");
        var sidebar = document.querySelector("[data-sidebar]");
        var backdrop = document.querySelector("[data-sidebar-backdrop]");

        if (!shell || !sidebar) {
            return;
        }

        window.__taskTrackerSidebarInitialized = true;

        function isMobile() {
            return window.matchMedia("(max-width: 880px)").matches;
        }

        /*
         * Apply previously saved sidebar state
         */
        function applyStoredCollapse() {

            if (isMobile()) {
                return;
            }

            var stored = window.localStorage.getItem(STORAGE_KEY);

            if (stored === "1") {
                shell.classList.add("is-collapsed");
            } else {
                shell.classList.remove("is-collapsed");
            }
        }

        /*
         * Toggle sidebar only from logo click
         */
        function toggleCollapse() {

            if (isMobile()) {
                return;
            }

            var isCollapsed =
                shell.classList.contains("is-collapsed");

            if (isCollapsed) {

                shell.classList.remove("is-collapsed");

                window.localStorage.setItem(
                    STORAGE_KEY,
                    "0"
                );

            } else {

                shell.classList.add("is-collapsed");

                window.localStorage.setItem(
                    STORAGE_KEY,
                    "1"
                );
            }
        }

        /*
         * Apply saved state immediately
         */
        applyStoredCollapse();

        /*
         * Remove preload class after state is applied
         */
        document.documentElement.classList.remove(
            "sidebar-collapsed-preload"
        );

        /*
         * Logo click
         * ONLY logo controls sidebar collapse/expand
         */
        var sidebarLogo =
            document.querySelector(".brand-logo");

        if (sidebarLogo) {

            sidebarLogo.style.cursor = "pointer";
            sidebarLogo.style.userSelect = "none";

            sidebarLogo.addEventListener(
                "click",
                function (e) {

                    e.preventDefault();
                    e.stopPropagation();

                    if (isMobile()) {
                        return;
                    }

                    toggleCollapse();
                }
            );
        }

        /*
         * IMPORTANT:
         * No nav-item click handler here.
         *
         * Navigation works normally using Django href.
         * Sidebar state is already stored in localStorage.
         */

        /* =========================
           Mobile Sidebar
           ========================= */

        function openMobileSidebar() {

            sidebar.classList.add("is-open");

            if (backdrop) {
                backdrop.classList.add("is-visible");
            }

            document.body.style.overflow = "hidden";
        }

        function closeMobileSidebar() {

            sidebar.classList.remove("is-open");

            if (backdrop) {
                backdrop.classList.remove("is-visible");
            }

            document.body.style.overflow = "";
        }

        function toggleMobileSidebar() {

            if (sidebar.classList.contains("is-open")) {
                closeMobileSidebar();
            } else {
                openMobileSidebar();
            }
        }

        document
            .querySelectorAll("[data-hamburger]")
            .forEach(function (btn) {

                btn.addEventListener(
                    "click",
                    toggleMobileSidebar
                );

            });

        if (backdrop) {

            backdrop.addEventListener(
                "click",
                closeMobileSidebar
            );

        }

        document.addEventListener(
            "keydown",
            function (e) {

                if (
                    e.key === "Escape" &&
                    sidebar.classList.contains("is-open")
                ) {
                    closeMobileSidebar();
                }

            }
        );

        window.addEventListener(
            "resize",
            function () {

                if (!isMobile()) {
                    closeMobileSidebar();
                }

                /*
                 * Re-apply desktop saved state
                 * when switching back from mobile.
                 */
                if (!isMobile()) {
                    applyStoredCollapse();
                }

            }
        );
    }


    /*
     * Initialize after DOM is ready
     */
    if (document.readyState === "loading") {

        document.addEventListener(
            "DOMContentLoaded",
            initializeSidebar
        );

    } else {

        initializeSidebar();

    }

})();


/* =========================
   Profile Dropdown
   ========================= */

const profileToggle =
    document.querySelector(".profile-toggle");

const profileMenu =
    document.querySelector(".profile-menu");

if (profileToggle && profileMenu) {

    profileToggle.addEventListener(
        "click",
        function (e) {

            e.stopPropagation();

            profileMenu.classList.toggle("show");
        }
    );

    document.addEventListener(
        "click",
        function () {

            profileMenu.classList.remove("show");

        }
    );
}


/* =========================
   Password Show / Hide
   ========================= */

document
    .querySelectorAll("[data-toggle-password]")
    .forEach(function (btn) {

        btn.addEventListener(
            "click",
            function () {

                var passwordField =
                    btn.closest(".password-field");

                if (!passwordField) {
                    return;
                }

                var input =
                    passwordField.querySelector("input");

                if (!input) {
                    return;
                }

                var showing =
                    input.type === "text";

                input.type =
                    showing ? "password" : "text";

                btn.textContent =
                    showing ? "👁" : "🙈";
            }
        );
    });


/* =========================
   Complete Task Popup
   ========================= */

function openCompletePopup(taskId) {

    var popup =
        document.getElementById("completePopup");

    var form =
        document.getElementById("completeForm");

    if (!popup || !form) {
        return;
    }

    popup.style.display = "flex";

    form.action =
        `/tasks/update-status/${taskId}/`;
}


function closeCompletePopup() {

    var popup =
        document.getElementById("completePopup");

    if (!popup) {
        return;
    }

    popup.style.display = "none";
}


/* =========================
   Auto-dismiss Alert Banners
   ========================= */

document
    .querySelectorAll(".alert")
    .forEach(function (alert) {

        var closeBtn =
            document.createElement("button");

        closeBtn.type = "button";

        closeBtn.className =
            "alert-dismiss";

        closeBtn.setAttribute(
            "aria-label",
            "Dismiss message"
        );

        closeBtn.innerHTML = "&times;";

        alert.appendChild(closeBtn);


        function dismiss() {

            alert.style.opacity = "0";

            alert.style.transform =
                "translateY(-4px)";

            window.setTimeout(
                function () {
                    alert.remove();
                },
                200
            );
        }


        closeBtn.addEventListener(
            "click",
            dismiss
        );

        window.setTimeout(
            dismiss,
            6000
        );

    });


/* =========================
   Confirm Delete
   ========================= */

document
    .querySelectorAll("[data-confirm]")
    .forEach(function (el) {

        el.addEventListener(
            "click",
            function (e) {

                var msg =
                    el.getAttribute("data-confirm") ||
                    "Are you sure?";

                if (!window.confirm(msg)) {
                    e.preventDefault();
                }

            }
        );

    });