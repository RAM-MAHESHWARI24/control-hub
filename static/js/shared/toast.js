/**
 * ServerFF Control Hub - Toast Notification Engine
 */

import { escapeHtml } from "./formatters.js";

const toastContainer = document.getElementById("toast-container");

export function showToast(title, message, icon = "⚡", duration = 4000) {
  if (!toastContainer) return;
  const toast = document.createElement("div");
  toast.className = "toast-card";
  toast.innerHTML = `
    <div class="toast-icon">${icon}</div>
    <div class="toast-content">
      <div class="toast-title">${escapeHtml(title)}</div>
      <div class="toast-desc">${escapeHtml(message)}</div>
    </div>
    <button class="toast-close" title="Dismiss">&times;</button>
  `;
  const closeBtn = toast.querySelector(".toast-close");
  closeBtn.onclick = () => removeToast(toast);
  toastContainer.appendChild(toast);
  setTimeout(() => removeToast(toast), duration);
}

export function removeToast(toast) {
  if (!toast || toast.classList.contains("toast-hide")) return;
  toast.classList.add("toast-hide");
  setTimeout(() => { if (toast.parentNode) toast.remove(); }, 350);
}
