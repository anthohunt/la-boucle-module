import { describe, expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'

import { DONNEE_A_RELIRE, VUE_ETAPES34 } from './fixtures'

const PANE = { plugin: 'la-boucle-v2', component: 'Pane', requestId: 'la-boucle-v2', props: { title: 'La boucle', isFocused: true, bodyColumns: 140, placement: 'dock', scroll: { offset: 0, bodyRows: 160 }, view: {} } } as const
const RELECTURE = { ...PANE, requestId: 'la-boucle-v2-relecture' } as const

function monde(on: On) {
  const appels: { commande: string; args: Record<string, unknown> }[] = []
  mock.store(on)
  mock.clock(on, { now: Date.parse('2026-10-14T18:00:00Z') })
  mock.env(on, {})
  on('fs.stat', async () => ({ value: { kind: 'file', size: 1, mtimeMs: 0 } }) as never)
  on('process.run', async (_$, e) => {
    const commande = String(e.argv[e.argv.length - 1])
    const args = JSON.parse(String(e.init?.stdin ?? '{}')) as Record<string, unknown>
    appels.push({ commande, args })
    const r = commande === 'ouvrir' || commande === 'etat' ? VUE_ETAPES34 : commande === 'relire' ? { donnee: DONNEE_A_RELIRE, etat: {} } : {}
    return { value: { exitCode: 0, stdout: JSON.stringify({ ok: true, resultat: r }), stderr: '' } } as never
  })
  on('tool.register', async (_$, e) => ({ value: { tool: `mcp__la-boucle-v2__${(e as { name: string }).name}` } }) as never)
  on('ui.open', async () => ({ value: { isPlaced: true } }) as never)
  on('ui.toast', async () => ({ value: undefined }) as never)
  on('command.register', async () => ({ value: undefined }) as never)
  on('session.id', async () => ({ value: 'session-test' }) as never)
  on('prompt.submit', async (_$, e) => ({ text: e.text }) as never)
  return appels
}

const ouvrir = { command: 'la-boucle-v2', args: 'scelle', origin: { kind: 'composer' }, presentation: { isFullscreen: true, columns: 160 } } as never

describe('Étapes 3 et 4 dans le volet', () => {
  test('E4.3 : une sollicitation de la boucle passe en tête du volet', { timeoutMs: 60_000 }, async ($, on) => {
    monde(on)
    await $.command.run(ouvrir)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    expect(await ui.find({ type: 'Text', text: /La boucle te sollicite : plateau sous la porte 1/ })).toBeDefined()
    await ui.unmount()
  })

  test("E3.1 et E3.2 : la fabrication face au devis, la relecture et sa vue une donnée à la fois", { timeoutMs: 60_000 }, async ($, on) => {
    const appels = monde(on)
    await $.command.run(ouvrir)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    await ui.press({ key: 'basculer-3' })
    expect(await ui.find({ type: 'Text', text: /génération · fini · obtenues 7300 · jetées 128/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /coût réel 3\.20 € pour un devis de 3\.40 €/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /1 relues sur 3 · 0 erreur · erreur maximale prouvée/ })).toBeDefined()
    await ui.press({ key: 'ouvrir-relecture' })
    await ui.unmount()
    for (const surface of ['terminal', 'desktop'] as const) {
      const vue = await $.ui.mount({ ...RELECTURE, surface })
      expect(await vue.find({ type: 'Text', text: /affiche la liste de la semaine 1/ })).toBeDefined()
      expect(await vue.find({ type: 'Text', text: /Bonne réponse : EXECUTER/ })).toBeDefined()
      await vue.unmount()
    }
    const vue = await $.ui.mount({ ...RELECTURE, surface: 'terminal' })
    await vue.input({ key: 'correction', text: 'FAIRE_REPETER' })
    expect(appels.find(a => a.commande === 'relire' && a.args.action === 'noter')?.args).toEqual({ chantier: 'scelle', action: 'noter', id: 'd1', verdict: 'corrige', correction: 'FAIRE_REPETER' })
    await vue.unmount()
  })

  test("E5.6 : la boucle d'usage — consignes reçues, part scellée dès l'arrivée, jugements", { timeoutMs: 60_000 }, async ($, on) => {
    monde(on)
    await $.command.run(ouvrir)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    await ui.press({ key: 'basculer-5' })
    expect(await ui.find({ type: 'Text', text: /La boucle d'usage \(future, après déploiement\)/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /3 consignes réelles reçues · 2 scellées dès l'arrivée \(1 étiquetées, il en faut 200\) · 1 pour la sonde/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /jugements sur la part scellée : 1 sur 5/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /reconnaître « réduis » → non jugeable/ })).toBeDefined()
    await ui.unmount()
  })

  test('E4.2.10 : essais (stratégies, colonnes de l’arbre, champion, arrêté tôt), machines, journal des essais', { timeoutMs: 60_000 }, async ($, on) => {
    monde(on)
    await $.command.run(ouvrir)
    for (const surface of ['terminal', 'desktop'] as const) {
      const ui = await $.ui.mount({ ...PANE, surface })
      expect(await ui.find({ type: 'Text', text: /^Essais/ })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /indice 96 % · chances 40 %/ })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /N1 \(min 90 %\)  N2A/ })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /★ 1 / })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /≈70 %/ })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /arrêté tôt/ })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /essai 3 \(S1\) : 412 \/ 800/ })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /poste-1 · GPU 24 Go · essai 3 · 412 données · 90\/min · 310 W/ })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /poste-2 · hors ligne/ })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /Bibliothèque : 0 leçon\(s\) établie\(s\) ici · 1 à revérifier sur ce banc · 1 piste\(s\) non prouvée\(s\) · 0 harnais gardé/ })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /Audit avant la porte 1 \(essai 1\) : porte fermée — A3 : FAIRE_REPETER \+6 pts/ })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /Dépense de la lignée principale : 1 sessions de recherche · 1 mesures · 1\s200 appels au petit modèle · plafond 30 sessions/ })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /toutes les machines : 412 données · 90\/min · 9 min par mesure/ })).toBeDefined()
      expect((await ui.find({ key: 'strat:S1' }))?.text).toContain('découper en deux questions')
      expect((await ui.find({ key: 'detail-1' }))?.text).toContain('deux questions puis vote')
      await ui.press({ key: 'detail-1' })
      expect(await ui.find({ type: 'Text', text: /pose d’abord la question de fond/ })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /méthode · deux questions → confondu/ })).toBeDefined()
      await ui.press({ key: 'detail-1' })
      await ui.unmount()
    }
  })
})
