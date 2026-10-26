# Boucle d'usage après livraison — interface du livrable (greffe G7)

Rien n'est enregistré avant l'entraînement : la boucle d'usage ne démarre qu'après l'examen réussi (étape 4 scellée)
ou la recette (E5.5).

**FUTURE.** Rien à écrire maintenant, dans aucun livrable. Une fois une version déployée, ses consignes et ses réponses
pourront être journalisées en production et servir de données d'entraînement futures. E5.6 est une sous-étape future :
elle ne s'ouvre pas et ne bloque ni la recette ni le scellement. La taille de la part réelle scellée n'est pas décidée.

Ce fichier décrit le format qu'aura le journal de production d'une version déployée, le jour venu, pour que la sous-étape
E5.6 puisse l'importer (outil `usage_importer`). Le module La boucle ne touche pas au dépôt du livrable.

## Le journal des consignes réelles

Un fichier JSON Lines, en ajout seulement (jamais réécrit), une ligne par consigne réellement donnée à l'assistant, en
UTF-8. Le livrable l'écrit sur le poste de test ; il est copié vers la machine du programme par lots (fichier entier ou lignes nouvelles),
puis importé. Exemple pour l'appli de tâches fictive « Mini-tâches » (une ligne, présentée sur plusieurs) :

```json
{"id": "minitaches-2026-11-02T09:14:07.512Z-3f9c",
 "a": "2026-11-02T09:14:07Z",
 "version": "sha256:48b0cd52596f…",
 "source": "minitaches-test",
 "consentement": true,
 "session": "testeur-1-matin",
 "entree": {"consigne": "repousse la tâche du garage à demain",
            "ecran": "liste-semaine",
            "etat": {"filtre": "cette-semaine", "selection": null}},
 "sortie": {"decision": "EXECUTER", "commande": "repousser_tache", "parametres": {"tache": "garage", "jours": 1},
            "confiance": 0.81, "latence_s": 0.58, "appels": 2}}
```

| Champ | Obligatoire | Ce que c'est |
| --- | --- | --- |
| `id` | oui | unique et stable (horodatage + hasard) ; un doublon est ignoré à l'import |
| `a` | oui | l'heure de la consigne, UTC, ISO 8601 |
| `version` | oui | l'empreinte de la version du livrable (manifeste de la version figée, étape 4) |
| `source` | oui | d'où vient la ligne (ex. `minitaches-test`) |
| `consentement` | oui, `true` | l'utilisateur a accepté que ses consignes en test soient notées ; sinon la ligne est refusée |
| `entree` | oui, objet | l'entrée COMPLÈTE donnée au petit modèle : la consigne mot pour mot ET l'état de l'écran |
| `sortie` | oui, objet | ce que l'agent a rendu : décision, commande et paramètres, confiance, temps, nombre d'appels |
| `session` | non | pour regrouper les consignes d'une même séance |

Interdit dans le journal : toute étiquette ou « bonne réponse » (la ligne est refusée : l'étiquette vient après coup, d'un
agent d'étiquetage séparé, et seulement pour la part scellée) ; toute donnée hors de l'appli (le journal ne quitte la
machine que sur la décision de l'utilisateur).

## Ce que le programme en fait

1. À l'import, chaque consigne nouvelle est rangée AVANT que quiconque la voie : part scellée (tirage secret, graine du
   chantier, fraction `usage.part_scellee`, 0,5 par défaut) ou part de la sonde.
2. La sonde (agent frais, jamais un chercheur de l'étape 4) ne lit que sa part : refus et erreurs sur des consignes
   claires, contrastes entre consignes proches, confiances basses ; elle propose des modifications du harnais.
3. Chaque modification repart à l'étape 4 comme un essai. Elle n'est retenue que si `usage_juger` dit « adoptee » : aucun
   recul significatif sur le banc (test apparié) ET un gain significatif sur la part scellée étiquetée (test du signe
   apparié, au risque de la méthode), sur au moins `usage.scellee_min` consignes (200 par défaut, à dimensionner à l'étape 2).
4. Les décisions des deux versions sur la part scellée sont rejouées par le programme verrouillé (comme l'examen) et
   déposées dans `etape5/usage/decisions/<nom>.jsonl` (`{"id", "decision"}`), jamais par un agent.
5. Chaque jugement use la part scellée ; après `usage.consultations_max` (5) jugements, elle se renouvelle avec des
   consignes neuves (`usage_renouveler`, sur l'accord de l'utilisateur).
