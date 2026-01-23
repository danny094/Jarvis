# Sequential UI Test Suite

## 📋 Overview

Comprehensive test suite for Sequential Thinking UI features including:
- Auto-Detection logic
- Sensitivity slider
- Sidebar integration
- Chat flow
- API endpoint routing
- Settings persistence

## 🚀 How to Run

### Method 1: Browser Console (Recommended for quick tests)

1. **Open Jarvis WebUI** in browser (http://localhost:8400)
2. **Open Browser DevTools** (F12 or Ctrl+Shift+I)
3. **Go to Console tab**
4. **Load the test suite:**
   ```javascript
   // Load test script
   const script = document.createElement('script');
   script.src = '/static/js/test_sequential_ui.js';
   document.head.appendChild(script);
   ```

5. **Run all tests:**
   ```javascript
   const suite = new SequentialUITestSuite();
   suite.runAll();
   ```

### Method 2: Include in index.html (For automated testing)

Add to `adapters/Jarvis/index.html` before `</body>`:
```html
<!-- Test Suite (dev only) -->
<script src="./static/js/test_sequential_ui.js"></script>
```

Then in console:
```javascript
new SequentialUITestSuite().runAll();
```

## 🧪 Test Groups

### GROUP 1: Initialization (3 tests)
- ✅ SequentialThinking instance exists
- ✅ SequentialSidebar instance exists
- ✅ No double initialization

### GROUP 2: Auto-Detection Logic (5 tests)
- ✅ Keyword detection (step-by-step, analyze, etc.)
- ✅ Length bonus (>150 chars)
- ✅ Multiple questions detection
- ✅ Numbered list detection
- ✅ Complexity scoring

### GROUP 3: Sensitivity & Threshold (3 tests)
- ✅ Threshold mapping (-10→15, 0→5, 10→1)
- ✅ LocalStorage persistence
- ✅ Edge case protection

### GROUP 4: Execute Task (2 tests)
- ✅ Force flag override
- ✅ Disabled state behavior

### GROUP 5: Sidebar Integration (3 tests)
- ✅ Start task opens sidebar
- ✅ Progress updates
- ✅ Completion handling

### GROUP 6: Settings UI (3 tests)
- ✅ Slider exists
- ✅ Slider range (-10 to +10)
- ✅ Slider updates sensitivity

### GROUP 7: API Endpoints (1 test)
- ✅ getApiBase() available

**TOTAL: 20 tests**

## 📊 Expected Output

```
🧪 Starting Sequential UI Test Suite...

═══ GROUP 1: INITIALIZATION ═══
✅ PASS: SequentialThinking instance exists on window
✅ PASS: SequentialSidebar instance exists on window
✅ PASS: No double initialization (single sidebar instance)

═══ GROUP 2: AUTO-DETECTION LOGIC ═══
✅ PASS: Auto-detection keyword test: "Explain step-by-step..."
✅ PASS: Auto-detection keyword test: "Analyze in detail..."
...

═══════════════════════════════════════════════
🧪 TEST SUITE COMPLETE
═══════════════════════════════════════════════
✅ PASSED: 20
❌ FAILED: 0
📊 TOTAL:  20
📈 SUCCESS RATE: 100.0%
═══════════════════════════════════════════════
```

## 🐛 Debugging Failed Tests

If tests fail, check:

1. **Initialization failures:**
   - Check browser console for errors during page load
   - Verify `window.sequentialThinking` exists
   - Verify `window.sequentialSidebar` exists

2. **Auto-detection failures:**
   - Check `shouldUseSequential()` method exists
   - Verify keyword list is loaded
   - Test with: `window.sequentialThinking.shouldUseSequential("test")`

3. **Sensitivity failures:**
   - Check localStorage: `localStorage.getItem('sequential_sensitivity')`
   - Verify slider exists: `document.getElementById('sequential-sensitivity-slider')`
   - Test threshold: `window.sequentialThinking.getSensitivityThreshold()`

4. **Sidebar failures:**
   - Check sidebar element: `document.querySelector('[data-sequential-sidebar]')`
   - Verify CSS loaded: Check for `.sequential-sidebar` styles
   - Test manually: `window.sequentialSidebar.open('half')`

## 🔧 Manual Test Scenarios

### Scenario 1: Auto-Detection Trigger
```javascript
// Set sensitivity to balanced
window.sequentialThinking.setSensitivity(0);

// Test messages
const tests = [
  "Hi",  // Should NOT trigger
  "Explain step-by-step how photosynthesis works",  // SHOULD trigger
];

tests.forEach(msg => {
  const result = window.sequentialThinking.shouldUseSequential(msg);
  console.log(`"${msg}" → ${result ? 'TRIGGER' : 'no trigger'}`);
});
```

### Scenario 2: Sensitivity Impact
```javascript
const msg = "Explain photosynthesis";

// Strict (-10)
window.sequentialThinking.setSensitivity(-10);
console.log('Strict:', window.sequentialThinking.shouldUseSequential(msg));

// Balanced (0)
window.sequentialThinking.setSensitivity(0);
console.log('Balanced:', window.sequentialThinking.shouldUseSequential(msg));

// Loose (10)
window.sequentialThinking.setSensitivity(10);
console.log('Loose:', window.sequentialThinking.shouldUseSequential(msg));
```

### Scenario 3: Sidebar Interaction
```javascript
// Start a test task
window.sequentialSidebar.startTask('test-123', {
  title: 'Test Task',
  description: 'Testing sidebar functionality'
});

// Add a step
window.sequentialSidebar.addStep({
  id: 'step-1',
  title: 'Planning Phase',
  description: 'CIM: 5 priors checked',
  status: 'running',
  timestamp: new Date()
});

// Update progress
window.sequentialSidebar.updateProgress(50, 'Halfway done!');

// Complete
window.sequentialSidebar.completeTask(true);
```

## 📝 Adding New Tests

To add new tests, extend the `SequentialUITestSuite` class:

```javascript
testYourNewFeature() {
    // Your test logic
    const result = someFunction();
    
    this.assert(
        result === expectedValue,
        'Description of what you're testing',
        `Details: ${result}`
    );
}
```

Then add to `runAll()`:
```javascript
console.log('\n═══ GROUP X: YOUR GROUP ═══');
this.testYourNewFeature();
```

## 🎯 CI/CD Integration

For automated testing, you can run via Node.js with a headless browser:

```bash
# Install dependencies
npm install puppeteer

# Run tests
node run_ui_tests.js
```

See `run_ui_tests.js` for headless browser test runner.

## 📄 License

Part of Jarvis AI System - Sequential Thinking Module
