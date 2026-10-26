import { describe, expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'

import type { Vue } from '../types'
import { VUE_A_SCELLER, VUE_SCELLEE } from './fixtures'

const PANE = { plugin: 'la-boucle-v2', component: 'Pane', requestId: 'la-boucle-v2', props: { title: 'La boucle', isFocused: true, bodyColumns: 100, placement: 'dock', scroll: { offset: 0, bodyRows: 80 }, view: {} } } as const

function monde(on: On, v: Vue) {
  const appels: string[] = []
  mock.store(on)
  mock.clock(on, { now: Date.parse('2026-10-14T18:00:00Z') })
  mock.env(on, {})
  on('fs.stat', async () => ({ value: { kind: 'file', size: 1, mtimeMs: 0 } }) as never)
  on('process.run', async (_$, e) => {
    const commande = String(e.argv[e.argv.length - 1])
    appels.push(commande)
    const r = commande === 'ouvrir' || commande === 'etat' ? v : commande === 'lire' ? { contenu: '{"etape": 1}', chemin: 'etape1/scelle.json' } : { empreinte: 'abc' }
    return { value: { exitCode: 0, stdout: JSON.stringify({ ok: true, resultat: r }), stderr: '' } } as never
  })
  on('tool.register', async (_$, e) => ({ value: { tool: `mcp__la-boucle-v2__${(e as { name: string }).name}` } }) as never)
  on('ui.open', async () => ({ value: { isPlaced: true } }) as never)
  on('command.register', async () => ({ value: undefined }) as never)
  on('session.id', async () => ({ value: 'session-test' }) as never)
  on('prompt.submit', async (_$, e) => ({ text: e.text }) as never)
  return appels
}

const ouvrir = (nom: string) => ({ command: 'la-boucle-v2', args: nom, origin: { kind: 'composer' }, presentation: { isFullscreen: true, columns: 160 } }) as never

describe('sceller une étape', () => {
  test("à sceller : le volet dit d'attendre la confirmation sur le téléphone, avec l'empreinte", { timeoutMs: 60_000 }, async ($, on) => {
    monde(on, VUE_A_SCELLER)
    await $.command.run(ouvrir('scelle'))
    for (const surface of ['terminal', 'desktop'] as const) {
      const ui = await $.ui.mount({ ...PANE, surface })
      expect(await ui.find({ type: 'Text', text: /À confirmer par le canal de confirmation/ })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /empreinte [0-9a-f]{12}/ })).toBeDefined()
      expect((await ui.find({ key: 'basculer-1' }))?.text).toContain('à sceller')
      await ui.unmount()
    }
  })

  test("scellée : verrou, date, empreinte, fichier scellé ouvrable ; l'étape 2 s'ouvre", { timeoutMs: 60_000 }, async ($, on) => {
    const appels = monde(on, VUE_SCELLEE)
    await $.command.run(ouvrir('scelle'))
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    expect((await ui.find({ key: 'basculer-1' }))?.text).toContain('scellée')
    expect((await ui.find({ key: 'basculer-2' }))?.text).toContain("L'étude des données")
    expect(await ui.find({ type: 'Text', text: /Le type de donnée/ })).toBeDefined()
    await ui.press({ key: 'basculer-1' })
    expect(await ui.find({ type: 'Text', text: /verrou · / })).toBeDefined()
    await ui.press({ key: 'scelle-fichier-1' })
    expect(appels).toContain('lire')
    await ui.unmount()
  })

  test("les outils sceller et rouvrir_etape passent au programme", { timeoutMs: 60_000 }, async ($, on) => {
    const appels = monde(on, VUE_A_SCELLER)
    await $.command.run(ouvrir('scelle'))
    await $.tool.call({ tool: 'mcp__la-boucle-v2__sceller', etape: 1 } as never)
    await $.tool.call({ tool: 'mcp__la-boucle-v2__rouvrir_etape', etape: 1, raison: 'x', citation: 'oui', confirme: true } as never)
    expect(appels.filter(c => c !== 'etat' && c !== 'suivi')).toEqual(['ouvrir', 'sceller', 'rouvrir_etape'])
  })
})
