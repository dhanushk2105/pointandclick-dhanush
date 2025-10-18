console.log('Computer Use Agent content script loaded');

// Listen for messages from background script if needed
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    console.log('Content script received message:', request);
    
    if (request.action === 'ping') {
        sendResponse({ status: 'alive' });
    }
    
    return true;
});