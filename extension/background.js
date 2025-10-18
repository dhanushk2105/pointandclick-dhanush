// WebSocket connection to Python server
let ws = null;
let reconnectAttempts = 0;
const MAX_RECONNECT_ATTEMPTS = 5;
const RECONNECT_DELAY = 1000;

// Connect to WebSocket server
function connectWebSocket() {
    if (ws && ws.readyState === WebSocket.OPEN) return;
    
    console.log('Connecting to WebSocket server...');
    ws = new WebSocket('ws://localhost:8000/ws');
    
    ws.onopen = () => {
        console.log('WebSocket connected');
        reconnectAttempts = 0;
        ws.send(JSON.stringify({ type: 'connected', from: 'extension' }));
    };
    
    ws.onmessage = async (event) => {
        const message = JSON.parse(event.data);
        console.log('Received message:', message);
        
        if (message.type === 'ping') {
            ws.send(JSON.stringify({ type: 'pong' }));
            return;
        }
        
        try {
            const result = await handleAction(message);
            ws.send(JSON.stringify({
                id: message.id,
                status: 'success',
                data: result
            }));
        } catch (error) {
            console.error('Action error:', error);
            ws.send(JSON.stringify({
                id: message.id,
                status: 'error',
                error: error.message
            }));
        }
    };
    
    ws.onerror = (error) => {
        console.error('WebSocket error:', error);
    };
    
    ws.onclose = () => {
        console.log('WebSocket disconnected');
        attemptReconnect();
    };
}

// Reconnect with exponential backoff
function attemptReconnect() {
    if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
        console.error('Max reconnection attempts reached');
        return;
    }
    
    reconnectAttempts++;
    const delay = RECONNECT_DELAY * Math.pow(2, reconnectAttempts - 1);
    
    console.log(`Reconnecting in ${delay}ms... (attempt ${reconnectAttempts})`);
    setTimeout(connectWebSocket, delay);
}

// Handle actions from Python server
async function handleAction(message) {
    const { action, payload } = message;
    
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
            
        case 'switchTab':
            return await switchToTab(payload.index);
            
        case 'download':
            return await downloadFile(payload.url);
            
        default:
            throw new Error(`Unknown action: ${action}`);
    }
}

// Action implementations
async function navigateTo(url) {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    await chrome.tabs.update(tab.id, { url });
    
    // Wait for navigation to complete
    return new Promise(resolve => {
        chrome.webNavigation.onCompleted.addListener(function listener(details) {
            if (details.tabId === tab.id) {
                chrome.webNavigation.onCompleted.removeListener(listener);
                resolve({ navigated: true, url });
            }
        });
    });
}

async function waitForElement(selector, timeout) {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    
    return chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: (sel, ms) => {
            return new Promise((resolve, reject) => {
                const startTime = Date.now();
                const checkElement = () => {
                    const element = document.querySelector(sel);
                    if (element) {
                        resolve({ found: true, selector: sel });
                    } else if (Date.now() - startTime > ms) {
                        reject(new Error(`Element ${sel} not found within ${ms}ms`));
                    } else {
                        setTimeout(checkElement, 100);
                    }
                };
                checkElement();
            });
        },
        args: [selector, timeout]
    }).then(results => results[0].result);
}

async function clickElement(selector) {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    
    return chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: (sel) => {
            const element = document.querySelector(sel);
            if (!element) throw new Error(`Element not found: ${sel}`);
            element.click();
            return { clicked: true, selector: sel };
        },
        args: [selector]
    }).then(results => results[0].result);
}

async function typeText(selector, text) {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    
    return chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: (sel, txt) => {
            const element = document.querySelector(sel);
            if (!element) throw new Error(`Element not found: ${sel}`);
            
            element.focus();
            element.value = txt;
            element.dispatchEvent(new Event('input', { bubbles: true }));
            element.dispatchEvent(new Event('change', { bubbles: true }));
            
            return { typed: true, selector: sel, text: txt };
        },
        args: [selector, text]
    }).then(results => results[0].result);
}

async function pressKey(key) {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    
    return chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: (k) => {
            const event = new KeyboardEvent('keydown', {
                key: k,
                code: k === 'Enter' ? 'Enter' : k,
                bubbles: true,
                cancelable: true
            });
            document.activeElement.dispatchEvent(event);
            return { pressed: true, key: k };
        },
        args: [key]
    }).then(results => results[0].result);
}

async function queryDOM(selector, limit = 500) {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    
    return chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: (sel, lim) => {
            if (sel === 'body') {
                const text = document.body.innerText;
                return text.substring(0, lim);
            }
            const element = document.querySelector(sel);
            if (!element) return '';
            const text = element.innerText || element.textContent || '';
            return text.substring(0, lim);
        },
        args: [selector, limit]
    }).then(results => results[0].result);
}

async function switchToTab(index) {
    const tabs = await chrome.tabs.query({ currentWindow: true });
    if (index < 0 || index >= tabs.length) {
        throw new Error(`Tab index ${index} out of range`);
    }
    await chrome.tabs.update(tabs[index].id, { active: true });
    return { switched: true, index };
}

async function downloadFile(url) {
    await chrome.downloads.download({ url });
    return { downloading: true, url };
}

// Initialize WebSocket connection
connectWebSocket();

// Reconnect on extension startup
chrome.runtime.onStartup.addListener(connectWebSocket);
chrome.runtime.onInstalled.addListener(connectWebSocket);