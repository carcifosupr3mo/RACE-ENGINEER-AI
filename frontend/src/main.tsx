import React from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'

// ONE bundle, two presentation modes of the same app. The Driving Display (/driving-display) is loaded on its own so a
// Raspberry/tablet never downloads the dashboard charts (Plotly).
const isDisplay = location.pathname.replace(/\/+$/, '') === '/driving-display'
const root = createRoot(document.getElementById('root')!)
if (isDisplay) {
  import('./display/DrivingDisplay').then(m => root.render(<m.default />))
} else {
  import('./App').then(m => root.render(<m.default />))
}
