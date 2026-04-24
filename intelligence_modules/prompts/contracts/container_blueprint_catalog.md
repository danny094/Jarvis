---
scope: container_contract
target: output_layer
query_class: container_blueprint_catalog
variables: ["required_tools_line", "truth_mode_line"]
status: active
---

### CONTAINER-ANTWORTMODUS:
Containerantworten muessen Runtime-Inventar, Blueprint-Katalog und Session-Binding sichtbar getrennt halten.
Blueprint-Katalog, Runtime-Inventar und Binding niemals unmarkiert in denselben Antworttopf werfen.
Statische Profile oder Taxonomie duerfen erklaeren, aber keine Live-Bindung oder Runtime-Fakten erfinden.
{required_tools_line}
{truth_mode_line}
Pflichtreihenfolge: `Verfuegbare Blueprints`, dann `Einordnung`.
Im Abschnitt `Verfuegbare Blueprints` nur startbare oder katalogisierte Blueprint-Typen nennen.
Keine Behauptung ueber aktuell laufende oder installierte Container machen, wenn dafuer nur `blueprint_list` vorliegt.
Keine Session-Bindung, keinen aktiven Container und keine Runtime-Statusaussage als Hauptantwort behaupten.
Keine zusaetzlichen Runtime-Inventar-, Running-/Stopped- oder Empty-State-Aussagen machen, wenn kein `container_list`-Beleg vorliegt.
Die Antwort MUSS mit dem Literal `Verfuegbare Blueprints:` beginnen.

### VERPFLICHTENDES ANTWORTGERUEST:
Verfuegbare Blueprints: <verifizierter Katalog-Befund aus Blueprint-Evidence>.
Einordnung: <klare Trennung zwischen Blueprint-Katalog und aktuellem Runtime-Inventar>.
