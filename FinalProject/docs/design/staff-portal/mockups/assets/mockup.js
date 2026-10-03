/*
 * Mockup runtime: injects the icon sprite and switches between UI states via ?state=<id>.
 * Add &clean=1 to hide the state switcher (used for screenshots).
 * Generated sprite below is a copy of ../../icons.svg; regenerate if icons change.
 */
(function () {
  var SPRITE = "<svg xmlns=\"http://www.w3.org/2000/svg\" style=\"display:none\" aria-hidden=\"true\"><symbol id=\"i-check\" viewBox=\"0 0 24 24\"><path d=\"M20 6 9 17l-5-5\"/></symbol><symbol id=\"i-x\" viewBox=\"0 0 24 24\"><path d=\"M18 6 6 18M6 6l12 12\"/></symbol><symbol id=\"i-pause\" viewBox=\"0 0 24 24\"><path d=\"M12 8v5M12 16.5v.01\"/></symbol><symbol id=\"i-alert\" viewBox=\"0 0 24 24\"><path d=\"M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z\"/><path d=\"M12 9v4M12 17h.01\"/></symbol><symbol id=\"i-alert-octagon\" viewBox=\"0 0 24 24\"><path d=\"M7.9 2h8.2L22 7.9v8.2L16.1 22H7.9L2 16.1V7.9Z\"/><path d=\"M12 8v4M12 16h.01\"/></symbol><symbol id=\"i-info\" viewBox=\"0 0 24 24\"><circle cx=\"12\" cy=\"12\" r=\"10\"/><path d=\"M12 16v-4M12 8h.01\"/></symbol><symbol id=\"i-check-circle\" viewBox=\"0 0 24 24\"><circle cx=\"12\" cy=\"12\" r=\"10\"/><path d=\"m8 12 3 3 5-6\"/></symbol><symbol id=\"i-search\" viewBox=\"0 0 24 24\"><circle cx=\"11\" cy=\"11\" r=\"7\"/><path d=\"m21 21-4.3-4.3\"/></symbol><symbol id=\"i-logout\" viewBox=\"0 0 24 24\"><path d=\"M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9\"/></symbol><symbol id=\"i-user\" viewBox=\"0 0 24 24\"><circle cx=\"12\" cy=\"8\" r=\"4\"/><path d=\"M4 21a8 8 0 0 1 16 0\"/></symbol><symbol id=\"i-users\" viewBox=\"0 0 24 24\"><circle cx=\"9\" cy=\"8\" r=\"4\"/><path d=\"M2 21a7 7 0 0 1 14 0M16 3.1a4 4 0 0 1 0 7.8M22 21a7 7 0 0 0-4-6.3\"/></symbol><symbol id=\"i-download\" viewBox=\"0 0 24 24\"><path d=\"M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3\"/></symbol><symbol id=\"i-play\" viewBox=\"0 0 24 24\"><path d=\"m6 3 14 9-14 9Z\"/></symbol><symbol id=\"i-stop\" viewBox=\"0 0 24 24\"><rect x=\"5\" y=\"5\" width=\"14\" height=\"14\" rx=\"2\"/></symbol><symbol id=\"i-trash\" viewBox=\"0 0 24 24\"><path d=\"M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M10 11v6M14 11v6\"/></symbol><symbol id=\"i-external\" viewBox=\"0 0 24 24\"><path d=\"M15 3h6v6M10 14 21 3M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6\"/></symbol><symbol id=\"i-refresh\" viewBox=\"0 0 24 24\"><path d=\"M21 12a9 9 0 0 1-15.5 6.2L3 16M3 12a9 9 0 0 1 15.5-6.2L21 8M21 3v5h-5M3 21v-5h5\"/></symbol><symbol id=\"i-lock\" viewBox=\"0 0 24 24\"><rect x=\"4\" y=\"11\" width=\"16\" height=\"10\" rx=\"2\"/><path d=\"M8 11V7a4 4 0 0 1 8 0v4\"/></symbol><symbol id=\"i-chevron-right\" viewBox=\"0 0 24 24\"><path d=\"m9 18 6-6-6-6\"/></symbol><symbol id=\"i-chevron-left\" viewBox=\"0 0 24 24\"><path d=\"m15 18-6-6 6-6\"/></symbol><symbol id=\"i-clock\" viewBox=\"0 0 24 24\"><circle cx=\"12\" cy=\"12\" r=\"10\"/><path d=\"M12 6v6l4 2\"/></symbol><symbol id=\"i-inbox\" viewBox=\"0 0 24 24\"><path d=\"M22 12h-6l-2 3h-4l-2-3H2\"/><path d=\"M5.5 5.1 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.5-6.9A2 2 0 0 0 16.8 4H7.2a2 2 0 0 0-1.7 1.1Z\"/></symbol><symbol id=\"i-layers\" viewBox=\"0 0 24 24\"><path d=\"m12 2 10 5-10 5L2 7Z\"/><path d=\"m2 17 10 5 10-5M2 12l10 5 10-5\"/></symbol><symbol id=\"i-bell\" viewBox=\"0 0 24 24\"><path d=\"M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10.3 21a1.9 1.9 0 0 0 3.4 0\"/></symbol><symbol id=\"i-card\" viewBox=\"0 0 24 24\"><rect x=\"2\" y=\"5\" width=\"20\" height=\"14\" rx=\"2\"/><path d=\"M2 10h20M6 15h4\"/></symbol><symbol id=\"i-list\" viewBox=\"0 0 24 24\"><path d=\"M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01\"/></symbol><symbol id=\"i-activity\" viewBox=\"0 0 24 24\"><path d=\"M22 12h-4l-3 9L9 3l-3 9H2\"/></symbol><symbol id=\"i-server\" viewBox=\"0 0 24 24\"><rect x=\"2\" y=\"3\" width=\"20\" height=\"8\" rx=\"2\"/><rect x=\"2\" y=\"13\" width=\"20\" height=\"8\" rx=\"2\"/><path d=\"M6 7h.01M6 17h.01\"/></symbol><symbol id=\"i-database\" viewBox=\"0 0 24 24\"><ellipse cx=\"12\" cy=\"5\" rx=\"9\" ry=\"3\"/><path d=\"M3 5v14c0 1.7 4 3 9 3s9-1.3 9-3V5M3 12c0 1.7 4 3 9 3s9-1.3 9-3\"/></symbol><symbol id=\"i-file\" viewBox=\"0 0 24 24\"><path d=\"M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z\"/><path d=\"M14 2v6h6M8 13h8M8 17h5\"/></symbol><symbol id=\"i-shield\" viewBox=\"0 0 24 24\"><path d=\"M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z\"/></symbol><symbol id=\"i-eye\" viewBox=\"0 0 24 24\"><path d=\"M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z\"/><circle cx=\"12\" cy=\"12\" r=\"3\"/></symbol><symbol id=\"i-filter\" viewBox=\"0 0 24 24\"><path d=\"M22 3H2l8 9.5V19l4 2v-8.5Z\"/></symbol><symbol id=\"i-bar-chart\" viewBox=\"0 0 24 24\"><path d=\"M12 20V10M18 20V4M6 20v-4\"/></symbol><symbol id=\"i-gauge\" viewBox=\"0 0 24 24\"><path d=\"m12 14 4-4M3.3 19a10 10 0 1 1 17.4 0\"/></symbol><symbol id=\"i-arrow-up\" viewBox=\"0 0 24 24\"><path d=\"M12 19V5M5 12l7-7 7 7\"/></symbol><symbol id=\"i-arrow-down\" viewBox=\"0 0 24 24\"><path d=\"M12 5v14M19 12l-7 7-7-7\"/></symbol><symbol id=\"i-arrow-right\" viewBox=\"0 0 24 24\"><path d=\"M5 12h14M12 5l7 7-7 7\"/></symbol><symbol id=\"i-zap\" viewBox=\"0 0 24 24\"><path d=\"M13 2 3 14h9l-1 8 10-12h-9Z\"/></symbol><symbol id=\"i-home\" viewBox=\"0 0 24 24\"><path d=\"m3 10 9-7 9 7v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z\"/><path d=\"M9 22V12h6v10\"/></symbol><symbol id=\"i-plus\" viewBox=\"0 0 24 24\"><path d=\"M12 5v14M5 12h14\"/></symbol><symbol id=\"i-message\" viewBox=\"0 0 24 24\"><path d=\"M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2Z\"/></symbol><symbol id=\"i-wifi-off\" viewBox=\"0 0 24 24\"><path d=\"m2 2 20 20M8.5 16.4a5 5 0 0 1 7 0M5 12.9a10 10 0 0 1 5.2-2.8M19 12.9a10 10 0 0 0-2.4-1.7M2 8.8a15 15 0 0 1 4.2-2.6M22 8.8A15 15 0 0 0 11 5M12 20h.01\"/></symbol></svg>";

  function injectSprite() {
    var holder = document.createElement("div");
    holder.innerHTML = SPRITE;
    document.body.insertBefore(holder.firstChild, document.body.firstChild);
  }

  function parseStates() {
    var raw = document.body.getAttribute("data-states") || "";
    return raw
      .split(";")
      .map(function (s) { return s.trim(); })
      .filter(Boolean)
      .map(function (s) {
        var parts = s.split("|");
        return { id: parts[0].trim(), label: (parts[1] || parts[0]).trim() };
      });
  }

  function applyState(state) {
    document.documentElement.setAttribute("data-state", state);
    document.querySelectorAll("[data-show]").forEach(function (el) {
      el.hidden = el.getAttribute("data-show").split(/\s+/).indexOf(state) === -1;
    });
    document.querySelectorAll("[data-hide]").forEach(function (el) {
      el.hidden = el.getAttribute("data-hide").split(/\s+/).indexOf(state) !== -1;
    });
    document.querySelectorAll("dialog[data-open-in]").forEach(function (dlg) {
      var open = dlg.getAttribute("data-open-in").split(/\s+/).indexOf(state) !== -1;
      if (open && !dlg.open) {
        dlg.showModal();
      }
    });
  }

  function renderSwitcher(states, current) {
    if (states.length < 2) {
      return;
    }
    var bar = document.createElement("nav");
    bar.className = "mock-switcher";
    bar.setAttribute("aria-label", "Trạng thái mockup");
    var label = document.createElement("span");
    label.className = "mock-switcher__label";
    label.textContent = "Trạng thái:";
    bar.appendChild(label);
    states.forEach(function (s) {
      var a = document.createElement("a");
      a.href = "?state=" + encodeURIComponent(s.id);
      a.textContent = s.label;
      if (s.id === current) {
        a.setAttribute("aria-current", "true");
      }
      bar.appendChild(a);
    });
    var home = document.createElement("a");
    home.href = "index.html";
    home.className = "mock-switcher__home";
    home.textContent = "Mục lục";
    bar.appendChild(home);
    document.body.appendChild(bar);
  }

  function wireConfirmInputs() {
    document.querySelectorAll("[data-confirm-word]").forEach(function (input) {
      var target = document.getElementById(input.getAttribute("data-confirm-target"));
      var word = input.getAttribute("data-confirm-word");
      function sync() {
        var ok = input.value === word;
        if (target) {
          target.disabled = !ok;
        }
        input.setAttribute("aria-invalid", input.value && !ok ? "true" : "false");
      }
      input.addEventListener("input", sync);
      sync();
    });
  }

  function wireDemoAccounts() {
    document.querySelectorAll("[data-fill-user]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var field = document.getElementById("username");
        if (field) {
          field.value = btn.getAttribute("data-fill-user");
          var pw = document.getElementById("password");
          if (pw) {
            pw.focus();
          }
        }
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var params = new URLSearchParams(window.location.search);
    if (params.get("clean") === "1") {
      document.documentElement.setAttribute("data-clean", "");
    }
    injectSprite();
    var states = parseStates();
    var current = params.get("state") || (states[0] && states[0].id) || "default";
    applyState(current);
    renderSwitcher(states, current);
    wireConfirmInputs();
    wireDemoAccounts();
  });
})();
