What was changed
output.py:

```
# _build_full_prompt() NEU:
def _build_full_prompt(self, ..., chat_history: list = None):
    # Now integrate History into the Prompt:
    
### PREVIOUS CONVERSATION:
USER: My name is Danny
ASSISTANT: Hi Danny!
USER: What is 2 + 2?
ASSISTANT: That's 4.

### USER:
What's my name?
### YOUR REPLY:

```

bridge.py:

```
python# Streaming:
async for chunk in self.output.generate_stream(
    ...,
    chat_history=request.messages  # ← NEU
)

# Non-Streaming:
answer = await self.output.generate(
    ...,
    chat_history=request.messages  # ← NEU
)
```

---

## The new river
```
User: "My name is Danny"
  ↓
Output received: chat_history=[]
  ↓
Prompt:
### USER: My name is Danny
## YOUR REPLY:
  ↓
→ "Hi Danny!"

User: "What is my name?"
  ↓
Output received: chat_history=[
{user: "My name is Danny"},
{assistant: "Hi Danny!"}
]
  ↓
Prompt:
### PREVIOUS CONVERSATION:
USER: My name is Danny
ASSISTANT: Hi Danny!
  
### USER: What is my name?
#### YOUR ANSWER:
  ↓
→ "Your name is Danny!" ✅


Bonus: The history is limited to 10 messages.
python# In output.py:

```
history_to_show = chat_history[-11:-1] # Last 10 chats, excluding the most recent ones
This prevents the prompt from becoming too long during long conversations.

```

***

NEW WEBUI:


index.html >>> ettings modal, debug panel, new UI elements
app.js >>> Settings logic, LocalStorage, event listeners
api.js>>> setApiBase(), logging
chat.js >>> setHistoryLimit(), updateHistoryDisplay()
debug.js >>> NEW - Logging system


Test
start bash# WebUI
cd ~/Downloads/WEBUI
python3 -m http.server 8080

# In your browser: http://localhost:8080
# 1. Click the terminal icon → Open the debug panel
# 2. Click the gear icon → Open settings
# 3. Set the history to 5 → Save
# 4. Test the chat and monitor the logs!