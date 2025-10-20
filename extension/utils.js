/**
 * Shared utility functions for extension context
 * 
 * IMPORTANT: These utilities run in EXTENSION CONTEXT (background.js, etc.)
 * They CANNOT be used in page context (chrome.scripting.executeScript).
 * 
 * Page context utilities must be defined inline in the scriptFunction
 * because executeScript runs in an isolated environment.
 * 
 * What's here is used by:
 * - URLUtils: Used in action-handlers.js by getActiveTabSafe()
 * - Logger: Used throughout extension for logging
 */

/**
 * URL validation utilities - USED in action-handlers.js
 */
export const URLUtils = {
  isForbidden(url = '') {
    const forbidden = ['chrome://', 'edge://', 'about:', 'chrome-extension://'];
    return forbidden.some(prefix => url.startsWith(prefix));
  },

  isValid(url) {
    try {
      new URL(url);
      return true;
    } catch {
      return false;
    }
  }
};

/**
 * Logging utilities - USED throughout extension
 */
export const Logger = {
  verbose: true,

  log(emoji, message, details = '') {
    if (this.verbose) {
      console.log(`${emoji} [Extension] ${message}`);
      if (details) console.log('  →', details);
    }
  },

  section(title) {
    if (this.verbose) {
      console.log('\n' + '='.repeat(60));
      console.log(`  ${title}`);
      console.log('='.repeat(60));
    }
  },

  error(message, error) {
    console.error(`❌ [Extension] ${message}`, error);
  }
};

/**
 * String utilities
 */
export const StringUtils = {
  truncate(text, maxLength) {
    if (!text) return '';
    if (text.length <= maxLength) return text;
    return text.substring(0, maxLength) + '...';
  },

  sanitize(text) {
    if (!text) return '';
    return text.replace(/[<>]/g, '');
  }
};

/**
 * Async utilities
 */
export const AsyncUtils = {
  /**
   * Sleep for specified milliseconds
   */
  sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  },

  /**
   * Retry a function with exponential backoff
   */
  async retry(fn, maxAttempts = 3, baseDelay = 1000) {
    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      try {
        return await fn();
      } catch (error) {
        if (attempt === maxAttempts) throw error;
        const delay = baseDelay * Math.pow(2, attempt - 1);
        await this.sleep(delay);
      }
    }
  }
};