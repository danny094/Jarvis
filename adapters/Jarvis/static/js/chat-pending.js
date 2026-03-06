// chat-pending.js — contextual pending bubble in the chat window
//
// Shows what TRION is currently doing between the Control Layer output
// and the actual response. States: thinking | skill | tool | planning

const STATES = {
    thinking: {
        icon: "◉",
        iconAnim: "pending-icon--pulse",
        text: "Analysiere Anfrage",
        mod: "pending-bubble--thinking",
    },
    skill: {
        icon: "⚙",
        iconAnim: "pending-icon--spin",
        text: "Erstelle Skill",
        mod: "pending-bubble--skill",
    },
    tool: {
        icon: "⚡",
        iconAnim: "pending-icon--pulse",
        text: "Führe Tool aus",
        mod: "pending-bubble--tool",
    },
    planning: {
        icon: "⋯",
        iconAnim: "pending-icon--bounce",
        text: "Plane Schritte",
        mod: "pending-bubble--planning",
    },
};

let _currentState = null;

function _getEl() {
    return document.getElementById("trion-pending-bubble");
}

function _buildInner(cfg) {
    return `
        <span class="pending-icon ${cfg.iconAnim}">${cfg.icon}</span>
        <span class="pending-label">${cfg.text}</span>
        <span class="pending-dot-anim"><span>.</span><span>.</span><span>.</span></span>
    `;
}

export function createPendingBubble(state = "thinking") {
    removePendingBubble();
    _currentState = state;

    const cfg = STATES[state] || STATES.thinking;
    const el = document.createElement("div");
    el.id = "trion-pending-bubble";
    el.className = `pending-bubble ${cfg.mod}`;
    el.innerHTML = _buildInner(cfg);

    const list = document.getElementById("messages-list");
    if (list) {
        list.appendChild(el);
        el.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
}

export function updatePendingState(state) {
    const cfg = STATES[state] || STATES[_currentState] || STATES.thinking;
    let el = _getEl();
    if (!el) {
        createPendingBubble(state);
        return;
    }
    _currentState = state;

    // Swap modifier class
    el.className = `pending-bubble ${cfg.mod}`;

    const iconEl = el.querySelector(".pending-icon");
    if (iconEl) {
        iconEl.textContent = cfg.icon;
        iconEl.className = `pending-icon ${cfg.iconAnim}`;
    }
    const labelEl = el.querySelector(".pending-label");
    if (labelEl) labelEl.textContent = cfg.text;
}

export function removePendingBubble() {
    const el = _getEl();
    if (el) {
        el.classList.add("pending-bubble--fade-out");
        setTimeout(() => el.remove(), 200);
    }
    _currentState = null;
}

export function hasPendingBubble() {
    return Boolean(_getEl());
}
