import { describe, expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'

import { VUE_ETAPE1 } from './fixtures'

const PANE = { plugin: 'la-boucle-v2', component: 'Pane', requestId: 'la-boucle-v2', props: { title: 'La boucle', isFocused: true, bodyColumns: 120, placement: 'dock', scroll: { offset: 0, bodyRows: 80 }, view: {} } } as const

function monde(on: On) {
  const evenements: Record<string, unknown>[] = []
  mock.store(on)
  mock.clock(on, { now: Date.parse('2026-10-14T18:00:00Z') })
  mock.env(on, { CLAUDE_CONFIG_DIR: '/home/operateur/.claude-compte-c' })
  on('fs.stat', async () => ({ value: { kind: 'file', size: 1, mtimeMs: 0 } }) as never)
  on('process.run', async (_$, e) => {
    const commande = String(e.argv[e.argv.length - 1])
    const args = JSON.parse(String(e.init?.stdin ?? '{}')) as Record<string, unknown>
    if (commande === 'evenement') evenements.push(args)
    const r = commande === 'ouvrir' || commande === 'etat' ? VUE_ETAPE1 : {}
    return { value: { exitCode: 0, stdout: JSON.stringify({ ok: true, resultat: r }), stderr: '' } } as never
  })
  on('tool.register', async (_$, e) => ({ value: { tool: `mcp__la-boucle-v2__${(e as { name: string }).name}` } }) as never)
  on('ui.open', async () => ({ value: { isPlaced: true } }) as never)
  on('command.register', async () => ({ value: undefined }) as never)
  on('session.id', async () => ({ value: 'session-test' }) as never)
  on('prompt.submit', async (_$, e) => ({ text: e.text }) as never)
  on('turn.complete', () => ({ text: '' }))
  return evenements
}

const ouvrir = { command: 'la-boucle-v2', args: 'essai', origin: { kind: 'composer' }, presentation: { isFullscreen: true, columns: 160 } } as never

describe('tout mesurer', () => {
  test('chaque tour terminé écrit ses jetons et son compte au journal du chantier ; chaque message, son temps de réponse', { timeoutMs: 60_000 }, async ($, on) => {
    const evenements = monde(on)
    await $.command.run(ouvrir)
    await $.turn.complete({ answer: 'ok', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer', usage: { model: 'claude-opus-5-5', input_tokens: 10, output_tokens: 20, cache_read_input_tokens: 300, cache_creation_input_tokens: 4 } } as never)
    const tour = evenements.find(x => x.type === 'tour_termine')
    expect(tour).toEqual({ chantier: 'essai', type: 'tour_termine', donnees: { compte: '.claude-compte-c', raison: 'answer', modele: 'claude-opus-5-5', jetons_entree: 10, jetons_sortie: 20, jetons_cache_lus: 300, jetons_cache_ecrits: 4 } })
    await $.prompt.submit({ text: 'B', origin: { kind: 'composer' } } as never)
    const msg = evenements.find(x => x.type === 'message_utilisateur')
    expect(msg?.donnees).toEqual(expect.objectContaining({ longueur: 1, temps_reponse_s: 0 }))
  })

  test('le volet a une partie « Mesures » par étape et sous-étape, « non mesuré » plutôt que 0', { timeoutMs: 60_000 }, async ($, on) => {
    monde(on)
    await $.command.run(ouvrir)
    for (const surface of ['terminal', 'desktop'] as const) {
      const ui = await $.ui.mount({ ...PANE, surface })
      await ui.press({ key: 'mesures' })
      expect(await ui.find({ type: 'Text', text: /étape 1 · .* · toi / })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /Le besoin.* · .*échange/ })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /non mesuré : énergie/ })).toBeDefined()
      await ui.press({ key: 'mesures' })
      await ui.unmount()
    }
  })
})
