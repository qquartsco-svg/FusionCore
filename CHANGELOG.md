# Changelog

## 0.1.0 - 2026-03-23

- initial 5-layer FusionCore propulsion stack
- plasma FSM, confinement, reaction, thermal, shielding, power bus, propulsion
- Omega-based health monitoring and abort handling
- SHA-256 FusionChain audit log
- Rocket / Brain bridge entry points
- public package API and README added
- hardening pass:
  - abort phase consistency fixed
  - thermal sigma injection fixed
  - power bus base load now affects allocation
  - dead abort code removed
  - cache/bytecode clutter removed from tracked tree
