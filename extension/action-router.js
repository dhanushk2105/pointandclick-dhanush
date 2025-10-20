/**
 * Routes incoming actions to appropriate handlers
 */

import { Logger } from './utils.js';
import { actionHandlers } from './action-handlers.js';

/**
 * Main action router
 * Takes a message envelope and routes to the appropriate handler
 */
export async function handleAction(message) {
  const { action, payload = {} } = message;
  
  Logger.section(`⚡ EXECUTING: ${action}`);
  
  // Validate action exists
  const handler = actionHandlers[action];
  if (!handler) {
    throw new Error(`Unknown action: ${action}`);
  }
  
  // Validate payload
  validatePayload(action, payload);
  
  // Execute handler
  try {
    const result = await handler.execute(payload);
    return result;
  } catch (error) {
    // Re-throw with more context
    throw new Error(`Action '${action}' failed: ${error.message}`);
  }
}

/**
 * Validate payload for specific actions
 */
function validatePayload(action, payload) {
  const validations = {
    navigate: () => {
      if (!payload.url) {
        throw new Error('navigate requires payload.url');
      }
    },
    waitFor: () => {
      if (!payload.selector) {
        throw new Error('waitFor requires payload.selector');
      }
    },
    click: () => {
      if (!payload.selector) {
        throw new Error('click requires payload.selector');
      }
    },
    type: () => {
      if (!payload.selector) {
        throw new Error('type requires payload.selector');
      }
    },
    press: () => {
      if (!payload.key) {
        throw new Error('press requires payload.key');
      }
    },
    query: () => {
      if (!payload.selector) {
        throw new Error('query requires payload.selector');
      }
    },
    smartClick: () => {
      const hasIdentifier = payload.selector || payload.id || payload.name || 
                           payload.ariaLabel || payload.role || 
                           payload.text || payload.description;
      if (!hasIdentifier) {
        throw new Error('smartClick requires at least one identifier (selector, id, name, ariaLabel, role, text, or description)');
      }
    },
    smartType: () => {
      if (!payload.text) {
        throw new Error('smartType requires payload.text');
      }
    },
    switchTab: () => {
      if (typeof payload.index !== 'number') {
        throw new Error('switchTab requires payload.index (number)');
      }
    },
    download: () => {
      if (!payload.url) {
        throw new Error('download requires payload.url');
      }
    }
  };

  // Run validation if exists
  const validate = validations[action];
  if (validate) {
    validate();
  }
}

/**
 * Get list of available actions
 */
export function getAvailableActions() {
  return Object.keys(actionHandlers);
}

/**
 * Check if action is supported
 */
export function isActionSupported(action) {
  return action in actionHandlers;
}