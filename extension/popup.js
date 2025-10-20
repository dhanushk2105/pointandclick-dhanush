// Popup with PERSISTENT STATE - loads from storage on open
let connected = false;
let activeTaskId = null;
let statusPollTimer = null;
let prevStatus = null;
let prevStepIndex = -1;
let renderedLogKeys = new Set();

// Load state from storage on popup open
async function loadPersistentState() {
  try {
    const response = await chrome.runtime.sendMessage({ type: "getState" });
    const state = response?.state;
    
    if (!state) return;

    console.log("📂 Loading persistent state:", state);

    // Restore task info
    if (state.currentTaskId) {
      activeTaskId = state.currentTaskId;
      document.getElementById("taskInput").value = state.taskDescription || "";
      
      // Show activity section
      toggleActivity(true);
      
      // Restore logs
      if (state.logs && state.logs.length > 0) {
        state.logs.forEach(log => {
          appendLog(log.type, log.message, log.details || "");
        });
      }
      
      // If task is still running, start polling
      if (state.taskStatus === "processing" || 
          state.taskStatus === "planning" || 
          state.taskStatus === "verifying") {
        console.log("🔄 Task still active, resuming polling");
        renderActivityPhase(state.taskStatus);
        startStatusPolling(state.currentTaskId);
      } else if (state.taskStatus === "completed") {
        console.log("✅ Task was completed");
        renderActivityPhase("completed");
        document.getElementById("finalResult").className = "result success show";
        document.getElementById("finalResult").innerHTML = 
          `<strong>Task completed</strong><div style="margin-top:8px;opacity:.9;">Previously completed task</div>`;
      } else if (state.taskStatus === "failed") {
        console.log("❌ Task had failed");
        renderActivityPhase("failed");
        document.getElementById("finalResult").className = "result error show";
        document.getElementById("finalResult").innerHTML = 
          `<strong>Task failed</strong><div style="margin-top:8px;opacity:.9;">Previous task failed</div>`;
      }
    }
  } catch (e) {
    console.error("Failed to load persistent state:", e);
  }
}

// Listen for state updates from background
chrome.runtime.onMessage.addListener((req, _sender, sendResponse) => {
  if (req.type === "stateUpdate") {
    const s = req.state;
    console.log("📡 State update received:", s);
    
    // Update active task if changed
    if (s.currentTaskId && activeTaskId !== s.currentTaskId) {
      activeTaskId = s.currentTaskId;
      if (s.taskStatus !== "completed" && s.taskStatus !== "failed") {
        startStatusPolling(s.currentTaskId);
      }
    }
    
    // Update connection status
    if (s.connected !== undefined) {
      renderConnectionStatus(s.connected);
    }
  }
  sendResponse({ received: true });
  return true;
});

async function checkServerConnection() {
  try {
    chrome.runtime.sendMessage({ type: "checkConnection" }, (res) => {
      renderConnectionStatus(Boolean(res?.connected));
    });
  } catch {
    renderConnectionStatus(false);
  }
}

function renderConnectionStatus(isConnected) {
  connected = isConnected;
  const statusEl = document.getElementById("connectionStatus");
  const runBtn = document.getElementById("runButton");
  if (isConnected) {
    statusEl.textContent = "Connected";
    // Only enable button if no task is active
    if (!activeTaskId || prevStatus === "completed" || prevStatus === "failed") {
      runBtn.disabled = false;
    }
  } else {
    statusEl.textContent = "Disconnected";
    runBtn.disabled = true;
  }
}

document.getElementById("runButton").addEventListener("click", async () => {
  const task = document.getElementById("taskInput").value.trim();
  if (!task) {
    alert("Please enter a task");
    return;
  }

  // Clear previous state for NEW task
  resetActivity();
  prevStatus = null;
  prevStepIndex = -1;
  renderedLogKeys.clear();

  toggleActivity(true);
  document.getElementById("runButton").disabled = true;
  appendLog("info", "Starting task…", task);

  try {
    const resp = await fetch("http://localhost:8000/execute", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task }),
    });
    const data = await resp.json();

    if (resp.ok) {
      activeTaskId = data.task_id;
      appendLog("success", "Task submitted");
      startStatusPolling(data.task_id);
    } else {
      appendLog("error", "Failed to submit task", data.error);
      restoreReadyState();
    }
  } catch (err) {
    appendLog("error", "Connection error", err.message);
    restoreReadyState();
  }
});

function startStatusPolling(taskId) {
  if (statusPollTimer) clearInterval(statusPollTimer);

  statusPollTimer = setInterval(async () => {
    try {
      const resp = await fetch(`http://localhost:8000/status/${taskId}`);
      const data = await resp.json();

      const statusChanged = data.status !== prevStatus;
      const isNewStep = data.current_step && data.current_step.index !== prevStepIndex;

      if (statusChanged) {
        renderActivityPhase(data.status);
        prevStatus = data.status;

        if (data.status === "planning") appendLog("info", "Creating plan…");
        else if (data.status === "replanning") appendLog("warning", `Replanning (attempt ${data.retry_count + 1})…`);
        else if (data.status === "processing") appendLog("info", "Executing plan");
        else if (data.status === "verifying") appendLog("info", "Verifying completion…");
      }

      if (isNewStep) {
        const step = data.current_step;
        appendLog("step", `Step ${step.index}: ${step.action}`, step.description);
        prevStepIndex = step.index;
      }

      renderProgress(data.steps_executed, data.total_steps);

      if (data.status === "completed" || data.status === "failed") {
        stopStatusPolling();
        renderFinalResult(data);
        restoreReadyState();
      }
    } catch (e) {
      console.error("poll error:", e);
    }
  }, 1000);
}

function stopStatusPolling() {
  if (statusPollTimer) {
    clearInterval(statusPollTimer);
    statusPollTimer = null;
  }
}

function renderActivityPhase(phase) {
  document.getElementById("phaseBadge").textContent = phase;
}

function renderProgress(current, total) {
  const fill = document.getElementById("progressFill");
  if (total > 0) fill.style.width = String((current / total) * 100) + "%";
}

function appendLog(type, message, details = "") {
  const key = `${type}:${message}:${details}`;
  if (renderedLogKeys.has(key)) return;
  renderedLogKeys.add(key);

  // Limit log entries to prevent memory issues
  if (renderedLogKeys.size > 50) {
    const first = document.querySelector(".entry");
    if (first) {
      const firstKey = first.dataset.key;
      if (firstKey) renderedLogKeys.delete(firstKey);
      first.remove();
    }
  }

  const log = document.getElementById("logList");
  const row = document.createElement("div");
  row.className = `entry ${type}`;
  row.dataset.key = key;

  const icons = { info: "ℹ️", success: "✓", warning: "⚠️", error: "✗", step: "▸" };
  const i = document.createElement("span");
  i.className = "icon";
  i.textContent = icons[type] || "ℹ️";

  const t = document.createElement("span");
  t.className = "text";
  t.innerHTML = `<strong>${escapeHTML(message)}</strong>`;
  if (details) {
    t.innerHTML += `<br><span style="opacity:.7;font-size:11px;">${escapeHTML(details)}</span>`;
  }

  row.appendChild(i);
  row.appendChild(t);
  log.appendChild(row);
  log.scrollTop = log.scrollHeight;
}

function escapeHTML(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function renderFinalResult(data) {
  const el = document.getElementById("finalResult");
  if (data.status === "completed") {
    el.className = "result success show";
    el.innerHTML =
      `<strong>Task completed</strong>
       <div style="margin-top:8px;opacity:.9;">
         Executed ${data.steps_executed} steps${data.retry_count > 0 ? ` (${data.retry_count} retries)` : ""}
         <br>${escapeHTML((data.verification || "").substring(0, 200))}
       </div>`;
    appendLog("success", "Done");
  } else {
    el.className = "result error show";
    el.innerHTML =
      `<strong>Task failed</strong>
       <div style="margin-top:8px;opacity:.9;">
         ${escapeHTML((data.verification || "Unknown error").substring(0, 200))}
       </div>`;
    appendLog("error", "Failed", (data.verification || "").substring(0, 100));
  }
}

function resetActivity() {
  document.getElementById("logList").innerHTML = "";
  document.getElementById("progressFill").style.width = "0%";
  document.getElementById("finalResult").className = "result";
  document.getElementById("phaseBadge").textContent = "starting";
  renderedLogKeys.clear();
}

function toggleActivity(show) {
  const el = document.getElementById("activitySection");
  if (show) el.classList.add("show");
  else el.classList.remove("show");
}

function restoreReadyState() {
  // Only enable button if connected
  if (connected) {
    document.getElementById("runButton").disabled = false;
  }
}

// Initialize popup
(async function init() {
  console.log("🚀 Popup initializing...");
  
  // Load any existing state first
  await loadPersistentState();
  
  // Check connection
  checkServerConnection();
  
  // Check connection periodically
  setInterval(checkServerConnection, 5000);
  
  console.log("✅ Popup initialized");
})();

// Cleanup on popup close
window.addEventListener("beforeunload", () => {
  stopStatusPolling();
});