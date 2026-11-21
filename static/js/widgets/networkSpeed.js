/**
 * Widget: Network & Speedtest Lab
 * Strictly separates Live Server Interface (LAN) real-time throughput from
 * on-demand Broadband Benchmark (Speedtest). Renders HiDPI Retina sparklines
 * with dynamic Y-axis ticks and surfaces real Speedtest errors honestly.
 */

import { $, setCardSummary } from "../shared/dom.js";
import { state } from "../state.js";
import { ENDPOINTS } from "../config.js";
import { showToast } from "../shared/toast.js";
import { renderTorrents } from "./currentDownloads.js";
import { renderStorageOps } from "./storageOps.js";
import { renderOverview } from "./overview.js";

const btnUnitMbs = $("btn-unit-mbs");
const btnUnitMbps = $("btn-unit-mbps");

const lanTotalMbps = $("lan-total-mbps");
const lanUnitLabel = $("lan-unit-label");
const lanRxVal = $("lan-rx-val");
const lanTxVal = $("lan-tx-val");
const lanPeakVal = $("lan-peak-val");
const lanNicName = $("lan-nic-name");
const lanNicSpec = $("lan-nic-spec");
const lanTotalSub = $("lan-total-sub");
const btnRefreshLan = $("btn-refresh-lan");
const lanRefreshSpinner = $("lan-refresh-spinner");
const lanRefreshIcon = $("lan-refresh-icon");
const lanSparklineCanvas = $("lan-sparkline-canvas");

const lanScaleMax = $("lan-scale-max");
const lanScaleMid = $("lan-scale-mid");
const lanScaleMin = $("lan-scale-min");

const internetIspName = $("internet-isp-name");
const wanTestedTime = $("wan-tested-time");
const wanDlVal = $("wan-dl-val");
const wanUpVal = $("wan-up-val");
const wanPingVal = $("wan-ping-val");
const speedtestServerNote = $("speedtest-server-note");
const speedtestErrorNote = $("speedtest-error-note");
const btnRunSpeedtest = $("btn-run-speedtest");
const speedtestSpinner = $("speedtest-spinner");
const speedtestIcon = $("speedtest-icon");
const speedtestBtnLabel = $("speedtest-btn-label");

function niceCeiling(maxData, unit) {
  const minFloor = unit === "mbps" ? 10 : 1.5;
  const raw = Math.max(minFloor, maxData * 1.2);
  const steps = unit === "mbps"
    ? [10, 25, 50, 100, 250, 500, 1000, 2500]
    : [1.5, 5, 10, 25, 50, 100, 125, 250, 500];
  return steps.find((s) => s >= raw) || Math.ceil(raw / 50) * 50;
}

export function drawLanSparkline() {
  const canvas = lanSparklineCanvas;
  if (!canvas) return;
  const rect = canvas.getBoundingClientRect();
  if (rect.width === 0 || rect.height === 0) return;

  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const cssW = Math.round(rect.width);
  const cssH = Math.round(rect.height);
  if (canvas.width !== Math.round(cssW * dpr) || canvas.height !== Math.round(cssH * dpr)) {
    canvas.width = Math.round(cssW * dpr);
    canvas.height = Math.round(cssH * dpr);
  }

  const ctx = canvas.getContext("2d");
  ctx.save();
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, cssW, cssH);

  const styles = getComputedStyle(document.documentElement);
  const strokeColor = styles.getPropertyValue("--spark-stroke").trim() || "#38bdf8";
  const fillTop = styles.getPropertyValue("--spark-fill-top").trim() || "rgba(56, 189, 248, 0.25)";
  const fillBottom = styles.getPropertyValue("--spark-fill-bottom").trim() || "rgba(56, 189, 248, 0)";
  const gridColor = styles.getPropertyValue("--spark-grid").trim() || "rgba(148, 163, 184, 0.14)";

  const isMbps = state.currentUnit === "mbps";
  const mult = isMbps ? 8.0 : 1.0;
  const unitStr = isMbps ? "Mbps" : "MB/s";
  const series = (state.lanHistory || []).map((v) => v * mult);
  const maxPoint = series.length ? Math.max(...series) : 0;
  const ceiling = niceCeiling(maxPoint, state.currentUnit);

  if (lanScaleMax) lanScaleMax.textContent = `${ceiling} ${unitStr}`;
  if (lanScaleMid) lanScaleMid.textContent = `${(ceiling / 2).toFixed(ceiling < 10 ? 1 : 0)} ${unitStr}`;
  if (lanScaleMin) lanScaleMin.textContent = "0";

  // Subtle horizontal mid-line grid
  ctx.strokeStyle = gridColor;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(0, cssH / 2);
  ctx.lineTo(cssW, cssH / 2);
  ctx.stroke();

  if (series.length < 2) {
    ctx.restore();
    return;
  }

  const maxPoints = 60;
  const stepX = cssW / (maxPoints - 1);
  const startIdx = maxPoints - series.length;
  const padY = 4;
  const plotH = cssH - padY * 2;

  const grad = ctx.createLinearGradient(0, 0, 0, cssH);
  grad.addColorStop(0, fillTop);
  grad.addColorStop(1, fillBottom);

  ctx.beginPath();
  ctx.moveTo(startIdx * stepX, cssH);
  series.forEach((val, i) => {
    const x = (startIdx + i) * stepX;
    const y = cssH - padY - (Math.min(val, ceiling) / ceiling) * plotH;
    ctx.lineTo(x, y);
  });
  ctx.lineTo((startIdx + series.length - 1) * stepX, cssH);
  ctx.closePath();
  ctx.fillStyle = grad;
  ctx.fill();

  ctx.beginPath();
  series.forEach((val, i) => {
    const x = (startIdx + i) * stepX;
    const y = cssH - padY - (Math.min(val, ceiling) / ceiling) * plotH;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = strokeColor;
  ctx.lineWidth = 2;
  ctx.lineJoin = "round";
  ctx.stroke();
  ctx.restore();
}

export function setUnit(unit) {
  state.currentUnit = unit;
  if (btnUnitMbs) {
    btnUnitMbs.classList.toggle("active", unit === "mbs");
    btnUnitMbs.setAttribute("aria-pressed", unit === "mbs" ? "true" : "false");
  }
  if (btnUnitMbps) {
    btnUnitMbps.classList.toggle("active", unit === "mbps");
    btnUnitMbps.setAttribute("aria-pressed", unit === "mbps" ? "true" : "false");
  }
  renderSpeedReadouts();
  drawLanSparkline();
  renderOverview();
}

export function renderSpeedReadouts() {
  const isMbps = state.currentUnit === "mbps";
  const mult = isMbps ? 8.0 : 1.0;
  const unitStr = isMbps ? "Mbps" : "MB/s";

  if (lanUnitLabel) lanUnitLabel.textContent = unitStr;
  const lanDisplay = (state.lastLanTotalMbs * mult).toFixed(2);
  const lanRxDisplay = (state.lastLanRxMbs * mult).toFixed(2);
  const lanTxDisplay = (state.lastLanTxMbs * mult).toFixed(2);
  const lanPeakDisplay = (state.lanPeakMbs * mult).toFixed(2);

  if (lanTotalMbps) lanTotalMbps.textContent = lanDisplay;
  if (lanRxVal) lanRxVal.textContent = `${lanRxDisplay} ${unitStr}`;
  if (lanTxVal) lanTxVal.textContent = `${lanTxDisplay} ${unitStr}`;
  if (lanPeakVal) lanPeakVal.textContent = `${lanPeakDisplay} ${unitStr}`;

  const sp = state.lastSpeedtest || {};
  if (sp.available && typeof sp.download_mbs === "number") {
    const dlTxt = isMbps ? `${sp.download_mbps} Mbps` : `${sp.download_mbs} MB/s`;
    const ulTxt = isMbps ? `${sp.upload_mbps} Mbps` : `${sp.upload_mbs} MB/s`;
    if (wanDlVal) wanDlVal.textContent = dlTxt;
    if (wanUpVal) wanUpVal.textContent = ulTxt;
    if (wanPingVal) wanPingVal.textContent = typeof sp.ping_ms === "number" ? `${sp.ping_ms} ms` : "--";
  } else {
    if (wanDlVal) wanDlVal.textContent = "Not tested";
    if (wanUpVal) wanUpVal.textContent = "Not tested";
    if (wanPingVal) wanPingVal.textContent = "--";
  }

  setCardSummary(
    "speedometers",
    `LAN ${lanDisplay} ${unitStr}${sp.available && typeof sp.download_mbps === "number" ? ` · ISP ↓ ${sp.download_mbps} Mbps` : ""}`
  );
}

export async function fetchSpeedometers() {
  try {
    const res = await fetch(ENDPOINTS.networkSpeed);
    if (!res.ok) return false;
    const data = await res.json();

    const sp = data.speedtest || {};
    state.lastSpeedtest = sp;

    if (internetIspName) {
      internetIspName.textContent = sp.available && sp.isp ? sp.isp : "Not tested yet";
    }
    if (wanTestedTime) {
      wanTestedTime.textContent = sp.available && sp.tested_at
        ? `Last tested ${sp.tested_at}`
        : (sp.reason || "Run speedtest to benchmark ISP line");
    }
    if (speedtestServerNote) {
      speedtestServerNote.textContent = sp.available && sp.server ? `Server: ${sp.server}` : "";
    }
    if (speedtestErrorNote) {
      if (sp.last_error) {
        speedtestErrorNote.textContent = `Last speedtest error: ${sp.last_error}`;
        speedtestErrorNote.hidden = false;
      } else if (sp.cli_available === false) {
        speedtestErrorNote.textContent = "No speedtest CLI installed on host (install Ookla speedtest or speedtest-cli).";
        speedtestErrorNote.hidden = false;
      } else {
        speedtestErrorNote.hidden = true;
      }
    }

    const net = data.network || {};
    const totalLanMbs = typeof net.total_mbs === "number" ? net.total_mbs : 0.0;
    const rxMbs = typeof net.rx_mbs === "number" ? net.rx_mbs : 0.0;
    const txMbs = typeof net.tx_mbs === "number" ? net.tx_mbs : 0.0;

    state.lastLanTotalMbs = totalLanMbs;
    state.lastLanRxMbs = rxMbs;
    state.lastLanTxMbs = txMbs;
    if (totalLanMbs > state.lanPeakMbs) state.lanPeakMbs = totalLanMbs;

    state.lanHistory.push(totalLanMbs);
    if (state.lanHistory.length > 60) state.lanHistory.shift();

    if (lanNicName) lanNicName.textContent = net.interface || "No NIC detected";
    if (lanNicSpec) lanNicSpec.textContent = net.spec_text || "Link speed unavailable";
    if (lanTotalSub) {
      lanTotalSub.textContent = net.interface
        ? `Live throughput on ${net.interface}`
        : "No active physical interface";
    }

    renderSpeedReadouts();
    drawLanSparkline();

    if (data.torrents_queue) renderTorrents(data.torrents_queue);
    if (data.storage_ops) renderStorageOps(data.storage_ops);

    const testing = Boolean(sp.is_testing);
    const cliMissing = sp.cli_available === false;
    if (btnRunSpeedtest) btnRunSpeedtest.disabled = testing || cliMissing;
    if (speedtestSpinner) speedtestSpinner.style.display = testing ? "inline-block" : "none";
    if (speedtestIcon) speedtestIcon.style.display = testing ? "none" : "inline-block";
    if (speedtestBtnLabel) {
      speedtestBtnLabel.textContent = testing
        ? "Benchmarking..."
        : (cliMissing ? "CLI Not Installed" : "Run Speedtest");
    }

    renderOverview();
    return true;
  } catch (err) {
    console.error("Error fetching speedometers:", err);
    return false;
  }
}

export async function triggerSpeedtest() {
  if (!btnRunSpeedtest) return;
  btnRunSpeedtest.disabled = true;
  if (speedtestSpinner) speedtestSpinner.style.display = "inline-block";
  if (speedtestIcon) speedtestIcon.style.display = "none";
  if (speedtestBtnLabel) speedtestBtnLabel.textContent = "Benchmarking...";

  try {
    const res = await fetch(ENDPOINTS.speedtestRun, { method: "POST" });
    const data = await res.json();
    if (res.ok && data.success) {
      showToast("Speedtest Started", "Running ISP benchmark in background...", "info");
      let attempts = 0;
      const pollId = setInterval(async () => {
        attempts += 1;
        const sRes = await fetch(ENDPOINTS.speedtestLatest);
        const sData = await sRes.json();
        if (!sData.is_testing || attempts >= 28) {
          clearInterval(pollId);
          await fetchSpeedometers();
          if (sData.last_error) {
            showToast("Speedtest Failed", sData.last_error, "danger");
          } else if (sData.available) {
            showToast(
              "Speedtest Complete",
              `↓ ${sData.download_mbps} Mbps | ↑ ${sData.upload_mbps} Mbps (${sData.ping_ms} ms)`,
              "success"
            );
          }
        }
      }, 2500);
    } else {
      showToast("Speedtest Unavailable", data.message || "Speedtest could not start.", "warning");
      await fetchSpeedometers();
    }
  } catch (_) {
    showToast("Error", "Could not trigger speedtest benchmark", "danger");
    await fetchSpeedometers();
  }
}

export function setupNetworkSpeed() {
  if (btnUnitMbs) btnUnitMbs.addEventListener("click", () => setUnit("mbs"));
  if (btnUnitMbps) btnUnitMbps.addEventListener("click", () => setUnit("mbps"));
  if (btnRunSpeedtest) btnRunSpeedtest.addEventListener("click", triggerSpeedtest);

  if (btnRefreshLan) {
    btnRefreshLan.addEventListener("click", () => {
      if (lanRefreshSpinner) lanRefreshSpinner.style.display = "inline-block";
      if (lanRefreshIcon) lanRefreshIcon.style.display = "none";
      fetchSpeedometers().finally(() => {
        setTimeout(() => {
          if (lanRefreshSpinner) lanRefreshSpinner.style.display = "none";
          if (lanRefreshIcon) lanRefreshIcon.style.display = "inline-block";
        }, 400);
      });
    });
  }

  if (lanSparklineCanvas && typeof ResizeObserver !== "undefined") {
    const ro = new ResizeObserver(() => drawLanSparkline());
    ro.observe(lanSparklineCanvas);
  }
}
