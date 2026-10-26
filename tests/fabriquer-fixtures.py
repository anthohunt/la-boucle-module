#!/usr/bin/env python3
"""Fabrique tests/fixtures.ts à partir du VRAI programme : les tests du mod dessinent ce que le programme rend.
Relancer après tout changement de la forme de la vue : python3 tests/fabriquer-fixtures.py"""
import json, os, sys, tempfile
ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ICI, '..', 'programme'))
import boucle  # noqa: E402
import reglages  # noqa: E402

boucle.REGLAGES = dict(reglages.DEFAUTS)   # des réglages fixes, pour que les vues fabriquées ne dépendent pas de la machine

with tempfile.TemporaryDirectory() as r:
    # G2 : une bibliothèque de fixture (jamais la vraie, qui change) : une leçon d'un autre chantier, une piste non prouvée
    bib = os.path.join(r, '_bibliotheque'); os.makedirs(bib)
    with open(os.path.join(bib, 'lecons.jsonl'), 'w') as f:
        for e in ({'id': 'L0001', 'statut': 'etablie', 'chantier': 'tickets', 'categorie': 'classique', 'situation': 's', 'lecon': 'l', 'sens': 'aide'},
                  {'id': 'L0002', 'statut': 'a_prouver', 'chantier': 'email_agenda', 'situation': 's', 'lecon': 'l'}):
            f.write(json.dumps(e, ensure_ascii=False) + '\n')
    os.environ['LA_BOUCLE_BIBLIOTHEQUE'] = bib
    x = lambda c, **a: boucle.executer(c, a, r)
    neuf = x('ouvrir', chantier='essai', session='s1')
    x('avancer', chantier='essai', sous_etape='E1.1', etat='validee', citation="j'ai compris, je suis prêt")
    apres = x('etat', chantier='essai')
    x('decision', chantier='essai', sous_etape='E1.2', resume='Vue globale acceptée', citation="oui, c'est ça", option='A')
    x('ecrire', chantier='essai', chemin='etape1/besoin.md', contenu='# Besoin\n\nUn assistant qui pilote Mini-tâches, une appli de tâches fictive.\n')
    reprise = x('ouvrir', chantier='essai', session='s2')
    # Une étape 1 bien avancée : catégorie, catalogue, cadrage, arbre, relecture (lot 2).
    x('avancer', chantier='essai', sous_etape='E1.2', etat='validee', citation='oui, valide')
    x('categorie', chantier='essai', categorie='agent-interaction-logicielle', raison="pilote l'appli", citation='A')
    x('ecrire', chantier='essai', chemin='etape1/outil/catalogue.tsv', contenu='ecran\taction\tdescription\nListe\tafficher la semaine\tonglet\nListe\trepousser une tâche\t\nOutils\tannuler\tdernière action\n')
    x('decision', chantier='essai', sous_etape='E1.4', point='p01', resume='Une action par consigne', citation='ça donne trois options')
    x('terme', chantier='essai', id='N1', libelle='action / faire répéter', etat='redecoupe', citation='on découpe')
    x('terme', chantier='essai', id='N2A', libelle='consigne claire', parent='N1', etat='liste', liste=['oui', 'non'], citation='liste')
    x('registre', chantier='essai', cle='b1.couche1', valeur=0.9, citation='90', libelle='B1 couche 1')
    x('relecture', chantier='essai', passe=1, relecteur='A', reponses={'ex1': {'N1': 'action'}, 'ex2': {'N1': 'répéter'}})
    x('relecture', chantier='essai', passe=1, relecteur='B', reponses={'ex1': {'N1': 'action'}, 'ex2': {'N1': 'action'}})
    etape1 = x('etat', chantier='essai')
    # Agents, comptes, budget (lot 5).
    releve = {'comptes': [
        {'id': 'compte-a', 'nom': 'Compte A', 'ok': True, 'h5': {'pct': 30}, 'semaine': {'pct': 81}},
        {'id': 'compte-b', 'nom': 'Compte B', 'ok': True, 'h5': {'pct': 10}, 'semaine': {'pct': 31}},
        {'id': 'compte-c', 'nom': 'Compte C', 'ok': True, 'h5': {'pct': 95}, 'semaine': {'pct': 20}}],
        'sessions': [{'id': 'ici:claude-redacteur-def', 'etat': 'travaille', 'action': 'écrit les définitions', 'activite': '2026-10-14T17:55:00Z', 'lien': 'https://example.org/session-x'},
                     {'id': 'ici:claude-relecteur-a', 'etat': 'travaille', 'action': 'relit', 'activite': '2026-10-14T17:00:00Z'}]}
    for cpt in ('compte-b', 'compte-c'):
        x('comptes', chantier='essai', action='brancher', compte=cpt)
    x('agent', chantier='essai', nom='redacteur-def', role='rédacteur des définitions', sous_etape='E1.6', quoi='définitions au propre', releve=releve)
    x('agent', chantier='essai', nom='relecteur-a', role='relecteur A', sous_etape='E1.7', quoi='relecture à l’aveugle', releve=releve)
    x('depense', chantier='essai', action='prevoir', passe='pilote-gen', role='génération', fournisseur='fournisseur-a', modele='petit-modele', cout_estime_eur=0.44, quota_pct=0)
    x('depense', chantier='essai', action='accepter', passe='pilote-gen', citation='ok', montant_accepte_eur=0.5)
    x('depense', chantier='essai', action='depenser', passe='pilote-gen', montant_eur=0.3)
    x('depense', chantier='essai', action='prevoir', passe='arbitre', role='arbitrage', fournisseur='fournisseur-b', modele='grand-modele', cout_estime_eur=0, quota_pct=8)
    suivi = x('suivi', chantier='essai', releve=releve)
    # Scellement (lot 3) : un chantier « scelle » dont l'étape 1 est à sceller, puis scellée.
    conf = tempfile.mkdtemp()
    boucle.CONFIRMATIONS, boucle.UID_CONFIRMATION = conf, os.getuid()
    x('ouvrir', chantier='scelle')
    x('avancer', chantier='scelle', sous_etape='E1.1', etat='validee', citation='prêt')
    for sid in ('E1.2', 'E1.3', 'E1.4', 'E1.5', 'E1.6', 'E1.7'):
        x('avancer', chantier='scelle', sous_etape=sid, etat='validee', citation='ok')
    x('ecrire', chantier='scelle', chemin='etape1/besoin.md', contenu='besoin')
    d = x('sceller', chantier='scelle', etape=1)
    a_sceller = x('etat', chantier='scelle')
    with open(os.path.join(conf, 'scelle-etape1.json'), 'w') as f:
        json.dump({'empreinte': d['empreinte'], 'par': 'operateur'}, f)
    os.chmod(os.path.join(conf, 'scelle-etape1.json'), 0o644)
    scellee = x('etat', chantier='scelle')
    # Étape 2 (lot 6) : notions comprises et calcul des quantités, chiffres d'un exemple.
    x('avancer', chantier='scelle', sous_etape='E2.1', etat='validee', citation='oui')
    x('avancer', chantier='scelle', sous_etape='E2.2', etat='validee', citation='générer')
    x('avancer', chantier='scelle', sous_etape='E2.3', etat='validee', citation='pilote ok')
    x('avancer', chantier='scelle', sous_etape='E2.4', etat='validee', citation="c'est clair, les lots ne se mélangent pas")
    for cle, val in (('barre.qualite', 0.90), ('niveau_vise.qualite', 0.97), ('calcul.tentatives_examen', 3)):
        x('registre', chantier='scelle', cle=cle, valeur=val, citation='x')
    x('ecrire', chantier='scelle', chemin='etape2/pilote/mesures.json', contenu=json.dumps({'unites': 931, 'sorties': {'EXECUTER': 700, 'FAIRE_REPETER': 231}, 'verite': {'relues': 300, 'erreurs': 0}, 'voie': 'generation'}))
    x('calcul', chantier='scelle')
    etape2 = x('etat', chantier='scelle')
    # Étapes 3 et 4 (lot 7) : fabrication, relecture, tableau de la boucle, sollicitation.
    d3 = os.path.join(r, 'scelle', 'etape3'); os.makedirs(d3, exist_ok=True)
    json.dump({'devis_eur': 3.4, 'phases': [{'nom': 'génération', 'etat': 'fini', 'comptes': {'obtenues': 7300, 'jetées': 128}, 'cout_eur': 3.0},
               {'nom': 'étiquetage', 'etat': 'en_cours', 'cout_eur': 0.2}]}, open(os.path.join(d3, 'fabrication.json'), 'w'), ensure_ascii=False)
    with open(os.path.join(d3, 'a-relire.jsonl'), 'w') as f:
        for i in range(3):
            f.write(json.dumps({'id': f'd{i}', 'lot': 'examen', 'donnee': f'affiche la liste de la semaine {i}', 'reponse': 'EXECUTER'}, ensure_ascii=False) + '\n')
    x('relire', chantier='scelle', action='noter', id='d0', verdict='ok')
    json.dump({'termes': [{'id': 'N1', 'libelle': 'sortie', 'couche': 1, 'parent': None, 'etat': 'redecoupe', 'liste': None, 'citation': 'x'},
                          {'id': 'N2A', 'libelle': 'claire', 'couche': 2, 'parent': 'N1', 'etat': 'modele', 'liste': None, 'citation': 'x'}]},
              open(os.path.join(r, 'scelle', 'etape1', 'arbre-definitions.json'), 'w'), ensure_ascii=False)
    x('registre', chantier='scelle', cle='b1.couche1', valeur=0.9, citation='x')
    d4 = os.path.join(r, 'scelle', 'etape4'); os.makedirs(d4, exist_ok=True)
    with open(os.path.join(d4, 'essais.jsonl'), 'w') as f:
        for e in ({'essai': 0, 'strategie': 'depart', 'scores': {'N1': 0.61, 'N2A': 0.7}, 'verdict': 'retenu', 'resume': 'examen à vide', 'vitesse_s': 0.6},
                  {'essai': 1, 'strategie': 'S1', 'scores': {'N1': 0.93, 'N2A': 0.85}, 'verdict': 'champion', 'resume': 'deux questions puis vote', 'detail': 'pose d’abord la question de fond', 'vitesse_s': 0.58,
                   'attribution': [{'modification': 'm1', 'dimension': 'méthode', 'changement': 'deux questions', 'verdict': 'confondu'}, {'modification': 'm2', 'dimension': 'métier', 'changement': 'vote', 'verdict': 'confondu'}]},
                  {'essai': 2, 'strategie': 'S1', 'scores': {'N1': 0.7}, 'verdict': 'arrete_tot', 'partiel': True, 'resume': 'ajoute un exemple'}):
            f.write(json.dumps(e, ensure_ascii=False) + '\n')
    json.dump({'S1': {'nom': 'S1', 'idee': 'découper en deux questions', 'etat': 'active', 'essais': 2, 'indice': 0.96, 'chances': 0.4},
               'depart': {'nom': 'départ', 'idee': 'harnais de départ', 'etat': 'en_pause', 'essais': 1}},
              open(os.path.join(d4, 'strategies.json'), 'w'), ensure_ascii=False)
    json.dump({'machines': [{'nom': 'poste-1', 'carte': 'GPU 24 Go', 'activite': 'essai 3', 'donnees': 412, 'vitesse': 90, 'puissance_w': 310, 'cout_eur': 0.12},
                            {'nom': 'poste-2', 'activite': 'hors ligne', 'donnees': 0}],
               'total': {'donnees': 412, 'vitesse': 90, 'minutes_par_mesure': 9}, 'mesures': [{'essai': 3, 'strategie': 'S1', 'faites': 412, 'total': 800, 'etat': 'en_cours'}]},
              open(os.path.join(d4, 'machines.json'), 'w'), ensure_ascii=False)
    with open(os.path.join(d4, 'registre-budget-principale.jsonl'), 'w') as f:   # G5 : registre de dépense d'une lignée
        for e in ({'identite': {'chantier': 'scelle', 'lignee': 'principale'}, 'budget': {'sessions_recherche': 30}, 'ouvert': '2026-01-01T00:00:00Z'},
                  {'sorte': 'session', 'role': 'recherche', 'etiquette': 'developpe noeud 1#1'}, {'sorte': 'mesure', 'role': 'entrainement', 'etiquette': '/m/ent-r1n1.json'},
                  {'sorte': 'appels', 'role': 'petit modele', 'etiquette': 'appels:/m/ent-r1n1.json', 'appels': 1200, 'n': 600}):
            f.write(json.dumps(e, ensure_ascii=False) + '\n')
    with open(os.path.join(d4, 'audits-portes.jsonl'), 'w') as f:   # G8 : la porte 1 fermée par le biais vers le refus
        f.write(json.dumps({'a': '2026-01-01T00:00:00Z', 'porte': '1', 'version': 'essai 1', 'passe': False, 'echecs': [{'id': 'A3', 'preuve': 'FAIRE_REPETER +6 pts, EXECUTER -4 pts'}]}, ensure_ascii=False) + '\n')
    du = os.path.join(r, 'scelle', 'etape5', 'usage'); os.makedirs(du, exist_ok=True)   # G7 : la boucle d'usage après livraison
    json.dump({'generation': 1, 'consultations': 1}, open(os.path.join(du, 'etat.json'), 'w'))
    for nom, lignes in (('arrivees.jsonl', [{'id': f'c{i}'} for i in range(3)]), ('scellee.jsonl', [{'id': 'c0', 'generation': 1}, {'id': 'c1', 'generation': 1}]),
                        ('etiquettes.jsonl', [{'id': 'c0', 'etiquette': 'EXECUTER'}]), ('sonde.jsonl', [{'id': 'c2'}]),
                        ('jugements.jsonl', [{'modification': 'reconnaître « réduis »', 'verdict': 'non_jugeable', 'pourquoi': 'part scellée étiquetée trop petite : 1 sur 200'}])):
        with open(os.path.join(du, nom), 'w') as f:
            for e in lignes:
                f.write(json.dumps(e, ensure_ascii=False) + '\n')
    with open(os.path.join(d4, 'sollicitations.jsonl'), 'w') as f:
        f.write(json.dumps({'id': 'plateau-1', 'quoi': 'plateau sous la porte 1', 'statut': 'ouverte'}, ensure_ascii=False) + '\n')
    etapes34 = x('etat', chantier='scelle')
    donnee = x('relire', chantier='scelle')['donnee']
    def net(v):  # chemins et dates stables
        s = json.dumps(v, ensure_ascii=False).replace(r, '/data/chantiers')
        return s
    out = ['// Fabriqué par tests/fabriquer-fixtures.py depuis le programme réel ; ne pas éditer à la main.',
           "import type { Suivi, Vue } from '../types'", '',
           f'export const VUE_NEUF: Vue = {net(neuf)}', '',
           f'export const VUE_APRES_BIENVENUE: Vue = {net(apres)}', '',
           f'export const VUE_REPRISE: Vue = {net(reprise)}', '',
           f'export const VUE_ETAPE1: Vue = {net(etape1)}', '',
           f'export const SUIVI: Suivi = {net(suivi)}', '',
           f'export const VUE_A_SCELLER: Vue = {net(a_sceller)}', '',
           f'export const VUE_SCELLEE: Vue = {net(scellee)}', '',
           f'export const VUE_ETAPE2: Vue = {net(etape2)}', '',
           f'export const VUE_ETAPES34: Vue = {net(etapes34)}', '',
           f'export const DONNEE_A_RELIRE = {net(donnee)}', '']
    open(os.path.join(ICI, 'fixtures.ts'), 'w', encoding='utf-8').write('\n'.join(out))
import shutil; shutil.rmtree(conf, ignore_errors=True)
print("fixtures.ts écrit")
