/*
 * Görevli ekranı: dinamik QR kodun yenilenmesi, oturum sayacı ve canlı listenin
 * güncellenmesi.
 */
(function () {
  "use strict";

  const wrapper = document.getElementById("liveWrapper");
  if (!wrapper) return;

  const codeUrl = wrapper.dataset.codeUrl;
  const stateUrl = wrapper.dataset.stateUrl;
  const qrUrl = wrapper.dataset.qrUrl;
  const detailUrl = wrapper.dataset.detailUrl;

  const qrImage = document.getElementById("qrImage");
  const codeText = document.getElementById("codeText");
  const refreshBar = document.getElementById("refreshBar");
  const refreshInfo = document.getElementById("refreshInfo");
  const countdown = document.getElementById("sessionCountdown");
  const closedNotice = document.getElementById("closedNotice");
  const liveList = document.getElementById("liveList");
  const lastUpdate = document.getElementById("lastUpdate");

  let refreshSeconds = parseInt(wrapper.dataset.refreshSeconds, 10) || 15;
  let secondsLeft = 0;
  let secondsToRefresh = refreshSeconds;
  let sessionOpen = wrapper.dataset.isOpen === "1";

  function formatClock(totalSeconds) {
    if (totalSeconds < 0) totalSeconds = 0;
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    return String(minutes).padStart(2, "0") + ":" + String(seconds).padStart(2, "0");
  }

  function markClosed(message) {
    sessionOpen = false;
    if (closedNotice) {
      closedNotice.textContent = message || "Bu oturum kapandı. Yeni kayıt alınamaz.";
      closedNotice.classList.remove("d-none");
    }
    if (qrImage) qrImage.classList.add("opacity-25");
    if (codeText) codeText.textContent = "KAPANDI";
    if (refreshBar) refreshBar.style.width = "0%";
    if (refreshInfo) refreshInfo.textContent = "Oturum kapandı.";
  }

  async function fetchCode() {
    if (!sessionOpen) return;
    try {
      const response = await fetch(codeUrl, { headers: { "Accept": "application/json" } });
      if (!response.ok) throw new Error("kod alınamadı");
      const data = await response.json();

      if (!data.is_open) {
        markClosed(data.message);
        setTimeout(function () { window.location.href = detailUrl; }, 2500);
        return;
      }

      refreshSeconds = data.refresh_seconds || refreshSeconds;
      secondsToRefresh = data.refresh_in || refreshSeconds;
      secondsLeft = data.seconds_left;

      if (codeText) codeText.textContent = data.code;
      if (qrImage) qrImage.src = qrUrl + "?t=" + Date.now();
    } catch (error) {
      if (refreshInfo) {
        refreshInfo.textContent = "Bağlantı hatası, yeniden denenecek…";
      }
    }
  }

  async function fetchState() {
    try {
      const response = await fetch(stateUrl, { headers: { "Accept": "application/json" } });
      if (!response.ok) return;
      const data = await response.json();
      const summary = data.summary || {};

      setText("statPresent", summary.present);
      setText("statAbsent", summary.absent);
      setText("statExcused", (summary.excused || 0) + (summary.reported || 0));
      setText("statRate", (summary.rate || 0) + "%");

      if (liveList && Array.isArray(data.records)) {
        liveList.innerHTML = data.records.map(renderRow).join("");
      }
      if (lastUpdate) {
        lastUpdate.textContent = "son güncelleme " + new Date().toLocaleTimeString("tr-TR");
      }
      if (!data.is_open && sessionOpen) markClosed();
    } catch (error) {
      /* sessizce geç: bir sonraki turda tekrar denenir */
    }
  }

  function setText(id, value) {
    const node = document.getElementById(id);
    if (node && value !== undefined && value !== null) node.textContent = value;
  }

  function escapeHtml(text) {
    return String(text === null || text === undefined ? "" : text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function renderRow(record) {
    return (
      "<tr><td>" + escapeHtml(record.student) +
      '<div class="text-body-secondary" style="font-size:.75rem">' +
      escapeHtml(record.student_no) + "</div></td>" +
      '<td class="small">' + escapeHtml(record.room_no) + "</td>" +
      '<td><span class="badge text-bg-' + escapeHtml(record.badge) + '">' +
      escapeHtml(record.status_label) + "</span></td>" +
      '<td class="small">' + escapeHtml(record.marked_at) + "</td></tr>"
    );
  }

  function tick() {
    if (!sessionOpen) return;

    secondsLeft = Math.max(0, secondsLeft - 1);
    if (countdown) countdown.textContent = "kapanışa " + formatClock(secondsLeft);
    if (secondsLeft === 0) {
      markClosed();
      setTimeout(function () { window.location.href = detailUrl; }, 2000);
      return;
    }

    secondsToRefresh -= 1;
    if (refreshBar) {
      const ratio = Math.max(0, Math.min(1, secondsToRefresh / refreshSeconds));
      refreshBar.style.width = (ratio * 100).toFixed(0) + "%";
    }
    if (refreshInfo) {
      refreshInfo.textContent = "Yeni kod " + Math.max(0, secondsToRefresh) + " saniye sonra.";
    }
    if (secondsToRefresh <= 0) {
      secondsToRefresh = refreshSeconds;
      fetchCode();
    }
  }

  fetchCode();
  fetchState();
  setInterval(tick, 1000);
  setInterval(fetchState, 5000);
})();
