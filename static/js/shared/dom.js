export const $ = (id) => document.getElementById(id);

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
