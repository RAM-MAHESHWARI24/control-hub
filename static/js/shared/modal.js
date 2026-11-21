/**
 * Shared accessible modal dialog controller (WCAG 2.2 AA).
 * Ensures role="dialog", aria-modal="true", aria-labelledby, focus trapping,
 * Escape-to-close, backdrop-click-to-close, and focus restoration.
 */

const modalStack = [];
const modalConfigs = new WeakMap();
let listenersBound = false;

function syncBackgroundInert() {
  const active = modalStack.length > 0;
  document.querySelectorAll(".hub-header, .hub-shell").forEach((node) => {
    if (active) {
      node.setAttribute("aria-hidden", "true");
      node.inert = true;
    } else {
      node.removeAttribute("aria-hidden");
      node.inert = false;
    }
  });
}

function getFocusableElements(container) {
  const selector = [
    "a[href]",
    "button:not([disabled])",
    "input:not([disabled]):not([type='hidden'])",
    "select:not([disabled])",
    "textarea:not([disabled])",
    "[tabindex]:not([tabindex='-1'])",
  ].join(", ");

  return Array.from(container.querySelectorAll(selector)).filter((el) => {
    const style = window.getComputedStyle(el);
    return style.display !== "none" && style.visibility !== "hidden" && el.offsetParent !== null;
  });
}

function ensureDialogSemantics(modalEl) {
  if (!modalEl.getAttribute("role")) modalEl.setAttribute("role", "dialog");
  modalEl.setAttribute("aria-modal", "true");
  if (!modalEl.hasAttribute("tabindex")) modalEl.setAttribute("tabindex", "-1");

  if (!modalEl.getAttribute("aria-labelledby")) {
    const heading = modalEl.querySelector("h1, h2, h3, h4");
    if (heading) {
      if (!heading.id) {
        heading.id = `${modalEl.id || "dialog"}-title`;
      }
      modalEl.setAttribute("aria-labelledby", heading.id);
    }
  }
}

function bindGlobalListeners() {
  if (listenersBound) return;
  listenersBound = true;

  document.addEventListener("keydown", (e) => {
    const top = modalStack[modalStack.length - 1];
    if (!top) return;

    if (e.key === "Escape") {
      e.preventDefault();
      closeModal(top.el);
      return;
    }

    if (e.key === "Tab") {
      const dialogBox = top.el.querySelector(".modal-glass") || top.el;
      const focusable = getFocusableElements(dialogBox);
      if (focusable.length === 0) {
        e.preventDefault();
        top.el.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && (document.activeElement === first || !dialogBox.contains(document.activeElement))) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && (document.activeElement === last || !dialogBox.contains(document.activeElement))) {
        e.preventDefault();
        first.focus();
      }
    }
  });
}

export function registerModal(modalEl, { closeButtons = [], onClose = null } = {}) {
  if (!modalEl) return;
  ensureDialogSemantics(modalEl);
  bindGlobalListeners();
  modalConfigs.set(modalEl, { onClose });

  closeButtons.forEach((btn) => {
    if (btn) {
      btn.addEventListener("click", () => closeModal(modalEl));
    }
  });

  modalEl.addEventListener("click", (e) => {
    if (e.target === modalEl) {
      closeModal(modalEl);
    }
  });
}

export function openModal(modalEl, triggerEl = null) {
  if (!modalEl) return;
  ensureDialogSemantics(modalEl);
  bindGlobalListeners();

  const existingIdx = modalStack.findIndex((item) => item.el === modalEl);
  if (existingIdx !== -1) {
    modalStack.splice(existingIdx, 1);
  }
  modalStack.push({
    el: modalEl,
    previousFocus: triggerEl || document.activeElement,
  });

  modalEl.style.display = "flex";
  syncBackgroundInert();
  const dialogBox = modalEl.querySelector(".modal-glass") || modalEl;
  const focusable = getFocusableElements(dialogBox);
  if (focusable.length > 0) {
    focusable[0].focus();
  } else {
    modalEl.focus();
  }
}

export function closeModal(modalEl) {
  if (!modalEl) return;
  modalEl.style.display = "none";

  const cfg = modalConfigs.get(modalEl);
  if (cfg && typeof cfg.onClose === "function") {
    cfg.onClose();
  }

  const idx = modalStack.findIndex((item) => item.el === modalEl);
  let previousFocus = null;
  if (idx !== -1) {
    previousFocus = modalStack[idx].previousFocus;
    modalStack.splice(idx, 1);
  }
  syncBackgroundInert();

  if (previousFocus && typeof previousFocus.focus === "function" && document.contains(previousFocus)) {
    previousFocus.focus();
  }
}
