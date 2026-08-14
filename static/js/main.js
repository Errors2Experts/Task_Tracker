/*
 * Task Tracker — UI behavior (vanilla JS, no dependencies)
 * Handles: desktop sidebar collapse (persisted), mobile off-canvas sidebar,
 * backdrop + escape-to-close, and auto-dismissing alert banners.
 */
(function () {
  "use strict";

  var STORAGE_KEY = "tt-sidebar-collapsed";

  var shell = document.querySelector("[data-app-shell]");
  var sidebar = document.querySelector("[data-sidebar]");
  var backdrop = document.querySelector("[data-sidebar-backdrop]");

  if (!shell || !sidebar) return;

  function isMobile() {
    return window.matchMedia("(max-width: 880px)").matches;
  }

  /* ---- Desktop collapse (persisted) ---- */
  // function applyStoredCollapse() {
  //   if (isMobile()) return;
  //   var stored = window.localStorage.getItem(STORAGE_KEY);
  //   if (stored === "1") {
  //     shell.classList.add("is-collapsed");
  //   }
  // }

  // function toggleCollapse() {
  //   var collapsed = shell.classList.toggle("is-collapsed");
  //   window.localStorage.setItem(STORAGE_KEY, collapsed ? "1" : "0");
  // }

  // document.querySelectorAll("[data-sidebar-collapse-toggle]").forEach(function (btn) {
  //   btn.addEventListener("click", function () {
  //     if (isMobile()) {
  //       toggleMobileSidebar();
  //     } else {
  //       toggleCollapse();
  //     }
  //   });
  // });

  // applyStoredCollapse();

  /* ---- Mobile off-canvas sidebar ---- */
  function openMobileSidebar() {
    sidebar.classList.add("is-open");
    if (backdrop) backdrop.classList.add("is-visible");
    document.body.style.overflow = "hidden";
  }

  function closeMobileSidebar() {
    sidebar.classList.remove("is-open");
    if (backdrop) backdrop.classList.remove("is-visible");
    document.body.style.overflow = "";
  }

  function toggleMobileSidebar() {
    if (sidebar.classList.contains("is-open")) {
      closeMobileSidebar();
    } else {
      openMobileSidebar();
    }
  }

  document.querySelectorAll("[data-hamburger]").forEach(function (btn) {
    btn.addEventListener("click", toggleMobileSidebar);
  });

  if (backdrop) backdrop.addEventListener("click", closeMobileSidebar);

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && sidebar.classList.contains("is-open")) {
      closeMobileSidebar();
    }
  });

  // Close the mobile drawer automatically if the viewport grows past the
  // breakpoint (e.g. rotating a tablet) so state never gets stuck open.
  window.addEventListener("resize", function () {
    if (!isMobile()) closeMobileSidebar();
  });

  /* ---- Auto-dismiss alert banners ---- */
  document.querySelectorAll(".alert").forEach(function (alert) {
    var closeBtn = document.createElement("button");
    closeBtn.type = "button";
    closeBtn.className = "alert-dismiss";
    closeBtn.setAttribute("aria-label", "Dismiss message");
    closeBtn.innerHTML = "&times;";
    alert.appendChild(closeBtn);

    function dismiss() {
      alert.style.opacity = "0";
      alert.style.transform = "translateY(-4px)";
      window.setTimeout(function () {
        alert.remove();
      }, 200);
    }

    closeBtn.addEventListener("click", dismiss);
    window.setTimeout(dismiss, 6000);
  });

  /* ---- Confirm before irreversible deletes ---- */
  document.querySelectorAll("[data-confirm]").forEach(function (el) {
    el.addEventListener("click", function (e) {
      var msg = el.getAttribute("data-confirm") || "Are you sure?";
      if (!window.confirm(msg)) {
        e.preventDefault();
      }
    });
  });
})();

const profileToggle = document.querySelector(".profile-toggle");
const profileMenu = document.querySelector(".profile-menu");

if(profileToggle){

    profileToggle.addEventListener("click",function(e){

        e.stopPropagation();

        profileMenu.classList.toggle("show");

    });

    document.addEventListener("click",function(){

        profileMenu.classList.remove("show");

    });

}


document.querySelectorAll("[data-toggle-password]").forEach(function (btn) {
  btn.addEventListener("click", function () {
    var input = btn.closest(".password-field").querySelector("input");
    var showing = input.type === "text";
    input.type = showing ? "password" : "text";
    btn.textContent = showing ? "👁" : "🙈";
  });
});

// ===== Completed alert ========== 
function openCompletePopup(taskId) {
    document.getElementById("completePopup").style.display = "flex";

    document.getElementById("completeForm").action =
        `/tasks/update-status/${taskId}/`;
}

function closeCompletePopup() {
    document.getElementById("completePopup").style.display = "none";
}
