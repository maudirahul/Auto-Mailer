document.addEventListener("DOMContentLoaded", () => {
  // Elements
  const dropZoneHr = document.getElementById("dropZoneHr");
  const dropZoneResume = document.getElementById("dropZoneResume");
  const statusHr = document.getElementById("statusHr");
  const statusResume = document.getElementById("statusResume");
  
  const campaignForm = document.getElementById("campaignForm");
  const bodyTemplate = document.getElementById("body_template");
  const togglePassword = document.getElementById("togglePassword");
  const appPassword = document.getElementById("app_password");
  
  const btnStart = document.getElementById("btnStart");
  const btnStop = document.getElementById("btnStop");
  
  const metricStatus = document.getElementById("metricStatus");
  const metricProgress = document.getElementById("metricProgress");
  const metricSent = document.getElementById("metricSent");
  const metricFailed = document.getElementById("metricFailed");
  const progressBar = document.getElementById("progressBar");
  const terminalLogs = document.getElementById("terminalLogs");
  
  let eventSource = null;

  // Toggle Password Visibility
  togglePassword.addEventListener("click", () => {
    const type = appPassword.getAttribute("type") === "password" ? "text" : "password";
    appPassword.setAttribute("type", type);
    togglePassword.textContent = type === "password" ? "👁️" : "🙈";
  });

  // Insert Template Placeholders
  document.querySelectorAll(".chip").forEach(chip => {
    chip.addEventListener("click", () => {
      const placeholder = chip.getAttribute("data-placeholder");
      const startPos = bodyTemplate.selectionStart;
      const endPos = bodyTemplate.selectionEnd;
      const text = bodyTemplate.value;
      
      bodyTemplate.value = text.substring(0, startPos) + placeholder + text.substring(endPos);
      bodyTemplate.focus();
      bodyTemplate.selectionStart = startPos + placeholder.length;
      bodyTemplate.selectionEnd = startPos + placeholder.length;
    });
  });

  // Setup Drag & Drop Uploads
  setupDragAndDrop(dropZoneHr, "hr_list", (data) => {
    statusHr.textContent = `Attached: hr_contacts.pdf (${data.contacts_found} HRs found)`;
    addTerminalLine(`[system] Contacts file validated. Found ${data.contacts_found} unique contacts.`, "system");
  });

  setupDragAndDrop(dropZoneResume, "resume", (data) => {
    statusResume.textContent = `Attached: ${data.resume_filename || 'resume.pdf'}`;
    addTerminalLine("[system] Resume file successfully uploaded and ready.", "system");
  });

  function setupDragAndDrop(zone, fieldName, onSuccess) {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".pdf";
    input.style.display = "none";
    zone.appendChild(input);

    zone.addEventListener("click", () => input.click());

    zone.addEventListener("dragover", (e) => {
      e.preventDefault();
      zone.classList.add("dragover");
    });

    ["dragleave", "drop"].forEach(event => {
      zone.addEventListener(event, () => zone.classList.remove("dragover"));
    });

    zone.addEventListener("drop", (e) => {
      e.preventDefault();
      const files = e.dataTransfer.files;
      if (files.length > 0) {
        uploadFile(files[0], fieldName, zone, onSuccess);
      }
    });

    input.addEventListener("change", () => {
      if (input.files.length > 0) {
        uploadFile(input.files[0], fieldName, zone, onSuccess);
      }
    });
  }

  async function uploadFile(file, fieldName, zone, onSuccess) {
    if (file.type !== "application/pdf") {
      alert("Only PDF files are supported!");
      return;
    }

    const formData = new FormData();
    formData.append(fieldName, file);
    
    zone.classList.remove("loaded");
    zone.classList.add("loading");
    const statusEl = zone.querySelector(".file-status");
    const originalText = statusEl.textContent;
    statusEl.textContent = "Uploading & Parsing...";
    
    try {
      const response = await fetch("/api/upload", {
        method: "POST",
        body: formData
      });
      const data = await response.json();
      if (response.ok && data.success) {
        zone.classList.add("loaded");
        onSuccess(data);
      } else {
        zone.classList.remove("loaded");
        statusEl.textContent = "Upload failed";
        alert(data.detail || "File upload failed");
      }
    } catch (err) {
      console.error(err);
      zone.classList.remove("loaded");
      statusEl.textContent = "Error";
      alert("Error connecting to server to upload file.");
    } finally {
      zone.classList.remove("loading");
      zone.classList.remove("dragover");
    }
  }

  // Handle EventSource Stream logs
  function connectLogs() {
    if (eventSource) {
      eventSource.close();
    }
    
    eventSource = new EventSource("/api/logs");
    
    eventSource.onmessage = (event) => {
      const data = event.data;
      
      if (data.startsWith("STATUS:")) {
        const parts = data.replace("STATUS:", "").split(",");
        const progress = parts[0] + "%";
        const sent = parts[1];
        const failed = parts[2];
        const isRunning = parts[3] === "True";
        
        metricProgress.textContent = progress;
        progressBar.style.width = progress;
        metricSent.textContent = sent;
        metricFailed.textContent = failed;
        
        if (isRunning) {
          metricStatus.textContent = "RUNNING";
          metricStatus.className = "metric-value status-badge running";
          btnStart.disabled = true;
          btnStop.disabled = false;
        } else {
          metricStatus.textContent = "IDLE";
          metricStatus.className = "metric-value status-badge idle";
          btnStart.disabled = false;
          btnStop.disabled = true;
        }
      } 
      else if (data.startsWith("LOG:")) {
        const logLine = data.replace("LOG:", "");
        
        let type = "output";
        if (logLine.includes("[OK]")) type = "ok";
        else if (logLine.includes("[FAIL]")) type = "fail";
        else if (logLine.includes("[WAIT]")) type = "wait";
        else if (logLine.includes("[system]")) type = "system";
        else if (logLine.includes("[SMTP]")) type = "system";
        else if (logLine.includes("[!]")) type = "warn";
        
        addTerminalLine(logLine, type);
      }
    };
    
    eventSource.onerror = (err) => {
      console.error("SSE connection closed / failed", err);
      eventSource.close();
    };
  }

  // Helper to insert terminal messages
  function addTerminalLine(text, type = "output") {
    const line = document.createElement("div");
    line.className = `terminal-line ${type}`;
    line.textContent = text;
    terminalLogs.appendChild(line);
    
    // Auto Scroll to bottom
    terminalLogs.scrollTop = terminalLogs.scrollHeight;
  }

  // Start campaign trigger
  btnStart.addEventListener("click", async () => {
    // Basic validation
    if (!campaignForm.checkValidity()) {
      campaignForm.reportValidity();
      return;
    }
    if (!bodyTemplate.value.trim()) {
      alert("Please provide email template content!");
      return;
    }

    const formData = new FormData(campaignForm);
    formData.append("body_template", bodyTemplate.value);
    
    btnStart.disabled = true;
    addTerminalLine("[system] Requesting server to start email campaign...", "system");
    
    try {
      const response = await fetch("/api/start", {
        method: "POST",
        body: formData
      });
      const data = await response.json();
      
      if (response.ok && data.success) {
        addTerminalLine("[system] Campaign started successfully! Connecting logs...", "system");
        btnStop.disabled = false;
        // Listen to logs
        connectLogs();
      } else {
        addTerminalLine(`[system] Error starting campaign: ${data.detail}`, "fail");
        btnStart.disabled = false;
        alert(data.detail || "Failed to start campaign");
      }
    } catch (err) {
      console.error(err);
      addTerminalLine("[system] Could not connect to API to start campaign.", "fail");
      btnStart.disabled = false;
    }
  });

  // Stop campaign trigger
  btnStop.addEventListener("click", async () => {
    btnStop.disabled = true;
    addTerminalLine("[system] Sending pause request to campaign runner...", "warn");
    
    try {
      const response = await fetch("/api/stop", {
        method: "POST"
      });
      const data = await response.json();
      if (response.ok && data.success) {
        addTerminalLine("[system] Campaign pause command accepted.", "warn");
      } else {
        addTerminalLine(`[system] Stop call returned: ${data.message}`, "fail");
        btnStop.disabled = false;
      }
    } catch (err) {
      console.error(err);
      addTerminalLine("[system] Connection error stopping campaign.", "fail");
      btnStop.disabled = false;
    }
  });

  // Auto connect logs on initial page load (in case campaign is already active in background)
  connectLogs();
});
