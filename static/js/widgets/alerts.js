/**
 * Widget: Alerts
 * Always-visible header Alerts bell showing open firing count even when no
 * external delivery channel is enabled, global Attention Strip banner, and
 * full channel/rule/quiet-hours configuration modal.
 */

import { $ } from "../shared/dom.js";
import { ENDPOINTS } from "../config.js";
import { openModal, registerModal } from "../shared/modal.js";
import { showToast } from "../shared/toast.js";
import { state } from "../state.js";

const CHANNELS = {
  ntfy: {
    title: "ntfy (phone app, no account)",
    help: "Install the ntfy app, add a subscription to the topic below, and keep the topic private: anyone who knows it can read the alerts.",
    fields: [
      { key: "server", label: "Server", type: "url" },
      { key: "topic", label: "Topic", type: "text", generate: true },
      { key: "token", label: "Access token (optional, for a protected server)", type: "password" },
    ],
  },
  telegram: {
    title: "Telegram bot",
    help: "Create a bot with @BotFather, send it a message, then put its token and your chat ID here.",
    fields: [
      { key: "bot_token", label: "Bot token", type: "password" },
      { key: "chat_id", label: "Chat ID", type: "text" },
    ],
  },
  discord: {
    title: "Discord webhook",
    help: "Channel settings → Integrations → Webhooks → New webhook → Copy URL.",
    fields: [{ key: "webhook_url", label: "Webhook URL", type: "password" }],
  },
  email: {
    title: "Email (SMTP)",
    help: "For Gmail use smtp.gmail.com, port 587 and an app password.",
    fields: [
      { key: "host", label: "SMTP server", type: "text" },
      { key: "port", label: "Port", type: "number" },
      { key: "starttls", label: "Use STARTTLS", type: "checkbox" },
      { key: "username", label: "User name", type: "text" },
      { key: "password", label: "Password", type: "password" },
      { key: "sender", label: "From address", type: "email" },
      { key: "recipient", label: "Send to", type: "email" },
    ],
  },
};

const RULE_FIELDS = {
  disk_warning: [{ key: "percent", label: "at %", min: 50, max: 99 }],
  disk_critical: [{ key: "percent", label: "at %", min: 50, max: 99 }],
  container_down: [{ key: "minutes", label: "after minutes", min: 1, max: 120 }],
  cpu_temp: [
    { key: "celsius", label: "above °C", min: 50, max: 105 },
    { key: "minutes", label: "for minutes", min: 1, max: 60 },
  ],
};

const RULE_ORDER = [
  "backup_failed", "drive_unreachable", "restore_test_failed", "backup_stale", "disk_critical", "disk_warning",
  "container_down", "cpu_temp", "tv_update_failed", "signin_failures",
];

const SEVERITY_TEXT = { critical: "Critical", warning: "Warning", info: "Info" };

let current = null;

function el(tag, attrs = {}, text) {
  const node = document.createElement(tag);
  Object.entries(attrs).forEach(([k, v]) => {
    if (v === undefined || v === null || v === false) return;
    if (k === "className") node.className = v;
    else node.setAttribute(k, v === true ? "" : v);
  });
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function randomTopic() {
  const bytes = new Uint8Array(12);
  crypto.getRandomValues(bytes);
  return `homelab-${Array.from(bytes, (b) => b.toString(36).padStart(2, "0")).join("").slice(0, 18)}`;
}

function renderBadge(data) {
  const btn = $("btn-open-alerts");
  const badge = $("alerts-count");
  const banner = $("alerts-firing-banner");
  const bannerTitle = $("alerts-banner-title");
  const bannerDetail = $("alerts-banner-detail");
  const firing = data.firing || [];
  const open = firing.length;

  // Always show firing alert count even when no external channel is turned on!
  if (btn && badge) {
    if (open > 0) {
      badge.textContent = String(open);
      badge.className = "alerts-count is-open";
      badge.hidden = false;
      btn.setAttribute("aria-label", `Alerts: ${open} open`);
    } else if (!data.any_channel) {
      badge.textContent = "off";
      badge.className = "alerts-count is-off";
      badge.hidden = false;
      btn.setAttribute("aria-label", "Alerts: no channel set up yet");
    } else {
      badge.hidden = true;
      btn.setAttribute("aria-label", "Alerts: nothing open");
    }
  }

  if (banner) {
    if (open > 0) {
      const hasCrit = firing.some((f) => f.severity === "critical");
      banner.className = `notice-banner ${hasCrit ? "notice-danger" : "notice-warning"}`;
      if (bannerTitle) bannerTitle.textContent = `${open} active alert${open === 1 ? "" : "s"} need attention`;
      if (bannerDetail) {
        const preview = firing.slice(0, 2).map((f) => f.title).join(" · ");
        const extra = open > 2 ? ` (+${open - 2} more)` : "";
        bannerDetail.textContent = `${preview}${extra}`;
      }
      banner.hidden = false;
    } else {
      banner.hidden = true;
    }
  }
}

function renderFiring(data) {
  const list = $("alerts-firing");
  if (!list) return;
  list.replaceChildren();
  const firing = data.firing || [];
  if (!firing.length) {
    list.append(el("li", { className: "alerts-item" }, "Nothing needs attention right now."));
    return;
  }
  firing.forEach((f) => {
    const li = el("li", { className: `alerts-item sev-${f.severity}` });
    const top = el("div", { className: "alerts-item-top" });
    top.append(el("span", { className: `alerts-sev sev-${f.severity}` }, SEVERITY_TEXT[f.severity] || f.severity), el("strong", {}, f.title));
    li.append(top, el("div", { className: "alerts-item-msg" }, f.message), el("div", { className: "alerts-item-when" }, `Since ${f.since}`));
    list.append(li);
  });
}

function renderHistory(data) {
  const list = $("alerts-history");
  if (!list) return;
  list.replaceChildren();
  const items = data.history || [];
  if (!items.length) {
    list.append(el("li", { className: "alerts-item" }, "No alerts sent yet."));
    return;
  }
  items.slice(0, 20).forEach((h) => {
    const li = el("li", { className: `alerts-item sev-${h.resolved ? "resolved" : h.severity}` });
    const when = (h.at || "").replace("T", " ").slice(0, 16);
    const top = el("div", { className: "alerts-item-top" });
    top.append(el("span", { className: "alerts-item-when font-mono" }, when), el("strong", {}, h.title));
    li.append(top);
    if (h.queued) li.append(el("div", { className: "alerts-item-when" }, "Held for the morning digest (quiet hours)"));
    if (h.unsent) li.append(el("div", { className: "alerts-item-when" }, "Not sent: no channel was on (sent when one is turned on, if still open)"));
    list.append(li);
  });
}

function channelStatusText(name, data) {
  const st = (data.channel_status || {})[name];
  if (!st) return "";
  return st.error ? `Last send failed: ${st.error}` : `Last sent ${st.at.replace("T", " ").slice(0, 16)}`;
}

function renderChannels(data) {
  const wrap = $("alerts-channels");
  if (!wrap) return;
  wrap.replaceChildren();
  Object.entries(CHANNELS).forEach(([name, spec]) => {
    const cfg = data.config.channels[name];
    const fs = el("fieldset", { className: "alerts-channel", "data-channel": name });
    fs.append(el("legend", {}, spec.title));

    const enableId = `alerts-${name}-enabled`;
    const enableRow = el("div", { className: "form-check-row" });
    const enable = el("input", { type: "checkbox", id: enableId, "data-field": "enabled" });
    enable.checked = Boolean(cfg.enabled);
    enableRow.append(enable, el("label", { for: enableId }, "Send alerts here"));
    fs.append(enableRow, el("p", { className: "alerts-help" }, spec.help));

    spec.fields.forEach((f) => {
      const id = `alerts-${name}-${f.key}`;
      if (f.type === "checkbox") {
        const row = el("div", { className: "form-check-row" });
        const input = el("input", { type: "checkbox", id, "data-field": f.key });
        input.checked = Boolean(cfg[f.key]);
        row.append(input, el("label", { for: id }, f.label));
        fs.append(row);
        return;
      }
      const field = el("div", { className: "form-field" });
      field.append(el("label", { for: id }, f.label));
      const input = el("input", {
        type: f.type, id, className: "form-input", "data-field": f.key,
        autocomplete: f.type === "password" ? "off" : undefined, spellcheck: "false",
      });
      input.value = cfg[f.key] ?? "";
      if (f.generate) {
        const row = el("div", { className: "alerts-input-row" });
        const gen = el("button", { type: "button", className: "btn-secondary" }, "New topic");
        gen.addEventListener("click", () => {
          input.value = randomTopic();
          input.focus();
        });
        row.append(input, gen);
        field.append(row);
      } else {
        field.append(input);
      }
      fs.append(field);
    });

    const actions = el("div", { className: "alerts-channel-actions" });
    const test = el("button", { type: "button", className: "btn-secondary", "data-test": name }, "Send test");
    const status = el("span", { className: "alerts-channel-status", "aria-live": "polite" }, channelStatusText(name, data));
    test.addEventListener("click", () => sendTest(name, status, test));
    actions.append(test, status);
    fs.append(actions);
    wrap.append(fs);
  });
}

function renderRules(data) {
  const wrap = $("alerts-rules");
  if (!wrap) return;
  wrap.replaceChildren();
  const rules = Object.keys(data.rules_info).sort((a, b) => {
    const ia = RULE_ORDER.indexOf(a);
    const ib = RULE_ORDER.indexOf(b);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
  });
  rules.forEach((rule) => {
    const info = data.rules_info[rule];
    const cfg = data.config.rules[rule] || {};
    const row = el("div", { className: "alerts-rule", "data-rule": rule });
    const id = `alerts-rule-${rule}`;
    const check = el("div", { className: "form-check-row" });
    const box = el("input", { type: "checkbox", id, "data-field": "enabled" });
    box.checked = cfg.enabled !== false;
    check.append(box, el("label", { for: id }, info.title));
    check.append(el("span", { className: `alerts-sev sev-${info.severity}` }, SEVERITY_TEXT[info.severity]));
    row.append(check);

    const fields = RULE_FIELDS[rule] || [];
    if (fields.length || rule === "container_down") {
      const opts = el("div", { className: "alerts-rule-opts" });
      fields.forEach((f) => {
        const fid = `${id}-${f.key}`;
        const field = el("div", { className: "form-field" });
        field.append(el("label", { for: fid }, f.label));
        const input = el("input", { type: "number", id: fid, className: "form-input", min: f.min, max: f.max, "data-field": f.key });
        input.value = cfg[f.key] ?? "";
        field.append(input);
        opts.append(field);
      });
      if (rule === "container_down") {
        const fid = `${id}-ignore`;
        const field = el("div", { className: "form-field alerts-wide" });
        field.append(el("label", { for: fid }, "Ignore these containers (comma separated)"));
        const input = el("input", { type: "text", id: fid, className: "form-input", "data-field": "ignore", spellcheck: "false" });
        input.value = (cfg.ignore || []).join(", ");
        field.append(input);
        opts.append(field);
      }
      row.append(opts);
    }
    wrap.append(row);
  });
}

function renderSchedule(data) {
  const q = data.config.quiet_hours;
  const s = data.config.daily_summary;
  const set = (id, prop, value) => { const n = $(id); if (n) n[prop] = value; };
  set("alerts-quiet-enabled", "checked", Boolean(q.enabled));
  set("alerts-quiet-start", "value", q.start);
  set("alerts-quiet-end", "value", q.end);
  set("alerts-summary-enabled", "checked", Boolean(s.enabled));
  set("alerts-summary-time", "value", s.time);
}

function renderAll(data) {
  current = data;
  state.alertsSnapshot = data;
  renderBadge(data);
  renderFiring(data);
  renderChannels(data);
  renderRules(data);
  renderSchedule(data);
  renderHistory(data);
  const hint = $("alerts-hint");
  if (hint) {
    hint.textContent = data.any_channel
      ? (data.quiet_now ? `Quiet hours now: only critical alerts go out${data.queued ? `, ${data.queued} waiting` : ""}.` : "Rules are checked every minute.")
      : "No channel is on yet: alerts are only listed here.";
  }
}

function readChannels() {
  const out = {};
  document.querySelectorAll("#alerts-channels fieldset[data-channel]").forEach((fs) => {
    const name = fs.dataset.channel;
    out[name] = {};
    fs.querySelectorAll("[data-field]").forEach((input) => {
      out[name][input.dataset.field] = input.type === "checkbox" ? input.checked : input.value.trim();
    });
  });
  return out;
}

function readForm() {
  const rules = {};
  document.querySelectorAll("#alerts-rules [data-rule]").forEach((row) => {
    const r = {};
    row.querySelectorAll("[data-field]").forEach((input) => {
      if (input.type === "checkbox") r[input.dataset.field] = input.checked;
      else if (input.dataset.field === "ignore") r.ignore = input.value.split(",").map((v) => v.trim()).filter(Boolean);
      else if (input.value !== "") r[input.dataset.field] = Number(input.value);
    });
    rules[row.dataset.rule] = r;
  });
  return {
    channels: readChannels(),
    rules,
    quiet_hours: { enabled: $("alerts-quiet-enabled").checked, start: $("alerts-quiet-start").value, end: $("alerts-quiet-end").value },
    daily_summary: { enabled: $("alerts-summary-enabled").checked, time: $("alerts-summary-time").value },
  };
}

async function sendTest(name, statusEl, button) {
  button.disabled = true;
  statusEl.textContent = "Sending...";
  try {
    const res = await fetch(ENDPOINTS.alertsTest, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ channel: name, channels: readChannels() }),
    });
    const data = await res.json();
    statusEl.textContent = data.ok ? "Test sent. Check that it arrived." : `Failed: ${data.error}`;
  } catch (_) {
    statusEl.textContent = "Failed: the Control Hub did not answer.";
  } finally {
    button.disabled = false;
  }
}

async function save() {
  const btn = $("alerts-save");
  if (btn) btn.disabled = true;
  try {
    const res = await fetch(ENDPOINTS.alertsConfig, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(readForm()),
    });
    const data = await res.json();
    if (!res.ok) {
      showToast("Alerts not saved", data.error || "Check the values.", "warning");
      return;
    }
    renderAll(data);
    showToast("Alerts saved", data.any_channel ? "Rules are checked every minute." : "Turn on a channel to receive alerts.", "success");
  } catch (_) {
    showToast("Alerts not saved", "The Control Hub did not answer.", "danger");
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function checkNow() {
  const btn = $("alerts-check-now");
  if (btn) btn.disabled = true;
  try {
    const res = await fetch(ENDPOINTS.alertsCheck, { method: "POST" });
    const data = await res.json();
    renderAll(data);
    const n = (data.sent_now || []).length;
    showToast("Rules checked", n ? `${n} alert(s) sent.` : "Nothing new to send.", "info");
  } finally {
    if (btn) btn.disabled = false;
  }
}

export async function fetchAlerts() {
  try {
    const res = await fetch(ENDPOINTS.alerts);
    if (!res.ok) return false;
    const data = await res.json();
    state.alertsSnapshot = data;
    const modal = $("alerts-modal");
    if (modal && modal.style.display !== "none" && current) {
      current = { ...current, firing: data.firing, history: data.history, channel_status: data.channel_status };
      renderBadge(data);
      renderFiring(data);
      renderHistory(data);
    } else {
      current = data;
      renderBadge(data);
    }
    return true;
  } catch (_) {
    return false;
  }
}

async function openAlertsDialog(triggerEl = null) {
  const modal = $("alerts-modal");
  if (!modal) return;
  await fetchAlerts();
  if (current) renderAll(current);
  openModal(modal, triggerEl);
}

export function setupAlerts() {
  const modal = $("alerts-modal");
  const openBtn = $("btn-open-alerts");
  const bannerBtn = $("btn-alerts-banner-open");
  registerModal(modal, { closeButtons: [$("alerts-modal-close"), $("alerts-cancel")] });
  if (openBtn) openBtn.addEventListener("click", () => openAlertsDialog(openBtn));
  if (bannerBtn) bannerBtn.addEventListener("click", () => openAlertsDialog(bannerBtn));

  const saveBtn = $("alerts-save");
  if (saveBtn) saveBtn.addEventListener("click", save);
  const checkBtn = $("alerts-check-now");
  if (checkBtn) checkBtn.addEventListener("click", checkNow);
}
