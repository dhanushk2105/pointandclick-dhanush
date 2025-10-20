// WebSocket connection to Python server
let ws = null;
let reconnectAttempts = 0;
const MAX_RECONNECT_ATTEMPTS = 5;
const RECONNECT_DELAY = 1000;
const VERBOSE = true;

// Persistent state
let persistentState = {
  currentTaskId: null,
  taskStatus: 'idle',
  taskDescription: '',
  logs: [],
  lastUpdate: null,
  connected: false
};

function logVerbose(emoji, message, details = '') {
  if (VERBOSE) {
    console.log(`${emoji} [Extension] ${message}`);
    if (details) console.log('  →', details);
  }
}

function logSection(title) {
  if (VERBOSE) {
    console.log('\n' + '='.repeat(60));
    console.log(`  ${title}`);
    console.log('='.repeat(60));
  }
}

// ---- helpers ----
function isForbidden(url = '') {
  const s = url || '';
  return ['chrome://', 'edge://', 'about:', 'chrome-extension://'].some(p => s.startsWith(p));
}

// Safe active tab getter for SCRIPTING (blocks forbidden schemes)
async function getActiveTabSafe() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.id) throw new Error('No active tab');
  if (isForbidden(tab.url || '')) {
    throw new Error(`Unsupported scheme for scripting: ${tab.url || ''}`);
  }
  return tab;
}

// Load persistent state
async function loadPersistentState() {
  try {
    const result = await chrome.storage.local.get('agentState');
    if (result.agentState) {
      persistentState = result.agentState;
      logVerbose('📂', 'Loaded persistent state');
    }
  } catch (error) {
    logVerbose('⚠️', 'Failed to load state', error.message);
  }
}

// Save persistent state
async function savePersistentState() {
  try {
    await chrome.storage.local.set({ agentState: persistentState });
    logVerbose('💾', 'Saved persistent state');
  } catch (error) {
    logVerbose('⚠️', 'Failed to save state', error.message);
  }
}

// Update state
function updateState(updates) {
  persistentState = { ...persistentState, ...updates };
  persistentState.lastUpdate = new Date().toISOString();
  savePersistentState();

  chrome.runtime.sendMessage({
    type: 'stateUpdate',
    state: persistentState
  }).catch(() => {});
}

// ---- WebSocket connection (router guarded) ----
function connectWebSocket() {
  if (ws && ws.readyState === WebSocket.OPEN) return;

  logVerbose('🔌', 'Connecting to WebSocket server...');
  ws = new WebSocket('ws://localhost:8000/ws');

  ws.onopen = () => {
    logSection('✅ WEBSOCKET CONNECTED');
    reconnectAttempts = 0;
    wsSend({ type: 'connected', from: 'extension' });
    updateState({ connected: true });
  };

  ws.onmessage = async (event) => {
    let message = null;
    try {
      message = JSON.parse(event.data);
    } catch {
      return;
    }

    if (message && message.type === 'ping') {
      wsSend({ type: 'pong' });
      return;
    }

    // Only handle server→extension action envelopes that contain BOTH id and action
    if (!message || typeof message !== 'object' || !('id' in message) || !('action' in message)) {
      return; // ignore non-action messages to avoid echo loops
    }

    logSection('📨 RECEIVED ACTION');
    logVerbose('📬', 'Message', JSON.stringify(message, null, 2));

    try {
      const result = await handleAction(message);
      wsSend({ id: message.id, status: 'success', data: result });
      logVerbose('✅', 'Action completed');
    } catch (error) {
      logVerbose('❌', 'Action failed', String(error && error.message || error));
      wsSend({ id: message.id, status: 'error', error: String(error && error.message || error) });
    }
  };

  ws.onerror = () => {
    logVerbose('❌', 'WebSocket error');
    updateState({ connected: false });
  };

  ws.onclose = () => {
    logVerbose('🔌', 'WebSocket disconnected');
    updateState({ connected: false });
    attemptReconnect();
  };
}

function wsSend(obj) {
  try { ws && ws.readyState === WebSocket.OPEN && ws.send(JSON.stringify(obj)); } catch {}
}

function attemptReconnect() {
  if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
    logVerbose('❌', 'Max reconnection attempts reached');
    chrome.notifications.create({
      type: 'basic',
      iconUrl: 'icon.png',
      title: 'Agent Disconnected',
      message: 'Cannot connect to server. Please restart the Python server.'
    });
    return;
  }

  reconnectAttempts++;
  const delay = RECONNECT_DELAY * Math.pow(2, reconnectAttempts - 1);
  logVerbose('🔄', `Reconnecting in ${delay}ms (${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS})`);
  setTimeout(connectWebSocket, delay);
}

// ---- Action router (no recursion inside handlers) ----
async function handleAction(message) {
  const { action, payload = {} } = message;
  logSection(`⚡ EXECUTING: ${action}`);

  switch (action) {
    case 'navigate':
      return await navigateTo(payload.url);
    case 'waitFor':
      return await waitForElement(payload.selector, payload.timeout || 5000);
    case 'click':
      return await clickElement(payload.selector);
    case 'type':
      return await typeText(payload.selector, payload.text);
    case 'press':
      return await pressKey(payload.key);
    case 'query':
      return await queryDOM(payload.selector, payload.limit);
    case 'getPageInfo':
      return await getPageInfo();
    case 'getInteractiveElements':
      return await getInteractiveElements();
    case 'smartClick':
      return await smartClick(payload);
    case 'smartType':
      return await smartType(payload);
    case 'switchTab':
      return await switchToTab(payload.index);
    case 'download':
      return await downloadFile(payload.url);
    case 'uploadFile':
      return await uploadFile(payload);
    case 'captureScreenshot':
      return await captureScreenshot();
    default:
      throw new Error(`Unknown action: ${action}`);
  }
}

// ---- Handlers (pure; no router calls) ----

// Navigation — DO NOT call getActiveTabSafe() here.
// We can update a forbidden tab (e.g., chrome://newtab/) or create a new one.
async function navigateTo(url) {
  if (!url) throw new Error('navigate requires payload.url');
  logVerbose('🌐', `Navigating to: ${url}`);

  const [active] = await chrome.tabs.query({ active: true, currentWindow: true });

  // If no active tab, just create one
  if (!active || !active.id) {
    const tab = await chrome.tabs.create({ url, active: true });
    return await waitForTabComplete(tab.id, url);
  }

  // If current tab is forbidden for scripting, it's still fine to update its URL
  if (isForbidden(active.url || '')) {
    await chrome.tabs.update(active.id, { url });
    return await waitForTabComplete(active.id, url);
  }

  // Normal case: update current tab
  await chrome.tabs.update(active.id, { url });
  return await waitForTabComplete(active.id, url);
}

function waitForTabComplete(tabId, fallbackUrl) {
  return new Promise((resolve) => {
    const listener = (updatedTabId, info, updatedTab) => {
      if (updatedTabId === tabId && info.status === 'complete') {
        chrome.tabs.onUpdated.removeListener(listener);
        logVerbose('✅', 'Navigation completed');
        resolve({ navigated: true, url: updatedTab?.url || fallbackUrl });
      }
    };
    chrome.tabs.onUpdated.addListener(listener);
  });
}

// Wait for element
async function waitForElement(selector, timeout) {
  if (!selector) throw new Error('waitFor requires selector');
  logVerbose('⏳', `Waiting for: ${selector}`);
  const tab = await getActiveTabSafe();

  return chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: (sel, ms) => {
      if (typeof document === 'undefined') {
        throw new Error('No DOM available in target page context');
      }
      return new Promise((resolve, reject) => {
        const startTime = Date.now();
        const tick = () => {
          const el = document.querySelector(sel);
          if (el) return resolve({ found: true, selector: sel });
          if (Date.now() - startTime > ms) return reject(new Error(`Timeout: ${sel} not found within ${ms}ms`));
          setTimeout(tick, 100);
        };
        tick();
      });
    },
    args: [selector, timeout]
  }).then(results => results[0].result);
}

// Click element
async function clickElement(selector) {
  if (!selector) throw new Error('click requires selector');
  logVerbose('🖱️', `Clicking: ${selector}`);
  const tab = await getActiveTabSafe();

  return chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: (sel) => {
      if (typeof document === 'undefined') {
        throw new Error('No DOM available in target page context');
      }
      const el = document.querySelector(sel);
      if (!el) throw new Error(`Element not found: ${sel}`);
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      if (r.width === 0 || r.height === 0 || cs.display === 'none' || cs.visibility === 'hidden') {
        throw new Error('Element not visible/clickable');
      }
      el.scrollIntoView({ block: 'center' });
      el.click();
      return { clicked: true, selector: sel };
    },
    args: [selector]
  }).then(results => results[0].result);
}

// Type text
async function typeText(selector, text) {
  if (!selector) throw new Error('type requires selector');
  logVerbose('⌨️', `Typing: "${text}"`);
  const tab = await getActiveTabSafe();

  return chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: (sel, txt) => {
      if (typeof document === 'undefined') {
        throw new Error('No DOM available in target page context');
      }
      const input = document.querySelector(sel);
      if (!input) throw new Error(`Element not found: ${sel}`);
      input.focus();
      input.value = txt ?? '';
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
      return { typed: true, selector: sel, text: txt ?? '' };
    },
    args: [selector, text]
  }).then(results => results[0].result);
}

// Press key
async function pressKey(key) {
  if (!key) throw new Error('press requires key');
  logVerbose('⌨️', `Pressing: ${key}`);
  const tab = await getActiveTabSafe();

  return chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: (k) => {
      if (typeof document === 'undefined') {
        throw new Error('No DOM available in target page context');
      }
      const tgt = document.activeElement || document.body;
      const mk = (type) => new KeyboardEvent(type, { key: k, code: k, bubbles: true, cancelable: true });
      tgt.dispatchEvent(mk('keydown'));
      tgt.dispatchEvent(mk('keypress'));
      tgt.dispatchEvent(mk('keyup'));

      // Opportunistic submit on Enter
      if (k === 'Enter') {
        const form = tgt && tgt.closest ? tgt.closest('form') : null;
        form?.submit?.();
      }

      return { pressed: true, key: k };
    },
    args: [key]
  }).then(results => results[0].result);
}

// Query DOM
async function queryDOM(selector, limit = 500) {
  if (!selector) throw new Error('query requires selector');
  logVerbose('🔍', `Querying DOM: ${selector}`);
  const tab = await getActiveTabSafe();

  return chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: (sel, lim) => {
      if (typeof document === 'undefined') {
        throw new Error('No DOM available in target page context');
      }
      if (sel === 'body') return (document.body.innerText || '').substring(0, lim);
      const el = document.querySelector(sel);
      if (!el) return '';
      const text = el.innerText || el.textContent || '';
      return text.substring(0, lim);
    },
    args: [selector, limit]
  }).then(results => results[0].result);
}

// Page info
async function getPageInfo() {
  logVerbose('📄', 'Getting page info');
  try {
    const tab = await getActiveTabSafe();
    return chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => ({
        url: window.location.href,
        title: document.title || '',
        readyState: document.readyState || '',
      }),
    }).then(r => ({ ...(r[0]?.result || {}), diagnostics: {} }));
  } catch (e) {
    return { url: '', title: '', readyState: '', diagnostics: { error: String(e.message || e) } };
  }
}

// Interactive elements
async function getInteractiveElements() {
  logVerbose('🧭', 'Collecting interactive elements');
  try {
    const tab = await getActiveTabSafe();
    return chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => {
        if (typeof document === 'undefined') {
        throw new Error('No DOM available in target page context');
      }
        const sel = `a[href], button, [role="button"], input:not([type="hidden"]), textarea, select`;
        const out = [];
        for (const el of Array.from(document.querySelectorAll(sel))) {
          const rect = el.getBoundingClientRect();
          const style = getComputedStyle(el);
          if (!rect || rect.width === 0 || rect.height === 0) continue;
          if (style.display === 'none' || style.visibility === 'hidden') continue;
          out.push({
            type: el.tagName.toLowerCase(),
            text: (el.innerText || el.textContent || '').trim().slice(0, 120),
            id: el.id || '',
            name: el.name || '',
            placeholder: el.placeholder || '',
            role: el.getAttribute('role') || '',
            ariaLabel: el.getAttribute('aria-label') || '',
            href: el.href || '',
            value: el.value || '',
          });
          if (out.length >= 30) break;
        }
        return out;
      },
    }).then(r => r[0]?.result || []);
  } catch (e) {
    return [];
  }
}

// Smart click - simplified + visibility checks
async function smartClick(payload) {
  logVerbose('🎯', 'Smart click');
  const tab = await getActiveTabSafe();

  return chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: (opts) => {
      if (typeof document === 'undefined') {
        throw new Error('No DOM available in target page context');
      }
      const visible = (el) => {
        const r = el.getBoundingClientRect();
        const cs = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && cs.display !== 'none' && cs.visibility !== 'hidden';
      };

      // 1) selector first
      if (opts.selector) {
        const el = document.querySelector(opts.selector);
        if (el && visible(el)) {
          el.scrollIntoView({ block: 'center' });
          el.click();
          return { clicked: true, method: 'selector' };
        }
      }

      // 2) id
      if (opts.id) {
        const el = document.getElementById(opts.id);
        if (el && visible(el)) {
          el.scrollIntoView({ block: 'center' });
          el.click();
          return { clicked: true, method: 'id' };
        }
      }

      // 3) name
      if (opts.name) {
        const el = document.querySelector(`[name="${opts.name}"]`);
        if (el && visible(el)) {
          el.scrollIntoView({ block: 'center' });
          el.click();
          return { clicked: true, method: 'name' };
        }
      }

      // 4) aria-label
      if (opts.ariaLabel) {
        const el = document.querySelector(
          `[aria-label="${opts.ariaLabel}"], button[aria-label="${opts.ariaLabel}"], a[aria-label="${opts.ariaLabel}"]`
        );
        if (el && visible(el)) {
          el.scrollIntoView({ block: 'center' });
          el.click();
          return { clicked: true, method: 'ariaLabel' };
        }
      }

      // 5) role
      if (opts.role) {
        const el = document.querySelector(`[role="${opts.role}"]`);
        if (el && visible(el)) {
          el.scrollIntoView({ block: 'center' });
          el.click();
          return { clicked: true, method: 'role' };
        }
      }

      // 6) text/description fallback
      const searchText = (opts.text || opts.description || '').toLowerCase().trim();
      if (searchText) {
        const candidates = Array.from(document.querySelectorAll([
          'button', 'a[href]', '[role="button"]', 'input[type="submit"]', 'input[type="button"]', '[onclick]',
          '[tabindex]', '[aria-label]', '[title]'
        ].join(',')));

        const norm = s => (s || '').toLowerCase().replace(/\s+/g, ' ').trim();

        for (const el of candidates) {
          if (!visible(el)) continue;
          const texts = [
            norm(el.innerText),
            norm(el.textContent),
            norm(el.value),
            norm(el.getAttribute('aria-label')),
            norm(el.getAttribute('title'))
          ];
          if (texts.some(t => t && (t.includes(searchText) || searchText.includes(t)))) {
            el.scrollIntoView({ block: 'center' });
            el.click();
            return { clicked: true, method: 'text', matched: texts.find(Boolean)?.slice(0, 80) };
          }
        }
      }

      throw new Error(`Could not find element: ${JSON.stringify(opts)}`);
    },
    args: [payload]
  }).then(results => results[0].result);
}

// Smart type - simplified
async function smartType(payload) {
  logVerbose('⌨️', 'Smart type');
  const tab = await getActiveTabSafe();

  return chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: (opts) => {
      if (typeof document === 'undefined') {
        throw new Error('No DOM available in target page context');
      }
      if (!opts.text) throw new Error('smartType requires "text"');
      const visible = (el) => {
        const r = el.getBoundingClientRect();
        const cs = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && cs.display !== 'none' && cs.visibility !== 'hidden';
      };

      let input = null;
      if (opts.selector) input = document.querySelector(opts.selector);

      if (!input) {
        const inputs = Array.from(document.querySelectorAll('input:not([type="hidden"]), textarea'));
        input = inputs.find(visible);
      }
      if (!input) throw new Error('No input field found');

      input.focus();
      input.value = opts.text;
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
      return { typed: true, text: opts.text };
    },
    args: [payload]
  }).then(results => results[0].result);
}

// Switch tab
async function switchToTab(index) {
  logVerbose('🔀', `Switching to tab: ${index}`);
  const tabs = await chrome.tabs.query({ currentWindow: true });
  if (index < 0 || index >= tabs.length) {
    throw new Error(`Tab index ${index} out of range (0-${tabs.length - 1})`);
  }
  await chrome.tabs.update(tabs[index].id, { active: true });
  return { switched: true, index };
}

// Download file
async function downloadFile(url) {
  if (!url) throw new Error('download requires url');
  logVerbose('💾', `Downloading: ${url}`);
  try {
    const downloadId = await chrome.downloads.download({ url });
    return { downloading: true, url, downloadId };
  } catch (error) {
    throw new Error(`Download failed: ${error.message}`);
  }
}

// Upload file (trigger dialog)
async function uploadFile(payload) {
  logVerbose('📤', 'Uploading file');
  const tab = await getActiveTabSafe();

  return chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: (opts) => {
      if (typeof document === 'undefined') {
        throw new Error('No DOM available in target page context');
      }
      const input = document.querySelector(opts.selector || 'input[type="file"]');
      if (!input) throw new Error('File input not found');
      input.click(); // user must pick file manually
      return { triggered: true, message: 'File dialog opened - user must select file manually' };
    },
    args: [payload]
  }).then(results => results[0].result);
}

// Capture screenshot
async function captureScreenshot() {
  logVerbose('📸', 'Capturing screenshot');
  try {
    // just validate we have a tab; we won't inject scripts here
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.id) throw new Error('No active tab');
    const dataUrl = await chrome.tabs.captureVisibleTab(null, { format: 'png' });
    const base64Data = dataUrl.split(',')[1] || '';
    logVerbose('✅', 'Screenshot captured');
    return base64Data;
  } catch (error) {
    logVerbose('❌', 'Screenshot failed', error.message);
    return '';
  }
}

// Message listener (popup)
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.type === 'checkConnection') {
    const connected = ws && ws.readyState === WebSocket.OPEN;
    sendResponse({ connected });
  }

  if (request.type === 'getState') {
    sendResponse({ state: persistentState });
  }

  if (request.type === 'clearState') {
    persistentState = {
      currentTaskId: null,
      taskStatus: 'idle',
      taskDescription: '',
      logs: [],
      lastUpdate: null,
      connected: false
    };
    savePersistentState();
    sendResponse({ cleared: true });
  }

  return true;
});

// Initialize
logSection('🚀 EXTENSION INITIALIZING');
loadPersistentState().then(connectWebSocket);

chrome.runtime.onStartup.addListener(() => {
  loadPersistentState().then(connectWebSocket);
});

chrome.runtime.onInstalled.addListener(() => {
  loadPersistentState().then(connectWebSocket);
});
