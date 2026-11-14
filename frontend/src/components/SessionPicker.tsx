import { useEffect, useState } from 'react'
import { api } from '../lib/api'

/** Shared finished-session selector used by the analysis panels. */
export default function SessionPicker({ value, onChange }: { value: string | null; onChange: (id: string) => void }) {
  const [rows, setRows] = useState<any[]>([])
  useEffect(() => { api('/api/sessions').then(r => setRows(r.filter((s: any) => s.status !== 'recording'))) }, [])
  return (
    <label className="inl">Sessione <select value={value ?? ''} onChange={e => onChange(e.target.value)} data-testid="picker">
      <option value="">—</option>{rows.map(s => <option key={s.id} value={s.id}>{s.is_synthetic ? '[SINT] ' : ''}{s.track} · {s.session_type} · </option>)}</select></label>)
}
