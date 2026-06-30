// static/script.js - Legacy helper kept in sync with the FastAPI backend.

// Helper to display alerts
function showAlert(message, type = "info") {
  const banner = document.getElementById("alertBanner");
  banner.textContent = message;
  banner.className = `alert alert-${type}`;
  banner.style.display = "block";
  setTimeout(() => (banner.style.display = "none"), 5000);
}

// Load employee profile placeholder (could be extended later)
function loadEmployeeInfo() {
  const empSelect = document.getElementById("employeeId");
  const empId = empSelect.value;
  // For now we just update badge
  document.getElementById("learnerBadge").textContent = "Loaded";
  document.getElementById("learnerBadge").className = "badge-status badge-loaded";
}

// Core function to call backend actions
async function callAction(action) {
  try {
    showAlert(`Calling ${action}…`, "info");
    const employee_id = document.getElementById("employeeId").value;
    const targetModuleInput = document.getElementById("targetModule");
    const body = { employee_id, action };
    if (targetModuleInput && targetModuleInput.value) {
      body.target_module = targetModuleInput.value;
    }

    const response = await fetch("/pipeline", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error(`Server error ${response.status}`);
    const data = await response.json();
    renderResult(action, data);
    showAlert(`${action} completed`, "success");
  } catch (err) {
    console.error(err);
    showAlert(`Error: ${err.message}`, "danger");
  }
}

// Render the backend JSON into the workspace area based on active tab
function renderResult(action, payload) {
  const contentDiv = document.getElementById("workspaceContent");
  // Simple pretty‑print for demo purposes
  const pre = document.createElement("pre");
  pre.textContent = JSON.stringify(payload, null, 2);
  contentDiv.innerHTML = ""; // clear previous
  contentDiv.appendChild(pre);
  // Update progress bar if schedule generated
  if (action === "GENERATE_SCHEDULE" && payload.progress) {
    const prog = Math.min(100, Math.round((payload.progress || 0) * 100));
    document.getElementById("progressBar").style.width = prog + "%";
    document.getElementById("progressVal").textContent = prog + "%";
  }
}

// Tab navigation
function switchTab(tab) {
  const tabs = ["schedule", "quiz", "dashboard", "inspection", "raw"];
  tabs.forEach((t) => {
    document.getElementById(`tab-${t}`).classList.toggle("active", t === tab);
  });
  // For demo we just clear the workspace on tab change
  document.getElementById("workspaceContent").innerHTML = "<em>Select an action to see results here.</em>";
}

// Simple log inspection – fetch raw log file from server (optional endpoint)
async function getInspection() {
  try {
    const resp = await fetch("/logs/telemetry.log");
    if (!resp.ok) throw new Error("Log not available");
    const txt = await resp.text();
    const pre = document.createElement("pre");
    pre.textContent = txt;
    document.getElementById("workspaceContent").innerHTML = "";
    document.getElementById("workspaceContent").appendChild(pre);
  } catch (e) {
    showAlert(e.message, "danger");
  }
}

// Initialize UI
document.addEventListener("DOMContentLoaded", () => {
  loadEmployeeInfo();
  switchTab("schedule");
});
