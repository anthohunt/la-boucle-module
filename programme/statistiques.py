"""Statistiques exactes du calcul de l'étape 2 (E2.9, E2.12, E2.14).

Fonctions _queue_courte, _queue, _critique, borne_erreur, _dimensionner, _niveau_predit de la recette de la boucle,
sans dépendance au registre d'un chantier. Chiffres de contrôle : 535 données par sortie à l'examen au risque
5 %/(2 × 3), 83 ratés au plus sur 1 070 (vérifiés par programme/tests/test_boucle.py).
Binomiale exacte, sans approximation normale. Ce module ne fait que des tests binomiaux d'UN critère ; boucle.py
(cmd_calcul) en pose un par critère et par lot (une porte par sortie, le plafond, B1), sans jamais mélanger les
sorties, et règle le risque de chaque lot.
"""
import math
from functools import lru_cache


def queue_courte(n, p, k, direction):
    """Sommer depuis la masse près du mode vers la queue, sans sous-flux initial."""
    terme = math.exp(math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
                     + k * math.log(p) + (n - k) * math.log1p(-p))
    termes = [terme]
    total = terme
    while 0 <= k + direction <= n:
        if direction == 1:
            terme *= (n - k) / (k + 1) * p / (1 - p)
        else:
            terme *= k / (n - k + 1) * (1 - p) / p
        k += direction
        termes.append(terme)
        if total + terme == total:
            break  # Les termes suivants décroissent : précision machine seulement.
        total += terme
    return min(1.0, math.fsum(termes))


def queue(n, p, k):
    """P[Bin(n,p) >= k], sans approximation normale."""
    if k <= 0:
        return 1.0
    if k > n or p == 0:
        return 0.0
    if p == 1:
        return 1.0
    if k > n * p:
        return queue_courte(n, p, k, 1)
    return max(0.0, 1 - queue_courte(n, p, k - 1, -1))


def critique(n, p, risque):
    """Premier nombre de succès rejetant H0:p ; n+1 indique une porte impossible."""
    bas, haut = 0, n + 1
    while bas < haut:
        milieu = (bas + haut) // 2
        if queue(n, p, milieu) <= risque:
            haut = milieu
        else:
            bas = milieu + 1
    return bas


def borne_erreur(*, erreurs, relues, risque):
    """Borne supérieure binomiale exacte unilatérale (A88), pas Wald/Wilson."""
    if erreurs > relues:
        raise ValueError('erreurs supérieures au nombre de relectures')
    if erreurs == relues:
        return 1.0
    if erreurs == 0:
        return -math.expm1(math.log(risque) / relues)
    bas, haut = 0.0, 1.0
    for _ in range(64):  # Résolution numérique, sans effet sur le risque de méthode.
        milieu = (bas + haut) / 2
        # P[X <= erreurs] = P[Bin(n,1-p) >= n-erreurs].
        if queue(relues, 1 - milieu, relues - erreurs) > risque:
            bas = milieu
        else:
            haut = milieu
    return haut


@lru_cache(maxsize=128)
def dimensionner(risque, puissance, gain):
    """Plus petit n du test confirmé, avec puissance exacte (pas une table fixe)."""
    p0, p1 = (1 - gain) / 2, (1 + gain) / 2
    # Hoeffding fournit uniquement la fin de recherche ; chaque n est testé
    # exactement. n >= (sqrt(log(1/alpha)/2)+sqrt(log(1/beta)/2))² / gain².
    borne = ((math.sqrt(-math.log(risque) / 2)
              + math.sqrt(-math.log1p(-puissance) / 2)) / gain) ** 2
    if not math.isfinite(borne):
        raise ValueError('dimensionnement hors précision numérique')
    for n in range(1, math.ceil(borne) + 2):
        if queue(n, p1, critique(n, p0, risque)) >= puissance:
            return n
    raise ValueError('dimensionnement binomial non résolu, aucun repli')


def niveau_predit(n, k, puissance):
    if k > n:
        return (n + 1) / n
    bas, haut = 0.0, 1.0
    for _ in range(64):
        milieu = (bas + haut) / 2
        if queue(n, milieu, k) < puissance:
            bas = milieu
        else:
            haut = milieu
    return haut



def dimensionner_niveaux(risque, puissance, p0, p1):
    """« Au plus juste » (E2.10) : le plus petit n qui sépare la barre p0 du niveau visé p1 à leurs vrais niveaux
    (le calcul prudent, dimensionner, centre les deux proportions sur 1/2, le cas le plus irrégulier)."""
    if not 0 < p0 < p1 < 1:
        raise ValueError('il faut 0 < barre < niveau visé < 1')
    for n in range(1, 2_000_000):
        if queue(n, p1, critique(n, p0, risque)) >= puissance:
            return n
    raise ValueError('dimensionnement non résolu')


def plus_petit_n(passe, debut=1, fin=10_000_000):
    """Plus petit n tel que passe(n), par doublement puis bisection (la puissance binomiale n'est pas strictement
    monotone en n : le n rendu vérifie passe(n) ; un n plus petit de quelques unités peut, rarement, la vérifier aussi).
    None si aucun n ≤ fin."""
    n = max(1, int(debut))
    if passe(n):
        return n
    while not passe(2 * n):
        n *= 2
        if n > fin:
            return None
    bas, haut = n, 2 * n
    while haut - bas > 1:
        milieu = (bas + haut) // 2
        if passe(milieu):
            haut = milieu
        else:
            bas = milieu
    return haut


def relectures_necessaires(tolerance, risque, erreurs=0):
    """Plus petit nombre de relectures qui, avec `erreurs` erreurs trouvées, donne une borne exacte (borne_erreur,
    même risque) au plus égale à la tolérance. Sans erreur : n ≥ log(risque) / log(1 − tolérance) (« règle de trois »
    exacte : ≈ 3 / tolérance au risque 5 %). La borne décroît quand n croît, à erreurs fixées."""
    if not 0 < tolerance < 1:
        raise ValueError('il faut 0 < tolérance < 1')
    def passe(n):
        return n > erreurs and borne_erreur(erreurs=erreurs, relues=n, risque=risque) <= tolerance
    debut = erreurs + 1
    if erreurs == 0:
        debut = max(1, math.floor(math.log(risque) / math.log1p(-tolerance)) - 1)
    return plus_petit_n(passe, debut)


def erreurs_permises(tolerance, risque, relues):
    """Le plus grand nombre d'erreurs sur `relues` relectures qui garde la borne au plus égale à la tolérance
    (−1 : même zéro erreur ne suffit pas)."""
    e = -1
    while e + 1 < relues and borne_erreur(erreurs=e + 1, relues=relues, risque=risque) <= tolerance:
        e += 1
    return e
