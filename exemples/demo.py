#!/usr/bin/env python3
"""End-to-end demo of the module's program, with no model call and no network.

It drives programme/boucle.py exactly as the Claude Code module does (one command per gesture, JSON on stdin,
JSON on stdout) on two invented worksites:
  1. "tickets-support": a closed decision on fictional support tickets (urgent / to check / nothing);
  2. "mini-taches": an interaction with a fictional task app (adds the sub-step "understand the tool").
Usage: python3 exemples/demo.py [--racine DIR]   (default: a temporary folder, removed at the end)
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

ICI = os.path.dirname(os.path.abspath(__file__))
PROGRAMME = os.path.join(ICI, '..', 'programme', 'boucle.py')


def gesture(racine, commande, **args):
    r = subprocess.run([sys.executable, '-B', PROGRAMME, commande, '--racine', racine], input=json.dumps(args),
                       capture_output=True, text=True, timeout=60)
    out = json.loads(r.stdout.strip().splitlines()[-1])
    if not out['ok']:
        raise SystemExit(f'refused by the program: {out["refus"]}')
    return out['resultat']


def resume(titre, vue):
    et = next(e for e in vue['etapes'] if e['n'] == vue['etape_courante'])
    fait = [s['id'] for e in vue['etapes'] for s in e['sous_etapes'] if s['etat'] == 'validee']
    print(f'--- {titre}\n    step {et["n"]} "{et["titre"]}" ; validated sub-steps: {", ".join(fait) or "none"}')
    print(f'    waiting for the operator: {vue["attend"]["quoi"] if vue["attend"] else "nothing"}')
    print(f'    decisions recorded: {sum(len(s["decisions"]) for e in vue["etapes"] for s in e["sous_etapes"])}'
          f' ; terms in the tree: {len(vue["arbre"]["termes"])} ; rules in the register: {len(vue["registre"])}')


def cas_tickets(racine):
    c = 'tickets-support'
    base = os.path.join(ICI, 'tickets-support')
    gesture(racine, 'ouvrir', chantier=c, session='demo')
    gesture(racine, 'avancer', chantier=c, sous_etape='E1.1', etat='validee', citation="I understood, I am ready")
    cad = json.load(open(os.path.join(base, 'cadrage.json'), encoding='utf-8'))
    for d in cad['decisions']:
        gesture(racine, 'decision', chantier=c, **d)
    gesture(racine, 'ecrire', chantier=c, chemin='etape1/besoin.md', contenu=open(os.path.join(base, 'besoin.md'), encoding='utf-8').read())
    gesture(racine, 'avancer', chantier=c, sous_etape='E1.2', etat='validee', citation='yes, valid')
    gesture(racine, 'categorie', chantier=c, categorie='classique', raison='the model reads a ticket and returns a closed decision', citation='A')
    for t in cad['arbre']:
        gesture(racine, 'terme', chantier=c, **t)
    for r in cad['registre']:
        gesture(racine, 'registre', chantier=c, **r)
    resume('case 1 - tickets-support (closed decision)', gesture(racine, 'etat', chantier=c))
    # A word-for-word quote is mandatory: the program refuses a validation without one.
    refus = subprocess.run([sys.executable, '-B', PROGRAMME, 'avancer', '--racine', racine], input=json.dumps(
        {'chantier': c, 'sous_etape': 'E1.3', 'etat': 'validee'}), capture_output=True, text=True)
    print('    the program refuses a validation without the operator\'s words:', json.loads(refus.stdout)['refus'][:90])


def cas_taches(racine):
    c = 'mini-taches'
    base = os.path.join(ICI, 'mini-taches')
    gesture(racine, 'ouvrir', chantier=c, session='demo')
    gesture(racine, 'avancer', chantier=c, sous_etape='E1.1', etat='validee', citation='ready')
    gesture(racine, 'ecrire', chantier=c, chemin='etape1/besoin.md', contenu='# Need\n\nAn assistant that drives Mini-tâches, a fictional task app.\n')
    gesture(racine, 'avancer', chantier=c, sous_etape='E1.2', etat='validee', citation='yes')
    gesture(racine, 'categorie', chantier=c, categorie='agent-interaction-logicielle', raison='the model drives an app', citation='A')
    gesture(racine, 'ecrire', chantier=c, chemin='etape1/outil/catalogue.tsv', contenu=open(os.path.join(base, 'catalogue.tsv'), encoding='utf-8').read())
    gesture(racine, 'ecrire', chantier=c, chemin='etape1/outil/consignes-reelles.md', contenu=open(os.path.join(base, 'consignes-reelles.md'), encoding='utf-8').read())
    vue = gesture(racine, 'etat', chantier=c)
    ids = [s['id'] for e in vue['etapes'] for s in e['sous_etapes']]
    resume('case 2 - mini-taches (interaction with a task app)', vue)
    print(f'    the category adds sub-step E1.3.1 "understand the tool": {"E1.3.1" in ids} ; catalogue: {vue["catalogue"]["actions"]} actions on {len(vue["catalogue"]["ecrans"])} screens')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--racine')
    o = ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        racine = o.racine or os.path.join(tmp, 'chantiers')
        cas_tickets(racine)
        cas_taches(racine)
        print('chantiers on disk:', ', '.join(sorted(gesture(racine, 'liste')['chantiers'])))
        print('DEMO OK (no model called)')


if __name__ == '__main__':
    main()
