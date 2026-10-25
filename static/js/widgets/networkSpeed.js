/**
 * Widget: Network & Transfer Speeds
 * Real-time WAN (Broadband Fiber) & LAN (Ethernet) transfer speeds, unit conversion,
 * 60-second canvas sparkline rendering, and Ookla Speedtest line benchmark.
 */

import { $ } from "../shared/dom.js";
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

export function drawSparkline(canvas, historyData, strokeColor, fillStart, fillEnd, maxVal = 12.5) {
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;

  ctx.clearRect(0, 0, w, h);
  if (!historyData || historyData.length < 2) return;

  const ceiling = Math.max(maxVal, ...historyData, 0.1);
  const stepX = w / 59; // 60 data points

  // Gradient Fill Area
  const grad = ctx.createLinearGradient(0, 0, 0, h);
  grad.addColorStop(0, fillStart);
  grad.addColorStop(1, fillEnd);

  ctx.beginPath();
  const startIdx = 60 - historyData.length;
  ctx.moveTo(startIdx * stepX, h);

  historyData.forEach((val, i) => {
    const x = (startIdx + i) * stepX;
    const y = h - (Math.min(val, ceiling) / ceiling) * (h - 6) - 3;
    if (i === 0) {
      ctx.lineTo(x, y);
    } else {
      ctx.lineTo(x, y);
    }
  });

  ctx.lineTo((startIdx + historyData.length - 1) * stepX, h);
  ctx.closePath();
  ctx.fillStyle = grad;
  ctx.fill();

  // Stroke Line
  ctx.beginPath();
  historyData.forEach((val, i) => {
    const x = (startIdx + i) * stepX;
    const y = h - (Math.min(val, ceiling) / ceiling) * (h - 6) - 3;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = strokeColor;
  ctx.lineWidth = 1.8;
  ctx.shadowColor = strokeColor;
  ctx.shadowBlur = 6;
  ctx.stroke();
  ctx.shadowBlur = 0;

  // Active Head Pulse Dot
  const lastX = (startIdx + historyData.length - 1) * stepX;
  const lastY = h - (Math.min(historyData[historyData.length - 1], ceiling) / ceiling) * (h - 6) - 3;
  ctx.beginPath();
  ctx.arc(lastX, lastY, 3, 0, Math.PI * 2);
  ctx.fillStyle = "#ffffff";
  ctx.shadowColor = strokeColor;
  ctx.shadowBlur = 8;
  ctx.fill();
  ctx.shadowBlur = 0;
}

export function setUnit(unit) {
  state.currentUnit = unit;
  if (btnUnitMbs) btnUnitMbs.classList.toggle("active", unit === "mbs");
  if (btnUnitMbps) btnUnitMbps.classList.toggle("active", unit === "mbps");

  // Scale labels
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
  const isMbps = (state.currentUnit === "mbps");
  const multiplier = isMbps ? 8.0 : 1.0;
  const unitStr = isMbps ? "Mbps" : "MB/s";

  if (wanUnitLabel) wanUnitLabel.textContent = unitStr;
  if (lanUnitLabel) lanUnitLabel.textContent = unitStr;

  const wanDisplay = (state.lastWanDlMbs * multiplier).toFixed(1);
  const wanDlDisplay = (state.lastWanDlMbs * multiplier).toFixed(1);
  const wanUpDisplay = (state.lastWanUpMbs * multiplier).toFixed(1);
  const wanPeakDisplay = (state.wanPeakMbs * multiplier).toFixed(1);

  if (wanTotalMbps) wanTotalMbps.textContent = wanDisplay;
  if (wanDlVal) wanDlVal.textContent = `${wanDlDisplay} ${unitStr}`;
  if (wanUpVal) wanUpVal.textContent = `${wanUpDisplay} ${unitStr}`;
  if (wanPeakVal) wanPeakVal.textContent = `${wanPeakDisplay} ${unitStr}`;

  const lanDisplay = (state.lastLanTotalMbs * multiplier).toFixed(2);
  const lanRxDisplay = (state.lastLanRxMbs * multiplier).toFixed(2);
  const lanTxDisplay = (state.lastLanTxMbs * multiplier).toFixed(2);
  const lanPeakDisplay = (state.lanPeakMbs * multiplier).toFixed(2);

  if (lanTotalMbps) lanTotalMbps.textContent = lanDisplay;
  if (lanRxVal) lanRxVal.textContent = `${lanRxDisplay} ${unitStr}`;
  if (lanTxVal) lanTxVal.textContent = `${lanTxDisplay} ${unitStr}`;
  if (lanPeakVal) lanPeakVal.textContent = `${lanPeakDisplay} ${unitStr}`;
}

export async function fetchSpeedometers() {
  try {
    const res = await fetch(ENDPOINTS.networkSpeed);
    const data = await res.json();

    // 1. WAN Internet
    const inet = data.internet || {};
    const sp = data.speedtest || {};

    let dlMbs = inet.dl_mbs !== undefined ? inet.dl_mbs : 0.0;
    let upMbs = inet.up_mbs !== undefined ? inet.up_mbs : 0.0;
    if (dlMbs === 0 && sp.download_mbs) dlMbs = sp.download_mbs;
    if (upMbs === 0 && sp.upload_mbs) upMbs = sp.upload_mbs;

    state.lastWanDlMbs = dlMbs;
    state.lastWanUpMbs = upMbs;
    if (dlMbs > state.wanPeakMbs) state.wanPeakMbs = dlMbs;

    state.wanHistory.push(dlMbs);
    if (state.wanHistory.length > 60) state.wanHistory.shift();
    drawSparkline(wanSparklineCanvas, state.wanHistory, "#00f2fe", "rgba(0, 242, 254, 0.35)", "rgba(0, 242, 254, 0.0)", 12.5);

    const isp = sp.isp || "Excitel";
    const ping = sp.ping_ms || 2.7;
    if (internetIspName) internetIspName.textContent = `${isp} (${ping}ms)`;
    if (wanTestedTime) {
      const timeStr = sp.tested_at ? ` • ${sp.tested_at}` : "";
      wanTestedTime.textContent = `${isp} Line Benchmark${timeStr}`;
    }

    // 2. LAN Interface
    const net = data.network || {};
    const totalLanMbs = net.total_mbs !== undefined ? net.total_mbs : 0.0;
    const rxMbs = net.rx_mbs !== undefined ? net.rx_mbs : 0.0;
    const txMbs = net.tx_mbs !== undefined ? net.tx_mbs : 0.0;

    state.lastLanTotalMbs = totalLanMbs;
    state.lastLanRxMbs = rxMbs;
    state.lastLanTxMbs = txMbs;
    if (totalLanMbs > state.lanPeakMbs) state.lanPeakMbs = totalLanMbs;

    state.lanHistory.push(totalLanMbs);
    if (state.lanHistory.length > 60) state.lanHistory.shift();
    drawSparkline(lanSparklineCanvas, state.lanHistory, "#00f5a0", "rgba(0, 245, 160, 0.35)", "rgba(0, 245, 160, 0.0)", 12.5);

    if (net.interface && lanNicName) lanNicName.textContent = net.interface;
    if (net.spec_text && lanNicSpec) lanNicSpec.textContent = net.spec_text;
    if (net.link_speed_mbps && lanTotalSub) {
      const linkLabel = net.link_speed_mbps >= 1000 ? `${(net.link_speed_mbps / 1000).toFixed(0)} Gbps` : `${net.link_speed_mbps} Mbps`;
      lanTotalSub.textContent = `Ethernet Traffic • ${linkLabel} ${(net.duplex || "Full").toUpperCase() === "FULL" ? "Full Duplex" : "Half Duplex"}`;
    }

    renderSpeedReadouts();

    // Pass data along to child widgets
    if (data.torrents_queue) renderTorrents(data.torrents_queue);
    if (data.storage_ops) renderStorageOps(data.storage_ops);

    // Speedtest running state
    if (sp.is_testing) {
      if (btnRunSpeedtest) btnRunSpeedtest.disabled = true;
      if (speedtestSpinner) speedtestSpinner.style.display = "inline-block";
      if (speedtestIcon) speedtestIcon.style.display = "none";
      if (speedtestBtnLabel) speedtestBtnLabel.textContent = "Benchmarking Line...";
    } else {
      if (btnRunSpeedtest) btnRunSpeedtest.disabled = false;
      if (speedtestSpinner) speedtestSpinner.style.display = "none";
      if (speedtestIcon) speedtestIcon.style.display = "inline-block";
      if (speedtestBtnLabel) speedtestBtnLabel.textContent = "Refresh Internet Speed";
    }
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
      showToast("Speedtest Started", "Running official Ookla benchmark in background...", "🚀");
      // Poll faster for results
      let attempts = 0;
      const pollId = setInterval(async () => {
        attempts++;
        const sRes = await fetch(ENDPOINTS.speedtestLatest);
        const sData = await sRes.json();
        if (!sData.is_testing || attempts >= 25) {
          clearInterval(pollId);
          await fetchSpeedometers();
          showToast(
            "Speedtest Complete",
            `↓ ${sData.download_mbps || 0} Mbps | ↑ ${sData.upload_mbps || 0} Mbps (${sData.ping_ms || 0}ms)`,
            "⚡"
          );
        }
      }, 2500);
    } else {
      showToast("Speedtest Busy", data.message || "Speedtest already in progress", "⚠️");
    }
  } catch (err) {
    showToast("Error", "Could not trigger speedtest benchmark", "❌");
    btnRunSpeedtest.disabled = false;
    if (speedtestSpinner) speedtestSpinner.style.display = "none";
    if (speedtestIcon) speedtestIcon.style.display = "inline-block";
    if (speedtestBtnLabel) speedtestBtnLabel.textContent = "Refresh Internet Speed";
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
        }, 600);
      });
    });
  }
}
