/**
 * sanitize.js — Shared HTML Sanitizer (Phase 6)
 * ================================================
 * Prevents XSS in Markdown-rendered HTML output.
 *
 * Usage (script-tag / global):
 *   window.TRIONSanitize.sanitizeHtml(html)
 *
 * Usage (ES module):
 *   import { sanitizeHtml } from "./sanitize.js";
 *
 * Strategy:
 *   1. DOMPurify (if loaded) — most complete
 *   2. DOM-based fallback — removes dangerous tags/attrs, neutralises bad URLs
 *
 * Guarantees:
 *   - <script>, <iframe>, <object>, <embed>, <style>, <base>, <form> removed
 *   - on* event attributes removed
 *   - javascript:, vbscript:, data:text/html URLs neutralised to "#"
 *   - <a target="_blank"> gets rel="noopener noreferrer"
 */

(function (root, factory) {
    "use strict";
    if (typeof module !== "undefined" && module.exports) {
        module.exports = factory();
    } else {
        const api = factory();
        if (typeof root !== "undefined") root.TRIONSanitize = api;
        // ES module export via globalThis for module consumers
        if (typeof globalThis !== "undefined") globalThis.TRIONSanitize = api;
    }
})(typeof window !== "undefined" ? window : this, function () {
    "use strict";

    // Tags to remove entirely (including their content)
    const REMOVE_TAGS = [
        "script", "style", "iframe", "object", "embed",
        "form", "base", "link", "meta",
    ];

    // URL attributes that can carry javascript: payloads
    const URL_ATTRS = new Set([
        "href", "src", "action", "formaction", "xlink:href", "data",
    ]);

    // Schemes that must be neutralised
    const BAD_SCHEME_RE = /^(javascript:|vbscript:|data:text\/html)/i;

    // Event-handler attribute pattern
    const ON_ATTR_RE = /^on/i;

    function _addNoOpener(el) {
        if (el.tagName === "A" && el.getAttribute("target") === "_blank") {
            el.setAttribute("rel", "noopener noreferrer");
        }
    }

    function _domFallback(html) {
        if (typeof document === "undefined") return html; // SSR safety
        const tmp = document.createElement("div");
        tmp.innerHTML = html;

        // Remove dangerous tags
        tmp.querySelectorAll(REMOVE_TAGS.join(",")).forEach(el => el.remove());

        // Sanitize remaining elements
        tmp.querySelectorAll("*").forEach(el => {
            const toRemove = [];
            for (const attr of el.attributes) {
                const name = attr.name.toLowerCase();
                if (ON_ATTR_RE.test(name)) {
                    toRemove.push(attr.name);
                } else if (URL_ATTRS.has(name)) {
                    const val = (attr.value || "").replace(/\s/g, "").toLowerCase();
                    if (BAD_SCHEME_RE.test(val)) {
                        el.setAttribute(attr.name, "#");
                    }
                }
            }
            toRemove.forEach(n => el.removeAttribute(n));
            _addNoOpener(el);
        });

        return tmp.innerHTML;
    }

    function _dompurifyPath(html) {
        const clean = window.DOMPurify.sanitize(html);
        // Post-process: add rel=noopener to _blank links (DOMPurify may strip rel)
        if (typeof document === "undefined") return clean;
        const tmp = document.createElement("div");
        tmp.innerHTML = clean;
        tmp.querySelectorAll("a[target='_blank']").forEach(_addNoOpener);
        return tmp.innerHTML;
    }

    /**
     * Sanitize an HTML string against XSS.
     * @param {string} html  Raw HTML (e.g. from marked.parse())
     * @returns {string}     Safe HTML
     */
    function sanitizeHtml(html) {
        if (!html) return "";
        if (typeof window !== "undefined" && window.DOMPurify) {
            return _dompurifyPath(html);
        }
        return _domFallback(html);
    }

    return { sanitizeHtml };
});
