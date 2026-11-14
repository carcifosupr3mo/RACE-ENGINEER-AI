import { useSims } from '../lib/sims'

/** Top-right quick switch. Switching saves the choice, loads that game's profile and starts its data collection. */
export default function SimMenu() {
  const { data, choose, current } = useSims()
  if (!data) return null
  return (
    <label className="simmenu" title="Cambia il simulatore di cui raccogliere i dati">
      <span>Simulatore</span>
      <select value={current?.id ?? ''} onChange={e => choose(e.target.value)} data-testid="sim-menu" aria-label="Simulatore in uso">
        {!current && <option value="">Scegli…</option>}
        {data.sims.map(s => <option key={s.id} value={s.id} disabled={!s.selectable}>{s.name}{s.selectable ? '' : ` (${s.status_label.toLowerCase()})`}</option>)}
      </select>
    </label>)
}
