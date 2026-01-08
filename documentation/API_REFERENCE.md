# PERSONA MANAGEMENT API - QUICK REFERENCE

**Base URL:** `http://localhost:8100/api/personas`  
**Version:** 2.0  
**Format:** JSON  
**Auth:** None (internal API)

---

## 📋 ENDPOINTS OVERVIEW

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/` | List all personas | ❌ |
| GET | `/{name}` | Get persona content | ❌ |
| POST | `/` | Upload new persona | ❌ |
| PUT | `/switch?name={name}` | Switch active | ❌ |
| DELETE | `/{name}` | Delete persona | ❌ |

---

## 🚀 QUICK START EXAMPLES

### JavaScript (Fetch API)

```javascript
// List all personas
const response = await fetch('http://localhost:8100/api/personas/');
const data = await response.json();
console.log(data.personas); // ["default", "dev"]

// Get specific persona
const persona = await fetch('http://localhost:8100/api/personas/default');
const details = await persona.json();
console.log(details.content); // File content

// Upload new persona
const formData = new FormData();
formData.append('file', fileInput.files[0]);
const upload = await fetch('http://localhost:8100/api/personas/', {
  method: 'POST',
  body: formData
});

// Switch persona
const switchResponse = await fetch(
  'http://localhost:8100/api/personas/switch?name=dev',
  { method: 'PUT' }
);

// Delete persona
const deleteResponse = await fetch(
  'http://localhost:8100/api/personas/dev',
  { method: 'DELETE' }
);
```

### cURL

```bash
# List all
curl http://localhost:8100/api/personas/

# Get specific
curl http://localhost:8100/api/personas/default

# Upload
curl -X POST http://localhost:8100/api/personas/ \
  -F "file=@my_persona.txt"

# Switch
curl -X PUT "http://localhost:8100/api/personas/switch?name=dev"

# Delete
curl -X DELETE http://localhost:8100/api/personas/dev
```

---

## 📖 DETAILED ENDPOINT SPECS

### 1. List All Personas

**GET** `/api/personas/`

**Response:**
```json
{
  "personas": ["default", "dev", "creative"],
  "active": "default",
  "count": 3
}
```

**Status Codes:**
- `200`: Success
- `500`: Server error

---

### 2. Get Persona Content

**GET** `/api/personas/{name}`

**Parameters:**
- `name` (path, required): Persona name

**Response:**
```json
{
  "name": "default",
  "content": "# Persona: Jarvis\n[IDENTITY]\n...",
  "exists": true,
  "size": 1464,
  "active": true
}
```

**Status Codes:**
- `200`: Success
- `400`: Invalid name
- `404`: Not found
- `500`: Server error

---

### 3. Upload Persona

**POST** `/api/personas/`

**Content-Type:** `multipart/form-data`

**Form Fields:**
- `file` (file, required): .txt file

**Constraints:**
- Max size: 10KB
- Extension: .txt only
- Encoding: UTF-8
- Must contain `[IDENTITY]` section
- Must have `name` field

**Response:**
```json
{
  "success": true,
  "name": "my_persona",
  "size": 380,
  "message": "Persona 'my_persona' uploaded successfully"
}
```

**Status Codes:**
- `200`: Success
- `400`: Invalid file/content
- `500`: Server error

**JavaScript Example:**
```javascript
async function uploadPersona(file) {
  const formData = new FormData();
  formData.append('file', file);
  
  const response = await fetch('/api/personas/', {
    method: 'POST',
    body: formData
  });
  
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail);
  }
  
  return await response.json();
}
```

---

### 4. Switch Active Persona

**PUT** `/api/personas/switch`

**Query Parameters:**
- `name` (query, required): Persona to switch to

**Response:**
```json
{
  "success": true,
  "previous": "default",
  "current": "dev",
  "message": "Switched to 'dev'",
  "persona_name": "DevBot"
}
```

**Status Codes:**
- `200`: Success
- `400`: Invalid name
- `404`: Not found
- `500`: Server error

**JavaScript Example:**
```javascript
async function switchPersona(name) {
  const response = await fetch(
    `/api/personas/switch?name=${encodeURIComponent(name)}`,
    { method: 'PUT' }
  );
  
  if (!response.ok) {
    throw new Error('Failed to switch persona');
  }
  
  return await response.json();
}
```

---

### 5. Delete Persona

**DELETE** `/api/personas/{name}`

**Parameters:**
- `name` (path, required): Persona to delete

**Protection:**
- Cannot delete "default" persona

**Response:**
```json
{
  "success": true,
  "deleted": "dev",
  "message": "Persona 'dev' deleted successfully"
}
```

**Status Codes:**
- `200`: Success
- `400`: Protected persona
- `404`: Not found
- `500`: Server error

**JavaScript Example:**
```javascript
async function deletePersona(name) {
  if (name === 'default') {
    throw new Error('Cannot delete default persona');
  }
  
  const response = await fetch(`/api/personas/${name}`, {
    method: 'DELETE'
  });
  
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail);
  }
  
  return await response.json();
}
```

---

## ⚠️ ERROR HANDLING

### Error Response Format:
```json
{
  "detail": "Error message here"
}
```

### Common Errors:

**400 Bad Request:**
```json
{
  "detail": "Invalid persona name. Use alphanumeric, dash, underscore only."
}
```

**404 Not Found:**
```json
{
  "detail": "Persona 'xyz' not found"
}
```

**400 Protected:**
```json
{
  "detail": "Cannot delete 'default' persona (protected)"
}
```

### JavaScript Error Handling:
```javascript
try {
  const response = await fetch('/api/personas/invalid-name');
  if (!response.ok) {
    const error = await response.json();
    console.error('API Error:', error.detail);
    // Show to user
    alert(error.detail);
  }
} catch (error) {
  console.error('Network Error:', error);
  alert('Connection failed. Please try again.');
}
```

---

## 🎯 FRONTEND INTEGRATION GUIDE

### Complete Persona Manager Class:

```javascript
class PersonaManager {
  constructor(baseUrl = 'http://localhost:8100/api/personas') {
    this.baseUrl = baseUrl;
  }
  
  async listAll() {
    const response = await fetch(this.baseUrl);
    if (!response.ok) throw new Error('Failed to list personas');
    return await response.json();
  }
  
  async getPersona(name) {
    const response = await fetch(`${this.baseUrl}/${name}`);
    if (!response.ok) throw new Error(`Persona '${name}' not found`);
    return await response.json();
  }
  
  async upload(file) {
    const formData = new FormData();
    formData.append('file', file);
    
    const response = await fetch(this.baseUrl, {
      method: 'POST',
      body: formData
    });
    
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail);
    }
    
    return await response.json();
  }
  
  async switch(name) {
    const response = await fetch(
      `${this.baseUrl}/switch?name=${encodeURIComponent(name)}`,
      { method: 'PUT' }
    );
    
    if (!response.ok) throw new Error('Failed to switch persona');
    return await response.json();
  }
  
  async delete(name) {
    if (name === 'default') {
      throw new Error('Cannot delete default persona');
    }
    
    const response = await fetch(`${this.baseUrl}/${name}`, {
      method: 'DELETE'
    });
    
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail);
    }
    
    return await response.json();
  }
}

// Usage:
const manager = new PersonaManager();

// List
const { personas, active } = await manager.listAll();

// Switch
await manager.switch('dev');

// Upload
const fileInput = document.getElementById('fileInput');
await manager.upload(fileInput.files[0]);

// Delete
await manager.delete('old_persona');
```

---

## 📝 PERSONA FILE FORMAT

### Required Structure:
```txt
# Persona: Name
[IDENTITY]
name: Display Name
role: Role Description
language: deutsch
user_name: Danny

[PERSONALITY]
- trait1
- trait2

[STYLE]
tone: casual
verbosity: medium

[RULES]
1. Rule one
2. Rule two

[PRIVACY]
- Privacy rule

[GREETINGS]
greeting: Hello!
farewell: Goodbye!
```

### Validation Rules:
- ✅ Max size: 10KB
- ✅ Encoding: UTF-8
- ✅ Extension: .txt
- ✅ Must contain: `[IDENTITY]` section
- ✅ Must have: `name` field
- ✅ Filename: alphanumeric, dash, underscore only

---

## 🔒 SECURITY NOTES

### Input Validation:
- Filenames sanitized (no path traversal)
- Size limits enforced (10KB max)
- UTF-8 encoding required
- Special characters blocked

### Protection:
- Default persona cannot be deleted
- No authentication required (internal API)
- CORS enabled for localhost development

### Best Practices:
```javascript
// Always validate filenames client-side
function validateFilename(filename) {
  const regex = /^[a-zA-Z0-9_-]+\.txt$/;
  return regex.test(filename);
}

// Check file size before upload
function validateFileSize(file) {
  const maxSize = 10 * 1024; // 10KB
  return file.size <= maxSize;
}

// Validate before upload
if (!validateFilename(file.name)) {
  alert('Invalid filename. Use only letters, numbers, dash, underscore');
  return;
}

if (!validateFileSize(file)) {
  alert('File too large. Maximum 10KB');
  return;
}
```

---

## 🐛 TROUBLESHOOTING

### Issue: 404 Not Found
**Cause:** Persona doesn't exist  
**Solution:** Check spelling, use list endpoint first

### Issue: 400 Bad Request on Upload
**Cause:** Invalid file format or content  
**Solution:** 
- Check file has .txt extension
- Verify UTF-8 encoding
- Ensure [IDENTITY] section exists
- Check file size < 10KB

### Issue: Cannot Delete Persona
**Cause:** Trying to delete "default"  
**Solution:** Default persona is protected, create a different one

### Issue: CORS Error
**Cause:** Accessing from different domain  
**Solution:** API is configured for localhost, check nginx proxy

---

## 📊 PERFORMANCE TIPS

### Best Practices:
```javascript
// Cache persona list
let cachedPersonas = null;
let cacheTimestamp = 0;

async function getCachedPersonas() {
  const now = Date.now();
  if (!cachedPersonas || (now - cacheTimestamp) > 60000) {
    cachedPersonas = await manager.listAll();
    cacheTimestamp = now;
  }
  return cachedPersonas;
}

// Invalidate cache on changes
async function uploadPersona(file) {
  await manager.upload(file);
  cachedPersonas = null; // Force refresh
}

// Debounce switch calls
let switchTimeout;
function debouncedSwitch(name) {
  clearTimeout(switchTimeout);
  switchTimeout = setTimeout(() => {
    manager.switch(name);
  }, 500);
}
```

---

## 🎨 UI INTEGRATION PATTERNS

### Dropdown Selector:
```html
<select id="persona-selector">
  <option value="default">Jarvis (Default)</option>
  <option value="dev">DevBot</option>
</select>
```

```javascript
// Populate dropdown
async function populateSelector() {
  const { personas, active } = await manager.listAll();
  const select = document.getElementById('persona-selector');
  
  select.innerHTML = personas.map(name => 
    `<option value="${name}" ${name === active ? 'selected' : ''}>
      ${name}
    </option>`
  ).join('');
}

// Handle change
document.getElementById('persona-selector').addEventListener('change', async (e) => {
  await manager.switch(e.target.value);
  alert('Persona switched!');
});
```

### Upload Button:
```html
<input type="file" id="file-input" accept=".txt" />
<button onclick="handleUpload()">Upload Persona</button>
```

```javascript
async function handleUpload() {
  const input = document.getElementById('file-input');
  const file = input.files[0];
  
  if (!file) {
    alert('Please select a file');
    return;
  }
  
  try {
    const result = await manager.upload(file);
    alert(result.message);
    await populateSelector(); // Refresh list
  } catch (error) {
    alert('Upload failed: ' + error.message);
  }
}
```

---

## 📚 RELATED DOCS

- **Phase 1:** Backend Implementation
- **Phase 2:** API Endpoints (this doc)
- **Phase 3:** Frontend UI (upcoming)
- **Testing:** Test Suite Documentation
- **Persona Format:** `/personas/README.md`

---

**Last Updated:** 2026-01-06  
**API Version:** 2.0  
**Status:** Production Ready
