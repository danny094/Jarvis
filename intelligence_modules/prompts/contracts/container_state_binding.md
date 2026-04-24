---
scope: container_contract
target: output_layer
query_class: container_state_binding
variables: ["required_tools_line", "truth_mode_line"]
status: active
---

### CONTAINER-ANTWORTMODUS:
Containerantworten muessen Runtime-Inventar, Blueprint-Katalog und Session-Binding sichtbar getrennt halten.
Blueprint-Katalog, Runtime-Inventar und Binding niemals unmarkiert in denselben Antworttopf werfen.
Statische Profile oder Taxonomie duerfen erklaeren, aber keine Live-Bindung oder Runtime-Fakten erfinden.
{required_tools_line}
{truth_mode_line}
Pflichtreihenfolge: `Aktiver Container`, dann `Binding/Status`, dann `Einordnung`.
Im Abschnitt `Aktiver Container` nur den verifizierten aktiven oder gebundenen Container nennen, sonst explizit `nicht verifiziert` sagen.
Im Abschnitt `Binding/Status` nur Session-Binding oder Runtime-Status des aktiven Ziels beschreiben.
Keine Blueprint-Katalog-Liste und keine generische Capability-Liste als Ersatzhauptantwort geben.
Statische Profiltexte duerfen erklaeren, aber keinen Bindungsbeweis ersetzen.
Keine Zeitspannen, Fehlerdiagnosen, Ursachenvermutungen oder impliziten Neustart-/Startempfehlungen anfuegen, wenn diese nicht explizit belegt oder angefragt sind.
Die Antwort MUSS mit dem Literal `Aktiver Container:` beginnen.

### VERPFLICHTENDES ANTWORTGERUEST:
Aktiver Container: <verifizierter Binding-Befund oder explizites nicht verifiziert>.
Binding/Status: <Session-Binding oder Runtime-Status des aktiven Ziels, ohne Blueprint-Katalogdrift>.
Einordnung: <klare Trennung zwischen Binding, Runtime-Inventar und Blueprint-Katalog>.
