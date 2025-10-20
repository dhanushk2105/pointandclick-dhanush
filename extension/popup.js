// State management
let isConnected = false;
let currentTaskId = null;
let pollInterval = null;
let lastStatus = null;
let lastStepIndex = -1;
let displayedLogs = new Set();

// Load persistent state from background on popup open
async function loadPersisentState() {
    try {
        const response = await chrome.runtime.sendMessage({ type: 'getState' });
        if (response && response.state) {
            const state = response.state;
            
            // Restore task if one was running
            if (state.currentTaskId) {
                currentTaskId = state.currentTaskId;
                document.getElementById('task').value = state.taskDescription || '';
                showActivityLog(true);
                document.getElementById('examples').style.display = 'none';
                
                // Resume polling if task is active
                if (state.taskStatus === 'processing' || state.taskStatus === 'planning') {
                    startPolling(state.currentTaskId);
                }
            }
            
            console.log('✅ Loaded persistent state:', state);
        }
    } catch (error) {
        console.error('Failed to load state:', error);
    }
}

// Listen for state updates from background
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.type === 'stateUpdate') {
        const state = request.state;
        
        // Update UI based on state
        if (state.currentTaskId && currentTaskId !== state.currentTaskId) {
            currentTaskId = state.currentTaskId;
            if (state.taskStatus !== 'completed' && state.taskStatus !== 'failed') {
                startPolling(state.currentTaskId);
            }
        }
        
        console.log('📡 State update received:', state);
    }
    sendResponse({ received: true });
    return true;
});

// Check server connection
async function checkConnection() {
    try {
        chrome.runtime.sendMessage({ type: 'checkConnection' }, (response) => {
            updateConnectionStatus(response?.connected || false);
        });
    } catch (error) {
        updateConnectionStatus(false);
    }
}

function updateConnectionStatus(connected) {
    isConnected = connected;
    const statusEl = document.getElementById('status');
    const executeBtn = document.getElementById('executeBtn');
    
    if (connected) {
        statusEl.textContent = '✅ Connected';
        statusEl.className = 'status connected';
        executeBtn.disabled = false;
    } else {
        statusEl.textContent = '❌ Disconnected';
        statusEl.className = 'status disconnected';
        executeBtn.disabled = true;
    }
}

// Example buttons
document.querySelectorAll('.example-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.getElementById('task').value = btn.dataset.task;
    });
});

// Execute task
document.getElementById('executeBtn').addEventListener('click', async () => {
    const task = document.getElementById('task').value.trim();
    
    if (!task) {
        alert('Please enter a task');
        return;
    }
    
    // Reset state
    resetActivityLog();
    lastStatus = null;
    lastStepIndex = -1;
    displayedLogs.clear();
    
    showActivityLog(true);
    document.getElementById('examples').style.display = 'none';
    document.getElementById('executeBtn').disabled = true;
    
    addLog('info', '🚀 Starting task execution...', task);
    
    try {
        const response = await fetch('http://localhost:8000/execute', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ task })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            currentTaskId = data.task_id;
            addLog('success', '✓ Task submitted successfully');
            startPolling(data.task_id);
        } else {
            addLog('error', '✗ Failed to submit task', data.error);
            resetUI();
        }
    } catch (error) {
        addLog('error', '✗ Connection error', error.message);
        resetUI();
    }
});

// Polling for task status
function startPolling(taskId) {
    // Stop any existing polling
    if (pollInterval) {
        clearInterval(pollInterval);
    }
    
    // Poll every 1 second
    pollInterval = setInterval(async () => {
        try {
            const response = await fetch(`http://localhost:8000/status/${taskId}`);
            const data = await response.json();
            
            // Only update if status changed or new step
            const statusChanged = data.status !== lastStatus;
            const newStep = data.current_step && 
                           data.current_step.index !== lastStepIndex;
            
            if (statusChanged) {
                updateActivityStatus(data.status);
                lastStatus = data.status;
                
                // Add status change log
                if (data.status === 'planning') {
                    addLog('info', '🧠 Creating execution plan...');
                } else if (data.status === 'replanning') {
                    addLog('warning', `🔄 Replanning (attempt ${data.retry_count + 1})...`);
                } else if (data.status === 'processing') {
                    addLog('info', `⚙️ Executing plan`);
                } else if (data.status === 'verifying') {
                    addLog('info', '🔍 Verifying task completion...');
                }
            }
            
            if (newStep) {
                const step = data.current_step;
                addLog('step', 
                      `Step ${step.index}: ${step.action}`,
                      step.description);
                lastStepIndex = step.index;
            }
            
            updateProgress(data.steps_executed, data.total_steps);
            
            // Check if completed
            if (data.status === 'completed' || data.status === 'failed') {
                stopPolling();
                showFinalResult(data);
                resetUI();
            }
        } catch (error) {
            console.error('Polling error:', error);
        }
    }, 1000);
}

function stopPolling() {
    if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
    }
}

// Update activity status badge
function updateActivityStatus(status) {
    const statusEl = document.getElementById('activityStatus');
    statusEl.textContent = status;
    statusEl.className = `activity-status ${status}`;
}

// Update progress bar
function updateProgress(current, total) {
    const progressFill = document.getElementById('progressFill');
    if (total > 0) {
        const percentage = (current / total) * 100;
        progressFill.style.width = percentage + '%';
    }
}

// Add log entry (FILTERED)
function addLog(type, message, details = '') {
    // Create unique key to prevent duplicates
    const logKey = `${type}:${message}:${details}`;
    
    // Skip if already displayed
    if (displayedLogs.has(logKey)) {
        return;
    }
    
    displayedLogs.add(logKey);
    
    // Limit total logs to 20
    if (displayedLogs.size > 20) {
        const firstLog = document.querySelector('.log-entry');
        if (firstLog) {
            firstLog.remove();
        }
    }
    
    const logContainer = document.getElementById('logContainer');
    const entry = document.createElement('div');
    entry.className = `log-entry ${type}`;
    
    const icons = {
        'info': 'ℹ️',
        'success': '✓',
        'warning': '⚠️',
        'error': '✗',
        'step': '▸'
    };
    
    const icon = document.createElement('span');
    icon.className = 'icon';
    icon.textContent = icons[type] || 'ℹ️';
    
    const text = document.createElement('span');
    text.className = 'text';
    text.innerHTML = `<strong>${escapeHtml(message)}</strong>`;
    if (details) {
        text.innerHTML += `<br><span style="opacity: 0.7; font-size: 10px;">${escapeHtml(details)}</span>`;
    }
    
    entry.appendChild(icon);
    entry.appendChild(text);
    logContainer.appendChild(entry);
    
    // Auto scroll
    logContainer.scrollTop = logContainer.scrollHeight;
}

// Escape HTML to prevent XSS
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Show final result
function showFinalResult(data) {
    const resultEl = document.getElementById('finalResult');
    
    if (data.status === 'completed') {
        resultEl.className = 'final-result success show';
        resultEl.innerHTML = `
            <strong>✅ Task Completed Successfully!</strong><br>
            <div style="margin-top: 8px; opacity: 0.9;">
                Executed ${data.steps_executed} steps${data.retry_count > 0 ? ` (${data.retry_count} retries)` : ''}<br>
                ${escapeHtml(data.verification.substring(0, 200))}
            </div>
        `;
        addLog('success', '🎉 Task completed!');
    } else {
        resultEl.className = 'final-result error show';
        resultEl.innerHTML = `
            <strong>❌ Task Failed</strong><br>
            <div style="margin-top: 8px; opacity: 0.9;">
                ${escapeHtml(data.verification.substring(0, 200) || 'Unknown error occurred')}
            </div>
        `;
        addLog('error', '❌ Task failed', data.verification.substring(0, 100));
    }
}

// Reset activity log
function resetActivityLog() {
    const logContainer = document.getElementById('logContainer');
    logContainer.innerHTML = '';
    document.getElementById('progressFill').style.width = '0%';
    document.getElementById('finalResult').classList.remove('show');
    document.getElementById('activityStatus').textContent = 'starting';
    document.getElementById('activityStatus').className = 'activity-status planning';
}

// Show/hide activity log
function showActivityLog(show) {
    const activityLog = document.getElementById('activityLog');
    if (show) {
        activityLog.classList.add('show');
    } else {
        activityLog.classList.remove('show');
    }
}

// Reset UI after task completion
function resetUI() {
    document.getElementById('executeBtn').disabled = false;
    setTimeout(() => {
        document.getElementById('examples').style.display = 'block';
    }, 3000);
}

// Initialize
loadPersisentState(); // Load state first
checkConnection();
setInterval(checkConnection, 5000);

// Cleanup on close
window.addEventListener('beforeunload', () => {
    stopPolling();
});