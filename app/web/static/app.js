// Service worker registration and the "install this app" hints.
(function () {
  "use strict";

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js").catch(function () {});
    });
  }

  var deferredPrompt = null; // Android/desktop Chrome's install prompt, if offered
  var DISMISS_KEY = "installHintDismissed";

  function isStandalone() {
    return window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
  }

  function isIOS() {
    // iPadOS reports itself as a Mac; touch support gives it away.
    return /iphone|ipad|ipod/i.test(navigator.userAgent) ||
      (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  }

  function dismissed() {
    try { return localStorage.getItem(DISMISS_KEY) === "1"; } catch (e) { return false; }
  }

  function installMode() {
    if (isStandalone()) return "installed";
    if (deferredPrompt) return "prompt";
    if (isIOS()) return "ios";
    return "none";
  }

  // Elements with data-install="banner" (dismissible) or "panel" (settings page).
  function refresh() {
    var mode = installMode();
    document.querySelectorAll("[data-install]").forEach(function (el) {
      el.dataset.mode = mode;
      var isBanner = el.dataset.install === "banner";
      el.hidden = mode === "none" || (isBanner && (mode === "installed" || dismissed()));
    });
  }

  window.addEventListener("beforeinstallprompt", function (event) {
    event.preventDefault();
    deferredPrompt = event;
    refresh();
  });
  window.addEventListener("appinstalled", function () {
    deferredPrompt = null;
    refresh();
  });

  // Invite links: Copy, Share (phones), and select-all when the field is tapped.
  function setupShareButtons() {
    document.querySelectorAll("[data-share]").forEach(function (button) {
      button.hidden = !navigator.share;
    });
  }

  document.addEventListener("focusin", function (event) {
    if (event.target.matches && event.target.matches("[data-select-on-focus]")) {
      event.target.select();
    }
  });

  // Unknown food: the "goes bad in…" buttons fill the add form's date field, and the
  // preview refreshes from the change event.
  document.addEventListener("click", function (event) {
    var form = document.getElementById("add-form");
    if (!form) return;
    var dateInput = form.querySelector('input[name="user_expires_on"]');
    var setDate = event.target.closest("[data-set-date]");
    if (setDate && dateInput) {
      dateInput.value = setDate.dataset.setDate;
      form.querySelectorAll("[data-set-date]").forEach(function (b) {
        b.setAttribute("aria-pressed", b === setDate ? "true" : "false");
      });
      dateInput.dispatchEvent(new Event("change", { bubbles: true }));
    }
    if (event.target.closest("[data-pick-date]") && dateInput) {
      var more = form.querySelector("details.more");
      if (more) more.open = true;
      dateInput.focus();
      try { dateInput.showPicker(); } catch (e) { /* not supported: focus is enough */ }
    }
  });

  document.addEventListener("click", function (event) {
    var copy = event.target.closest("[data-copy]");
    if (copy) {
      var text = copy.dataset.copy;
      var done = function () { copy.textContent = "Copied"; };
      if (navigator.clipboard) {
        navigator.clipboard.writeText(text).then(done, function () {});
      }
    }
    var share = event.target.closest("[data-share]");
    if (share && navigator.share) {
      navigator.share({ title: "Join me on Pantry", url: share.dataset.share }).catch(function () {});
    }
  });

  document.addEventListener("DOMContentLoaded", setupShareButtons);
  document.addEventListener("htmx:afterSettle", setupShareButtons);

  document.addEventListener("click", function (event) {
    if (event.target.closest("[data-install-button]") && deferredPrompt) {
      deferredPrompt.prompt();
      deferredPrompt.userChoice.finally(function () {
        deferredPrompt = null;
        refresh();
      });
    }
    if (event.target.closest("[data-install-dismiss]")) {
      try { localStorage.setItem(DISMISS_KEY, "1"); } catch (e) { /* private mode */ }
      refresh();
    }
  });

  // Confirmation notices fade out after data-autohide seconds (longer when they offer Undo).
  function autohideNotices() {
    document.querySelectorAll("[data-autohide]").forEach(function (el) {
      if (el.dataset.autohideStarted) return;
      el.dataset.autohideStarted = "1";
      var seconds = parseFloat(el.dataset.autohide) || 4;
      setTimeout(function () {
        el.classList.add("is-hiding");
        setTimeout(function () { el.remove(); }, 350);
      }, seconds * 1000);
    });
  }

  document.addEventListener("DOMContentLoaded", refresh);
  document.addEventListener("DOMContentLoaded", autohideNotices);
  // hx-boost swaps the body on navigation; re-apply to the new content.
  document.addEventListener("htmx:afterSettle", refresh);
  document.addEventListener("htmx:afterSettle", autohideNotices);
})();
