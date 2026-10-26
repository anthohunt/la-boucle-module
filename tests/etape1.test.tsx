import { describe, expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'

import { VUE_ETAPE1 } from './fixtures'

const PANE = { plugin: 'la-boucle-v2', component: 'Pane', requestId: 'la-boucle-v2', props: { title: 'La boucle', isFocused: true, bodyColumns: 100, placement: 'dock', scroll: { offset: 0, bodyRows: 80 }, view: {} } } as const

function monde(on: On) {
  const soumis: string[] = []
  const appels: { commande: string; args: Record<string, unknown> }[] = []
  mock.store(on)
  mock.clock(on, { now: Date.parse('2026-10-14T18:00:00Z') })
  mock.env(on, {})
  on('fs.stat', async () => ({ value: { kind: 'file', size: 1, mtimeMs: 0 } }) as never)
  on('process.run', async (_$, e) => {
    const commande = String(e.argv[e.argv.length - 1])
    appels.push({ commande, args: JSON.parse(String(e.init?.stdin ?? '{}')) })
    const r = commande === 'ouvrir' || commande === 'etat' ? VUE_ETAPE1 : { ok: 1 }
    return { value: { exitCode: 0, stdout: JSON.stringify({ ok: true, resultat: r }), stderr: '' } } as never
  })
  on('tool.register', async (_$, e) => ({ value: { tool: `mcp__la-boucle-v2__${(e as { name: string }).name}` } }) as never)
  on('ui.open', async () => ({ value: { isPlaced: true } }) as never)
  on('command.register', async () => ({ value: undefined }) as never)
  on('session.id', async () => ({ value: 'session-test' }) as never)
  on('prompt.submit', async (_$, e) => (soumis.push(e.text), { text: e.text }) as never)
  return { soumis, appels }
}

const ouvrir = { command: 'la-boucle-v2', args: 'essai', origin: { kind: 'composer' }, presentation: { isFullscreen: true, columns: 160 } } as never

describe("Étape 1 dans le volet (E1.2 à E1.7)", () => {
  test('catégorie, catalogue écran par écran, points du cadrage, arbre, accord des relecteurs, registre', { timeoutMs: 60_000 }, async ($, on) => {
    const { soumis } = monde(on)
    await $.command.run(ouvrir)
    for (const surface of ['terminal', 'desktop'] as const) {
      const ui = await $.ui.mount({ ...PANE, surface })
      expect(await ui.find({ type: 'Text', text: /agent-interaction-logicielle/ })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /Comprendre l'outil/ })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /Catalogue de l'outil : 3 actions, 2 écrans/ })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /repousser une tâche/ })).toBeUndefined()
      await ui.press({ key: 'ecran-Liste' })
      expect(await ui.find({ type: 'Text', text: /repousser une tâche/ })).toBeDefined()
      await ui.press({ key: 'ecran-Liste' })
      expect(await ui.find({ type: 'Text', text: / · 1\/16/ })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /✓ Ce que le modèle décide/ })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /○ L'entrée complète/ })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /N2A consigne claire/ })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /seuils de la couche racine : B1 0\.9 · B2 à fixer/ })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /Passe 1 \(A et B, 2 exemples\) : 1 désaccord/ })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /N1 : accord 50 % · à préciser/ })).toBeDefined()
      await ui.press({ key: 'registre' })
      expect(await ui.find({ type: 'Text', text: /B1 couche 1 : 0\.9/ })).toBeDefined()
      await ui.press({ key: 'registre' })
      await ui.unmount()
    }
    // Rouvrir un point d'un clic ramène la discussion sur lui (E1.4).
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    expect(await ui.find({ key: 'rouvrir-p01' })).toBeUndefined()
    await ui.press({ key: 'ligne-p01' })
    await ui.press({ key: 'rouvrir-p01' })
    expect(soumis.at(-1)).toContain('rouvrir le point p01')
    await ui.unmount()
  })

  test("les outils de l'étape 1 (terme, relecture, accord) passent au programme", { timeoutMs: 60_000 }, async ($, on) => {
    const { appels } = monde(on)
    await $.command.run(ouvrir)
    await $.tool.call({ tool: 'mcp__la-boucle-v2__terme', id: 'N3A', libelle: 'fournisseur', parent: 'N2A', etat: 'liste', liste: ['Orion'], citation: 'oui' } as never)
    await $.tool.call({ tool: 'mcp__la-boucle-v2__relecture', passe: 2, relecteur: 'C', reponses: { ex1: { N1: 'action' } } } as never)
    await $.tool.call({ tool: 'mcp__la-boucle-v2__accord' } as never)
    expect(appels.map(a => a.commande).filter(c => c !== 'etat' && c !== 'suivi')).toEqual(['ouvrir', 'terme', 'relecture', 'accord'])
    expect(appels.find(a => a.commande === 'terme')?.args).toEqual(expect.objectContaining({ chantier: 'essai', id: 'N3A', liste: ['Orion'] }))
  })
})

import { ditPret, sansRappels } from '../hooks/textes'

describe('E1.1 — seul « je suis prêt » valide la bienvenue', () => {
  test('les réponses prêtes', () => {
    for (const t of ["j'ai compris, je suis prêt", 'Prêt', "c'est parti", 'ok on y va', 'Je suis prete', 'go']) expect(ditPret(t)).toBe(true)
  })
  test('une remarque ou une question ne valide rien', () => {
    for (const t of ['je ne vois pas le panel', "je ne suis pas encore prêt", 'attends, une question', 'pas compris']) expect(ditPret(t)).toBe(false)
  })
  test('un rappel système collé au message ne valide rien', () => {
    const rappel = '<system-reminder>\nThe user started this session without choosing a project folder. If they ask, ok, go.\n</system-reminder>'
    expect(ditPret(rappel + '\nouvre le dossier notes-du-chantier')).toBe(false)
    expect(ditPret(rappel + "\nj'ai compris, je suis prêt")).toBe(true)
    expect(sansRappels(rappel + '\nPrêt')).toBe('Prêt')
  })
})
