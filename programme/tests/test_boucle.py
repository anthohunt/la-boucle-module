"""Tests du programme du module La boucle v2 (lot 1 : socle). Lancer : python3 -m unittest discover -s programme/tests"""
import io
import json
import math
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import boucle  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.racine = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def run_(self, commande, **args):
        return boucle.executer(commande, args, self.racine)

    def refus(self, commande, **args):
        with self.assertRaises(boucle.Refus) as r:
            self.run_(commande, **args)
        return str(r.exception)

    def journal(self, nom='essai'):
        return boucle.lire_lignes(os.path.join(self.racine, nom, 'journal.jsonl'))


class Ouvrir(Base):
    def test_chantier_neuf_bienvenue_en_cours(self):
        v = self.run_('ouvrir', chantier='essai', session='s1')
        self.assertTrue(v['neuf'])
        e1 = v['etapes'][0]
        self.assertEqual(e1['sous_etapes'][0]['id'], 'E1.1')
        self.assertEqual(e1['sous_etapes'][0]['etat'], 'en_cours')
        self.assertEqual(v['attend']['sous_etape'], 'E1.1')
        self.assertEqual([e['etat'] for e in v['etapes']], ['ouverte', 'fermee', 'fermee', 'fermee', 'fermee'])
        self.assertTrue(os.path.exists(os.path.join(self.racine, 'essai', 'chantier.json')))
        self.assertEqual(self.journal()[0]['type'], 'chantier_cree')

    def test_cinq_etapes_et_sous_etapes_de_categorie_cachees(self):
        v = self.run_('ouvrir', chantier='essai')
        self.assertEqual(len(v['etapes']), 5)
        ids = [s['id'] for s in v['etapes'][0]['sous_etapes']]
        self.assertNotIn('E1.3.1', ids)
        self.assertEqual(ids, ['E1.1', 'E1.2', 'E1.3', 'E1.4', 'E1.5', 'E1.6', 'E1.7', 'E1.8'])

    def test_reprise_lit_les_fichiers(self):
        self.run_('ouvrir', chantier='essai', session='s1')
        self.run_('avancer', chantier='essai', sous_etape='E1.1', etat='validee', citation="j'ai compris, je suis prêt")
        v = self.run_('ouvrir', chantier='essai', session='s2')
        self.assertFalse(v['neuf'])
        self.assertEqual(v['attend']['sous_etape'], 'E1.2')
        self.assertEqual(self.journal()[-1]['type'], 'chantier_repris')

    def test_nom_invalide(self):
        self.assertIn('invalide', self.refus('ouvrir', chantier='../etc'))
        self.assertIn('invalide', self.refus('ouvrir', chantier='Taches Demo'))


class Avancer(Base):
    def setUp(self):
        super().setUp()
        self.run_('ouvrir', chantier='essai')

    def test_validation_exige_la_citation(self):
        self.assertIn('mot pour mot', self.refus('avancer', chantier='essai', sous_etape='E1.1', etat='validee'))

    def test_validation_ouvre_la_suivante(self):
        r = self.run_('avancer', chantier='essai', sous_etape='E1.1', etat='validee', citation='prêt')
        self.assertEqual(r['ouverte'], 'E1.2')
        v = self.run_('etat', chantier='essai')
        se = {s['id']: s for s in v['etapes'][0]['sous_etapes']}
        self.assertEqual(se['E1.1']['etat'], 'validee')
        self.assertEqual(se['E1.1']['citation'], 'prêt')
        self.assertEqual(se['E1.2']['etat'], 'en_cours')

    def test_a_valider_passe_en_tete(self):
        self.run_('avancer', chantier='essai', sous_etape='E1.1', etat='validee', citation='prêt')
        self.run_('avancer', chantier='essai', sous_etape='E1.2', etat='a_valider')
        v = self.run_('etat', chantier='essai')
        self.assertEqual(v['attend']['quoi'], "Valider : Le besoin, jusqu'à une vue globale")

    def test_scelle_refuse_par_avancer(self):
        self.assertIn('sceller', self.refus('avancer', chantier='essai', sous_etape='E1.1', etat='scellee'))

    def test_etape_fermee(self):
        self.assertIn("n'est pas encore ouverte", self.refus('avancer', chantier='essai', sous_etape='E2.1', etat='en_cours'))

    def test_sous_etape_de_categorie_refusee_sans_categorie(self):
        self.assertIn('autre catégorie', self.refus('avancer', chantier='essai', sous_etape='E1.3.1', etat='en_cours'))


class Decisions(Base):
    def setUp(self):
        super().setUp()
        self.run_('ouvrir', chantier='essai')

    def test_decision_mot_pour_mot_et_datee(self):
        r = self.run_('decision', chantier='essai', sous_etape='E1.2', resume='Besoin compris', citation='oui, c’est ça', option='A')
        self.assertEqual(r['decision']['citation'], 'oui, c’est ça')
        v = self.run_('etat', chantier='essai')
        d = v['etapes'][0]['sous_etapes'][1]['decisions'][0]
        self.assertEqual(d['citation'], 'oui, c’est ça')
        self.assertTrue(d['a'].endswith('Z'))
        self.assertEqual(self.journal()[-1]['type'], 'decision')

    def test_citation_vide_refusee(self):
        self.assertIn('mots exacts', self.refus('decision', chantier='essai', sous_etape='E1.2', resume='x', citation=' '))

    def test_cadrage_points_et_progression(self):
        r = self.run_('decision', chantier='essai', sous_etape='E1.4', point='p01', resume='Le modèle décide une action', citation='ça donne trois options')
        self.assertEqual(r['points'], {'tranches': 1, 'total': 16})
        with open(os.path.join(self.racine, 'essai', 'etape1', 'cadrage.json'), encoding='utf-8') as f:
            cadrage = json.load(f)
        self.assertEqual(cadrage['points'][0]['citation'], 'ça donne trois options')
        self.assertEqual(cadrage['points'][1]['etat'], 'ouvert')
        self.assertIn('Point inconnu', self.refus('decision', chantier='essai', sous_etape='E1.4', point='p99', resume='x', citation='y'))

    def test_option_autre_chose(self):
        r = self.run_('decision', chantier='essai', sous_etape='E1.2', resume='x', citation='autre idée', option='autre')
        self.assertEqual(r['decision']['option'], 'autre')
        self.assertIn('Option inconnue', self.refus('decision', chantier='essai', sous_etape='E1.2', resume='x', citation='y', option='Z'))


class Categorie(Base):
    def setUp(self):
        super().setUp()
        self.run_('ouvrir', chantier='essai')

    def test_agent_interaction_logicielle_ajoute_comprendre_l_outil(self):
        r = self.run_('categorie', chantier='essai', categorie='agent-interaction-logicielle', raison='pilote une appli', citation='A')
        self.assertEqual(r['ajoutees'], ['E1.3.1'])
        ids = [s['id'] for s in self.run_('etat', chantier='essai')['etapes'][0]['sous_etapes']]
        self.assertEqual(ids[3], 'E1.3.1')

    def test_aucune_suit_le_classique_et_note_le_cas(self):
        r = self.run_('categorie', chantier='essai', categorie='aucune', raison='rien ne colle', citation='C')
        self.assertEqual(r['categorie']['id'], 'classique')
        self.assertTrue(os.path.exists(os.path.join(self.racine, 'essai', 'etape1', 'cas-futures-categories.jsonl')))

    def test_inconnue(self):
        self.assertIn('Catégorie inconnue', self.refus('categorie', chantier='essai', categorie='xyz', citation='A'))


class Sorties(Base):
    def setUp(self):
        super().setUp()
        self.run_('ouvrir', chantier='essai')

    def test_ecrire_garde_les_versions(self):
        r1 = self.run_('ecrire', chantier='essai', chemin='etape1/besoin.md', contenu='v1')
        self.assertEqual(len(r1['empreinte']), 64)
        r2 = self.run_('ecrire', chantier='essai', chemin='etape1/besoin.md', contenu='v2', pourquoi='précision')
        self.assertIsNotNone(r2['version_precedente'])
        with open(os.path.join(self.racine, 'essai', r2['version_precedente']), encoding='utf-8') as f:
            self.assertEqual(f.read(), 'v1')
        self.assertTrue(self.run_('ecrire', chantier='essai', chemin='etape1/besoin.md', contenu='v2')['inchange'])
        v = self.run_('etat', chantier='essai')
        sortie = v['etapes'][0]['sous_etapes'][1]['sorties'][0]
        self.assertTrue(sortie['existe'])
        self.assertEqual(self.run_('lire', chantier='essai', chemin='etape1/besoin.md')['contenu'], 'v2')

    def test_chemins_refuses(self):
        for mauvais in ('../x', 'chantier.json', 'etape1/../../x', 'etape9/x', 'etape1/.versions/x'):
            self.refus('ecrire', chantier='essai', chemin=mauvais, contenu='x')


class Rouvrir(Base):
    def test_rouvrir_compte_et_journalise(self):
        self.run_('ouvrir', chantier='essai')
        self.run_('avancer', chantier='essai', sous_etape='E1.1', etat='validee', citation='prêt')
        self.assertIn('pourquoi', self.refus('rouvrir', chantier='essai', sous_etape='E1.1'))
        r = self.run_('rouvrir', chantier='essai', sous_etape='E1.1', raison='je veux revoir')
        self.assertEqual(r['avant'], 'validee')
        self.assertEqual(self.journal()[-1]['type'], 'sous_etape_rouverte')

    def test_rouvrir_referme_la_suivante_sans_decision(self):
        self.run_('ouvrir', chantier='essai')
        self.run_('avancer', chantier='essai', sous_etape='E1.1', etat='validee', citation='prêt')
        etats = lambda: {x['id']: x['etat'] for x in self.run_('etat', chantier='essai')['etapes'][0]['sous_etapes']}
        self.assertEqual(etats()['E1.2'], 'en_cours')
        self.run_('rouvrir', chantier='essai', sous_etape='E1.1', raison='validée à tort')
        self.assertEqual((etats()['E1.1'], etats()['E1.2']), ('en_cours', 'a_faire'))


class Registre(Base):
    def test_seuil_propose_avec_historique(self):
        self.run_('ouvrir', chantier='essai')
        self.run_('registre', chantier='essai', cle='qualite.min', valeur=0.9, statut='propose', citation='90 %', sous_etape='E1.4')
        r = self.run_('registre', chantier='essai', cle='qualite.min', valeur=0.92, statut='propose', citation='plutôt 92')
        self.assertEqual(r['regle']['historique'][0]['valeur'], 0.9)
        self.assertIn('Statut refusé', self.refus('registre', chantier='essai', cle='x', valeur=1, statut='scelle', citation='a'))


class Arbre(Base):
    def setUp(self):
        super().setUp()
        self.run_('ouvrir', chantier='essai')

    def test_couches_par_parent_et_seuils(self):
        self.run_('terme', chantier='essai', id='N1', libelle='risque / à vérifier / pas de risque', etat='redecoupe', citation='on découpe')
        self.run_('terme', chantier='essai', id='N2A', libelle='signal', parent='N1', etat='redecoupe', citation='oui')
        r = self.run_('terme', chantier='essai', id='N3A', libelle='fournisseur', parent='N2A', etat='liste', liste=['Orion', 'Intel'], citation='la liste des 94')
        self.assertEqual(r['terme']['couche'], 3)
        self.run_('terme', chantier='essai', id='N3B', libelle='événement actif', parent='N2A', etat='modele', citation='laisse au modèle')
        self.run_('registre', chantier='essai', cle='b1.couche1', valeur=0.9, citation='90')
        v = self.run_('etat', chantier='essai')
        self.assertEqual([t['id'] for t in v['arbre']['termes']], ['N1', 'N2A', 'N3A', 'N3B'])
        self.assertEqual(v['arbre']['seuils']['1'], {'b1': 0.9, 'b2': None})
        self.assertTrue(os.path.exists(os.path.join(self.racine, 'essai', 'etape1', 'arbre-definitions.json')))

    def test_refus(self):
        self.assertIn('Parent inconnu', self.refus('terme', chantier='essai', id='N2A', libelle='x', parent='N1'))
        self.assertIn('liste', self.refus('terme', chantier='essai', id='N1', libelle='x', etat='liste', citation='a'))
        self.assertIn('citation', self.refus('terme', chantier='essai', id='N1', libelle='x', etat='modele'))

    def test_historique_garde_l_ancien(self):
        self.run_('terme', chantier='essai', id='N1', libelle='x', etat='modele', citation='a')
        r = self.run_('terme', chantier='essai', id='N1', libelle='x', etat='redecoupe', citation='b')
        self.assertEqual(r['terme']['historique'][0]['etat'], 'modele')


class Relecture(Base):
    def setUp(self):
        super().setUp()
        self.run_('ouvrir', chantier='essai')

    def test_accord_par_critere_et_desaccords(self):
        a = {'ex1': {'N1': 'risque', 'N2A': 'oui'}, 'ex2': {'N1': 'pas de risque', 'N2A': 'non'}}
        b = {'ex1': {'N1': 'Risque', 'N2A': 'non'}, 'ex2': {'N1': 'pas de risque', 'N2A': 'non'}}
        r1 = self.run_('relecture', chantier='essai', passe=1, relecteur='A', reponses=a)
        self.assertFalse(r1['accord']['complet'])
        r2 = self.run_('relecture', chantier='essai', passe=1, relecteur='B', reponses=b)
        acc = r2['accord']
        self.assertEqual(acc['par_critere']['N1'], {'accord': 1.0, 'exemples': 2, 'garde': True})
        self.assertEqual(acc['par_critere']['N2A']['accord'], 0.5)
        self.assertFalse(acc['par_critere']['N2A']['garde'])
        self.assertEqual(acc['desaccords'], [{'exemple': 'ex1', 'critere': 'N2A', 'A': 'oui', 'B': 'non'}])
        v = self.run_('etat', chantier='essai')
        self.assertEqual(v['relecture'][0]['desaccords'], 1)

    def test_aveugle_un_relecteur_ne_rend_qu_une_fois(self):
        self.run_('relecture', chantier='essai', passe=1, relecteur='A', reponses={'e': {'k': 1}})
        self.assertIn('déjà rendu', self.refus('relecture', chantier='essai', passe=1, relecteur='A', reponses={'e': {'k': 1}}))
        self.run_('relecture', chantier='essai', passe=1, relecteur='B', reponses={'e': {'k': 1}})
        self.assertIn('deux relecteurs', self.refus('relecture', chantier='essai', passe=1, relecteur='C', reponses={'e': {'k': 1}}))
        self.assertIn('Passe 1 ou 2', self.refus('relecture', chantier='essai', passe=3, relecteur='E', reponses={'e': {'k': 1}}))


class Catalogue(Base):
    def test_catalogue_ecran_par_ecran(self):
        self.run_('ouvrir', chantier='essai')
        self.run_('ecrire', chantier='essai', chemin='etape1/outil/catalogue.tsv',
                  contenu='ecran\taction\tdescription\nListe\tafficher la semaine\tonglet\nListe\trepousser une tâche\t\nOutils\tannuler\tdernière action\n')
        cat = self.run_('etat', chantier='essai')['catalogue']
        self.assertEqual(cat['actions'], 3)
        self.assertEqual([e['ecran'] for e in cat['ecrans']], ['Liste', 'Outils'])


class Scellement(Base):
    def setUp(self):
        super().setUp()
        self.conf = tempfile.TemporaryDirectory()
        self._c, self._u = boucle.CONFIRMATIONS, boucle.UID_CONFIRMATION
        boucle.CONFIRMATIONS, boucle.UID_CONFIRMATION = self.conf.name, os.getuid()
        self.run_('ouvrir', chantier='essai')
        self.run_('avancer', chantier='essai', sous_etape='E1.1', etat='validee', citation='prêt')
        for sid in ('E1.2', 'E1.3', 'E1.4', 'E1.5', 'E1.6', 'E1.7'):
            self.run_('decision', chantier='essai', sous_etape=sid, resume=f'décision {sid}', citation=f'oui {sid}')
            self.run_('avancer', chantier='essai', sous_etape=sid, etat='validee', citation=f'validé {sid}')
        self.run_('ecrire', chantier='essai', chemin='etape1/besoin.md', contenu='besoin')
        self.run_('registre', chantier='essai', cle='qualite.min', valeur=0.9, citation='90')

    def tearDown(self):
        boucle.CONFIRMATIONS, boucle.UID_CONFIRMATION = self._c, self._u
        self.conf.cleanup()
        super().tearDown()

    def confirmer(self, empreinte, etape=1, mode=0o644):
        chemin = os.path.join(self.conf.name, f'essai-etape{etape}.json')
        with open(chemin, 'w') as f:
            json.dump({'empreinte': empreinte, 'par': 'operateur', 'canal': 'test'}, f)
        os.chmod(chemin, mode)

    def test_refus_si_sous_etape_ouverte(self):
        self.run_('rouvrir', chantier='essai', sous_etape='E1.5', raison='revoir')
        self.assertIn('E1.5', self.refus('sceller', chantier='essai', etape=1))

    def test_la_derniere_sous_etape_ne_se_valide_que_par_le_scellement(self):
        self.assertIn('scellement', self.refus('avancer', chantier='essai', sous_etape='E1.8', etat='validee', citation='ok'))

    def test_a_sceller_tant_que_non_confirme_puis_verrou(self):
        d = self.run_('sceller', chantier='essai', etape=1)
        self.assertEqual(len(d['empreinte']), 64)
        self.assertEqual(d['regles_proposees'], {'qualite.min': 0.9})
        self.assertEqual(d['regles_scellees'], {})
        v = self.run_('etat', chantier='essai')
        self.assertEqual(v['etapes'][0]['etat'], 'a_sceller')
        self.assertIn('téléphone', v['attend']['quoi'])
        self.confirmer(d['empreinte'])
        v = self.run_('etat', chantier='essai')
        self.assertEqual(v['etapes'][0]['etat'], 'scellee')
        self.assertEqual(v['etapes'][1]['etat'], 'ouverte')
        self.assertEqual(v['attend']['sous_etape'], 'E2.1')
        self.assertTrue(all(s['etat'] == 'scellee' for s in v['etapes'][0]['sous_etapes']))
        besoin = os.path.join(self.racine, 'essai', 'etape1', 'besoin.md')
        self.assertFalse(os.stat(besoin).st_mode & 0o222)
        self.assertIn('scellé', self.refus('ecrire', chantier='essai', chemin='etape1/besoin.md', contenu='autre'))
        self.assertEqual(v['registre']['qualite.min']['statut'], 'propose')
        with open(os.path.join(self.racine, 'essai', 'etape1', 'scelle.json')) as f:
            scelle = json.load(f)
        self.assertEqual(scelle['confirmation']['par'], 'operateur')
        self.assertIn('scellement_confirme', [ev['type'] for ev in self.journal()])

    def test_confirmation_hors_canal_ou_autre_empreinte_refusee(self):
        d = self.run_('sceller', chantier='essai', etape=1)
        self.confirmer('0' * 64)
        self.assertEqual(self.run_('etat', chantier='essai')['etapes'][0]['etat'], 'a_sceller')
        self.confirmer(d['empreinte'], mode=0o666)
        self.assertEqual(self.run_('etat', chantier='essai')['etapes'][0]['etat'], 'a_sceller')
        boucle.UID_CONFIRMATION = 0 if os.getuid() != 0 else 1
        self.confirmer(d['empreinte'])
        self.assertEqual(self.run_('etat', chantier='essai')['etapes'][0]['etat'], 'a_sceller')
        refus = [ev for ev in self.journal() if ev['type'] == 'confirmation_refusee']
        self.assertEqual(len(refus), 3)

    def test_document_change_apres_la_demande(self):
        d = self.run_('sceller', chantier='essai', etape=1)
        with open(os.path.join(self.racine, 'essai', 'etape1', 'besoin.md'), 'w') as f:
            f.write('modifié en douce')
        self.confirmer(d['empreinte'])
        self.assertEqual(self.run_('etat', chantier='essai')['etapes'][0]['etat'], 'ouverte')

    def test_rouvrir_une_etape_scellee_relance_les_suivantes(self):
        d = self.run_('sceller', chantier='essai', etape=1)
        self.confirmer(d['empreinte'])
        self.run_('etat', chantier='essai')
        self.run_('avancer', chantier='essai', sous_etape='E2.1', etat='a_valider')
        self.assertIn('confirme=true', self.refus('rouvrir_etape', chantier='essai', etape=1, raison='x', citation='oui rouvre'))
        r = self.run_('rouvrir_etape', chantier='essai', etape=1, raison='un critère change', citation='oui rouvre', confirme=True)
        self.assertEqual(r['relancees'], [2])
        v = self.run_('etat', chantier='essai')
        self.assertEqual([e['etat'] for e in v['etapes'][:2]], ['ouverte', 'fermee'])
        self.assertEqual(v['etapes'][1]['sous_etapes'][0]['etat'], 'a_faire')
        self.run_('ecrire', chantier='essai', chemin='etape1/besoin.md', contenu='v2')
        self.assertEqual(self.journal()[-1]['type'], 'sortie_ecrite')


class ScellementEtape2(Base):
    def test_seuils_proposes_scelles_a_l_etape_2_et_probleme_majeur(self):
        conf = tempfile.TemporaryDirectory()
        c0, u0 = boucle.CONFIRMATIONS, boucle.UID_CONFIRMATION
        boucle.CONFIRMATIONS, boucle.UID_CONFIRMATION = conf.name, os.getuid()
        try:
            self.run_('ouvrir', chantier='essai')
            ch = boucle.Chantier(self.racine, 'essai')
            c = ch.lire()
            for s in boucle.visibles(c):
                c['sous_etapes'][s['id']] = {'etat': 'validee'}
            c['etapes']['1'] = {'etat': 'scellee'}
            c['etapes']['2'] = {'etat': 'ouverte'}
            c['sous_etapes']['E2.16'] = {'etat': 'en_cours'}
            ch.enregistrer(c)
            self.run_('registre', chantier='essai', cle='barre.qualite', valeur=0.9, citation='90')
            self.run_('ecrire', chantier='essai', chemin='etape2/donnee.md', contenu='donnée')
            self.run_('ecrire', chantier='essai', chemin='etape2/verification.json',
                      contenu=json.dumps({'points': [{'id': 'M1', 'niveau': 'majeur', 'decision': None}]}))
            self.assertIn('M1', self.refus('sceller', chantier='essai', etape=2))
            self.run_('ecrire', chantier='essai', chemin='etape2/verification.json',
                      contenu=json.dumps({'points': [{'id': 'M1', 'niveau': 'majeur', 'decision': 'ecarte'}]}))
            d = self.run_('sceller', chantier='essai', etape=2)
            self.assertEqual(d['regles_scellees'], {'barre.qualite': {'valeur': 0.9, 'citation': '90'}})
            with open(os.path.join(conf.name, 'essai-etape2.json'), 'w') as f:
                json.dump({'empreinte': d['empreinte']}, f)
            os.chmod(os.path.join(conf.name, 'essai-etape2.json'), 0o644)
            v = self.run_('etat', chantier='essai')
            self.assertEqual(v['registre']['barre.qualite']['statut'], 'scelle')
            self.assertIn('scellée', self.refus('registre', chantier='essai', cle='barre.qualite', valeur=0.8, citation='x'))
        finally:
            boucle.CONFIRMATIONS, boucle.UID_CONFIRMATION = c0, u0
            conf.cleanup()


class Mesures(Base):
    def test_durees_attente_frictions_jetons(self):
        self.run_('ouvrir', chantier='essai')
        ch = boucle.Chantier(self.racine, 'essai')
        j = ch.chemin('journal.jsonl')
        evs = [
            {'a': '2026-10-14T10:00:00Z', 'type': 'sous_etape', 'sous_etape': 'E1.2', 'etat': 'en_cours'},
            {'a': '2026-10-14T10:01:00Z', 'type': 'message_utilisateur', 'sous_etape': 'E1.2', 'longueur': 40, 'temps_reponse_s': 30},
            {'a': '2026-10-14T10:02:00Z', 'type': 'tour_termine', 'jetons_entree': 100, 'jetons_sortie': 50, 'jetons_cache_lus': 1000, 'jetons_cache_ecrits': 0},
            {'a': '2026-10-14T10:03:00Z', 'type': 'decision', 'sous_etape': 'E1.2', 'option': 'autre'},
            {'a': '2026-10-14T10:03:30Z', 'type': 'decision', 'sous_etape': 'E1.2', 'option': 'A'},
            {'a': '2026-10-14T10:04:00Z', 'type': 'sous_etape', 'sous_etape': 'E1.2', 'etat': 'a_valider'},
            {'a': '2026-10-14T10:10:00Z', 'type': 'message_utilisateur', 'sous_etape': 'E1.2', 'longueur': 3, 'temps_reponse_s': 360},
            {'a': '2026-10-14T10:10:00Z', 'type': 'sous_etape', 'sous_etape': 'E1.2', 'etat': 'validee'},
            {'a': '2026-10-14T10:11:00Z', 'type': 'sous_etape_rouverte', 'sous_etape': 'E1.2', 'raison': 'pas clair'},
            {'a': '2026-10-14T10:12:00Z', 'type': 'agent_panne', 'sous_etape': 'E1.2'},
            {'a': '2026-10-14T10:13:00Z', 'type': 'truc_inconnu'},
        ]
        with open(j, 'w') as f:
            for ev in evs:
                f.write(json.dumps(ev) + '\n')
        m = boucle.mesures(ch, ch.lire(), fin='2026-10-14T10:21:00Z')
        x = m['sous_etapes']['E1.2']
        self.assertEqual(x['duree_s'], 600 + 600)
        self.assertTrue(x['en_cours'])
        self.assertEqual(x['attente_utilisateur_s'], 360)
        self.assertEqual(x['echanges'], 2)
        self.assertEqual(x['temps_reponse_median_s'], 360)
        self.assertEqual(x['part_autre_chose'], 0.5)
        self.assertEqual(x['reouvertures'], 1)
        self.assertEqual(x['raisons_reouverture'], ['pas clair'])
        self.assertEqual((x['jetons_entree'], x['jetons_sortie']), (1100, 50))
        self.assertEqual(x['incidents'], 1)
        self.assertEqual(m['etapes']['1']['decisions'], 2)
        self.assertEqual(m['autres'], 1)

    def test_non_mesure_reste_none(self):
        self.run_('ouvrir', chantier='essai')
        m = self.run_('mesures', chantier='essai')
        self.assertIsNone(m['sous_etapes']['E1.1']['attente_utilisateur_s'])
        self.assertIsNone(m['sous_etapes']['E1.1']['jetons_entree'])


RELEVE = {'comptes': [
    {'id': 'compte-a', 'nom': 'Compte A', 'ok': True, 'h5': {'pct': 30}, 'semaine': {'pct': 81}},
    {'id': 'compte-b', 'nom': 'Compte B', 'ok': True, 'h5': {'pct': 10}, 'semaine': {'pct': 31}},
    {'id': 'compte-c', 'nom': 'Compte C', 'ok': True, 'h5': {'pct': 95}, 'semaine': {'pct': 20}},
], 'sessions': [
    {'id': 'ici:claude-redacteur-def', 'etat': 'travaille', 'action': 'écrit les définitions', 'activite': '2026-10-14T16:00:00Z', 'lien': 'https://example.org/session-x'},
]}


class Comptes(Base):
    def setUp(self):
        super().setUp()
        self.run_('ouvrir', chantier='essai')
        for c in ('compte-a', 'compte-b', 'compte-c'):
            self.run_('comptes', chantier='essai', action='brancher', compte=c)

    def test_le_plus_de_quota_hors_orange(self):
        choix = boucle.choisir_compte(['compte-a', 'compte-b', 'compte-c'], RELEVE)
        self.assertEqual(choix['compte'], 'compte-b')
        self.assertEqual(choix['ecartes_orange'], ['compte-c'])
        self.assertEqual(boucle.choisir_compte(['compte-a', 'compte-c'], RELEVE)['compte'], 'compte-a')
        self.assertEqual(boucle.choisir_compte(['compte-c'], RELEVE)['compte'], 'compte-c')
        self.assertEqual(boucle.choisir_compte(['compte-a', 'compte-c'], RELEVE, 'compte-c')['raison'], 'choisi par toi')
        with self.assertRaises(boucle.Refus):
            boucle.choisir_compte(['compte-a'], RELEVE, 'compte-c')

    def test_debrancher(self):
        self.assertEqual(self.run_('comptes', chantier='essai', action='debrancher', compte='compte-a')['branches'], ['compte-b', 'compte-c'])

    def test_fiche_agent_compte_et_suivi(self):
        f = self.run_('agent', chantier='essai', nom='redacteur-def', role='rédacteur des définitions', sous_etape='E1.6', quoi='définitions au propre', releve=RELEVE)
        self.assertEqual(f['compte'], 'compte-b')
        self.assertEqual(f['choix_compte']['ecartes_orange'], ['compte-c'])
        suivi = self.run_('suivi', chantier='essai', releve=RELEVE)
        a = suivi['agents'][0]
        self.assertEqual((a['etat_session'], a['lien']), ('travaille', 'https://example.org/session-x'))
        cpt = {c['id']: c for c in suivi['comptes']['comptes']}
        self.assertEqual(cpt['compte-b']['agents'], ['redacteur-def'])
        self.assertTrue(cpt['compte-c']['orange'])
        self.run_('agent', chantier='essai', nom='redacteur-def', etat='fini')
        self.assertEqual(self.journal()[-1]['type'], 'agent_fini')
        self.assertEqual(self.run_('suivi', chantier='essai', releve=RELEVE)['comptes']['comptes'][1]['agents'], [])

    def test_programme_sans_compte(self):
        f = self.run_('agent', chantier='essai', nom='calcul-tailles', role='calcul des tailles', genre='programme', quoi='calcul', releve=RELEVE)
        self.assertNotIn('compte', f)


class Depenses(Base):
    def setUp(self):
        super().setUp()
        self.run_('ouvrir', chantier='essai')

    def test_rien_ne_part_sans_accord_et_depassement_arrete(self):
        self.assertIn('chiffres', self.refus('depense', chantier='essai', action='prevoir', passe='pilote-gen', role='génération'))
        self.run_('depense', chantier='essai', action='prevoir', passe='pilote-gen', role='génération', fournisseur='Groq', modele='llama',
                  relectures_par_donnee=2, cout_unitaire_eur=0.0004, cout_estime_eur=0.44, duree_estimee='4 min', quota_pct=0)
        self.assertIn("pas acceptée", self.refus('depense', chantier='essai', action='depenser', passe='pilote-gen', montant_eur=0.1))
        self.assertIn('mot pour mot', self.refus('depense', chantier='essai', action='accepter', passe='pilote-gen'))
        r = self.run_('depense', chantier='essai', action='accepter', passe='pilote-gen', citation='ok pour 0,50 €', montant_accepte_eur=0.5)
        self.assertEqual(r['budget']['valide_eur'], 0.5)
        r = self.run_('depense', chantier='essai', action='depenser', passe='pilote-gen', montant_eur=0.3)
        self.assertEqual(r['budget']['depense_eur'], 0.3)
        self.assertIn('Dépassement', self.refus('depense', chantier='essai', action='depenser', passe='pilote-gen', montant_eur=0.3))
        self.assertEqual(self.journal()[-1]['type'], 'depense_arretee')
        b = self.run_('suivi', chantier='essai', releve=RELEVE)['budget']
        self.assertEqual((b['prevu_eur'], b['valide_eur'], b['depense_eur']), (0.44, 0.5, 0.3))


class Etape2(Base):
    def ouvrir_etape2(self):
        self.run_('ouvrir', chantier='taches')
        ch = boucle.Chantier(self.racine, 'taches')
        c = ch.lire()
        c['etapes']['1'] = {'etat': 'scellee'}
        c['etapes']['2'] = {'etat': 'ouverte'}
        c['sous_etapes']['E2.4'] = {'etat': 'en_cours'}
        ch.enregistrer(c)

    def test_lexique_des_notions_comprises(self):
        self.ouvrir_etape2()
        self.run_('avancer', chantier='taches', sous_etape='E2.4', etat='validee', citation="c'est clair, les lots ne se mélangent pas")
        lex = self.run_('etat', chantier='taches')['lexique']
        self.assertEqual([(x['sous_etape'], x['notion']) for x in lex], [('E2.4', 'Les lots')])
        self.assertEqual(lex[0]['citation'], "c'est clair, les lots ne se mélangent pas")

    def test_calcul_formules_de_reference(self):
        """Les formules reprises du programme de la boucle redonnent les chiffres de contrôle :
        535 données par sortie à l'examen (risque 5 % / (2 × 3 tentatives), gain 7 points), 83 ratés au plus sur 1 070.
        Le calcul v2 (une porte par sortie, risque / tentatives par lot, borne des corrigés à la livraison) en part."""
        import statistiques as st
        self.assertEqual(st.dimensionner(0.05 / 6, 0.8, 0.07), 535)
        self.assertEqual(1070 - st.critique(1070, 0.90, 0.05 / 6), 83)
        self.ouvrir_etape2()
        for cle, v in (('barre.qualite', 0.90), ('niveau_vise.qualite', 0.97), ('calcul.facon', 'prudent'),
                       ('calcul.tentatives_examen', 3), ('cas_rares.regle', 'sur_representer'), ('etiquettes.tolerance', 0.02)):
            self.run_('registre', chantier='taches', cle=cle, valeur=v, citation='x')
        self.run_('ecrire', chantier='taches', chemin='etape2/pilote/mesures.json',
                  contenu=json.dumps({'unites': 931, 'sorties': {'EXECUTER': 700, 'FAIRE_REPETER': 231}, 'verite': {'relues': 300, 'erreurs': 0}, 'voie': 'generation'}))
        r = self.run_('calcul', chantier='taches')
        # Sans barre par sortie : la barre unique vaut pour chaque sortie (repli des anciens chantiers).
        self.assertEqual([c['id'] for c in r['criteres']], ['justesse:EXECUTER', 'justesse:FAIRE_REPETER'])
        self.assertAlmostEqual(r['risque_par_lot']['examen'], 0.05 / 3)
        # 888 par sortie = barre 90 % + marge des corrigés 2 % contre 97 %, au risque 5 % / 3.
        self.assertEqual(r['n_par_sortie']['examen'], {'EXECUTER': st.dimensionner(0.05 / 3, 0.8, 0.05), 'FAIRE_REPETER': 888})
        t = r['tailles']
        self.assertEqual((t['examen'], t['verification'], t['entrainement'], t['selection']), (1776, 1776, 4000, 800))
        self.assertEqual(r['portes']['3']['par_critere']['justesse:EXECUTER']['examen'], 'au plus 61 ratés sur 888')
        self.assertEqual(r['fixe_par']['examen'], 'la sortie (N1)')
        self.assertTrue(os.path.exists(os.path.join(self.racine, 'taches', 'etape2', 'calcul', 'parametres.json')))

    REGISTRE_TACHES = (('barre.qualite', 0.90), ('niveau_vise.qualite', 0.95), ('calcul.facon', 'prudent'), ('etiquettes.tolerance', 0.01),
               ('b1.couche1', 0.9), ('barre.par_sortie', {'EXECUTER': 0.9, 'SUGGERER': 0.8, 'NE_RIEN_FAIRE': 0.8}),
               ('niveau_vise.par_sortie', {'EXECUTER': 0.95, 'SUGGERER': 0.9, 'NE_RIEN_FAIRE': 0.9}),
               ('plafond.executer_a_tort', {'barre': 0.02, 'vise': 0.005, 'strates': ['SUGGERER', 'NE_RIEN_FAIRE']}))
    PROFILS = [{'nom': '86/95/95', 'sorties': {'EXECUTER': 0.86, 'SUGGERER': 0.95, 'NE_RIEN_FAIRE': 0.95}, 'executer_a_tort': 0.005},
               {'nom': '95/85/85', 'sorties': {'EXECUTER': 0.95, 'SUGGERER': 0.85, 'NE_RIEN_FAIRE': 0.85}, 'executer_a_tort': 0.005},
               {'nom': 'exécute à tort 3 %', 'sorties': {'EXECUTER': 0.95, 'SUGGERER': 0.9, 'NE_RIEN_FAIRE': 0.9}, 'executer_a_tort': 0.03},
               {'nom': "n'exécute jamais à tort", 'sorties': {'EXECUTER': 0.95, 'SUGGERER': 0.9, 'NE_RIEN_FAIRE': 0.9}, 'executer_a_tort': 0.0}]

    def calcul_taches(self, *autres, sans=(), verite=None):
        self.ouvrir_etape2()
        for cle, v in self.REGISTRE_TACHES + autres:
            if cle not in sans:
                self.run_('registre', chantier='taches', cle=cle, valeur=v, citation='x')
        self.run_('ecrire', chantier='taches', chemin='etape2/pilote/mesures.json',
                  contenu=json.dumps({'unites': 194, 'sorties': {'EXECUTER': 132, 'SUGGERER': 34, 'NE_RIEN_FAIRE': 28}, 'verite': verite or {'relues': 300, 'erreurs': 0}, 'voie': 'generation'}))
        r = self.run_('calcul', chantier='taches', profils=self.PROFILS)
        return r, {p['nom']: p for p in r['profils']}

    def test_une_porte_par_sortie_jamais_sur_le_melange(self):
        """avec les barres 90/80/80, un modèle qui exécute juste à 86 % est refusé, quelles que soient ses
        autres sorties ; un modèle à 95/85/85, qui respecte toutes ses barres, est reçu à la livraison (la porte sur le
        mélange le refusait à coup sûr). Tailles faites pour que toutes les portes passent au niveau visé."""
        r, p = self.calcul_taches(('calcul.toutes_portes_au_vise', True))
        self.assertIn('justesse:SUGGERER', r['portes_par_critere'])
        self.assertLess
        self.assertEqual
        self.assertGreater
        self.assertGreater
        self.assertGreaterEqual(r['chance_au_vise'], 0.8)
        self.assertGreaterEqual(p['au niveau visé']['chance_recu'], 0.8)
        self.assertLess(p['à la barre']['chance_recu'], 0.01)
        self.assertEqual(r['motifs_compromis'], [])

    def test_chaque_sortie_dimensionnee_sur_sa_barre_et_son_vise(self):
        import statistiques as st
        r, p = self.calcul_taches(sans=('plafond.executer_a_tort',))
        n = r['n_par_sortie']['examen']
        # Examen : risque 5 % / 2 tentatives ; barre + borne des corrigés (tolérance 1 %) contre le niveau visé.
        self.assertEqual(n['EXECUTER'], st.dimensionner(0.025, 0.8, 0.04))
        self.assertEqual(n['SUGGERER'], st.dimensionner(0.025, 0.8, 0.09))
        self.assertLess(n['SUGGERER'], n['EXECUTER'] / 3)
        self.assertEqual(r['tailles']['examen'], sum(n.values()))
        # B1 se lit sur les données « fait » et les propositions imposées, jamais sur NE_RIEN_FAIRE (fiche de notation § 4.4).
        b1 = next(c for c in r['criteres'] if c['id'] == 'b1')
        self.assertEqual((b1['compte_sur'], b1['touche']), ('EXECUTER', ['EXECUTER', 'SUGGERER']))
        self.assertFalse(any(c['compte_sur'] == 'NE_RIEN_FAIRE' and c['genre'] == 'b1' for c in r['criteres']))
        # Une barre par sortie : sous la barre d'exécuter, refusé ; les autres sorties à 85 % passent leur porte.
        self.assertLess
        self.assertGreater
        # Seuils lisibles : « au plus N ratés sur M », par porte et par lot.
        x = r['portes_par_critere']['justesse:EXECUTER']['lots']['examen']
        self.assertEqual(x['texte'], f"au plus {x['n'] - x['k']} ratés sur {x['n']}")

    def test_plafond_d_execution_a_tort(self):
        """le plafond (au plus 2 %, visé 0,5 %) est une porte à part, sur chacune de ses strates. Second
        audit, n2 : il reçoit la borne des corrigés (un corrigé EXÉCUTER faux peut cacher une exécution à tort)."""
        import statistiques as st
        r, p = self.calcul_taches()
        self.assertEqual([c for c in r['portes_par_critere'] if c.startswith('plafond:')], ['plafond:SUGGERER', 'plafond:NE_RIEN_FAIRE'])
        borne = st.borne_erreur(erreurs=0, relues=300, risque=0.05)
        n = st.dimensionner_niveaux(0.025, 0.8, 0.98 + 0.01, 0.995)   # dimensionné sur la tolérance (1 %)
        self.assertEqual(r['n_par_sortie']['examen']['SUGGERER'], n)
        self.assertEqual(r['fixe_par_sortie']['examen']['SUGGERER'], 'plafond:SUGGERER')
        x = r['portes_par_critere']['plafond:NE_RIEN_FAIRE']['lots']['verification']
        self.assertEqual(x['texte'], f"au plus {n - st.critique(n, 0.98 + borne, 0.025)} exécutions à tort sur {n}")
        self.assertAlmostEqual(r['portes_par_critere']['plafond:SUGGERER']['barre_testee'], round(0.98 + borne, 6))
        self.assertEqual(p['exécute à tort 3 %']['chance_livraison'], 0.0)
        self.assertGreater(p["n'exécute jamais à tort"]['chance_livraison'], 0.99)
        # Plafond seulement à sa barre (2 %) : livré au plus une fois sur mille par tentative (≤ risque par lot).
        self.assertLess(p['à la barre']['par_critere_livraison']['plafond:SUGGERER'], 0.025)

    def test_plafond_sans_borne_des_corriges(self):
        """Clé plafond.executer_a_tort.borne_corriges à false, le plafond est testé sans la
        borne des corrigés ; la règle des inversions vers EXÉCUTER est écrite au calcul (473 relectures : 0 admise)."""
        import statistiques as st
        avec, _ = self.calcul_taches(('etiquettes.erreurs_permises', 1))
        self.tearDown()
        self.setUp()
        r, p = self.calcul_taches(('etiquettes.erreurs_permises', 1), ('plafond.executer_a_tort.borne_corriges', False))
        x = r['portes_par_critere']['plafond:SUGGERER']
        self.assertAlmostEqual(x['barre_testee'], 0.98)
        n = x['lots']['examen']['n']
        self.assertEqual(x['lots']['examen']['texte'], f"au plus {n - st.critique(n, 0.98, 0.025)} exécutions à tort sur {n}")
        self.assertLessEqual(r['total'], avec['total'])
        # Les justesses gardent la borne des corrigés.
        self.assertAlmostEqual(r['portes_par_critere']['justesse:SUGGERER']['barre_testee'], avec['portes_par_critere']['justesse:SUGGERER']['barre_testee'])
        inv = r['etiquettes']['inversions_vers_executer']
        self.assertEqual((inv['tolerance'], inv['relectures'], inv['permises'], inv['strates']), (0.0075, 473, 0, ['SUGGERER', 'NE_RIEN_FAIRE']))
        self.assertLessEqual(inv['borne_a_zero'], 0.0075)
        self.assertGreater(inv['borne_au_dela'], 0.0075)
        self.assertIn('au plus 0 inversion vers EXÉCUTER sur les 473 relectures', ' '.join(r['a_confirmer']))
        self.assertIsNone(avec['etiquettes']['inversions_vers_executer'])
        self.assertIs(self.run_('etat', chantier='taches')['calcul']['criteres'][-2]['borne_corriges'], False)

    def test_plafond_sans_borne_refuse_sans_relecture_suffisante(self):
        # 299 relectures (plan sans erreur, 1 %) : même zéro inversion ne borne pas à 0,75 % → refus, avec le nombre utile.
        self.assertIn('398', self.refus_calcul(('plafond.executer_a_tort.borne_corriges', False)))
        self.assertIn('etiquettes.tolerance', self.refus_calcul(('plafond.executer_a_tort.borne_corriges', False), sans=('etiquettes.tolerance',)))
        self.assertIn('true ou false', self.refus_calcul(('plafond.executer_a_tort.borne_corriges', 'non')))

    def refus_calcul(self, *autres, sans=()):
        self.tearDown()
        self.setUp()
        self.ouvrir_etape2()
        for cle, v in self.REGISTRE_TACHES + autres:
            if cle not in sans:
                self.run_('registre', chantier='taches', cle=cle, valeur=v, citation='x')
        self.run_('ecrire', chantier='taches', chemin='etape2/pilote/mesures.json',
                  contenu=json.dumps({'unites': 194, 'sorties': {'EXECUTER': 132, 'SUGGERER': 34, 'NE_RIEN_FAIRE': 28}, 'verite': {'relues': 300, 'erreurs': 0}}))
        return self.refus('calcul', chantier='taches')

    def test_risque_par_lot_et_borne_des_corriges_a_la_livraison(self):
        """examen ET vérification exigés → risque / tentatives par lot ; la porte 3 teste la barre
        plus la borne d'erreur des corrigés mesurée ; la porte 1 = la porte 2 (la borne n'est pas comptée deux fois)."""
        import statistiques as st
        r, _ = self.calcul_taches()
        self.assertEqual(r['risque_par_lot'], {'selection': 0.05, 'pre_evaluation': 0.01, 'examen': 0.025, 'verification': 0.025})
        borne = st.borne_erreur(erreurs=0, relues=300, risque=0.05)
        x = r['portes_par_critere']['justesse:EXECUTER']
        self.assertAlmostEqual(x['barre_testee'], 0.9 + borne, places=6)
        self.assertEqual(x['lots']['examen']['k'], st.critique(x['lots']['examen']['n'], 0.9 + borne, 0.025))
        self.assertEqual(x['porte1'], x['porte2'])
        self.assertAlmostEqual(r['portes_par_critere']['plafond:SUGGERER']['barre_testee'], round(0.98 + borne, 6))
        self.assertIn('flatté par la sélection', r['portes']['1']['note'])

    def test_portes_filtres_livraison_seule_garantit(self):
        """Option calcul.portes_filtres : portes 1 et 2 = filtres au seuil de la porte 3
        (même fraction) ; la porte 3 garde la garantie (risque / tentatives par lot, borne des corrigés) ; un modèle au
        niveau visé est livré au moins 8 fois sur 10 et franchit chaque filtre au moins 9 fois sur 10 ; un modèle à la
        barre d'un critère franchit le test de ce critère au plus une fois sur deux."""
        import statistiques as st
        r, p = self.calcul_taches(('calcul.portes_filtres', True))
        self.assertTrue(r['portes_filtres'])
        self.assertGreaterEqual(r['chance_livraison_au_vise'], 0.8)
        self.assertGreaterEqual(p['au niveau visé']['chance_livraison'], 0.8)
        for lot in ('selection', 'pre_evaluation'):
            self.assertGreaterEqual(r['filtres']['chance_au_vise'][lot], 0.9)
        self.assertGreaterEqual(p['au niveau visé']['chance_filtre1'], 0.9)
        self.assertGreaterEqual(p['au niveau visé']['chance_filtre2'], 0.9)
        self.assertTrue(all(v <= 0.5 for x in r['filtres']['chance_a_la_barre'].values() for v in x.values()))
        borne = st.borne_erreur(erreurs=0, relues=300, risque=0.05)
        for cid, x in r['portes_par_critere'].items():
            ex = x['lots']['examen']
            p0 = x['barre'] + borne   # plafond compris
            self.assertEqual(ex['k'], st.critique(ex['n'], p0, 0.025))          # la garantie ne bouge pas
            self.assertAlmostEqual(x['porte1'], ex['k'] / ex['n'])
            self.assertEqual(x['porte1'], x['porte2'])
            self.assertTrue(x['filtre'])
            for lot in ('selection', 'pre_evaluation'):
                y = x['lots'][lot]
                self.assertEqual(y['k'], math.ceil(ex['k'] / ex['n'] * y['n'] - 1e-9))
        for l in r['comparaison_facons']['prudent']['portes']:
            self.assertLessEqual(l['livrer_a_la_barre'], 0.025)
        self.assertIn('ne garantit pas la livraison', r['portes']['1']['note'])
        self.assertIn('ne garantit pas la livraison', r['portes']['2']['note'])
        self.assertLess
        self.assertEqual(p['exécute à tort 3 %']['chance_livraison'], 0.0)
        self.assertEqual(r['motifs_compromis'], [])
        # Sorties aux mêmes critères : mêmes tailles.
        self.assertEqual(r['n_par_sortie']['examen']['SUGGERER'], r['n_par_sortie']['examen']['NE_RIEN_FAIRE'])

    def test_portes_filtres_cible_plus_basse_coute_moins(self):
        r9, _ = self.calcul_taches(('calcul.portes_filtres', True))
        self.tearDown()
        self.setUp()
        r5, _ = self.calcul_taches(('calcul.portes_filtres', True), ('calcul.filtre_chance_vise', 0.5))
        self.assertLess(r5['total'], r9['total'])
        self.assertGreaterEqual(r5['filtres']['chance_au_vise']['selection'], 0.5)
        self.assertGreaterEqual(r5['chance_livraison_au_vise'], 0.8)

    def test_portes_filtres_option_sans_effet_par_defaut(self):
        r, _ = self.calcul_taches()
        self.assertFalse(r['portes_filtres'])
        self.assertIsNone(r['filtres'])
        self.assertFalse(any(x['filtre'] for x in r['portes_par_critere'].values()))

    def test_portes_filtres_et_toutes_portes_au_vise_refuses_ensemble(self):
        self.ouvrir_etape2()
        for cle, v in self.REGISTRE_TACHES + (('calcul.portes_filtres', True), ('calcul.toutes_portes_au_vise', True)):
            self.run_('registre', chantier='taches', cle=cle, valeur=v, citation='x')
        self.run_('ecrire', chantier='taches', chemin='etape2/pilote/mesures.json',
                  contenu=json.dumps({'unites': 194, 'sorties': {'EXECUTER': 132, 'SUGGERER': 34, 'NE_RIEN_FAIRE': 28}, 'verite': {'relues': 300, 'erreurs': 0}}))
        self.assertIn('ne vont pas ensemble', self.refus('calcul', chantier='taches'))

    def test_partage_de_la_puissance_au_moindre_volume(self):
        import boucle
        # Sortie A : chère à rendre sûre ; B : presque gratuite. Le partage donne à A la plus grande part.
        # cout[u][j] : taille pour la part j du logarithme de la cible (plus de part = moins de puissance exigée).
        cout = {'A': [None] + [100 * (boucle.PARTS - j + 1) for j in range(1, boucle.PARTS + 1)], 'B': [None] + [10] * boucle.PARTS}
        self.assertEqual(boucle._partager(['A', 'B'], cout), {'A': 200, 'B': 10})
        cout['B'] = [None] * (boucle.PARTS + 1)
        self.assertIsNone(boucle._partager(['A', 'B'], cout))

    def test_ecart_au_registre_signale(self):
        # une valeur du registre que le calcul contredit est signalée.
        r, _ = self.calcul_taches(('banc.min_par_sortie_test', 250))
        self.assertEqual([e['cle'] for e in r['ecarts_registre']], ['banc.min_par_sortie_test'])

    def test_barre_par_sortie_incomplete_refusee(self):
        self.ouvrir_etape2()
        self.run_('registre', chantier='taches', cle='barre.par_sortie', valeur={'A': 0.9}, citation='x')
        self.run_('registre', chantier='taches', cle='niveau_vise.qualite', valeur=0.95, citation='x')
        self.run_('ecrire', chantier='taches', chemin='etape2/pilote/mesures.json',
                  contenu=json.dumps({'unites': 100, 'sorties': {'A': 60, 'B': 40}, 'verite': {'relues': 150, 'erreurs': 0}}))
        self.assertIn('barre.par_sortie', self.refus('calcul', chantier='taches'))

    def test_au_plus_juste_demande_bien_moins(self):
        self.ouvrir_etape2()
        for cle, v in (('barre.qualite', 0.90), ('niveau_vise.qualite', 0.97), ('calcul.facon', 'juste')):
            self.run_('registre', chantier='taches', cle=cle, valeur=v, citation='x')
        self.run_('ecrire', chantier='taches', chemin='etape2/pilote/mesures.json',
                  contenu=json.dumps({'unites': 100, 'sorties': {'A': 60, 'B': 40}, 'verite': {'relues': 150, 'erreurs': 0}, 'voie': 'generation'}))
        juste = self.run_('calcul', chantier='taches')['total']
        self.run_('registre', chantier='taches', cle='calcul.facon', valeur='prudent', citation='x')
        prudent = self.run_('calcul', chantier='taches')['total']
        self.assertGreater(prudent / juste, 3)

    def test_strategie_de_generation_seulement_si_la_voie_genere(self):
        """E2.2.1 : la stratégie de génération n'apparaît que si la voie choisie génère."""
        self.ouvrir_etape2()
        ch = boucle.Chantier(self.racine, 'taches')
        ids = lambda: [s['id'] for s in boucle.visibles(ch.lire())]
        self.assertIn('E2.2.1', ids())
        self.run_('registre', chantier='taches', cle='voie.donnees', valeur='collecte', citation='on récolte')
        self.assertNotIn('E2.2.1', ids())
        self.run_('registre', chantier='taches', cle='voie.donnees', valeur='mixte', citation='on mêle')
        self.assertIn('E2.2.1', ids())
        self.assertIn('collecte', self.refus('registre', chantier='taches', cle='voie.donnees', valeur='inventer', citation='x'))

    def test_diversite_d_un_lot_genere(self):
        """E2.2.1 : doublons, quasi-doublons, plan de quotas et vraies données servant de graines."""
        self.ouvrir_etape2()
        pauvre = [{'texte': 'ouvre le planning', 'case': 'A'}] * 8 + [{'texte': 'ouvre le planning svp', 'case': 'A'}] * 2
        self.run_('ecrire', chantier='taches', chemin='etape2/pilote/pauvre.jsonl', contenu='\n'.join(json.dumps(x) for x in pauvre))
        r = self.run_('diversite', chantier='taches', fichier='etape2/pilote/pauvre.jsonl', champ_case='case')
        self.assertFalse(r['passe'])
        self.assertEqual(r['distinctes'], 2)
        verbes = ['ouvre', 'ferme', 'déplace', 'renomme', 'supprime', 'copie', 'trie', 'filtre', 'compare', 'exporte']
        objets = ['le planning', 'la facture', 'ce rendez-vous', 'le stock du mardi', 'la commande urgente']
        riche = [{'texte': f'{v} {o}', 'case': 'A' if i % 2 else 'B'} for i, (v, o) in enumerate((v, o) for v in verbes for o in objets)]
        self.run_('ecrire', chantier='taches', chemin='etape2/pilote/riche.jsonl', contenu='\n'.join(json.dumps(x, ensure_ascii=False) for x in riche))
        self.run_('ecrire', chantier='taches', chemin='etape2/graines.jsonl', contenu=json.dumps({'texte': 'ouvre vite le planning, zut'}, ensure_ascii=False))
        self.run_('registre', chantier='taches', cle='generation.plan', valeur={'A': 25, 'B': 25, 'C': 5}, citation='x')
        r = self.run_('diversite', chantier='taches', fichier='etape2/pilote/riche.jsonl', champ_case='case', graines='etape2/graines.jsonl')
        self.assertEqual(r['part_distinctes'], 1.0)
        self.assertEqual(r['cases_sous_quota'], {'C': 5})
        self.assertIn('zut', r['graines']['mots_reels_jamais_generes'])
        self.assertFalse(r['passe'])
        self.assertTrue(os.path.exists(os.path.join(self.racine, 'taches', 'etape2', 'pilote', 'diversite.json')))

    def test_diversite_apostrophes_et_mots_exclus(self):
        """E2.2.1 : « l'onglet » se compte « onglet » ; les noms propres du cas réel (registre
        generation.mots_exclus) sortent du modèle des graines avant la couverture."""
        self.assertEqual(boucle._mots("Dans l'onglet, qu’il supprime aujourd'hui"), ['dans', 'onglet', 'il', 'supprime', "aujourd'hui"])
        self.ouvrir_etape2()
        lot = [{'texte': t} for t in ['ouvre onglet tâches', 'va sur onglet données', 'supprime ce rappel', 'réduis le délai']]
        self.run_('ecrire', chantier='taches', chemin='etape2/pilote/lot.jsonl', contenu='\n'.join(json.dumps(x, ensure_ascii=False) for x in lot))
        self.run_('ecrire', chantier='taches', chemin='etape2/graines.jsonl',
                  contenu='\n'.join(json.dumps({'texte': t}, ensure_ascii=False) for t in ["dans l'onglet tâches", "supprime le garage de l'agenda"]))
        r = self.run_('diversite', chantier='taches', fichier='etape2/pilote/lot.jsonl', graines='etape2/graines.jsonl')
        self.assertNotIn("l'onglet", r['graines']['mots_reels_jamais_generes'])
        self.assertIn('garage', r['graines']['mots_reels_jamais_generes'])
        self.assertEqual(r['graines']['part_mots_reels_couverts'], round(4 / 8, 4))
        self.run_('registre', chantier='taches', cle='generation.mots_exclus', valeur=['garage', "l'agenda"], citation='noms propres')
        r = self.run_('diversite', chantier='taches', fichier='etape2/pilote/lot.jsonl', graines='etape2/graines.jsonl')
        self.assertEqual(r['graines']['mots_exclus'], ['agenda', 'garage'])
        self.assertEqual(r['graines']['part_mots_reels_couverts'], round(4 / 6, 4))
        self.assertNotIn('garage', r['graines']['mots_reels_jamais_generes'])
        self.run_('registre', chantier='taches', cle='generation.mots_exclus', valeur='garage', citation='x')
        self.assertIn('liste', self.refus('diversite', chantier='taches', fichier='etape2/pilote/lot.jsonl', graines='etape2/graines.jsonl'))

    def test_comparaison_des_deux_facons_en_chiffres(self):
        """E2.10, refait par critère : une ligne par porte, sur l'examen et la vérification
        réunis, et la chance de franchir toutes les portes, pour prudent et au plus juste."""
        r, _ = self.calcul_taches()
        c = r['comparaison_facons']
        self.assertEqual(c['prudent']['total'], r['total'])
        self.assertGreater(c['prudent']['total'], c['juste']['total'])
        self.assertEqual(c['prudent']['risque_livrer_sous_barre'], c['juste']['risque_livrer_sous_barre'])
        for f in c:
            self.assertEqual([l['critere'] for l in c[f]['portes']], list(r['portes_par_critere']))
            for l in c[f]['portes']:
                self.assertLessEqual(l['livrer_a_la_barre'], 0.025)
                self.assertRegex(l['examen'], r'^au plus \d+ (ratés|exécutions à tort) sur \d+$')
            self.assertIn('chance_toutes_portes_au_vise', c[f])
            self.assertEqual([x['decalage'] for x in c[f]['refus_par_malchance']][:3], [0.0, 0.01, 0.02])
        ex = {f: next(l for l in c[f]['portes'] if l['critere'] == 'justesse:EXECUTER') for f in c}
        self.assertLess(ex['prudent']['refus_au_vise'], ex['juste']['refus_au_vise'])
        self.assertLess(ex['prudent']['seuil_examen'], ex['juste']['seuil_examen'])

    def test_motif_de_compromis_si_etiquettes_trop_peu_fiables(self):
        self.ouvrir_etape2()
        for cle, v in (('barre.qualite', 0.90), ('niveau_vise.qualite', 0.97), ('etiquettes.tolerance', 0.01)):
            self.run_('registre', chantier='taches', cle=cle, valeur=v, citation='x')
        self.run_('ecrire', chantier='taches', chemin='etape2/pilote/mesures.json',
                  contenu=json.dumps({'unites': 100, 'sorties': {'A': 60, 'B': 40}, 'verite': {'relues': 100, 'erreurs': 5}}))
        r = self.run_('calcul', chantier='taches')
        # 5 erreurs sur 100 réfutent une tolérance de 1 % (P[≥ 5 | 1 %] ≈ 0,3 % ≤ risque) : la borne mesurée reste.
        self.assertTrue(r['etiquettes']['pilote_contredit_tolerance'])
        self.assertFalse(r['etiquettes']['a_confirmer'])
        self.assertTrue(any('tolérance' in m for m in r['motifs_compromis']))
        self.assertEqual(r['marge_corriges']['seuils'], r['etiquettes']['borne_mesuree'])

    def test_borne_prevue_quand_le_pilote_est_trop_petit(self):
        """REGLE_BORNE_PREVUE : 1 erreur sur 10 relues (borne 39 %) ne dit rien d'une tolérance de 1 % ;
        les portes se posent avec la borne prévue, le résultat dit la borne mesurée, la borne prévue, les relectures sans
        erreur nécessaires (binomiale exacte) et « à confirmer par 299 relectures à l'étape 3 » ; aucun refus."""
        import statistiques as st
        r, _ = self.calcul_taches(('calcul.portes_filtres', True), verite={'relues': 10, 'erreurs': 1})
        e = r['etiquettes']
        self.assertAlmostEqual(e['borne_mesuree'], st.borne_erreur(erreurs=1, relues=10, risque=0.05))
        self.assertGreater(e['borne_mesuree'], 0.39)
        self.assertEqual(e['borne_prevue'], 0.01)
        self.assertTrue(e['a_confirmer'])
        self.assertFalse(e['pilote_contredit_tolerance'])
        self.assertEqual(e['plan']['relectures_sans_erreur'], 299)
        self.assertLessEqual(st.borne_erreur(erreurs=0, relues=299, risque=0.05), 0.01)
        self.assertGreater(st.borne_erreur(erreurs=0, relues=298, risque=0.05), 0.01)
        self.assertEqual(e['plan']['relectures_selon_erreurs'], {'0': 299, '1': 473, '2': 628})
        self.assertIn("à confirmer par 299 relectures à l'étape 3", r['a_confirmer'][0])
        self.assertFalse(any('tolérance' in m for m in r['motifs_compromis']))
        self.assertEqual(r['marge_corriges']['seuils'], 0.01)
        for x in r['portes_par_critere'].values():
            ex = x['lots']['examen']
            p0 = x['barre'] + 0.01   # plafond compris
            self.assertEqual(ex['k'], st.critique(ex['n'], p0, 0.025))
        self.assertGreaterEqual(r['chance_livraison_au_vise'], 0.8)
        # Un pilote assez grand garde sa borne mesurée (rien à confirmer).
        self.tearDown()
        self.setUp()
        r, _ = self.calcul_taches()
        self.assertFalse(r['etiquettes']['a_confirmer'])
        self.assertEqual(r['a_confirmer'], [])
        self.assertAlmostEqual(r['marge_corriges']['seuils'], st.borne_erreur(erreurs=0, relues=300, risque=0.05))

    def test_entrainement_minimum_hors_selection(self):
        """lots.entrainement_min fixe le cours (l'entraînement hors sélection),
        à parts égales entre sorties ; la sélection garde la taille que les filtres demandent ; examen, vérification et
        seuils ne bougent pas. Sans la clé : l'ancienne règle (entraînement = sélection / (f (1 − f)))."""
        r0, _ = self.calcul_taches(('calcul.portes_filtres', True), verite={'relues': 10, 'erreurs': 1})
        self.assertIsNone(r0['entrainement']['minimum_hors_selection'])
        self.assertIn('la sélection (part 0,2)', r0['fixe_par']['entrainement'])
        for u, v in r0['n_par_sortie']['entrainement'].items():
            self.assertEqual(r0['n_par_sortie']['selection'][u], math.ceil(v * 0.2))
        self.tearDown()
        self.setUp()
        r, _ = self.calcul_taches(('calcul.portes_filtres', True), ('lots.entrainement_min', 10704), verite={'relues': 10, 'erreurs': 1})
        e = r['entrainement']
        self.assertEqual(e['minimum_hors_selection'], 10704)
        self.assertEqual(e['hors_selection'], {'EXECUTER': 3568, 'SUGGERER': 3568, 'NE_RIEN_FAIRE': 3568})
        self.assertEqual(e['total_hors_selection'], 10704)
        n = r['n_par_sortie']
        for u in n['examen']:
            self.assertEqual(n['entrainement'][u], n['selection'][u] + 3568)
            self.assertEqual(n['pre_evaluation'][u], max(n['pre_evaluation'][u], n['selection'][u] + 1))
        self.assertEqual(r['tailles']['entrainement'], 10704 + r['tailles']['selection'])
        self.assertIn('lots.entrainement_min', r['fixe_par']['entrainement'])
        # La garantie reste celle de la porte 3 (l'examen gardé peut changer : la descente cherche le plus petit total).
        self.assertGreaterEqual(r['filtres']['chance_au_vise']['selection'], 0.9)
        self.assertGreaterEqual(r['chance_livraison_au_vise'], 0.8)
        self.assertEqual(r['comparaison_facons']['juste']['tailles']['entrainement'] - r['comparaison_facons']['juste']['tailles']['selection'], 10704)
        par = json.load(open(os.path.join(self.racine, 'taches', 'etape2', 'calcul', 'parametres.json')))
        self.assertEqual(par['registre']['lots.entrainement_min'], 10704)
        # Parts égales, arrondies au-dessus : la somme vaut au moins le minimum.
        self.assertEqual(boucle.cours_par_sortie(10, ['A', 'B', 'C']), {'A': 4, 'B': 4, 'C': 4})
        self.assertIsNone(boucle.cours_par_sortie(None, ['A']))

    def test_entrainement_minimum_refuse_hors_entier(self):
        self.ouvrir_etape2()
        for cle, v in self.REGISTRE_TACHES + (('lots.entrainement_min', -3),):
            self.run_('registre', chantier='taches', cle=cle, valeur=v, citation='x')
        self.run_('ecrire', chantier='taches', chemin='etape2/pilote/mesures.json',
                  contenu=json.dumps({'unites': 194, 'sorties': {'EXECUTER': 132, 'SUGGERER': 34, 'NE_RIEN_FAIRE': 28}, 'verite': {'relues': 300, 'erreurs': 0}}))
        self.assertIn('lots.entrainement_min', self.refus('calcul', chantier='taches'))

    def test_tableaux_ecrits_par_le_programme(self):
        """la comparaison prudent / juste et tous les chiffres à montrer sortent du programme
        (champ tableaux, markdown), recopiés des champs du résultat, sans calcul de l'agent."""
        r, _ = self.calcul_taches(('calcul.portes_filtres', True), ('lots.entrainement_min', 10704), verite={'relues': 10, 'erreurs': 1})
        t = r['tableaux']
        self.assertEqual(set(t), {'tailles', 'seuils', 'profils', 'facons'})
        P, J = r['comparaison_facons']['prudent'], r['comparaison_facons']['juste']
        self.assertIn(boucle._nb(P['total']), t['facons'])
        self.assertIn(boucle._nb(J['total']), t['facons'])
        self.assertIn('| Prudent | Au plus juste |', t['facons'])
        self.assertIn('dont cours (hors sélection)', t['tailles'])
        self.assertIn(boucle._nb(r['total']), t['tailles'])
        self.assertIn(r['portes_par_critere']['plafond:SUGGERER']['lots']['examen']['texte'], t['seuils'])
        self.assertIn('au niveau visé', t['profils'])
        self.assertEqual(boucle._nb(14396), '14\u202f396')
        self.assertEqual((boucle._pc(0.99924), boucle._pc(0.0), boucle._pc(1.0), boucle._pc(0.00001)), ('99,9 %', '0 %', '100 %', '< 0,1 %'))

    def test_calcul_sans_pilote_refuse(self):
        self.ouvrir_etape2()
        self.assertIn('pilote', self.refus('calcul', chantier='taches'))


def ecrire_lignes(chemin, lignes):
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    with open(chemin, 'w') as f:
        for x in lignes:
            f.write(json.dumps(x, ensure_ascii=False) + '\n')


class Etape3(Base):
    def test_fabrication_lue_et_depassement_du_devis(self):
        self.run_('ouvrir', chantier='essai')
        d = os.path.join(self.racine, 'essai', 'etape3')
        os.makedirs(d)
        with open(os.path.join(d, 'fabrication.json'), 'w') as f:
            json.dump({'devis_eur': 3.4, 'phases': [{'nom': 'génération', 'etat': 'fini', 'comptes': {'obtenues': 7300, 'jetees': 128}, 'cout_eur': 3.0},
                                                    {'nom': 'étiquetage', 'etat': 'en_cours', 'cout_eur': 0.6}]}, f)
        fab = self.run_('etat', chantier='essai')['fabrication']
        self.assertEqual(fab['cout_eur'], 3.6)
        self.assertTrue(fab['depasse'])

    def test_relecture_une_donnee_a_la_fois_et_borne(self):
        self.run_('ouvrir', chantier='essai')
        self.run_('registre', chantier='essai', cle='etiquettes.tolerance', valeur=0.02, citation='2 %')
        ecrire_lignes(os.path.join(self.racine, 'essai', 'etape3', 'a-relire.jsonl'),
                      [{'id': f'd{i}', 'lot': 'examen', 'donnee': f'consigne {i}', 'reponse': 'EXECUTER'} for i in range(3)])
        r = self.run_('relire', chantier='essai')
        self.assertEqual(r['donnee']['id'], 'd0')
        self.run_('relire', chantier='essai', action='noter', id='d0', verdict='ok')
        self.assertIn('correction', self.refus('relire', chantier='essai', action='noter', id='d1', verdict='corrige'))
        r = self.run_('relire', chantier='essai', action='noter', id='d1', verdict='corrige', correction='FAIRE_REPETER', mot='ambigu')
        e = r['etat']
        self.assertEqual((e['relues'], e['erreurs']), (2, 1))
        self.assertTrue(e['depasse'])
        self.assertEqual(self.run_('relire', chantier='essai')['donnee']['id'], 'd2')
        self.assertEqual(self.run_('etat', chantier='essai')['relecture_banc']['relues'], 2)


class ConfirmationPortes(Base):
    """REGLE_BORNE_PREVUE, étape 3 : après les relectures du plan, le calcul se relance avec la borne mesurée ; les
    portes se figent, ou l'écart ferme la fabrication."""
    ouvrir_etape2, calcul_taches = Etape2.ouvrir_etape2, Etape2.calcul_taches
    REGISTRE_TACHES, PROFILS = Etape2.REGISTRE_TACHES, Etape2.PROFILS

    def preparer(self, relectures):
        r, _ = self.calcul_taches(verite={'relues': 10, 'erreurs': 1})
        ch = boucle.Chantier(self.racine, 'taches')
        c = ch.lire()
        c['etapes']['2'] = {'etat': 'scellee'}
        c['etapes']['3'] = {'etat': 'ouverte'}
        c['sous_etapes'].update({'E3.1': {'etat': 'validee'}, 'E3.2': {'etat': 'validee'}, 'E3.3': {'etat': 'en_cours'}})
        ch.enregistrer(c)
        ecrire_lignes(os.path.join(self.racine, 'taches', 'etape3', 'a-relire.jsonl'),
                      [{'id': f'd{i}', 'lot': 'examen', 'donnee': f'consigne {i}', 'reponse': 'EXECUTER'} for i in range(320)])
        for i, v in enumerate(relectures):
            self.run_('relire', chantier='taches', action='noter', id=f'd{i}', verdict=v, **({'correction': 'SUGGERER'} if v == 'corrige' else {}))
        return r

    def test_portes_figees_sur_la_borne_mesuree(self):
        import statistiques as st
        r2 = self.preparer(['ok'] * 150)
        x = self.run_('confirmer_portes', chantier='taches')
        self.assertEqual((x['etat'], x['relues'], x['relectures_plan']), ('en_attente', 150, 299))
        self.assertIn('encore 149 relectures', x['motif'])
        self.assertIn('pas figées', self.refus('sceller', chantier='taches', etape=3))
        for i in range(150, 305):
            self.run_('relire', chantier='taches', action='noter', id=f'd{i}', verdict='ok')
        x = self.run_('confirmer_portes', chantier='taches')
        self.assertEqual((x['etat'], x['relues'], x['erreurs']), ('figees', 299, 0))   # les 299 premières seulement
        self.assertAlmostEqual(x['borne_mesuree'], st.borne_erreur(erreurs=0, relues=299, risque=0.05))
        self.assertEqual(x['tailles'], r2['tailles'])                                  # les tailles du plan scellé
        for cid, y in x['portes'].items():
            ex = y['lots']['examen']
            prevu = r2['portes_par_critere'][cid]['lots']['examen']
            self.assertEqual(ex['n'], prevu['n'])
            p0 = r2['portes_par_critere'][cid]['barre'] + x['borne_mesuree']   # plafond compris
            self.assertEqual(ex['k'], st.critique(ex['n'], p0, 0.025))
            self.assertLessEqual(ex['k'], prevu['k'])                                   # borne mesurée ≤ prévue
        self.assertGreaterEqual(x['chance_livraison_au_vise'], r2['chance_livraison_au_vise'])
        self.assertEqual(self.journal('taches')[-1]['type'], 'portes_figees')
        # Figées : un nouvel appel ne recalcule rien, même si une relecture tardive trouve une erreur.
        self.run_('relire', chantier='taches', action='noter', id='d306', verdict='corrige', correction='SUGGERER')
        y = self.run_('confirmer_portes', chantier='taches')
        self.assertTrue(y['deja_decide'])
        self.assertEqual(y['a'], x['a'])
        self.assertEqual(self.run_('etat', chantier='taches')['confirmation_portes']['etat'], 'figees')
        self.assertIn('empreinte', self.run_('sceller', chantier='taches', etape=3))

    def test_l_ecart_ferme_la_fabrication(self):
        self.preparer(['ok'] * 40 + ['corrige'])
        x = self.run_('confirmer_portes', chantier='taches')
        self.assertEqual((x['etat'], x['erreurs'], x['erreurs_permises']), ('ecart', 1, 0))
        self.assertIn('la fabrication est fermée', x['motif'])
        self.assertEqual(self.journal('taches')[-1]['type'], 'fabrication_fermee')
        self.assertIn('fabrication est fermée', self.refus('sceller', chantier='taches', etape=3))
        self.run_('depense', chantier='taches', action='prevoir', passe='etiquetage', role='étiquetage', fournisseur='Groq', modele='m', cout_estime_eur=1)
        self.run_('depense', chantier='taches', action='accepter', passe='etiquetage', citation='ok')
        self.assertIn('Fabrication fermée', self.refus('depense', chantier='taches', action='depenser', passe='etiquetage', montant_eur=0.1))
        with open(os.path.join(self.racine, 'taches', 'etape3', 'fabrication.json'), 'w') as f:
            json.dump({'phases': []}, f)
        self.assertIn('fermée', self.run_('etat', chantier='taches')['fabrication']['fermee'])
        # Rouvrir l'étape 2 (nouvelle tolérance, nouveau calcul) emporte l'écart avec l'ancien calcul.
        self.run_('rouvrir_etape', chantier='taches', etape=2, citation='on rouvre', raison='écart des étiquettes', confirme=True)
        self.assertIsNone(self.run_('etat', chantier='taches')['confirmation_portes'])
        self.run_('depense', chantier='taches', action='depenser', passe='etiquetage', montant_eur=0.1)

    def test_plan_qui_admet_une_erreur(self):
        # Registre etiquettes.erreurs_permises = 1 : le plan compte 473 relectures ; 1 erreur fige, 2 ferment.
        self.calcul_taches(('etiquettes.erreurs_permises', 1), verite={'relues': 10, 'erreurs': 1})
        r = self.run_('etat', chantier='taches')['calcul']
        self.assertEqual((r['etiquettes']['plan']['relectures'], r['etiquettes']['plan']['erreurs_permises']), (473, 1))
        self.assertIn('à confirmer par 473 relectures', r['a_confirmer'][0])
        self.tearDown()
        self.setUp()
        self.preparer([])
        self.run_('registre', chantier='taches', cle='etiquettes.erreurs_permises', valeur=1, citation='x')
        ch = boucle.Chantier(self.racine, 'taches')
        c = ch.lire()
        c['etapes']['2'] = {'etat': 'ouverte'}
        ch.enregistrer(c)
        self.run_('calcul', chantier='taches')
        c = ch.lire()
        c['etapes']['2'] = {'etat': 'scellee'}
        ch.enregistrer(c)
        ecrire_lignes(os.path.join(self.racine, 'taches', 'etape3', 'a-relire.jsonl'),
                      [{'id': f'd{i}', 'lot': 'examen', 'donnee': 'x', 'reponse': 'EXECUTER'} for i in range(480)])
        for i in range(473):
            v = 'corrige' if i == 7 else 'ok'
            self.run_('relire', chantier='taches', action='noter', id=f'd{i}', verdict=v, **({'correction': 'SUGGERER'} if v == 'corrige' else {}))
        x = self.run_('confirmer_portes', chantier='taches')
        self.assertEqual((x['etat'], x['relues'], x['erreurs'], x['erreurs_permises']), ('figees', 473, 1, 1))
        self.assertLessEqual(x['borne_mesuree'], 0.01)

    def preparer_sans_borne(self, verite):
        self.calcul_taches(('etiquettes.erreurs_permises', 1), ('plafond.executer_a_tort.borne_corriges', False), verite=verite)
        ch = boucle.Chantier(self.racine, 'taches')
        c = ch.lire()
        c['etapes']['2'] = {'etat': 'scellee'}
        c['etapes']['3'] = {'etat': 'ouverte'}
        c['sous_etapes'].update({'E3.1': {'etat': 'validee'}, 'E3.2': {'etat': 'validee'}, 'E3.3': {'etat': 'en_cours'}})
        ch.enregistrer(c)
        ecrire_lignes(os.path.join(self.racine, 'taches', 'etape3', 'a-relire.jsonl'),
                      [{'id': f'd{i}', 'lot': 'examen', 'donnee': 'x', 'reponse': 'SUGGERER' if i % 3 == 0 else 'EXECUTER'} for i in range(480)])

    def test_inversion_vers_executer_ferme_la_fabrication(self):
        # REGLE_INVERSIONS_EXECUTER : le plan admet 1 erreur sur 473, la règle 0 inversion vers EXÉCUTER.
        self.preparer_sans_borne({'relues': 10, 'erreurs': 1})
        self.run_('relire', chantier='taches', action='noter', id='d0', verdict='ok')
        self.run_('relire', chantier='taches', action='noter', id='d1', verdict='corrige', correction='FAIRE_REPETER')  # pas une strate
        x = self.run_('confirmer_portes', chantier='taches')
        self.assertEqual((x['etat'], x['erreurs'], x['inversions_vers_executer'], x['inversions_permises']), ('en_attente', 1, 0, 0))
        self.assertIn('inversions vers EXÉCUTER', x['regle_inversions'])
        self.tearDown()
        self.setUp()
        self.preparer_sans_borne({'relues': 10, 'erreurs': 1})
        self.run_('relire', chantier='taches', action='noter', id='d0', verdict='ok')
        self.run_('relire', chantier='taches', action='noter', id='d1', verdict='corrige', correction='NE_RIEN_FAIRE')
        x = self.run_('confirmer_portes', chantier='taches')   # 1 erreur, dans le plan ; mais 1 inversion de trop, dès la 2e relecture
        self.assertEqual((x['etat'], x['erreurs'], x['erreurs_permises'], x['inversions_vers_executer']), ('ecart', 1, 1, 1))
        self.assertIn('1 inversion vers EXÉCUTER', x['motif'])
        self.assertNotIn('écart à la borne prévue', x['motif'])
        self.assertIn('la fabrication est fermée', x['motif'])
        j = self.journal('taches')[-1]
        self.assertEqual((j['type'], j['inversions_vers_executer']), ('fabrication_fermee', 1))
        self.assertIn('fabrication est fermée', self.refus('sceller', chantier='taches', etape=3))

    def test_sans_inversion_les_portes_se_figent(self):
        # Pilote assez grand (300 relues) : rien « à confirmer » pour la borne, mais le scellement attend le compte des inversions.
        self.preparer_sans_borne({'relues': 300, 'erreurs': 0})
        self.assertFalse(self.run_('etat', chantier='taches')['calcul']['etiquettes']['a_confirmer'])
        self.assertIn('pas figées', self.refus('sceller', chantier='taches', etape=3))
        for i in range(473):
            v = 'corrige' if i == 3 else 'ok'   # d3 : réponse SUGGERER corrigée en NE_RIEN_FAIRE, pas une inversion vers EXÉCUTER
            self.run_('relire', chantier='taches', action='noter', id=f'd{i}', verdict=v, **({'correction': 'NE_RIEN_FAIRE'} if v == 'corrige' else {}))
        x = self.run_('confirmer_portes', chantier='taches')
        self.assertEqual((x['etat'], x['relues'], x['erreurs'], x['inversions_vers_executer']), ('figees', 473, 1, 0))
        self.assertAlmostEqual(x['portes']['plafond:SUGGERER']['barre_testee'], 0.98)

    def test_rien_a_confirmer_hors_etape3(self):
        self.calcul_taches(verite={'relues': 10, 'erreurs': 1})
        self.assertIn("l'étape 3 ouverte", self.refus('confirmer_portes', chantier='taches'))



class PlanParSortie(Base):
    """registre etiquettes.plan_par_sortie, REGLE_PLAN_PAR_SORTIE.
    Le plan de fiabilité borne ce que les portes lisent : par sortie, dans le test seulement."""
    ouvrir_etape2, calcul_taches = Etape2.ouvrir_etape2, Etape2.calcul_taches
    REGISTRE_TACHES, PROFILS = Etape2.REGISTRE_TACHES, Etape2.PROFILS
    # Le registre de appli de tâches (portes filtres, cours de 10 704) : l'examen d'EXÉCUTER y est plus petit que les deux strates
    # du plafond réunies, d'où une règle des inversions qui tient sur 473 relectures.
    PAR_SORTIE = (('etiquettes.erreurs_permises', 1), ('plafond.executer_a_tort.borne_corriges', False),
                  ('calcul.portes_filtres', True), ('lots.entrainement_min', 10704), ('etiquettes.plan_par_sortie', True))

    def test_calcul_plan_par_sortie_et_inversions_dans_l_unite_des_strates(self):
        import statistiques as st
        r, _ = self.calcul_taches(*self.PAR_SORTIE, verite={'relues': 300, 'erreurs': 0})
        plan = r['etiquettes']['plan']
        self.assertEqual((plan['par_sortie'], plan['relectures'], plan['relectures_total'], plan['lots']),
                         (True, 473, 1419, ['pre_evaluation', 'examen', 'verification']))
        self.assertEqual(plan['sorties'], ['EXECUTER', 'SUGGERER', 'NE_RIEN_FAIRE'])
        # Le pilote (300 relues, 0 erreur) suffirait au plan d'ensemble, mais pas par sortie dans le test : à confirmer.
        self.assertTrue(r['etiquettes']['a_confirmer'])
        self.assertIn('473 relectures par sortie dans le test (1419 en tout)', r['a_confirmer'][0])
        self.assertIn('au plus 1 erreur par sortie', r['a_confirmer'][0])
        inv = r['etiquettes']['inversions_vers_executer']
        n = r['n_par_sortie']
        rapport = min(sum(n[l][s] for s in ('SUGGERER', 'NE_RIEN_FAIRE')) / n[l]['EXECUTER'] for l in ('examen', 'verification'))
        self.assertAlmostEqual(inv['tolerance'], round(0.0075 * rapport, 10))
        self.assertEqual((inv['relectures'], inv['permises']), (473, st.erreurs_permises(inv['tolerance'], 0.05, 473)))
        u = inv['unite']
        self.assertEqual(u['tolerance_strates'], 0.0075)
        self.assertLessEqual(u['points_strates'], 0.0075 + 1e-9)          # la règle tient dans l'unité des strates
        self.assertGreater(u['points_une_strate'], u['points_strates'])   # limite écrite : une seule strate
        self.assertIn('corrigés EXÉCUTER du test', inv['texte'])
        # Troisième audit, c8 : un minimum par sortie au registre, égal au calcul, n'est plus un écart.
        self.run_('registre', chantier='taches', cle='banc.min_par_sortie_test', valeur=dict(n['examen']), citation='x')
        self.assertEqual(self.run_('calcul', chantier='taches')['ecarts_registre'], [])
        self.run_('registre', chantier='taches', cle='banc.min_par_sortie_test', valeur=dict(n['examen'], SUGGERER=1), citation='x')
        self.assertEqual([e['cle'] for e in self.run_('calcul', chantier='taches')['ecarts_registre']], ['banc.min_par_sortie_test'])
        # Sans la clé : rien ne change (un seul plan, inversions sur les relectures du plan).
        self.tearDown()
        self.setUp()
        r0, _ = self.calcul_taches(*self.PAR_SORTIE[:4], verite={'relues': 300, 'erreurs': 0})
        self.assertNotIn('par_sortie', r0['etiquettes']['plan'])
        self.assertNotIn('unite', r0['etiquettes']['inversions_vers_executer'])
        self.assertEqual(r0['etiquettes']['inversions_vers_executer']['tolerance'], 0.0075)
        self.assertEqual(r0['tailles'], r['tailles'])                     # mêmes tailles : la borne prévue est la même

    def test_cle_refusee_si_pas_booleenne_ou_sans_tolerance(self):
        self.assertIn('true ou false', Etape2.refus_calcul(self, ('etiquettes.plan_par_sortie', 'oui')))
        self.assertIn('etiquettes.tolerance', Etape2.refus_calcul(self, ('etiquettes.plan_par_sortie', True), sans=('etiquettes.tolerance',)))
        # Sans portes filtres, l'examen d'EXÉCUTER dépasse les deux strates réunies : ramenée aux corrigés EXÉCUTER, la
        # tolérance du plafond ne tient plus sur 473 relectures ; le refus dit combien il en faudrait.
        x = Etape2.refus_calcul(self, ('etiquettes.erreurs_permises', 1), ('plafond.executer_a_tort.borne_corriges', False),
                                ('etiquettes.plan_par_sortie', True))
        self.assertIn('ramené aux corrigés EXÉCUTER du test', x)
        self.assertIn('il en faut au moins', x)

    def preparer(self):
        r, _ = self.calcul_taches(*self.PAR_SORTIE, verite={'relues': 10, 'erreurs': 1})
        ch = boucle.Chantier(self.racine, 'taches')
        c = ch.lire()
        c['etapes']['2'] = {'etat': 'scellee'}
        c['etapes']['3'] = {'etat': 'ouverte'}
        c['sous_etapes'].update({'E3.1': {'etat': 'validee'}, 'E3.2': {'etat': 'validee'}, 'E3.3': {'etat': 'en_cours'}})
        ch.enregistrer(c)
        lignes = []
        for u in ('EXECUTER', 'SUGGERER', 'NE_RIEN_FAIRE'):
            lignes += [{'id': f'{u[0]}{i}', 'lot': ('pre_evaluation', 'examen', 'verification')[i % 3], 'donnee': 'x', 'reponse': u}
                       for i in range(480)]
        lignes += [{'id': f'C{i}', 'lot': 'entrainement', 'donnee': 'x', 'reponse': 'SUGGERER'} for i in range(50)]
        ecrire_lignes(os.path.join(self.racine, 'taches', 'etape3', 'a-relire.jsonl'), lignes)
        return r

    def noter(self, notes):
        """notes : [(id, verdict, correction)] écrites dans l'ordre, comme la vue de relecture."""
        ecrire_lignes(os.path.join(self.racine, 'taches', 'etape3', 'relecture-utilisateur.jsonl'),
                      [{'a': 't', 'id': i, 'verdict': v, 'correction': c, 'mot': None, 'lot': None} for i, v, c in notes])

    def test_portes_figees_chaque_sortie_sur_sa_borne(self):
        import statistiques as st
        r = self.preparer()
        # Des erreurs hors du test (cours) ne comptent pas ; SUGGERER : 1 erreur (permise), les autres : 0.
        notes = [(f'C{i}', 'corrige', 'NE_RIEN_FAIRE') for i in range(5)]
        notes += [(f'E{i}', 'ok', None) for i in range(473)]
        notes += [(f'S{i}', 'corrige' if i == 4 else 'ok', 'NE_RIEN_FAIRE' if i == 4 else None) for i in range(300)]
        self.noter(notes)
        x = self.run_('confirmer_portes', chantier='taches')
        self.assertEqual(x['etat'], 'en_attente')
        self.assertIn('SUGGERER : encore 173', x['motif'])
        self.assertIn('NE_RIEN_FAIRE : encore 473', x['motif'])
        self.assertNotIn('EXECUTER : encore', x['motif'])
        self.assertEqual(x['hors_test'], 5)
        self.assertIn('pas figées', self.refus('sceller', chantier='taches', etape=3))
        notes += [(f'S{i}', 'ok', None) for i in range(300, 480)] + [(f'N{i}', 'ok', None) for i in range(480)]
        self.noter(notes)
        x = self.run_('confirmer_portes', chantier='taches')
        self.assertEqual(x['etat'], 'figees')
        self.assertEqual({u: (y['relues'], y['erreurs']) for u, y in x['par_sortie'].items()},
                         {'EXECUTER': (473, 0), 'SUGGERER': (473, 1), 'NE_RIEN_FAIRE': (473, 0)})
        b0, b1 = st.borne_erreur(erreurs=0, relues=473, risque=0.05), st.borne_erreur(erreurs=1, relues=473, risque=0.05)
        self.assertEqual(x['borne_mesuree'], {'EXECUTER': b0, 'SUGGERER': b1, 'NE_RIEN_FAIRE': b0})
        # La justesse de chaque sortie reçoit SA borne ; B1 (compte sur EXÉCUTER) celle d'EXÉCUTER ; le plafond aucune.
        for cid, u in (('justesse:EXECUTER', 'EXECUTER'), ('justesse:SUGGERER', 'SUGGERER'), ('justesse:NE_RIEN_FAIRE', 'NE_RIEN_FAIRE'), ('b1', 'EXECUTER')):
            y = x['portes'][cid]
            self.assertAlmostEqual(y['barre_testee'], round(r['portes_par_critere'][cid]['barre'] + x['borne_mesuree'][u], 6))
            ex = y['lots']['examen']
            self.assertEqual(ex['k'], st.critique(ex['n'], r['portes_par_critere'][cid]['barre'] + x['borne_mesuree'][u], 0.025))
        self.assertAlmostEqual(x['portes']['plafond:SUGGERER']['barre_testee'], 0.98)
        self.assertGreater(x['portes']['justesse:SUGGERER']['barre_testee'] - 0.8, x['portes']['justesse:NE_RIEN_FAIRE']['barre_testee'] - 0.8)
        self.assertIn('chaque sortie sur sa borne mesurée', x['motif'])
        self.assertEqual(x['inversions_vers_executer'], 0)
        e = self.run_('relire', chantier='taches', action='suivante')['etat']
        self.assertEqual(e['par_sortie']['SUGGERER']['erreurs'], 1)
        self.assertIn('empreinte', self.run_('sceller', chantier='taches', etape=3))

    def test_deux_erreurs_dans_une_sortie_ferment_tout_de_suite(self):
        self.preparer()
        # 2 erreurs dans NE_RIEN_FAIRE dès ses 10 premières relectures : écart, même si les autres sorties n'ont rien de relu
        # et que le total (2 sur 1 419) tiendrait dans un plan d'ensemble.
        self.noter([(f'N{i}', 'corrige' if i in (2, 7) else 'ok', 'SUGGERER' if i in (2, 7) else None) for i in range(10)])
        x = self.run_('confirmer_portes', chantier='taches')
        self.assertEqual(x['etat'], 'ecart')
        self.assertIn('NE_RIEN_FAIRE : 2 erreurs sur ses 10 premières relectures du test', x['motif'])
        self.assertIn('la fabrication est fermée', x['motif'])
        self.assertIn('fabrication est fermée', self.refus('sceller', chantier='taches', etape=3))

    def test_une_inversion_dans_les_corriges_executer_du_test_ferme(self):
        self.preparer()
        # Une erreur dans EXÉCUTER est permise par la règle de la sortie, mais c'est une inversion vers EXÉCUTER : 0 admise.
        self.noter([('E0', 'ok', None), ('E1', 'corrige', 'NE_RIEN_FAIRE')])
        x = self.run_('confirmer_portes', chantier='taches')
        self.assertEqual((x['etat'], x['inversions_vers_executer'], x['inversions_permises']), ('ecart', 1, 0))
        self.assertIn('des corrigés EXÉCUTER du test', x['motif'])
        self.assertNotIn('écart à la borne prévue', x['motif'])


class Boucle(Base):
    def preparer(self):
        self.run_('ouvrir', chantier='essai')
        self.run_('terme', chantier='essai', id='N1', libelle='sortie', etat='redecoupe', citation='x')
        self.run_('terme', chantier='essai', id='N2A', libelle='claire', parent='N1', etat='modele', citation='x')
        d = os.path.join(self.racine, 'essai', 'etape4')
        ecrire_lignes(os.path.join(d, 'essais.jsonl'), [
            {'essai': 0, 'strategie': 'depart', 'scores': {'N1': 0.61, 'N2A': 0.7}, 'verdict': 'retenu', 'resume': 'examen à vide'},
            {'essai': 1, 'strategie': 'S1', 'scores': {'N1': 0.8, 'N2A': 0.85}, 'verdict': 'champion', 'resume': 'découpe en deux questions'},
            {'essai': 2, 'strategie': 'S1', 'scores': {'N1': 1.4}, 'verdict': 'champion'},
        ])
        with open(os.path.join(d, 'strategies.json'), 'w') as f:
            json.dump({'S1': {'nom': 'S1', 'idee': 'deux questions', 'etat': 'active', 'essais': 3}, 'S2': {'nom': 'S2', 'etat': 'en_pause', 'essais': 0}}, f)
        with open(os.path.join(d, 'machines.json'), 'w') as f:
            json.dump({'machines': [{'nom': 'tour', 'donnees': 10}, {'nom': 'vr-1', 'donnees': 5}, {'nom': 'vr-2', 'activite': 'libre'}],
                       'total': {'donnees': 20}, 'mesures': [{'essai': 7, 'etat': 'fini'}]}, f)

    def test_tableau_lu_et_controle(self):
        self.preparer()
        b = self.run_('etat', chantier='essai')['boucle']
        self.assertEqual(b['colonnes'], ['N1', 'N2A'])
        self.assertEqual(len(b['essais']), 3)
        quoi = ' | '.join(p['quoi'] for p in b['controle'])
        for attendu in ("l'essai 2 n'a pas de résumé", 'valeur impossible pour N1', "S1 annonce 3 essais, le tableau en a 2",
                        "S2 n'a pas d'idée", "2 essais portent l'étoile", 'vr-2 n\'a pas de relevé', "total (20) n'est pas la somme", "l'essai 7 est absente"):
            self.assertIn(attendu, quoi)
        r = self.run_('controle_boucle', chantier='essai')
        self.assertFalse(r['rien_a_signaler'])
        self.assertEqual(self.journal()[-1]['type'], 'controle_tableau')

    def test_attribution_g3(self):
        # G3 : deux modifications non isolées sont toujours « confondu » ; un verdict inconnu est signalé.
        self.preparer()
        d = os.path.join(self.racine, 'essai', 'etape4')
        ecrire_lignes(os.path.join(d, 'essais.jsonl'), [
            {'essai': 1, 'strategie': 'S1', 'verdict': 'retenu', 'resume': 'r', 'attribution': [{'modification': 'm1', 'verdict': 'aide'}]},
            {'essai': 2, 'strategie': 'S1', 'verdict': 'retenu', 'resume': 'r', 'attribution': [{'modification': 'm1', 'verdict': 'aide'}, {'modification': 'm2', 'verdict': 'confondu'}]},
            {'essai': 3, 'strategie': 'S1', 'verdict': 'retenu', 'resume': 'r', 'attribution': [{'modification': 'm1', 'verdict': 'peut-être'}]},
            {'essai': 4, 'strategie': 'S1', 'verdict': 'retenu', 'resume': 'r', 'attribution': [{'modification': 'm1', 'verdict': 'confondu'}, {'modification': 'm2', 'verdict': 'confondu'}]},
        ])
        quoi = ' | '.join(p['quoi'] for p in self.run_('etat', chantier='essai')['boucle']['controle'])
        self.assertIn("l'essai 2 attribue un effet à une modification non isolée", quoi)
        self.assertIn("verdict d'attribution inconnu à l'essai 3", quoi)
        self.assertNotIn("l'essai 1 attribue", quoi)
        self.assertNotIn("l'essai 4 attribue", quoi)

    def test_greffes_hors_du_calcul_g4(self):
        # Les règles des greffes (methode.json, « greffes_h2 ») ne changent pas le calcul de l'étape 2.
        self.assertNotIn('greffes_h2', boucle.methode({}))
        self.assertEqual(boucle.greffes()['g4_validation']['rattrapages'], 1)
        self.assertIn('validation mécanique du programme', json.dumps(boucle.parcours(), ensure_ascii=False))
        g = boucle.greffes()
        self.assertEqual(g['g1_recherche']['defaut'], 'ciblee')
        self.assertIn('2610.14224', g['decision']['reference'])

    def test_depense_des_lignees_g5(self):
        self.preparer()
        d = os.path.join(self.racine, 'essai', 'etape4')
        ecrire_lignes(os.path.join(d, 'registre-budget-a.jsonl'), [
            {'identite': {'lignee': 'a'}, 'budget': {'sessions_recherche': 10}},
            {'sorte': 'session', 'role': 'recherche', 'etiquette': 'x#1'}, {'sorte': 'mesure', 'role': 'entrainement', 'etiquette': '/m/1'},
            {'sorte': 'mesure', 'role': 'entrainement', 'etiquette': '/m/1'}, {'sorte': 'appels', 'etiquette': 'appels:/m/1', 'appels': 50}])
        ecrire_lignes(os.path.join(d, 'registre-budget-b.jsonl'), [{'identite': {'lignee': 'b'}, 'budget': {'sessions_recherche': 12}}])
        b = self.run_('etat', chantier='essai')['boucle']
        a = next(x for x in b['depense'] if x['lignee'] == 'a')
        self.assertEqual((a['sessions_recherche'], a['mesures'], a['appels'], a['doublons']), (1, 2, 50, ['/m/1']))
        quoi = ' | '.join(p['quoi'] for p in b['controle'])
        self.assertIn('lignée a : étiquettes de dépense en double', quoi)
        self.assertIn("n'ont pas le même plafond", quoi)

    def test_verifier_contexte_g6(self):
        self.preparer()
        d = os.path.join(self.racine, 'essai', 'etape4', 'pour-chercheur')
        ecrire_lignes(os.path.join(d, 'journal.jsonl'), [{'noeud': 1, 'decision': 'examen', 'notes': {'a': 0.5}}])
        r = self.run_('verifier_contexte', chantier='essai', dossier='etape4/pour-chercheur')
        self.assertTrue(r['propre'], r)
        ecrire_lignes(os.path.join(d, 'journal.jsonl'), [{'noeud': 1, 'examen': {'gagnes': 30, 'perdus': 8}}])
        r = self.run_('verifier_contexte', chantier='essai', dossier='etape4/pour-chercheur')
        self.assertEqual((r['propre'], r['fuites'][0]['par']), (False, 'contenu'))
        self.assertTrue(self.run_('verifier_contexte', chantier='essai', dossier='etape4/pour-chercheur', mode='agreges')['fuites'])
        ecrire_lignes(os.path.join(d, 'journal.jsonl'), [{'noeud': 1, 'examen': {'notes': {'a': 0.5}}}])
        # par défaut, aucun agent ne voit l'examen, même agrégé par catégorie
        self.assertEqual(boucle.greffes()['g6_garde']['mode_defaut'], 'aucun')
        self.assertFalse(self.run_('verifier_contexte', chantier='essai', dossier='etape4/pour-chercheur')['propre'])
        self.assertFalse(self.run_('verifier_contexte', chantier='essai', dossier='etape4/pour-chercheur', mode='aucun')['propre'])
        self.assertTrue(self.run_('verifier_contexte', chantier='essai', dossier='etape4/pour-chercheur', mode='agreges')['propre'])
        ecrire_lignes(os.path.join(d, 'exa-r1n3.json'), [{}])
        r = self.run_('verifier_contexte', chantier='essai', dossier='etape4/pour-chercheur')
        self.assertIn('nom', [x['par'] for x in r['fuites']])
        self.assertIn('Dossier refusé', self.refus('verifier_contexte', chantier='essai', dossier='../x'))
        self.assertEqual(self.journal()[-1]['type'], 'verification_contexte')

    def test_audit_porte_g8(self):
        self.preparer()
        pts = [p['id'] for p in boucle.greffes()['g8_audit']['points']]
        self.assertEqual(pts, ['A1', 'A2', 'A3', 'B1', 'B2', 'B3', 'C1', 'C2', 'C3'])
        rep = [{'id': i, 'verdict': 'ok', 'preuve': 'lu'} for i in pts]
        self.assertIn('Points sans réponse : C3', self.refus('audit_porte', chantier='essai', porte='1', reponses=rep[:-1]))
        self.assertIn('preuve', self.refus('audit_porte', chantier='essai', porte='1', reponses=rep[:-1] + [{'id': 'C3', 'verdict': 'ok', 'preuve': ' '}]))
        self.assertTrue(self.run_('audit_porte', chantier='essai', porte='1', version='e1', reponses=rep)['passe'])
        rep[2] = {'id': 'A3', 'verdict': 'echec', 'preuve': 'FAIRE_REPETER +6, EXECUTER -4'}
        r = self.run_('audit_porte', chantier='essai', porte='1', version='e2', reponses=rep)
        self.assertEqual((r['passe'], r['echecs'][0]['id']), (False, 'A3'))
        a = self.run_('etat', chantier='essai')['boucle']['audits']
        self.assertEqual((len(a), a[0]['version'], a[0]['passe']), (1, 'e2', False))

    def test_bibliotheque_g2(self):
        self.preparer()
        bib = os.path.join(self.racine, '_bib')
        ecrire_lignes(os.path.join(bib, 'lecons.jsonl'), [
            {'id': 'L0001', 'statut': 'etablie', 'chantier': 'essai', 'categorie': 'classique', 'situation': 's1', 'lecon': 'ici'},
            {'id': 'L0002', 'statut': 'etablie', 'chantier': 'tickets', 'categorie': 'classique', 'situation': 's2', 'lecon': 'ailleurs'},
            {'id': 'L0003', 'statut': 'etablie', 'chantier': 'tickets', 'situation': 's3', 'lecon': 'revérifiée ici', 'verifications': [{'chantier': 'essai', 'verdict': 'confirmee'}]},
            {'id': 'L0004', 'statut': 'a_prouver', 'chantier': 'email', 'situation': 's4', 'lecon': 'piste'},
            {'id': 'L0005', 'statut': 'sortie', 'chantier': 'tickets', 'situation': 's5', 'lecon': 'contredite'}])
        ancien = os.environ.get('LA_BOUCLE_BIBLIOTHEQUE')
        os.environ['LA_BOUCLE_BIBLIOTHEQUE'] = bib
        try:
            b = self.run_('bibliotheque', chantier='essai')
            self.assertEqual(sorted(x['id'] for x in b['etablies_ici']), ['L0001', 'L0003'])
            self.assertEqual([x['id'] for x in b['a_reverifier']], ['L0002'])
            self.assertEqual((len(b['pistes_non_prouvees']), b['sorties']), (1, 1))
            self.assertEqual(self.run_('etat', chantier='essai')['boucle']['bibliotheque'], {'etablies_ici': 2, 'a_reverifier': 1, 'pistes': 1, 'sorties': 1, 'harnais': 0})
        finally:
            if ancien is None:
                os.environ.pop('LA_BOUCLE_BIBLIOTHEQUE', None)
            else:
                os.environ['LA_BOUCLE_BIBLIOTHEQUE'] = ancien

    def test_boucle_usage_g7(self):
        self.preparer()
        lot = os.path.join(self.racine, 'lot.jsonl')
        lignes = [{'id': f'c{i}', 'a': '2026-11-02T09:00:00Z', 'version': 'v1', 'source': 'test', 'consentement': True,
                   'entree': {'consigne': f'consigne {i}', 'ecran': 'e'}, 'sortie': {'decision': 'EXECUTER'}} for i in range(60)]
        lignes.append({'id': 'x1', 'a': 'a', 'version': 'v1', 'source': 's', 'consentement': False, 'entree': {}, 'sortie': {}})
        lignes.append({**lignes[0], 'id': 'x2', 'etiquette': 'EXECUTER'})
        ecrire_lignes(lot, lignes)
        self.assertIn("après l'examen réussi", self.refus('usage_importer', chantier='essai', fichier=lot))
        cj = os.path.join(self.racine, 'essai', 'chantier.json')
        with open(cj) as f:
            c = json.load(f)
        c['etapes']['4']['etat'] = 'scellee'
        with open(cj, 'w') as f:
            json.dump(c, f)
        r = self.run_('usage_importer', chantier='essai', fichier=lot)
        self.assertEqual(r['scellees'] + r['sonde'], 60)
        self.assertTrue(10 < r['scellees'] < 50)
        self.assertEqual(len(r['refusees']), 2)
        self.assertEqual(self.run_('usage_importer', chantier='essai', fichier=lot)['scellees'], 0)   # doublons ignorés
        for chemin in ('etape5/usage/scellee.jsonl', 'etape5/usage/.graine', 'etape5/usage/etiquettes.jsonl'):
            self.assertIn('tenu par le programme', self.refus('lire', chantier='essai', chemin=chemin))
        self.assertIn('tenu par le programme', self.refus('ecrire', chantier='essai', chemin='etape5/usage/scellee.jsonl', contenu='x'))
        self.assertIn("n'étiquettent jamais", self.refus('usage_etiqueter', chantier='essai', id='c0', etiquette='E', par='sonde-1'))
        sc = self.run_('usage_a_etiqueter', chantier='essai', par='etiqueteur-1', n=50)['donnees']
        ids = [x['id'] for x in sc]
        for i in ids:
            self.run_('usage_etiqueter', chantier='essai', id=i, etiquette='EXECUTER', par='etiqueteur-1')
        d = os.path.join(self.racine, 'essai', 'etape5', 'usage', 'decisions')
        ecrire_lignes(os.path.join(d, 'base.jsonl'), [{'id': i, 'decision': 'FAIRE_REPETER'} for i in ids])
        ecrire_lignes(os.path.join(d, 'cand.jsonl'), [{'id': i, 'decision': 'EXECUTER'} for i in ids])
        banc = {'test': 'signe', 'hausses': 12, 'baisses': 10}
        self.assertEqual(self.run_('usage_juger', chantier='essai', modification='m', base='base.jsonl', candidat='cand.jsonl', banc=banc)['verdict'], 'non_jugeable')
        self.run_('registre', chantier='essai', cle='usage.scellee_min', valeur=10, statut='fixe', citation='test')
        r = self.run_('usage_juger', chantier='essai', modification='m', base='base.jsonl', candidat='cand.jsonl', banc=banc)
        self.assertEqual(r['verdict'], 'adoptee', r)
        r = self.run_('usage_juger', chantier='essai', modification='m2', base='base.jsonl', candidat='cand.jsonl', banc={'test': 'signe', 'hausses': 2, 'baisses': 30})
        self.assertEqual(r['verdict'], 'refusee')
        self.assertIn('banc', r['pourquoi'])
        u = self.run_('etat', chantier='essai')['usage']
        self.assertEqual((u['consultations'], u['etiquetees'], len(u['jugements'])), (2, len(ids), 3))

    def test_sollicitation_en_tete_puis_traitee(self):
        self.preparer()
        ecrire_lignes(os.path.join(self.racine, 'essai', 'etape4', 'sollicitations.jsonl'),
                      [{'id': 'plateau-1', 'quoi': 'plateau sous la porte 1', 'statut': 'ouverte'}])
        v = self.run_('etat', chantier='essai')
        self.assertIn('plateau sous la porte 1', v['attend']['quoi'])
        self.assertIn('mot pour mot', self.refus('traiter_sollicitation', chantier='essai', id='plateau-1'))
        self.run_('traiter_sollicitation', chantier='essai', id='plateau-1', citation='B, refais l’étude', choix='B')
        v = self.run_('etat', chantier='essai')
        self.assertNotIn('sollicite', v['attend']['quoi'])
        self.assertEqual(v['boucle']['sollicitations'], [])


class FinsEtRelances(Base):
    def setUp(self):
        super().setUp()
        self.fins = tempfile.TemporaryDirectory()
        self._f = boucle.FINS
        boucle.FINS = self.fins.name
        self.run_('ouvrir', chantier='essai')
        self.run_('comptes', chantier='essai', action='brancher', compte='compte-b')

    def tearDown(self):
        boucle.FINS = self._f
        self.fins.cleanup()
        super().tearDown()

    def fin(self, nom, code):
        import time
        time.sleep(0.01)
        with open(os.path.join(self.fins.name, nom + '.fin'), 'w') as f:
            f.write(f'{code} 2026-10-14T18:00:00Z')
        future = datetime_now() + 5
        os.utime(os.path.join(self.fins.name, nom + '.fin'), (future, future))

    def test_fin_constatee_par_le_programme(self):
        self.run_('agent', chantier='essai', nom='redacteur', role='rédacteur', sous_etape='E1.6', releve=RELEVE)
        self.run_('agent', chantier='essai', nom='relecteur-a', role='relecteur A', sous_etape='E1.7', releve=RELEVE)
        self.fin('redacteur', 0)
        self.fin('relecteur-a', 2)
        agents = {a['nom']: a for a in self.run_('suivi', chantier='essai', releve=RELEVE)['agents']}
        self.assertEqual(agents['redacteur']['etat'], 'fini')
        self.assertEqual(agents['relecteur-a']['etat'], 'panne')
        self.assertTrue(agents['relecteur-a']['bloque'])
        types = [ev['type'] for ev in self.journal()]
        self.assertIn('agent_fini', types)
        self.assertIn('agent_panne', types)

    def test_relance_limitee(self):
        self.run_('agent', chantier='essai', nom='pilote', role='pilote', relance=['true'], releve=RELEVE)
        self.assertIn('liste', self.refus('agent', chantier='essai', nom='pilote', relance='true'))
        self.fin('pilote', 1)
        a = self.run_('suivi', chantier='essai', releve=RELEVE)['agents'][0]
        self.assertTrue(a['relancable'])
        r = self.run_('relancer', chantier='essai', nom='pilote')
        self.assertEqual((r['etat'], r['relances']), ('travaille', 1))
        self.assertFalse(os.path.exists(os.path.join(self.fins.name, 'pilote.fin')))
        self.assertIn('vient', self.refus('relancer', chantier='essai', nom='pilote'))
        self.assertEqual(self.journal()[-1]['type'], 'agent_relance')


def datetime_now():
    import time
    return time.time()


class Ligne(Base):
    def test_cli_json(self):
        sys_stdin = sys.stdin
        try:
            sys.stdin = io.StringIO(json.dumps({'chantier': 'cli'}))
            out = io.StringIO()
            with redirect_stdout(out):
                boucle.main(['ouvrir', '--racine', self.racine])
            r = json.loads(out.getvalue())
            self.assertTrue(r['ok'])
            sys.stdin = io.StringIO(json.dumps({'chantier': 'cli', 'sous_etape': 'E1.1', 'etat': 'validee'}))
            out = io.StringIO()
            with redirect_stdout(out):
                boucle.main(['avancer', '--racine', self.racine])
            r = json.loads(out.getvalue())
            self.assertFalse(r['ok'])
            self.assertIn('citation', r['refus'])
        finally:
            sys.stdin = sys_stdin


class GreffesEtape4(Base):
    """Les greffes inspirées de Harness² : G1 (test des deux façons au démarrage de l'étape 4),
    G8 (sorties prudentes posées à l'utilisateur avant la première porte), G7 (E5.6 future, ne bloque rien)."""

    def etape(self, n, en_cours):
        self.run_('ouvrir', chantier='taches')
        ch = boucle.Chantier(self.racine, 'taches')
        c = ch.lire()
        for m in range(1, n):
            c['etapes'][str(m)] = {'etat': 'scellee'}
        c['etapes'][str(n)] = {'etat': 'ouverte'}
        c['sous_etapes'][en_cours] = {'etat': 'en_cours'}
        ch.enregistrer(c)
        return ch

    def test_e41_points_g1_g8_poses_avant_validation(self):
        self.etape(4, 'E4.1')
        s = boucle.sous_etape(boucle.Chantier(self.racine, 'taches').lire(), 'E4.1')
        self.assertIn('OBLIGATOIRE au démarrage', s['consigne'])
        self.assertIn('POSES et ne tranches jamais', s['consigne'])
        self.assertIn('D — autre chose, précise-moi', s['consigne'])
        r = self.refus('avancer', chantier='taches', sous_etape='E4.1', etat='validee', citation='go')
        self.assertIn('p01', r)
        self.assertIn('p02', r)
        self.run_('decision', chantier='taches', sous_etape='E4.1', point='p01', resume='plafond commun : 6 mesures par lignée', citation='6 chacune', option='A')
        self.assertIn('p02', self.refus('avancer', chantier='taches', sous_etape='E4.1', etat='validee', citation='go'))
        self.run_('decision', chantier='taches', sous_etape='E4.1', point='p02', resume='sorties prudentes : faire répéter', citation='A', option='A')
        self.run_('avancer', chantier='taches', sous_etape='E4.1', etat='validee', citation='go')
        with open(os.path.join(self.racine, 'taches', 'etape4', 'depart.json')) as f:
            dep = json.load(f)
        self.assertEqual([(x['id'], x['etat']) for x in dep['points']], [('p01', 'tranche'), ('p02', 'tranche')])

    def test_e42_ne_se_valide_pas_sans_le_test_des_deux_facons(self):
        self.etape(4, 'E4.2')
        s = boucle.sous_etape(boucle.Chantier(self.racine, 'taches').lire(), 'E4.2')
        self.assertIn('PREMIER geste', s['consigne'])
        self.assertIn('etape4/test-ab.json', self.refus('avancer', chantier='taches', sous_etape='E4.2', etat='validee', citation='ok'))
        ecrire_lignes(os.path.join(self.racine, 'taches', 'etape4', 'test-ab.json'), [{'gagnante': 'ciblee'}])
        self.run_('avancer', chantier='taches', sous_etape='E4.2', etat='validee', citation='ok')

    def test_e56_future_ne_bloque_ni_la_recette_ni_le_scellement(self):
        ch = self.etape(5, 'E5.5')
        c = ch.lire()
        self.assertEqual(boucle.derniere_sous_etape(c, 5)['id'], 'E5.5')
        self.assertNotIn('E5.6', [x['id'] for x in boucle.actives(c)])
        self.assertIn('future', self.refus('avancer', chantier='taches', sous_etape='E5.6', etat='en_cours'))
        for sid in ('E5.1', 'E5.2', 'E5.3', 'E5.4'):
            self.run_('avancer', chantier='taches', sous_etape=sid, etat='validee', citation='ok')
        v = self.run_('etat', chantier='taches')
        e5 = [e for e in v['etapes'] if e['n'] == 5][0]['sous_etapes']
        self.assertEqual([(x['id'], x['future']) for x in e5][-1], ('E5.6', True))
        self.assertIn('future', e5[-1]['titre'])
        self.assertIn('pas un geste de livraison', e5[-1]['consigne'])
        self.assertEqual(v['attend']['sous_etape'], 'E5.5')
        ecrire_lignes(os.path.join(self.racine, 'taches', 'etape5', 'recette', 'rapport.md'), [{'x': 1}])
        r = self.run_('sceller', chantier='taches', etape=5)
        self.assertNotIn('E5.6', json.dumps(r, ensure_ascii=False))


if __name__ == '__main__':
    unittest.main()


class DocumentsEtape(Base):
    def test_caches_python_hors_du_scellement(self):
        self.run_('ouvrir', chantier='essai')
        base = os.path.join(self.racine, 'essai', 'etape1')
        os.makedirs(os.path.join(base, '__pycache__'), exist_ok=True)
        for rel in ('notation.py', '__pycache__/notation.cpython-312.pyc', 'vieux.pyc'):
            with open(os.path.join(base, rel), 'w') as f:
                f.write('x')

        class C:
            dossier = os.path.join(self.racine, 'essai')

            def chemin(self, *a):
                return os.path.join(self.dossier, *a)
        chemins = [d['chemin'] for d in boucle.documents_etape(C(), 1)]
        self.assertIn('etape1/notation.py', chemins)
        self.assertFalse([c for c in chemins if 'pyc' in c])
