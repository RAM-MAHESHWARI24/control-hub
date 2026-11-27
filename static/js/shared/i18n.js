/**
 * Control Hub Localization (Phase 4D): English & Hindi (हिन्दी)
 * Local-only dictionary switching key navigation, headers, and action labels cleanly.
 */

const LANG_KEY = "hub_lang";

const DICTIONARIES = {
  en: {
    nav_overview: "Overview",
    nav_apps: "Apps",
    nav_backups: "Backups",
    nav_tvs: "TVs",
    nav_system: "System",
    heading_quick_launch: "Quick Launch",
    heading_managed_containers: "Managed Containers",
    heading_photo_backup: "Photo Cloud Backup",
    heading_tv_fleet: "Android TV Fleet",
    heading_system_vitals: "Hardware Vitals & Storage",
    heading_sleep_guard: "Sleep Guard",
    heading_history_insights: "History & Monthly Insights",
    heading_network_health: "Network Ports, Tailscale & Port Map",
    heading_integrations: "Integrations (Home Assistant & UPS)",
    heading_node_admin: "Node Administration",
    btn_refresh: "Refresh",
    btn_customize_layout: "Customize Layout",
    btn_kiosk_mode: "Wall Kiosk Mode",
    btn_exit_kiosk: "Exit Kiosk",
  },
  hi: {
    nav_overview: "सारांश",
    nav_apps: "ऐप्स",
    nav_backups: "बैकअप",
    nav_tvs: "टीवी",
    nav_system: "सिस्टम",
    heading_quick_launch: "त्वरित लॉन्च",
    heading_managed_containers: "प्रबंधित कंटेनर",
    heading_photo_backup: "फ़ोटो क्लाउड बैकअप",
    heading_tv_fleet: "एंड्रॉइड टीवी बेड़ा",
    heading_system_vitals: "हार्डवेयर स्वास्थ्य और स्टोरेज",
    heading_sleep_guard: "स्लीप गार्ड",
    heading_history_insights: "इतिहास और मासिक रिपोर्ट",
    heading_network_health: "नेटवर्क पोर्ट्स, टेलस्केल और पोर्ट मैप",
    heading_integrations: "एकीकरण (होम असिस्टेंट और UPS)",
    heading_node_admin: "नोड प्रशासन",
    btn_refresh: "रिफ्रेश",
    btn_customize_layout: "लेआउट अनुकूलित करें",
    btn_kiosk_mode: "किओस्क मोड",
    btn_exit_kiosk: "किओस्क बंद करें",
  },
};

export function getSavedLanguage() {
  try {
    const raw = localStorage.getItem(LANG_KEY);
    return raw === "hi" ? "hi" : "en";
  } catch (_) {
    return "en";
  }
}

export function applyLanguage(lang = "en") {
  const code = lang === "hi" ? "hi" : "en";
  const dict = DICTIONARIES[code] || DICTIONARIES.en;
  document.documentElement.lang = code;
  document.documentElement.dataset.lang = code;
  try {
    localStorage.setItem(LANG_KEY, code);
  } catch (_) { /* ignore */ }

  document.querySelectorAll("[data-i18n]").forEach((el) => {
    const key = el.getAttribute("data-i18n");
    if (key && dict[key]) {
      el.textContent = dict[key];
    }
  });

  document.querySelectorAll(".lang-opt-btn").forEach((btn) => {
    const active = btn.getAttribute("data-lang-choice") === code;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-pressed", active ? "true" : "false");
  });
}

export function setupI18n() {
  document.querySelectorAll(".lang-opt-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      applyLanguage(btn.getAttribute("data-lang-choice") || "en");
    });
  });
  applyLanguage(getSavedLanguage());
}
