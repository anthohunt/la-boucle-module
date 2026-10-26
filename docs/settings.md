# Settings of the La boucle module

Everything that depends on your machine is a setting. Nothing is read from a hard-coded path and nothing secret is stored in the repository.

## Where the program reads its settings
`programme/reglages.py` takes the first file that exists: `$LA_BOUCLE_REGLAGES`, then `boucle-module.json` at the root of the repository (ignored by git),
then `~/.config/la-boucle-module/boucle-module.json`. A file only needs the keys it changes; the complete model is `boucle-module.example.json`.
Paths accept `~`. When a command is run with `sudo` (the confirmation script), `~` becomes root's home: use absolute paths, and `sudo -E`.

## Account statement (`releve_comptes`)
An URL (`http://` or `https://`) or a path of a JSON file, in this shape (all fields optional except `id`):
```json
{
  "comptes": [
    {"id": "compte-a", "nom": "Compte A", "ok": true, "h5": {"pct": 30}, "semaine": {"pct": 81}},
    {"id": "compte-b", "nom": "Compte B", "ok": true, "h5": {"pct": 10}, "semaine": {"pct": 31}}
  ],
  "sessions": [
    {"id": "host:claude-redacteur-def", "etat": "travaille", "action": "writes the definitions",
     "activite": "2026-01-01T10:00:00Z", "lien": "https://example.org/session"}
  ]
}
```
`h5` and `semaine` are the use of the 5-hour and weekly quotas in percent. When an agent is created, the program chooses among the accounts plugged into the worksite
the one with the most weekly quota left, leaving aside accounts above 85 % (week) or 90 % (5 hours). With `releve_comptes` empty, the accounts of `comptes` are known without any quota.
A session `id` ends with the agent's session name (`claude-<agent name>` by default).

## Launching agents (`agents.lanceur`)
The module does not start agents itself: the operator's launcher does. The command is given in the instructions (`<launcher> <name> <instruction file>`); the agent must be started with
`LA_BOUCLE_CHANTIER=<worksite>` in its environment, which attaches its session to the worksite with the role "agent". At the end of an agent, the launcher writes
`<agents.dossier_fins>/<name>.fin` containing `<exit code> <time>`; the program then marks the agent finished (code 0) or broken down (other code), and can restart a broken agent
(at most 3 times, 15 minutes apart) with the `relance` command stored in its record. Stopping an agent from the pane runs `tmux kill-session -t =<session>` on its exact session name.

## Notification (`notification`)
Off by default. When `active` is true and `commande` is a list such as `["/usr/local/bin/my-notifier"]`, the program runs that command with the message as last argument (at most 600 characters)
when an agent finishes or breaks down while the operator has been away for 15 minutes. **Never write a token in `boucle-module.json`**; give it to your notifier through its own environment or file.

## Confirmation channel (`confirmations`)
Sealing a step is not decided by the model: the program writes a request with a fingerprint (`etapeN/demande-scellement.json`), and the step is sealed only when a confirmation file
`<dossier>/<worksite>-etape<N>.json` containing the same fingerprint exists, **owned by the account `uid` and not writable by anyone else**. By default that account is root, so that agents
(which run as a normal user) cannot confirm for the operator:
```bash
sudo -E python3 programme/confirmer.py <worksite> <step> <fingerprint>
```
Any other channel (a phone application, a button) can write the same file, provided it runs under the trusted account.

## Engine command (`moteur`)
Given to the agents of steps 3 and 4 (`python3 -m boucle`, sub-commands `sceller`, `verifier`, `noter`, `run`, `tableau` of the repository `la-boucle-engine`).
