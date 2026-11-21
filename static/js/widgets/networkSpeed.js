/**
 * Widget: Network & Transfer Speeds
 * Real-time WAN & LAN transfer speeds, unit conversion, 60-second sparkline
 * rendering, and Ookla Speedtest benchmark. Shows honest states when untested.
 */

import { $, setCardSummary } from "../shared/dom.js";
import { state } from "../state.js";
import { ENDPOINTS } from "../config.js";
import { showToast } from "../shared/toast.js";
import { renderTorrents } from "./currentDownloads.js";
import { renderStorageOps } from "./storageOps.js";

const btnUnitMbs = $("btn-unit-mbs");
const btnUnitMbps = $("btn-unit-mbps");

const wanTotalMbps = $("wan-total-mbps");
const wanUnitLabel = $("wan-unit-label");
const wanDlVal = $("wan-dl-val");
const wanUpVal = $("wan-up-val");
const internetIspName = $("internet-isp-name");
const wanTestedTime = $("wan-tested-time");
const btnRunSpeedtest = $("btn-run-speedtest");
const speedtestSpinner = $("speedtest-spinner");
const speedtestIcon = $("speedtest-icon");
const speedtestBtnLabel = $("speedtest-btn-label");
const wanSparklineCanvas = $("wan-sparkline-canvas");
const wanPeakVal = $("wan-peak-val");

const lanTotalMbps = $("lan-total-mbps");
const lanUnitLabel = $("lan-unit-label");
const lanRxVal = $("lan-rx-val");
const lanTxVal = $("lan-tx-val");
const lanNicName = $("lan-nic-name");
const lanNicSpec = $("lan-nic-spec");
const lanTotalSub = $("lan-total-sub");
const btnRefreshLan = $("btn-refresh-lan");
const lanRefreshSpinner = $("lan-refresh-spinner");
const lanRefreshIcon = $("lan-refresh-icon");
const lanSparklineCanvas = $("lan-sparkline-canvas");
const lanPeakVal = $("lan-peak-val");

const wanScale0 = $("wan-scale-0");
const wanScale1 = $("wan-scale-1");
const wanScale2 = $("wan-scale-2");
const wanScale3 = $("wan-scale-3");
const wanScale4 = $("wan-scale-4");

const lanScale0 = $("lan-scale-0");
const lanScale1 = $("lan-scale-1");
const lanScale2 = $("lan-scale-2");
const lanScale3 = $("lan-scale-3");
const lanScale4 = $("lan-scale-4");

let hasMeasuredSpeedtest = false;

export function drawSparkline(canvas, historyData, strokeColor, fillStart, fillEnd, maxVal = 12.5) {
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;

  ctx.clearRect(0, 0, w, h);
  if (!historyData || historyData.length < 2) return;

  const ceiling = Math.max(maxVal, ...historyData, 0.1);
  const stepX = w / 59;

  const grad = ctx.createLinearGradient(0, 0, 0, h);
  grad.addColorStop(0, fillStart);
  grad.addColorStop(1, fillEnd);

  ctx.beginPath();
  const startIdx = 60 - historyData.length;
  ctx.moveTo(startIdx * stepX, h);
  historyData.forEach((val, i) => {
    const x = (startIdx + i) * stepX;
    const y = h - (Math.min(val, ceiling) / ceiling) * (h - 6) - 3;
    ctx.lineTo(x, y);
  });
  ctx.lineTo((startIdx + historyData.length - 1) * stepX, h);
  ctx.closePath();
  ctx.fillStyle = grad;
  ctx.fill();

  ctx.beginPath();
  historyData.forEach((val, i) => {
    const x = (startIdx + i) * stepX;
    const y = h - (Math.min(val, ceiling) / ceiling) * (h - 6) - 3;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = strokeColor;
  ctx.lineWidth = 1.8;
  ctx.stroke();
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

  if (unit === "mbs") {
    if (wanScale0) wanScale0.textContent = "0";
    if (wanScale1) wanScale1.textContent = "3M";
    if (wanScale2) wanScale2.textContent = "6M";
    if (wanScale3) wanScale3.textContent = "9M";
    if (wanScale4) wanScale4.textContent = "12.5M";

    if (lanScale0) lanScale0.textContent = "0";
    if (lanScale1) lanScale1.textContent = "3M";
    if (lanScale2) lanScale2.textContent = "6M";
    if (lanScale3) lanScale3.textContent = "9M";
    if (lanScale4) lanScale4.textContent = "12.5M";
  } else {
    if (wanScale0) wanScale0.textContent = "0";
    if (wanScale1) wanScale1.textContent = "25M";
    if (wanScale2) wanScale2.textContent = "50M";
    if (wanScale3) wanScale3.textContent = "75M";
    if (wanScale4) wanScale4.textContent = "100M";

    if (lanScale0) lanScale0.textContent = "0";
    if (lanScale1) lanScale1.textContent = "25M";
    if (lanScale2) lanScale2.textContent = "50M";
    if (lanScale3) lanScale3.textContent = "75M";
    if (lanScale4) lanScale4.textContent = "100M";
  }

  renderSpeedReadouts();
}

export function renderSpeedReadouts() {
  const isMbps = state.currentUnit === "mbps";
  const multiplier = isMbps ? 8.0 : 1.0;
  const unitStr = isMbps ? "Mbps" : "MB/s";

  if (wanUnitLabel) wanUnitLabel.textContent = unitStr;
  if (lanUnitLabel) lanUnitLabel.textContent = unitStr;

  const hasWanRate = hasMeasuredSpeedtest || state.lastWanDlMbs > 0 || state.lastWanUpMbs > 0;
  if (hasWanRate) {
    const wanDlDisplay = (state.lastWanDlMbs * multiplier).toFixed(1);
    const wanUpDisplay = (state.lastWanUpMbs * multiplier).toFixed(1);
    const wanPeakDisplay = (state.wanPeakMbs * multiplier).toFixed(1);
    if (wanTotalMbps) wanTotalMbps.textContent = wanDlDisplay;
    if (wanDlVal) wanDlVal.textContent = `${wanDlDisplay} ${unitStr}`;
    if (wanUpVal) wanUpVal.textContent = `${wanUpDisplay} ${unitStr}`;
    if (wanPeakVal) wanPeakVal.textContent = `${wanPeakDisplay} ${unitStr}`;
  } else {
    if (wanTotalMbps) wanTotalMbps.textContent = "--";
    if (wanDlVal) wanDlVal.textContent = "Not tested";
    if (wanUpVal) wanUpVal.textContent = "Not tested";
    if (wanPeakVal) wanPeakVal.textContent = "--";
  }

  const lanDisplay = (state.lastLanTotalMbs * multiplier).toFixed(2);
  const lanRxDisplay = (state.lastLanRxMbs * multiplier).toFixed(2);
  const lanTxDisplay = (state.lastLanTxMbs * multiplier).toFixed(2);
  const lanPeakDisplay = (state.lanPeakMbs * multiplier).toFixed(2);

  if (lanTotalMbps) lanTotalMbps.textContent = lanDisplay;
  if (lanRxVal) lanRxVal.textContent = `${lanRxDisplay} ${unitStr}`;
  if (lanTxVal) lanTxVal.textContent = `${lanTxDisplay} ${unitStr}`;
  if (lanPeakVal) lanPeakVal.textContent = `${lanPeakDisplay} ${unitStr}`;

  setCardSummary(
    "speedometers",
    `Network: WAN ${hasWanRate ? `${(state.lastWanDlMbs * multiplier).toFixed(1)} ${unitStr}` : "untested"} · LAN ${lanDisplay} ${unitStr}`
  );
}

export async function fetchSpeedometers() {
  try {
    const res = await fetch(ENDPOINTS.networkSpeed);
    if (!res.ok) return;
    const data = await res.json();

    const inet = data.internet || {};
    const sp = data.speedtest || {};
    hasMeasuredSpeedtest = Boolean(sp.available && typeof sp.download_mbs === "number");

    let dlMbs = typeof inet.dl_mbs === "number" ? inet.dl_mbs : 0.0;
    let upMbs = typeof inet.up_mbs === "number" ? inet.up_mbs : 0.0;
    if (dlMbs === 0 && typeof sp.download_mbs === "number") dlMbs = sp.download_mbs;
    if (upMbs === 0 && typeof sp.upload_mbs === "number") upMbs = sp.upload_mbs;

    state.lastWanDlMbs = dlMbs;
    state.lastWanUpMbs = upMbs;
    if (dlMbs > state.wanPeakMbs) state.wanPeakMbs = dlMbs;

    if (hasMeasuredSpeedtest || dlMbs > 0) {
      state.wanHistory.push(dlMbs);
      if (state.wanHistory.length > 60) state.wanHistory.shift();
      drawSparkline(wanSparklineCanvas, state.wanHistory, "#00f2fe", "rgba(0, 242, 254, 0.35)", "rgba(0, 242, 254, 0.0)", 12.5);
    }

    if (internetIspName) {
      if (sp.available && sp.isp) {
        const pingTxt = typeof sp.ping_ms === "number" ? ` (${sp.ping_ms} ms)` : "";
        internetIspName.textContent = `${sp.isp}${pingTxt}`;
      } else {
        internetIspName.textContent = "Not tested yet";
      }
    }
    if (wanTestedTime) {
      if (sp.available && sp.isp) {
        const timeStr = sp.tested_at ? ` • ${sp.tested_at}` : "";
        wanTestedTime.textContent = `${sp.isp} Line Benchmark${timeStr}`;
      } else {
        wanTestedTime.textContent = sp.reason || "Run speedtest to measure line";
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
    drawSparkline(lanSparklineCanvas, state.lanHistory, "#00f5a0", "rgba(0, 245, 160, 0.35)", "rgba(0, 245, 160, 0.0)", 12.5);

    if (lanNicName) lanNicName.textContent = net.interface || "Unknown";
    if (lanNicSpec) lanNicSpec.textContent = net.spec_text || "Link unknown";
    if (net.link_speed_mbps && lanTotalSub) {
      const linkLabel = net.link_speed_mbps >= 1000 ? `${(net.link_speed_mbps / 1000).toFixed(0)} Gbps` : `${net.link_speed_mbps} Mbps`;
      const duplex = String(net.duplex || "").toLowerCase();
      const duplexLabel = duplex === "full" ? "Full Duplex" : duplex === "half" ? "Half Duplex" : "duplex unknown";
      lanTotalSub.textContent = `Ethernet Traffic • ${linkLabel} ${duplexLabel}`;
    }

    renderSpeedReadouts();

    if (data.torrents_queue) renderTorrents(data.torrents_queue);
    if (data.storage_ops) renderStorageOps(data.storage_ops);

    if (btnRunSpeedtest) btnRunSpeedtest.disabled = Boolean(sp.is_testing);
    if (speedtestSpinner) speedtestSpinner.style.display = sp.is_testing ? "inline-block" : "none";
    if (speedtestIcon) speedtestIcon.style.display = sp.is_testing ? "none" : "inline-block";
    if (speedtestBtnLabel) speedtestBtnLabel.textContent = sp.is_testing ? "Benchmarking..." : "Run Speedtest";
  } catch (err) {
    console.error("Error fetching speedometers:", err);
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
    if (data.success) {
      showToast("Speedtest Started", "Running Ookla benchmark in background...", "🚀");
      let attempts = 0;
      const pollId = setInterval(async () => {
        attempts++;
        const sRes = await fetch(ENDPOINTS.speedtestLatest);
        const sData = await sRes.json();
        if (!sData.is_testing || attempts >= 25) {
          clearInterval(pollId);
          await fetchSpeedometers();
          if (sData.available) {
            showToast(
              "Speedtest Complete",
              `↓ ${sData.download_mbps} Mbps | ↑ ${sData.upload_mbps} Mbps (${sData.ping_ms}ms)`,
              "⚡"
            );
          }
        }
      }, 2500);
    } else {
      showToast("Speedtest Busy", data.message || "Speedtest already in progress", "⚠️");
      await fetchSpeedometers();
    }
  } catch (_) {
    showToast("Error", "Could not trigger speedtest benchmark", "❌");
    btnRunSpeedtest.disabled = false;
    if (speedtestSpinner) speedtestSpinner.style.display = "none";
    if (speedtestIcon) speedtestIcon.style.display = "inline-block";
    if (speedtestBtnLabel) speedtestBtnLabel.textContent = "Run Speedtest";
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
        }, 500);
      });
    });
  }
}
