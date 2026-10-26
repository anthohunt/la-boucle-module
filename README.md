# la-boucle-module — "La boucle" v2 as a Claude Code mod

> **EARLY ACCESS.** This module is written for the Claude Code *mods* API, whose type declarations say:
> "EARLY ACCESS: this surface may change between releases without notice". It was developed and tested against
> Claude Code 2.1.295; mods need Claude Code 2.1.287 or later. A new Claude Code release can break it. Check the
> [official mods documentation](https://code.claude.com/docs/en/plugins/mods/overview.md) first.

The module drives one **worksite** (*chantier*) of the **La boucle** method from inside Claude Code (terminal, the Code tab of
Claude Desktop, VS Code): a **control pane** on the side, a **band above the prompt**, instructions injected into the session
that is attached to the worksite, and a set of tools through which every gesture goes. Every decision of the operator is
recorded **word for word** with its time; the numbers (sample sizes, thresholds, chances) are computed by a program, never by the model.

> Code, strings shown to the user and method files are in **French** (the project's origin); this README and `docs/` are in English.

## What the module does, in 5 steps

The method turns a business process into something a **small model** can do on its own: trained to decide exactly what the operator
expects, and proved on a sealed exam before delivery. The module walks the operator through five steps (file `programme/parcours.json`):

1. **The objective** - from a need in the operator's words to a complete objective, defined layer by layer, scored by one function, reviewed blind by fresh readers, then **sealed**.
2. **The data study** - which data, how to get it, how many items per batch, which thresholds, at what cost; checked by a fresh agent, then sealed. The statistics (exact binomial) live in `programme/statistiques.py`.
3. **The bench** - build, without the operator, a labelled and verified bench according to the sealed plan; the operator may review a part of it, then seals it.
4. **The loop** - training and evaluation loop on their own: the loop searches better harnesses; the operator authorises the exam of a ready champion. This step uses the **engine** (see below).
5. **The deliverable** - package the version that passed the exam: framing, build, equivalence, measure, acceptance.

A step is **sealed** only when the operator confirms its fingerprint through a channel that agents cannot write (see `docs/settings.md`). A sealed step can be reopened only on the operator's explicit word.

## Dependency on the engine: `la-boucle-engine`

Steps 3 and 4 run the loop with the separate repository **`la-boucle-engine`** (Python >= 3.10, standard library only), command `python3 -m boucle ...`.
The module does not contain the engine; the command is a setting (`moteur`, default `python3 -m boucle`) that is given to the agents.

```bash
pip install git+https://github.com/anthohunt/la-boucle-engine
```
(The engine repository is not published yet when this README is written; until then, clone or copy it and put it on `PYTHONPATH`.)
Note: the program of this module is itself called `programme/boucle.py`. Do not add the `programme/` folder to `PYTHONPATH`, or it would shadow the engine's `boucle` package.

## Requirements

- Claude Code **2.1.287 or later**, logged in (a separate product of Anthropic, under Anthropic's terms; it is not distributed here).
- Python **3.10 or later** (standard library only) on the machine that runs the program.
- Node is **not** needed to use the module. To run the module's TypeScript tests you only need Claude Code (`claude plugin test`).
- Optional: an SSH client, if the program runs on another machine than Claude Code.

## Install

The module is a Claude Code plugin that holds a mod (`hooks/hooks.json` points to `hooks/register.tsx`). Official ways to load a plugin:
[Create a plugin - develop without a marketplace](https://code.claude.com/docs/en/plugins/create.md) and
[Install plugins](https://code.claude.com/docs/en/plugins/install.md). Two ways:

**A. For one session, from a clone (simplest)**
```bash
git clone https://github.com/anthohunt/la-boucle-module
cd <your project>
claude --plugin-dir /path/to/la-boucle-module
```

**B. Installed, through the marketplace file of this repository** (`.claude-plugin/marketplace.json`, marketplace `la-boucle`)
```bash
claude plugin marketplace add /path/to/la-boucle-module      # or: anthohunt/la-boucle-module once published on GitHub
claude plugin install la-boucle-v2@la-boucle
```
then run `/reload-plugins` in an open session. Once the repository is published, the one-step form also works: `/plugin install la-boucle-v2 --marketplace anthohunt/la-boucle-module`. The marketplace points at your clone: the module stops loading if you move or delete it.
See [Create a marketplace](https://code.claude.com/docs/en/plugins/create-marketplace.md) and [Install plugins](https://code.claude.com/docs/en/plugins/install.md).

Then, in the session you want to attach:
```text
/la-boucle-v2 my-worksite       # opens (or resumes) the worksite "my-worksite" in THIS session only
/la-boucle-v2                   # lists existing worksites, or shows what waits for you
/la-boucle-v2 off               # detaches the session
```
On a new worksite the module shows a welcome text and waits for the operator to say they are ready; the control pane opens on the side
(full-screen terminal or Claude Desktop) and the band above the prompt shows the step and what waits for the operator.
Agents launched for a worksite are attached by the environment variable `LA_BOUCLE_CHANTIER=<worksite>`.

### About the generated type declarations
`.claude-plugin/types/` (declarations of the mods API, of the built-in tools and of the connected MCP tools) is **written by Claude Code itself** each time it
loads a mod from a folder you own, and it is **not redistributed** here (it is in `.gitignore`). Load the module once in a session (`claude --plugin-dir .`) and Claude Code lays it
down; `tsconfig.json` extends it for editor type checking. `types/index.d.ts` is the module's **own** contract (the shape of the program's answers) and is part of this repository.

## Settings

Two levels, both optional:

1. **Plugin options** (`userConfig` in `.claude-plugin/plugin.json`, stored by Claude Code in your settings, `/config`): `hote` (empty = the program runs locally, otherwise an SSH destination such as `user@host.example`),
   `programme_distant` (path of `boucle.py` on that host), `python` (default `python3`), `nom_court` (also answer `/la-boucle`).
2. **Program settings** (`boucle-module.json`, model in [`boucle-module.example.json`](boucle-module.example.json)), read by `programme/reglages.py` from `$LA_BOUCLE_REGLAGES`, or `./boucle-module.json`, or `~/.config/la-boucle-module/boucle-module.json`:

| Key | Meaning | Default |
|---|---|---|
| `racine_chantiers` | folder holding one sub-folder per worksite (also `--racine` / `$LA_BOUCLE_V2_RACINE`) | `~/.la-boucle/chantiers` |
| `confirmations` | `dossier` and `uid` of the confirmation channel (a file only that account can write) | `/var/lib/la-boucle-module/confirmations`, uid 0 |
| `releve_comptes` | URL or JSON file with quotas of your Claude accounts; empty = no quota information | empty |
| `comptes` | the Claude accounts that a worksite can plug into its agents (neutral names) | `compte-a`, `compte-b` |
| `agents.lanceur` | command that starts an agent (list of arguments); `agents.dossier_fins` receives `<name>.fin` when an agent ends | empty |
| `notification` | `active` (**false by default**) and `commande` (list; the message is appended as last argument) | disabled |
| `moteur` | command of the engine, given to the agents of steps 3 and 4 | `["python3", "-m", "boucle"]` |
| `bibliotheque` | optional folder shared between worksites (also `$LA_BOUCLE_BIBLIOTHEQUE`) | empty |

**No secret belongs in the repository or in this file.** If your notification command needs a token (a chat bot, a push service), put it in the environment of that command, outside the repository.
Details, the format of the account statement and the confirmation channel: [`docs/settings.md`](docs/settings.md).

## Try it without any model

```bash
python3 exemples/demo.py        # two invented worksites, no model, no network, nothing written outside a temporary folder
python3 -m unittest discover -s programme/tests    # the program's tests (exact binomial computations: several minutes on a small machine)
claude plugin test .            # the mod's 37 tests (TypeScript, in the mods test kit; needs Claude Code, calls no model)
claude plugin validate .        # lists what the mod hooks and calls
# type check (optional): once Claude Code has written .claude-plugin/types by loading the mod in a session,
npx -p typescript tsc --noEmit -p tsconfig.json
```
The two invented cases (`exemples/`): **(1)** a closed decision on fictional support tickets (`URGENT` / `A_VERIFIER` / `RIEN`) and **(2)** an interaction with a fictional task app ("Mini-tâches").

## Layout

| Path | What |
|---|---|
| `hooks/` | the mod: `register.tsx` (pane, band, commands, tools), `textes.ts` (instructions injected into the session), `programme.ts` (bridge to the program) |
| `programme/boucle.py` | the program: state of a worksite in files, one command per gesture (JSON in, JSON out), seals, computations |
| `programme/parcours.json`, `categories.json`, `methode.json` | the generic path (5 steps), need categories, method defaults |
| `programme/statistiques.py`, `confirmer.py`, `reglages.py` | exact binomial statistics, confirmation script, settings |
| `programme/gabarits/`, `usage-interface.md` | templates and the format of a production log |
| `types/index.d.ts` | the module's own contract |
| `tests/`, `programme/tests/` | mod tests and program tests |
| `docs/` | settings, and the history of version 1 |

## Licenses

- **Code** (`hooks/`, `programme/*.py`, `tests/`, `exemples/demo.py`, configuration): [Apache License 2.0](LICENSE), see [`NOTICE`](NOTICE).
- **Texts, templates and documentation** (this README, `docs/`, `programme/parcours.json`, `methode.json`, `categories.json`, `programme/gabarits/`, `programme/usage-interface.md`, `exemples/` data): [Creative Commons Attribution 4.0](LICENSE-docs).
- No third-party source code is included. The failure checklist in `methode.json` is inspired by the paper *Harness^2* (Google Research, arXiv:2610.14224); no text or code of the paper is included.
- Claude Code and its generated type declarations belong to Anthropic and are not redistributed.

Copyright 2026 Anthony Hunt.
