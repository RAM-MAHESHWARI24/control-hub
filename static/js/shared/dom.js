/**
 * Shared DOM helpers, SVG icon helper, clipboard fallback, and accessible confirm dialog.
 */

import { closeModal, openModal, registerModal } from "./modal.js";

export const $ = (id) => document.getElementById(id);

export function uiIcon(name, className = "ui-icon") {
  return `<svg class="${className}" aria-hidden="true"><use href="/img/icons/ui-sprite.svg#icon-${name}"></use></svg>`;
}

export function setCardSummary(cardId, text) {
  const card = $(cardId);
  if (!card) return;
  const summary = card.querySelector(".card-summary");
  if (summary && text) summary.textContent = text;
}

export function setCardCollapsed(cardId, collapsed) {
  const card = $(cardId);
  if (!card) return;
  card.classList.toggle("is-collapsed", collapsed);
  const btn = card.querySelector(".card-collapse-btn");
  if (btn) btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
}

export function expandCard(cardId) {
  setCardCollapsed(cardId, false);
}

/**
 * Copies text to the clipboard with a plain-HTTP LAN fallback (execCommand).
 */
export async function copyTextToClipboard(text) {
  if (!text) return false;
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (_) {
      /* fall through to textarea fallback */
    }
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.top = "-9999px";
    ta.style.left = "-9999px";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch (_) {
    return false;
  }
}

let confirmWired = false;
let pendingConfirmResolve = null;

/**
 * Accessible confirmation dialog (replaces native window.confirm).
 * Returns Promise<boolean>.
 */
export function confirmAction({
  title = "Confirm action",
  message = "Are you sure you want to continue?",
  warning = "",
  confirmLabel = "Confirm",
  danger = false,
  triggerEl = null,
} = {}) {
  const modal = $("confirm-action-modal");
  const titleEl = $("confirm-modal-title");
  const msgEl = $("confirm-modal-message");
  const warnEl = $("confirm-modal-warning");
  const okBtn = $("confirm-modal-ok");
  const cancelBtn = $("confirm-modal-cancel");
  const closeBtn = $("confirm-modal-close");

  if (!modal || !okBtn) {
    return Promise.resolve(window.confirm(`${title}\n\n${message}`));
  }

  if (!confirmWired) {
    confirmWired = true;
    registerModal(modal, {
      closeButtons: [cancelBtn, closeBtn],
      onClose: () => {
        if (pendingConfirmResolve) {
          const resolve = pendingConfirmResolve;
          pendingConfirmResolve = null;
          resolve(false);
        }
      },
    });
    okBtn.addEventListener("click", () => {
      if (pendingConfirmResolve) {
        const resolve = pendingConfirmResolve;
        pendingConfirmResolve = null;
        closeModal(modal);
        resolve(true);
      }
    });
  }

  if (titleEl) titleEl.textContent = title;
  if (msgEl) msgEl.textContent = message;
  if (warnEl) {
    warnEl.textContent = warning;
    warnEl.hidden = !warning;
  }
  okBtn.textContent = confirmLabel;
  okBtn.className = danger ? "btn-danger" : "btn-primary";

  return new Promise((resolve) => {
    pendingConfirmResolve = resolve;
    openModal(modal, triggerEl);
  });
}
