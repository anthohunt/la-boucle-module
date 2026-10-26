# Version 1 of the module (history only, no code)

The first version of the mod ("La boucle", plugin name `la-boucle`) drove only the **framing of steps 1 and 2** of a new worksite. It followed a closed list of decision points
taken from the written specification of the method, injected the protocol and the state of every point into the system prompt, showed progress above the prompt and a table of active
agents, and gave the model two tools: `etat` (the state of the points) and `noter` (record a decision of the operator, word for word).

It is **not published**: it read a specification file of the original project that no longer exists, and version 2 replaces it entirely. Version 2 keeps the same principles:
the model does not keep the state, a program does; every decision is recorded with the operator's exact words; the closed list of points is data (`programme/parcours.json`), not code.

A small companion mod of the original project reminded the agent to propagate every change of the module to four places (module, program, user stories, documentation). It was specific
to that project's organisation and is not part of this repository.
