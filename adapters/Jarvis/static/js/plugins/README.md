# 🔌 Jarvis Plugin Development Guide

Create your own plugins to extend Jarvis functionality!

---

## 📁 Quick Start

1. Create a new file in `/static/js/plugins/your-plugin.js`
2. Add the script tag to `index.html`
3. Refresh browser - done!

---

## 🧩 Plugin Structure

```javascript
/**
 * MY AWESOME PLUGIN v1.0
 */

// 1. Define Manifest (required)
const MANIFEST = {
    id: 'my-plugin',           // Unique ID (kebab-case)
    name: 'My Plugin',         // Display name
    version: '1.0.0',          // Semantic version
    description: 'What it does',
    author: 'Your Name',
    icon: 'star'               // Lucide icon name
};

// 2. Create Plugin Class (extends PluginBase)
class MyPlugin extends PluginBase {
    constructor(panel, manager) {
        super(panel, manager);
        // Your state here
        this.myState = {};
    }
    
    // Called when plugin is enabled
    init() {
        console.log('[MyPlugin] Starting...');
        // Setup listeners, inject UI, etc.
    }
    
    // Called when plugin is disabled
    destroy() {
        console.log('[MyPlugin] Stopping...');
        // Cleanup: remove listeners, UI elements, etc.
    }
    
    // Define configurable settings (optional)
    getSettings() {
        return [
            {
                key: 'myOption',
                label: 'My Option',
                type: 'toggle',      // toggle, number, text, select
                default: true,
                description: 'Enable this feature'
            }
        ];
    }
    
    // Called when user changes a setting
    onSettingChange(key, value) {
        console.log(`Setting ${key} changed to ${value}`);
    }
}

// 3. Register Plugin
if (window.PluginManager) {
    window.PluginManager.registerBuiltIn(MANIFEST, MyPlugin);
} else {
    window.addEventListener('DOMContentLoaded', () => {
        if (window.PluginManager) {
            window.PluginManager.registerBuiltIn(MANIFEST, MyPlugin);
        }
    });
}
```

---

## ⚙️ Settings Types

### Toggle (Boolean)
```javascript
{
    key: 'enabled',
    label: 'Enable Feature',
    type: 'toggle',
    default: true,
    description: 'Turn this on or off'
}
```

### Number (Slider)
```javascript
{
    key: 'maxItems',
    label: 'Maximum Items',
    type: 'number',
    default: 10,
    min: 1,
    max: 100,
    description: 'How many items to show'
}
```

### Text (Input)
```javascript
{
    key: 'apiKey',
    label: 'API Key',
    type: 'text',
    default: '',
    placeholder: 'Enter your key...',
    description: 'Your API key for the service'
}
```

### Select (Dropdown)
```javascript
{
    key: 'theme',
    label: 'Color Theme',
    type: 'select',
    default: 'dark',
    options: [
        { value: 'dark', label: 'Dark Mode' },
        { value: 'light', label: 'Light Mode' },
        { value: 'auto', label: 'System' }
    ]
}
```

---

## 🎨 Using the TRION Panel

Your plugin has access to `this.panel` (TRIONPanel instance):

```javascript
// Create a tab
this.panel.createTab(
    'my-tab-id',           // Unique ID
    '📊 My Tab',           // Title
    'markdown',            // Type: markdown, text, code
    { 
        autoOpen: true,    // Open panel automatically
        content: '# Hello' // Initial content
    }
);

// Update content
this.panel.updateContent('my-tab-id', 'New content', false);
// false = replace, true = append

// Close tab
this.panel.closeTab('my-tab-id');

// Panel state
this.panel.open('half');   // 'half' or 'full'
this.panel.close();
this.panel.toggle();
```

---

## 📡 Listening to SSE Events

React to backend events:

```javascript
init() {
    this.eventHandler = (e) => this.handleEvent(e);
    window.addEventListener('sse-event', this.eventHandler);
}

destroy() {
    window.removeEventListener('sse-event', this.eventHandler);
}

handleEvent(e) {
    const { type, ...data } = e.detail;
    
    switch(type) {
        case 'chat_start':
            console.log('Chat started:', data);
            break;
        case 'chat_token':
            console.log('Token received:', data.token);
            break;
        case 'chat_done':
            console.log('Chat finished');
            break;
    }
}
```

---

## 🔧 Using Plugin Manager

Access other plugins or settings:

```javascript
// Get all plugins
const plugins = this.manager.getAll();

// Check if plugin is enabled
if (this.manager.isEnabled('other-plugin')) {
    // ...
}

// Get/Set settings programmatically
const value = this.manager.getSetting('my-plugin', 'myOption');
this.manager.setSetting('my-plugin', 'myOption', newValue);

// Listen to plugin events
this.manager.on('plugin-enabled', ({ id }) => {
    console.log(`Plugin ${id} was enabled`);
});
```

---

## 📝 Example: Simple Chat Logger

```javascript
const MANIFEST = {
    id: 'chat-logger',
    name: 'Chat Logger',
    version: '1.0.0',
    description: 'Logs all chat messages to console',
    author: 'You',
    icon: 'scroll-text'
};

class ChatLoggerPlugin extends PluginBase {
    constructor(panel, manager) {
        super(panel, manager);
        this.handler = null;
        this.messageCount = 0;
    }
    
    init() {
        this.handler = (e) => {
            if (e.detail.type === 'chat_done') {
                this.messageCount++;
                console.log(`[ChatLogger] Message #${this.messageCount}`);
            }
        };
        window.addEventListener('sse-event', this.handler);
        console.log('[ChatLogger] Started logging');
    }
    
    destroy() {
        if (this.handler) {
            window.removeEventListener('sse-event', this.handler);
        }
        console.log(`[ChatLogger] Stopped. Total messages: ${this.messageCount}`);
    }
    
    getSettings() {
        return [
            {
                key: 'verbose',
                label: 'Verbose Mode',
                type: 'toggle',
                default: false,
                description: 'Log every token'
            }
        ];
    }
    
    onSettingChange(key, value) {
        if (key === 'verbose') {
            console.log(`[ChatLogger] Verbose mode: ${value}`);
        }
    }
}

if (window.PluginManager) {
    window.PluginManager.registerBuiltIn(MANIFEST, ChatLoggerPlugin);
}
```

---

## 🚀 Adding to Index.html

Add your plugin script **after** plugin-manager.js:

```html
<!-- Plugin System -->
<script src="./static/js/trion-panel.js"></script>
<script src="./static/js/plugin-manager.js"></script>
<script src="./static/js/plugin-settings.js"></script>

<!-- Built-in Plugins -->
<script src="./static/js/plugins/sequential-thinking.js"></script>
<script src="./static/js/plugins/code-beautifier.js"></script>

<!-- Your Plugin -->
<script src="./static/js/plugins/your-plugin.js"></script>
```

---

## 🎯 Best Practices

1. **Always cleanup in `destroy()`** - Remove event listeners, DOM elements, intervals
2. **Use unique IDs** - Prefix with your plugin name to avoid conflicts
3. **Handle missing dependencies** - Check if APIs exist before using
4. **Provide sensible defaults** - Plugin should work out of the box
5. **Log with prefix** - `[MyPlugin]` makes debugging easier

---

## 🐛 Debugging

Open browser DevTools (F12) and check:

```javascript
// List all plugins
window.PluginManager.getAll()

// Check specific plugin
window.PluginManager.get('my-plugin')

// Check if enabled
window.PluginManager.isEnabled('my-plugin')

// Manual enable/disable
window.PluginManager.enable('my-plugin')
window.PluginManager.disable('my-plugin')
```

---

## 📚 Available Icons

Use any [Lucide](https://lucide.dev/icons/) icon name:

`star`, `code`, `brain`, `puzzle`, `settings`, `terminal`, `database`, 
`cpu`, `wifi`, `zap`, `eye`, `shield`, `lock`, `key`, `bell`, `clock`,
`calendar`, `file`, `folder`, `image`, `video`, `music`, `mic`, etc.

---

Happy Plugin Development! 🎉
