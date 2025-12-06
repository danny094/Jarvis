// ui.js
import { getModels } from "./api.js";
import { setModel, handleUserMessage } from "./chat.js";

export async function initUI() {
    const models = await getModels();

    // Model Selector befüllen
    const dropdown = document.getElementById("model-dropdown");
    const btn = document.getElementById("model-selector-btn");

    dropdown.innerHTML = "";
    models.forEach(m => {
        const item = document.createElement("button");
        item.className = "w-full text-left px-3 py-2 hover:bg-hover rounded-lg";
        item.innerText = m;

        item.onclick = () => {
            setModel(m);
            btn.innerHTML = `${m} <i data-lucide="chevron-down" class="w-4 h-4"></i>`;
            dropdown.classList.add("hidden");
        };

        dropdown.appendChild(item);
    });

    // Default Modell setzen
    if (models.length > 0) {
        setModel(models[0]);
        btn.innerHTML = `${models[0]} <i data-lucide="chevron-down" class="w-4 h-4"></i>`;
    }

    // Input-Feld handler
    const input = document.getElementById("user-input");
    const sendBtn = document.getElementById("send-btn");

    sendBtn.onclick = () => {
        const text = input.value.trim();
        if (!text) return;
        input.value = "";
        handleUserMessage(text);
    };
}
