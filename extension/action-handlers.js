/**
 * Action handler implementations
 * Restored to match original working behavior
 */

import { Logger, URLUtils } from './utils.js';

/**
 * Get active tab, ensuring it's safe for scripting
 */
async function getActiveTabSafe() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.id) {
    throw new Error('No active tab');
  }
  if (URLUtils.isForbidden(tab.url || '')) {
    throw new Error(`Unsupported scheme for scripting: ${tab.url || ''}`);
  }
  return tab;
}

/**
 * Base handler class
 */
class ActionHandler {
  constructor(name) {
    this.name = name;
  }

  async execute(payload) {
    Logger.log('▶️', `Executing ${this.name}`);
    try {
      const result = await this.handle(payload);
      Logger.log('✅', `${this.name} completed`);
      return result;
    } catch (error) {
      Logger.error(`${this.name} failed`, error);
      throw error;
    }
  }

  async handle(payload) {
    throw new Error('handle() must be implemented');
  }
}

/**
 * Navigate to URL
 */
class NavigateHandler extends ActionHandler {
  constructor() {
    super('navigate');
  }

  async handle(payload) {
    if (!payload.url) {
      throw new Error('navigate requires payload.url');
    }
    
    Logger.log('🌐', `Navigating to: ${payload.url}`);
    
    const [active] = await chrome.tabs.query({ active: true, currentWindow: true });
    
    if (!active || !active.id) {
      const tab = await chrome.tabs.create({ url: payload.url, active: true });
      return this.waitForTabComplete(tab.id, payload.url);
    }
    
    if (URLUtils.isForbidden(active.url || '')) {
      await chrome.tabs.update(active.id, { url: payload.url });
      return this.waitForTabComplete(active.id, payload.url);
    }
    
    await chrome.tabs.update(active.id, { url: payload.url });
    return this.waitForTabComplete(active.id, payload.url);
  }

  waitForTabComplete(tabId, fallbackUrl) {
    return new Promise((resolve) => {
      const listener = (updatedTabId, info, updatedTab) => {
        if (updatedTabId === tabId && info.status === 'complete') {
          chrome.tabs.onUpdated.removeListener(listener);
          Logger.log('✅', 'Navigation completed');
          resolve({ navigated: true, url: updatedTab?.url || fallbackUrl });
        }
      };
      chrome.tabs.onUpdated.addListener(listener);
    });
  }
}

/**
 * Wait for element
 */
class WaitForHandler extends ActionHandler {
  constructor() {
    super('waitFor');
  }

  async handle(payload) {
    if (!payload.selector) {
      throw new Error('waitFor requires selector');
    }
    
    Logger.log('⏳', `Waiting for: ${payload.selector}`);
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
            if (Date.now() - startTime > ms) {
              return reject(new Error(`Timeout: ${sel} not found within ${ms}ms`));
            }
            setTimeout(tick, 100);
          };
          tick();
        });
      },
      args: [payload.selector, payload.timeout || 5000]
    }).then(results => results[0].result);
  }
}

/**
 * Click element
 */
class ClickHandler extends ActionHandler {
  constructor() {
    super('click');
  }

  async handle(payload) {
    if (!payload.selector) {
      throw new Error('click requires selector');
    }
    
    Logger.log('🖱️', `Clicking: ${payload.selector}`);
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
      args: [payload.selector]
    }).then(results => results[0].result);
  }
}

/**
 * Type text
 */
class TypeHandler extends ActionHandler {
  constructor() {
    super('type');
  }

  async handle(payload) {
    if (!payload.selector) {
      throw new Error('type requires selector');
    }
    
    Logger.log('⌨️', `Typing: "${payload.text}"`);
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
      args: [payload.selector, payload.text]
    }).then(results => results[0].result);
  }
}

/**
 * Press key - RESTORED TO ORIGINAL
 */
class PressHandler extends ActionHandler {
  constructor() {
    super('press');
  }

  async handle(payload) {
    if (!payload.key) {
      throw new Error('press requires key');
    }
    
    Logger.log('⌨️', `Pressing: ${payload.key}`);
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
      args: [payload.key]
    }).then(results => results[0].result);
  }
}

/**
 * Query DOM
 */
class QueryHandler extends ActionHandler {
  constructor() {
    super('query');
  }

  async handle(payload) {
    if (!payload.selector) {
      throw new Error('query requires selector');
    }
    
    Logger.log('🔍', `Querying DOM: ${payload.selector}`);
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
      args: [payload.selector, payload.limit || 500]
    }).then(results => results[0].result);
  }
}

/**
 * Get page info
 */
class GetPageInfoHandler extends ActionHandler {
  constructor() {
    super('getPageInfo');
  }

  async handle(payload) {
    Logger.log('📄', 'Getting page info');
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
}

/**
 * Get interactive elements
 */
class GetInteractiveElementsHandler extends ActionHandler {
  constructor() {
    super('getInteractiveElements');
  }

  async handle(payload) {
    Logger.log('🧭', 'Collecting interactive elements');
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
}

/**
 * Smart click - RESTORED TO ORIGINAL
 */
class SmartClickHandler extends ActionHandler {
  constructor() {
    super('smartClick');
  }

  async handle(payload) {
    Logger.log('🎯', 'Smart click');
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
}

/**
 * Smart type - RESTORED TO ORIGINAL
 */
class SmartTypeHandler extends ActionHandler {
  constructor() {
    super('smartType');
  }

  async handle(payload) {
    Logger.log('⌨️', 'Smart type');
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
}

/**
 * Switch tab
 */
class SwitchTabHandler extends ActionHandler {
  constructor() {
    super('switchTab');
  }

  async handle(payload) {
    Logger.log('🔀', `Switching to tab: ${payload.index}`);
    const tabs = await chrome.tabs.query({ currentWindow: true });
    if (payload.index < 0 || payload.index >= tabs.length) {
      throw new Error(`Tab index ${payload.index} out of range (0-${tabs.length - 1})`);
    }
    await chrome.tabs.update(tabs[payload.index].id, { active: true });
    return { switched: true, index: payload.index };
  }
}

/**
 * Download file
 */
class DownloadHandler extends ActionHandler {
  constructor() {
    super('download');
  }

  async handle(payload) {
    if (!payload.url) {
      throw new Error('download requires url');
    }
    Logger.log('💾', `Downloading: ${payload.url}`);
    try {
      const downloadId = await chrome.downloads.download({ url: payload.url });
      return { downloading: true, url: payload.url, downloadId };
    } catch (error) {
      throw new Error(`Download failed: ${error.message}`);
    }
  }
}

/**
 * Upload file
 */
class UploadFileHandler extends ActionHandler {
  constructor() {
    super('uploadFile');
  }

  async handle(payload) {
    Logger.log('📤', 'Uploading file');
    const tab = await getActiveTabSafe();

    return chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: (opts) => {
        if (typeof document === 'undefined') {
          throw new Error('No DOM available in target page context');
        }
        const input = document.querySelector(opts.selector || 'input[type="file"]');
        if (!input) throw new Error('File input not found');
        input.click();
        return { triggered: true, message: 'File dialog opened - user must select file manually' };
      },
      args: [payload]
    }).then(results => results[0].result);
  }
}

/**
 * Capture screenshot
 */
class CaptureScreenshotHandler extends ActionHandler {
  constructor() {
    super('captureScreenshot');
  }

  async handle(payload) {
    Logger.log('📸', 'Capturing screenshot');
    try {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (!tab || !tab.id) throw new Error('No active tab');
      const dataUrl = await chrome.tabs.captureVisibleTab(null, { format: 'png' });
      const base64Data = dataUrl.split(',')[1] || '';
      Logger.log('✅', 'Screenshot captured');
      return base64Data;
    } catch (error) {
      Logger.error('Screenshot failed', error);
      return '';
    }
  }
}

/**
 * Registry of all action handlers
 */
export const actionHandlers = {
  navigate: new NavigateHandler(),
  waitFor: new WaitForHandler(),
  click: new ClickHandler(),
  type: new TypeHandler(),
  press: new PressHandler(),
  query: new QueryHandler(),
  getPageInfo: new GetPageInfoHandler(),
  getInteractiveElements: new GetInteractiveElementsHandler(),
  smartClick: new SmartClickHandler(),
  smartType: new SmartTypeHandler(),
  switchTab: new SwitchTabHandler(),
  download: new DownloadHandler(),
  uploadFile: new UploadFileHandler(),
  captureScreenshot: new CaptureScreenshotHandler()
};