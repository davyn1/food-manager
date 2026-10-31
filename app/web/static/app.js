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

  document.addEventListener("DOMContentLoaded", refresh);
  // hx-boost swaps the body on navigation; re-apply to the new content.
  document.addEventListener("htmx:afterSettle", refresh);
})();
