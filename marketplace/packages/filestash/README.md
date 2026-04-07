# Filestash

`Filestash` ist der Referenzdienst fuer den generischen Storage-Pfad in TRION:

1. Datentraeger im Storage-Broker einrichten
2. Pfad als Commander-Asset veroeffentlichen
3. Asset spaeter als generischen Mount in einen Container geben

Der offizielle `filestash`-Blueprint bleibt bewusst einfach:

- Web-UI auf `8334/tcp`
- persistenter Anwendungszustand ueber das Docker-Volume `filestash_state`
- keine app-spezifische Storage-Sonderlogik

Ziel ist, den generischen Produktpfad fuer zusaetzliche Speicherfreigaben zu haerten, ohne `gaming-station` weiter anzufassen.
