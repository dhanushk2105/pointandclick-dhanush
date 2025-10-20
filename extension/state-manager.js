/**
 * Manages persistent agent state across extension lifecycle
 */

import { Logger } from './utils.js';

export class StateManager {
  constructor() {
    this.state = this.getDefaultState();
  }

  getDefaultState() {
    return {
      currentTaskId: null,
      taskStatus: 'idle',
      taskDescription: '',
      logs: [],
      lastUpdate: null,
      connected: false
    };
  }

  /**
   * Load state from chrome.storage.local
   */
  async load() {
    try {
      const result = await chrome.storage.local.get('agentState');
      if (result.agentState) {
        this.state = result.agentState;
        Logger.log('📂', 'Loaded persistent state');
      }
    } catch (error) {
      Logger.error('Failed to load state', error);
    }
    return this.state;
  }

  /**
   * Save state to chrome.storage.local
   */
  async save() {
    try {
      await chrome.storage.local.set({ agentState: this.state });
      Logger.log('💾', 'Saved persistent state');
    } catch (error) {
      Logger.error('Failed to save state', error);
    }
  }

  /**
   * Update state and broadcast to listeners
   */
  update(updates) {
    this.state = { ...this.state, ...updates };
    this.state.lastUpdate = new Date().toISOString();
    this.save();
    this.broadcast();
  }

  /**
   * Broadcast state update to all extension contexts
   */
  broadcast() {
    chrome.runtime.sendMessage({
      type: 'stateUpdate',
      state: this.state
    }).catch(() => {
      // Popup might not be open, ignore
    });
  }

  /**
   * Get current state
   */
  get() {
    return this.state;
  }

  /**
   * Get specific state property
   */
  getProperty(key) {
    return this.state[key];
  }

  /**
   * Clear all state
   */
  clear() {
    this.state = this.getDefaultState();
    this.save();
    this.broadcast();
  }

  /**
   * Check if task is active
   */
  isTaskActive() {
    return this.state.currentTaskId !== null && 
           ['planning', 'processing', 'verifying'].includes(this.state.taskStatus);
  }

  /**
   * Set task info
   */
  setTask(taskId, description) {
    this.update({
      currentTaskId: taskId,
      taskDescription: description,
      taskStatus: 'planning'
    });
  }

  /**
   * Update task status
   */
  setStatus(status) {
    this.update({ taskStatus: status });
  }

  /**
   * Set connection status
   */
  setConnected(connected) {
    this.update({ connected });
  }

  /**
   * Add log entry and persist
   */
  addLog(type, message, details = '') {
    const logs = [...this.state.logs];
    logs.push({
      timestamp: new Date().toISOString(),
      type,
      message,
      details
    });
    
    // Keep only last 100 logs
    if (logs.length > 100) {
      logs.shift();
    }
    
    this.update({ logs });
  }

  /**
   * Clear logs
   */
  clearLogs() {
    this.update({ logs: [] });
  }
}