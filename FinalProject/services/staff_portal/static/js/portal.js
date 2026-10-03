// Small progressive enhancements; the CSP forbids inline scripts, so behaviour lives here.
(function () {
  "use strict";

  // Enable a guarded submit button only when the confirmation word is typed exactly.
  function bindConfirmations(root) {
    root.querySelectorAll("[data-confirm-word]").forEach(function (input) {
      var form = input.closest("form");
      var button = form && form.querySelector("[data-confirm-target]");
      if (!button || input.dataset.bound) return;
      input.dataset.bound = "1";
      var sync = function () {
        button.disabled = input.value.trim() !== input.dataset.confirmWord;
      };
      input.addEventListener("input", sync);
      sync();
    });
  }

  // Show the "new limit" field only for the REDUCE action.
  function bindDecisionForm(root) {
    root.querySelectorAll("[data-limit-toggle]").forEach(function (form) {
      if (form.dataset.bound) return;
      form.dataset.bound = "1";
      var field = form.querySelector("[data-limit-field]");
      var sync = function () {
        var checked = form.querySelector("input[name=action]:checked");
        if (field) field.hidden = !(checked && checked.value === "REDUCE");
      };
      form.addEventListener("change", sync);
      sync();
    });
  }

  function init(root) {
    bindConfirmations(root);
    bindDecisionForm(root);
  }

  document.addEventListener("DOMContentLoaded", function () { init(document); });
  document.addEventListener("htmx:afterSwap", function (event) { init(event.target); });
})();
