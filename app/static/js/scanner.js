/*
 * Öğrenci tarafı QR okuyucu.
 * html5-qrcode kütüphanesi ile tarayıcı içinde kamera görüntüsü okunur; okunan
 * yük (payload) /api/yoklama/okut adresine gönderilerek doğrulanır.
 *
 * Not: Tarayıcılar kamera erişimine yalnızca HTTPS veya localhost üzerinden izin
 * verir. Yerel ağda test için adres çubuğuna http://localhost:5000 yazılmalıdır.
 */
(function () {
  "use strict";

  const card = document.getElementById("scanCard");
  if (!card) return;

  const scanUrl = card.dataset.scanUrl;
  const dashboardUrl = card.dataset.dashboardUrl;
  const sessionId = card.dataset.sessionId;

  const startButton = document.getElementById("startScan");
  const stopButton = document.getElementById("stopScan");
  const feedback = document.getElementById("scanFeedback");
  const manualForm = document.getElementById("manualForm");
  const manualCode = document.getElementById("manualCode");

  const csrfToken = (document.querySelector('meta[name="csrf-token"]') || {}).content || "";

  let scanner = null;
  let busy = false;
  let finished = false;

  function setFeedback(message, type) {
    if (!feedback) return;
    const colors = {
      success: "text-success",
      error: "text-danger",
      info: "text-primary",
      warn: "text-warning"
    };
    feedback.className = "scan-feedback text-center mt-3 " + (colors[type] || "");
    feedback.textContent = message;
  }

  async function stopScanner() {
    if (!scanner) return;
    try {
      await scanner.stop();
      scanner.clear();
    } catch (error) {
      /* kamera zaten kapanmış olabilir */
    }
    scanner = null;
    if (startButton) startButton.classList.remove("d-none");
    if (stopButton) stopButton.classList.add("d-none");
  }

  async function submitScan(body) {
    if (busy || finished) return;
    busy = true;
    setFeedback("Doğrulanıyor…", "info");

    try {
      const response = await fetch(scanUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken,
          "Accept": "application/json"
        },
        body: JSON.stringify(body)
      });
      const data = await response.json();

      if (data.ok) {
        finished = true;
        setFeedback("✓ " + data.message, "success");
        await stopScanner();
        setTimeout(function () { window.location.href = dashboardUrl; }, 1500);
      } else {
        setFeedback("✗ " + (data.message || "Kod doğrulanamadı."), "error");
        if (data.code === "duplicate" || data.code === "closed") {
          finished = true;
          await stopScanner();
          setTimeout(function () { window.location.href = dashboardUrl; }, 2500);
        }
      }
    } catch (error) {
      setFeedback("Sunucuya ulaşılamadı. Bağlantınızı kontrol edip tekrar deneyin.",
                  "error");
    } finally {
      busy = false;
    }
  }

  function onScanSuccess(decodedText) {
    if (busy || finished) return;
    submitScan({ payload: decodedText });
  }

  async function startScanner() {
    if (typeof Html5Qrcode === "undefined") {
      setFeedback("QR okuyucu yüklenemedi. İnternet bağlantınızı kontrol edin " +
                  "veya kodu elle girin.", "error");
      return;
    }
    setFeedback("Kamera başlatılıyor…", "info");
    scanner = new Html5Qrcode("qr-reader", { verbose: false });

    const config = {
      fps: 10,
      qrbox: function (viewWidth, viewHeight) {
        const edge = Math.floor(Math.min(viewWidth, viewHeight) * 0.75);
        return { width: edge, height: edge };
      }
    };

    try {
      await scanner.start({ facingMode: "environment" }, config, onScanSuccess);
      if (startButton) startButton.classList.add("d-none");
      if (stopButton) stopButton.classList.remove("d-none");
      setFeedback("Kodu kameraya gösterin.", "info");
    } catch (error) {
      scanner = null;
      setFeedback(
        "Kameraya erişilemedi (" + (error && error.name ? error.name : "hata") +
        "). Tarayıcı izinlerini kontrol edin veya kodu elle girin.",
        "error"
      );
    }
  }

  if (startButton) startButton.addEventListener("click", startScanner);
  if (stopButton) stopButton.addEventListener("click", stopScanner);

  if (manualForm) {
    manualForm.addEventListener("submit", function (event) {
      event.preventDefault();
      const code = (manualCode.value || "").trim();
      if (!/^\d{6}$/.test(code)) {
        setFeedback("Kod 6 haneli olmalıdır.", "warn");
        return;
      }
      submitScan({ session_id: sessionId, code: code });
    });
  }
})();
