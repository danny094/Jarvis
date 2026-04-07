# Runtime Hardware

`runtime-hardware` ist der neue generische Hardware-, Capability- und Attachment-Planungsdienst fuer Jarvis.

v0 liefert:

- Hardware-Discovery
- Connector-Registry
- Capability-Auskunft
- Plan- und Validate-Endpunkte
- einen ersten `container_connector`

v0 liefert bewusst noch nicht:

- allgemeines Live-Attach
- vollwertiges PCI-/USB-Hotplug
- QEMU-Hotplug
- Remote-Agent-Federation

Der Dienst ist als eigener Blueprint `runtime-hardware` installierbar und soll spaeter die gemeinsame Hardware-Schicht fuer `container`, `qemu` und weitere Runtime-Connectoren bilden.
