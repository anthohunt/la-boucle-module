"""Generates docs/architecture*.svg (EN + FR) for la-boucle-module, Atelier/parc style."""
import sys, os
from xml.sax.saxutils import escape as E
OUT = sys.argv[1]
BLUE, INK, MUTED, LINE, ZONE, YEL, YELINK = '#1f4fd1', '#14213d', '#5d6b82', '#c9d1dd', '#e6ebf2', '#ffd23f', '#5a4500'
FONT = 'IBM Plex Sans, Segoe UI, Helvetica Neue, Arial, sans-serif'
MONO = 'IBM Plex Mono, Consolas, monospace'
LX, RX, BW, BH = 30, 280, 170, 56

def tw(s, size): return len(s) * size * 0.56

class D:
    def __init__(s, w, h, title):
        s.w, s.h, s.p = w, h, []
        s.title = title
    def zone(s, y, h, label):
        s.p.append(f'<rect x="20" y="{y}" width="440" height="{h}" rx="14" fill="{ZONE}" stroke="{LINE}" stroke-dasharray="4 4"/>'
                   f'<text x="34" y="{y+20}" fill="{MUTED}" font-size="12" font-weight="600" letter-spacing=".7">{E(label)}</text>')
    def box(s, col, y, t, sub, model=None, strong=True, pill='top'):
        x = LX if col == 'L' else RX
        st = f'stroke="{BLUE}" stroke-width="2.2"' if strong else f'stroke="{LINE}" stroke-width="1.4"'
        s.p.append(f'<rect x="{x}" y="{y}" width="{BW}" height="{BH}" rx="10" fill="#fff" {st}/>'
                   f'<text x="{x+12}" y="{y+24}" fill="{INK}" font-size="16" font-weight="600">{E(t)}</text>'
                   f'<text x="{x+12}" y="{y+44}" fill="{MUTED}" font-size="13.5">{E(sub)}</text>')
        if model:
            w = tw(model, 10.5) + 12
            py = y - 9 if pill == 'top' else y + BH - 9
            s.p.append(f'<rect x="{x+BW-w+6}" y="{py}" width="{w}" height="18" rx="9" fill="{YEL}"/>'
                       f'<text x="{x+BW-w/2+6}" y="{py+13}" text-anchor="middle" fill="{YELINK}" font-size="10.5" font-weight="700" letter-spacing=".4">{E(model)}</text>')
    def arrow(s, d, label=None, at=None, num=None, grey=False, numpos='left', rot=False):
        c, sw, m = (MUTED, 1.6, 'm') if grey else (BLUE, 2.4, 'a')
        s.p.append(f'<path d="{d}" fill="none" stroke="{c}" stroke-width="{sw}" marker-end="url(#{m})"/>')
        if label:
            x, y = at
            w = tw(label, 13) + 10
            fw = '400' if grey else '600'
            if rot:
                s.p.append(f'<g transform="rotate(-90 {x} {y})"><rect x="{x-w/2}" y="{y-9}" width="{w}" height="18" rx="4" fill="#fff"/>'
                           f'<text x="{x}" y="{y+4.5}" text-anchor="middle" fill="{c}" font-size="13" font-weight="{fw}">{E(label)}</text></g>')
            else:
                s.p.append(f'<rect x="{x-w/2}" y="{y-9}" width="{w}" height="18" rx="4" fill="#fff"/>'
                           f'<text x="{x}" y="{y+4.5}" text-anchor="middle" fill="{c}" font-size="13" font-weight="{fw}">{E(label)}</text>')
            if num:
                cx, cy = (x - w/2 - 12, y) if numpos == 'left' else (x, y - 21)
                s.p.append(f'<circle cx="{cx}" cy="{cy}" r="10" fill="#fff" stroke="{BLUE}" stroke-width="1.6"/>'
                           f'<text x="{cx}" y="{cy+4}" text-anchor="middle" fill="{BLUE}" font-size="12" font-weight="700" font-family="{MONO}">{num}</text>')
    def svg(s):
        head = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {s.w} {s.h}" width="{s.w}" height="{s.h}" font-family="{FONT}" role="img" aria-label="{E(s.title)}">'
                f'<title>{E(s.title)}</title><defs>'
                f'<marker id="m" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="{MUTED}"/></marker>'
                f'<marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="{BLUE}"/></marker></defs>'
                f'<rect width="{s.w}" height="{s.h}" rx="16" fill="#ffffff"/>')
        return head + '\n'.join(s.p) + '</svg>\n'

T = {
 'en': dict(
  t1='La boucle module: one gesture, from the operator to the worksite files',
  z1='YOU', z2='CLAUDE CODE', z3='PROGRAM · PYTHON · NO MODEL', z4='WORKSITE', z5='STEPS 3–4',
  op=('Operator', 'terminal or Desktop'), conf=('Seal confirmation', 'confirmer.py, as root'),
  cl=('Claude', "the session's model"), mod=('Mod la-boucle-v2', 'pane · band · tools'),
  met=('Method data', '5 steps · statistics'), prg=('boucle.py', 'one command a gesture'),
  dec=('Decisions · journal', 'word for word, timed'), out=('Outputs · register', 'etapeN/ · seals'),
  ag=('Claude agents', 'via your launcher'), eng=('la-boucle-engine', 'loop · judge · exam'),
  model='MODEL', small='SMALL MODEL',
  a1='answers', a2='tool call', a2b='protocol', a3='JSON · local or SSH', a4='writes, word for word', a5='pane · band',
  g_rules='rules', g_fp='fingerprint file', g_runs='runs', g_bench='reads bench', g_same='same mod, same tools',
  t2='La boucle module: steps 3 and 4, the bench and the loop',
  y1='WORKSITE PROGRAM · NO MODEL', y2='CLAUDE AGENTS', y3='LA-BOUCLE-ENGINE', y4='BENCH · SUBJECT',
  plan=('Sealed plan', 'sizes · thresholds'), banc=('Sealed bench', 'you confirm the seal'),
  fab=('Bench builders', 'write · label · check'), loop=('Loop agent', 'starts the engine'),
  res=('Researcher', 'edits a harness copy'), jud=('Judge', 'marks every case'),
  subj=('Small model', '+ harness under test'), exam=('Sealed exam', 'judge only'),
  b1='plan', b2='bench', b3='sealed bench', b4='boucle run', b5='candidate', b6='runs each case', b7='vs champion', b8='ready?', bg='mistakes'),
 'fr': dict(
  t1="Module La boucle : un geste, de l'opérateur aux fichiers du chantier",
  z1='VOUS', z2='CLAUDE CODE', z3='PROGRAMME · PYTHON · AUCUN MODÈLE', z4='CHANTIER', z5='ÉTAPES 3–4',
  op=('Opérateur', 'terminal ou Desktop'), conf=('Confirmation', 'confirmer.py, en root'),
  cl=('Claude', 'modèle de la session'), mod=('Mod la-boucle-v2', 'volet · bandeau · outils'),
  met=('Méthode', '5 étapes · statistiques'), prg=('boucle.py', 'commande par geste'),
  dec=('Décisions · journal', 'mot pour mot, datées'), out=('Sorties · registre', 'etapeN/ · scellés'),
  ag=('Agents Claude', 'par votre lanceur'), eng=('la-boucle-engine', 'boucle · juge · examen'),
  model='MODÈLE', small='PETIT MODÈLE',
  a1='répond', a2='outil', a2b='protocole', a3='JSON · local ou SSH', a4='écrit, mot pour mot', a5='volet · bandeau',
  g_rules='règles', g_fp='fichier d’empreinte', g_runs='lance', g_bench='lit le banc', g_same='même mod, mêmes outils',
  t2='Module La boucle : étapes 3 et 4, le banc et la boucle',
  y1='PROGRAMME DU CHANTIER · AUCUN MODÈLE', y2='AGENTS CLAUDE', y3='LA-BOUCLE-ENGINE', y4='BANC · SUJET',
  plan=('Plan scellé', 'tailles · seuils'), banc=('Banc scellé', 'vous confirmez'),
  fab=('Fabricants du banc', 'écrire · étiqueter · vérifier'), loop=('Agent de boucle', 'lance le moteur'),
  res=('Chercheur', 'modifie une copie'), jud=('Juge', 'note chaque cas'),
  subj=('Petit modèle', '+ harnais testé'), exam=('Examen scellé', 'lu du juge seul'),
  b1='plan', b2='banc', b3='banc scellé', b4='boucle run', b5='candidat', b6='chaque cas', b7='vs champion', b8='prêt ?', bg='erreurs'),
}

for lang, t in T.items():
    sfx = '' if lang == 'en' else '.fr'
    # Overview
    d = D(480, 680, t['t1'])
    for y, z in ((10, 'z1'), (150, 'z2'), (290, 'z3'), (430, 'z4'), (570, 'z5')):
        d.zone(y, 96, t[z])
    d.box('L', 40, *t['op']); d.box('R', 40, *t['conf'], strong=False)
    d.box('L', 180, *t['cl'], model=t['model']); d.box('R', 180, *t['mod'])
    d.box('L', 320, *t['met'], strong=False); d.box('R', 320, *t['prg'])
    d.box('L', 460, *t['dec']); d.box('R', 460, *t['out'])
    d.box('L', 600, *t['ag'], model=t['model']); d.box('R', 600, *t['eng'], model=t['small'])
    d.arrow('M140 96V180', t['a1'], (140, 128), 1)
    d.arrow('M200 200H280', t['a2'], (240, 200), 2, numpos='above')
    d.arrow('M280 222H200', t['a2b'], (240, 223), grey=True)
    d.arrow('M360 236V320', t['a3'], (360, 270), 3)
    d.arrow('M360 376V460', None)
    d.arrow('M360 412H140V460', t['a4'], (240, 412), 4)
    d.arrow('M330 180V130H170V96', t['a5'], (275, 130), 5)
    d.arrow('M200 348H280', t['g_rules'], (240, 348), grey=True)
    d.arrow('M450 68H469V348H450', t['g_fp'], (469, 210), grey=True, rot=True)
    d.arrow('M200 628H280', t['g_runs'], (240, 628), grey=True)
    d.arrow('M320 600V516', t['g_bench'], (320, 556), grey=True)
    d.arrow('M30 628H11V214H30', t['g_same'], (11, 420), grey=True, rot=True)
    open(os.path.join(OUT, f'architecture{sfx}.svg'), 'w').write(d.svg())
    # Backend detail
    d = D(480, 540, t['t2'])
    for y, z in ((10, 'y1'), (150, 'y2'), (290, 'y3'), (430, 'y4')):
        d.zone(y, 96, t[z])
    d.box('L', 40, *t['plan']); d.box('R', 40, *t['banc'])
    d.box('L', 180, *t['fab'], model=t['model'], pill='bottom'); d.box('R', 180, *t['loop'], model=t['model'])
    d.box('L', 320, *t['res'], model=t['model'], pill='bottom'); d.box('R', 320, *t['jud'])
    d.box('L', 460, *t['subj'], model=t['small'], pill='bottom'); d.box('R', 460, *t['exam'], strong=False)
    d.arrow('M160 96V180', t['b1'], (160, 132), 1)
    d.arrow('M200 208H240V68H280', t['b2'], (240, 132), 2, numpos='above')
    d.arrow('M360 96V180', t['b3'], (360, 132), 3)
    d.arrow('M340 236V266H180V320', t['b4'], (260, 266), 4)
    d.arrow('M200 336H280', t['b5'], (240, 336), 5, numpos='above')
    d.arrow('M280 362H200', t['bg'], (240, 362), grey=True)
    d.arrow('M330 376V412H180V460', t['b6'], (255, 412), 6)
    d.arrow('M400 376V460', t['b7'], (400, 420), 7)
    d.arrow('M420 320V236', t['b8'], (420, 278), 8)
    open(os.path.join(OUT, f'architecture-loop{sfx}.svg'), 'w').write(d.svg())
print('ok')
