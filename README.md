**English** · [Français](README.fr.md)

# La boucle module

**A Claude Code mod that turns one business task into a small local model that does it alone, checked on test cases no agent ever sees.** It guides you through five steps; a program, not the model, keeps the record and computes the numbers. *La boucle* means “the loop”.

![La boucle explained in 16 minutes, on a real case](docs/demo.webp)

*The method on a real case: Kev, a local agent of 0.8 billion parameters. The video counts the bench and the loop as one step.*

<details>
<summary>Version française de la vidéo</summary>

![La boucle expliquée en 16 minutes](docs/demo.fr.webp)

</details>

## Using it

- **Steps.** Objective, data study, bench, loop, deliverable.
- **One worksite per session.** `/la-boucle-v2 <worksite>` attaches the session: a control pane on the side, a band above the prompt, the step's instructions injected.
- **Decisions word for word.** Each decision is stored with the operator's exact words and its time.
- **Numbers from a program.** Sample sizes, thresholds and the chance of passing come from exact binomial computations.
- **Seals.** A step is sealed only when the operator confirms its fingerprint in a file written by root (by default), which agents cannot write without sudo.
- **Agents and loop.** Steps 3 and 4 hand the work to Claude agents started by your launcher and to [`la-boucle-engine`](https://github.com/anthohunt/la-boucle-engine), whose researcher improves the harness (prompts, rules, code) around the small model.

## Architecture

![One decision: the operator answers, Claude calls a tool of the mod, the mod sends JSON to boucle.py, which writes the decision word for word in the worksite folder, then the pane and band refresh](docs/architecture.svg)

*Numbered arrows: one decision, in order. Yellow tags: where a model is called; the program calls none.*

![Steps 3 and 4: bench builders follow the sealed plan, the operator seals the bench, the loop agent runs the engine, the researcher edits a harness copy, the judge runs the small model on each case and compares the candidate with the champion on the sealed exam](docs/architecture-loop.svg)

<details>
<summary>Schémas en français</summary>

![Un geste : l'opérateur répond, Claude appelle un outil du mod, le mod passe du JSON à boucle.py, qui écrit la décision mot pour mot dans le dossier du chantier, puis le volet et le bandeau se mettent à jour](docs/architecture.fr.svg)

![Étapes 3 et 4 : les fabricants suivent le plan scellé, l'opérateur scelle le banc, l'agent de boucle lance le moteur, le chercheur modifie une copie du harnais, le juge fait tourner le petit modèle sur chaque cas et compare le candidat au champion sur l'examen scellé](docs/architecture-loop.fr.svg)
</details>

## Try it

```bash
git clone https://github.com/anthohunt/la-boucle-module && cd la-boucle-module
python3 exemples/demo.py               # two invented worksites, no model, no network
claude --plugin-dir .                  # then: /la-boucle-v2 my-worksite
```

Or install it, inside Claude Code:

```text
/plugin install la-boucle-v2 --marketplace anthohunt/la-boucle-module
```

Needs Claude Code 2.1.287 or later (mods) and Python 3.10 or later (standard library only). Installing, tests, layout: [`docs/install.md`](docs/install.md). Settings: [`docs/settings.md`](docs/settings.md).

## State

- **Early access** (version 0.1.1). On a real worksite, steps 1 and 2 are sealed and step 3 is under way; steps 3 to 5 are otherwise covered by tests on invented cases.
- Code, on-screen text and method files are in French; the documentation is in English.
- Code under [Apache 2.0](LICENSE), texts under [CC BY 4.0](LICENSE-docs). Nothing is sent to the author: [`docs/privacy.md`](docs/privacy.md).

---

**Anthony Hunt** · [ingevision.cloud](https://ingevision.cloud/?lang=en&p=boucle) · [LinkedIn](https://www.linkedin.com/in/anthony-hunt-3948a9196) · [GitHub](https://github.com/anthohunt)
