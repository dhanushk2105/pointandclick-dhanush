/**
 * Manages WebSocket connection with automatic reconnection
 */

import { Logger } from './utils.js';

export class WebSocketManager {
  constructor(url, actionHandler) {
    this.url = url;
    this.actionHandler = actionHandler;
    this.ws = null;
    this.reconnectAttempts = 0;
    this.maxReconnectAttempts = 5;
    this.reconnectDelay = 1000;
    this.pendingResponses = new Map();
  }

  /**
   * Establish WebSocket connection
   */
  connect() {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      return;
    }

    Logger.log('🔌', 'Connecting to WebSocket server...');
    this.ws = new WebSocket(this.url);

    this.ws.onopen = () => this.handleOpen();
    this.ws.onmessage = (event) => this.handleMessage(event);
    this.ws.onerror = () => this.handleError();
    this.ws.onclose = () => this.handleClose();
  }

  /**
   * Handle WebSocket open event
   */
  handleOpen() {
    Logger.section('✅ WEBSOCKET CONNECTED');
    this.reconnectAttempts = 0;
    this.send({ type: 'connected', from: 'extension' });
  }

  /**
   * Handle incoming WebSocket messages
   */
  async handleMessage(event) {
    let message;
    try {
      message = JSON.parse(event.data);
    } catch {
      return;
    }

    // Handle ping/pong
    if (message.type === 'ping') {
      this.send({ type: 'pong' });
      return;
    }

    // Handle connection confirmation
    if (message.type === 'connected') {
      Logger.log('✅', 'Extension ready and connected');
      return;
    }

    // Handle action envelope (must have id and action)
    if (!message.id || !message.action) {
      return;
    }

    Logger.section('📨 RECEIVED ACTION');
    Logger.log('📬', 'Message', JSON.stringify(message, null, 2));

    try {
      const result = await this.actionHandler(message);
      this.send({ 
        id: message.id, 
        status: 'success', 
        data: result 
      });
      Logger.log('✅', 'Action completed');
    } catch (error) {
      const errorMsg = error?.message || String(error);
      Logger.log('❌', 'Action failed', errorMsg);
      this.send({ 
        id: message.id, 
        status: 'error', 
        error: errorMsg 
      });
    }
  }

  /**
   * Handle WebSocket error
   */
  handleError() {
    Logger.log('❌', 'WebSocket error');
  }

  /**
   * Handle WebSocket close event
   */
  handleClose() {
    Logger.log('🔌', 'WebSocket disconnected');
    this.attemptReconnect();
  }

  /**
   * Attempt to reconnect with exponential backoff
   */
  attemptReconnect() {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      Logger.log('❌', 'Max reconnection attempts reached');
      chrome.notifications.create({
        type: 'basic',
        iconUrl: 'icon.png',
        title: 'Agent Disconnected',
        message: 'Cannot connect to server. Please restart the Python server.'
      });
      return;
    }

    this.reconnectAttempts++;
    const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);
    Logger.log('🔄', `Reconnecting in ${delay}ms`, `Attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts}`);
    
    setTimeout(() => this.connect(), delay);
  }

  /**
   * Send message through WebSocket
   */
  send(data) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      try {
        this.ws.send(JSON.stringify(data));
      } catch (error) {
        Logger.error('Failed to send message', error);
      }
    }
  }

  /**
   * Check if WebSocket is connected
   */
  isConnected() {
    return this.ws && this.ws.readyState === WebSocket.OPEN;
  }

  /**
   * Close WebSocket connection
   */
  disconnect() {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  /**
   * Send action and create response promise
   */
  createResponseFuture(actionId) {
    const future = new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.pendingResponses.delete(actionId);
        reject(new Error('Action timeout'));
      }, 20000);

      this.pendingResponses.set(actionId, { resolve, reject, timeout });
    });

    return future;
  }

  /**
   * Resolve pending response
   */
  resolveResponse(actionId, response) {
    const pending = this.pendingResponses.get(actionId);
    if (pending) {
      clearTimeout(pending.timeout);
      pending.resolve(response);
      this.pendingResponses.delete(actionId);
    }
  }
}