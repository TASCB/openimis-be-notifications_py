# openIMIS Notifications module (TASAF / CoreMIS)

Module number **28**, rights `28xxxx`. In-app notifications with a pluggable channel
registry. Domain modules never import this module — event adapters live here and bind to
service signals the domain already emits.

Design: `docs/NOTIFICATIONS_ARCHITECTURE.md` in the dist repo.
