/**
 * Control Hub - Accessible Toast Notification Engine
 */

import { escapeHtml } from "./formatters.js";

const toastContainer = document.getElementById("toast-container");
const srLive = document.getElementById("sr-status-live");

export function announceStatus(message) {
  if (!srLive || !message) return;
  srLive.textContent = "";
  window.requestAnimationFrame(() => {
    srLive.textContent = message;
  });
}

export function showToast(title, message, icon = "info", duration = 4200) {
  announceStatus(`${title}: ${message}`);
  if (!toastContainer) return;

  const toneMap = {
    "✅": "success",
    "✓": "success",
    "🟢": "success",
    "success": "success",
    "⚠️": "warning",
    "warning": "warning",
    "❌": "danger",
    "🔴": "danger",
    "danger": "danger",
  };
  const tone = toneMap[icon] || "info";
  const spriteIcon =
    tone === "success" ? "check"
      : tone === "warning" || tone === "danger" ? "alert"
        : "activity";

  const toast = document.createElement("div");
  toast.className = `toast-card toast-${tone}`;
  toast.setAttribute("role", "status");
  toast.innerHTML = `
    <div class="toast-icon" aria-hidden="true">
      <svg class="ui-icon"><use href="/img/icons/ui-sprite.svg#icon-${spriteIcon}"></use></svg>
    </div>
    <div class="toast-content">
      <div class="toast-title">${escapeHtml(title)}</div>
      <div class="toast-desc">${escapeHtml(message)}</div>
    </div>
    <button type="button" class="toast-close" aria-label="Dismiss notification">&times;</button>
  `;
  const closeBtn = toast.querySelector(".toast-close");
  closeBtn.onclick = () => removeToast(toast);
  toastContainer.appendChild(toast);
  setTimeout(() => removeToast(toast), duration);
}

export function removeToast(toast) {
  if (!toast || toast.classList.contains("toast-hide")) return;
  toast.classList.add("toast-hide");
  setTimeout(() => {
    if (toast.parentNode) toast.remove();
  }, 260);
}
