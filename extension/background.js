/**
 * Main background service worker entry point
 * Coordinates WebSocket connection, state management, and action routing
 */

import { StateManager } from './state-manager.js';
import { WebSocketManager } from './websocket-manager.js';
import { handleAction } from './action-router.js';
import { Logger } from './utils.js';

// Initialize managers
const stateManager = new StateManager();
const wsManager = new WebSocketManager('ws://localhost:8000/ws', handleAction);

/**
 * Initialize extension
 */
async function initialize() {
  Logger.section('🚀 EXTENSION INITIALIZING');
  
  // Load persistent state
  await stateManager.load();
  
  // Connect to WebSocket server
  wsManager.connect();
  
  // Monitor connection status
  startConnectionMonitoring();
  
  Logger.log('✅', 'Extension initialized');
}

/**
 * Monitor WebSocket connection and update state
 */
function startConnectionMonitoring() {
  const checkConnection = () => {
    const connected = wsManager.isConnected();
    
    // Only update if connection status changed
    if (stateManager.getProperty('connected') !== connected) {
      stateManager.setConnected(connected);
      
      if (connected) {
        Logger.log('✅', 'Connected to server');
      } else {
        Logger.log('❌', 'Disconnected from server');
      }
    }
  };
  
  // Check every 5 seconds
  setInterval(checkConnection, 5000);
  
  // Initial check
  checkConnection();
}

/**
 * Handle messages from popup and other extension contexts
 */
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  try {
    switch (request.type) {
      case 'checkConnection':
        sendResponse({ connected: wsManager.isConnected() });
        break;
      
      case 'getState':
        sendResponse({ state: stateManager.get() });
        break;
      
      case 'clearState':
        stateManager.clear();
        sendResponse({ cleared: true });
        break;
      
      case 'ping':
        sendResponse({ status: 'alive' });
        break;
      
      default:
        sendResponse({ error: 'Unknown message type' });
    }
  } catch (error) {
    Logger.error('Message handler error', error);
    sendResponse({ error: error.message });
  }
  
  return true; // Keep message channel open for async responses
});

/**
 * Handle extension lifecycle events
 */
chrome.runtime.onStartup.addListener(() => {
  Logger.log('🔄', 'Extension startup');
  initialize();
});

chrome.runtime.onInstalled.addListener((details) => {
  Logger.log('📦', 'Extension installed', details.reason);
  initialize();
  
  if (details.reason === 'install') {
    // First time install
    Logger.log('👋', 'Welcome! First time setup');
    stateManager.clear();
  } else if (details.reason === 'update') {
    // Extension updated
    Logger.log('⬆️', 'Extension updated', `from ${details.previousVersion}`);
  }
});

/**
 * Handle extension suspend (cleanup)
 */
chrome.runtime.onSuspend.addListener(() => {
  Logger.log('💤', 'Extension suspending');
  wsManager.disconnect();
});

/**
 * Handle tab updates (useful for detecting navigation changes)
 */
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  // Only log significant changes
  if (changeInfo.status === 'complete' && tab.active) {
    Logger.log('🌐', 'Tab loaded', tab.url);
  }
});

/**
 * Handle tab activation (useful for tracking which tab is active)
 */
chrome.tabs.onActivated.addListener((activeInfo) => {
  chrome.tabs.get(activeInfo.tabId, (tab) => {
    if (chrome.runtime.lastError) return;
    Logger.log('👁️', 'Tab activated', tab.url);
  });
});

/**
 * Error handler for uncaught errors
 */
self.addEventListener('error', (event) => {
  Logger.error('Uncaught error', event.error);
});

/**
 * Error handler for unhandled promise rejections
 */
self.addEventListener('unhandledrejection', (event) => {
  Logger.error('Unhandled promise rejection', event.reason);
});

// Start the extension
initialize();

// Export for debugging in console
self.stateManager = stateManager;
self.wsManager = wsManager;