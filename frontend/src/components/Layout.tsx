import { Outlet, Link } from 'react-router-dom'

export default function Layout() {
  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <nav style={{ padding: '1rem', borderBottom: '1px solid #ccc' }}>
        <ul style={{ display: 'flex', gap: '1rem', listStyle: 'none', margin: 0, padding: 0 }}>
          <li><Link to="/">Dashboard</Link></li>
          <li><Link to="/strategy-studio">Strategy Studio</Link></li>
          <li><Link to="/runs">Runs</Link></li>
          <li><Link to="/feeds">Feeds</Link></li>
          <li><Link to="/approvals">Approvals</Link></li>
          <li><Link to="/overrides">Overrides</Link></li>
          <li><Link to="/audit">Audit</Link></li>
          <li><Link to="/queues">Queues</Link></li>
          <li><Link to="/artifacts">Artifacts</Link></li>
        </ul>
      </nav>
      <main style={{ flex: 1, padding: '2rem' }}>
        <Outlet />
      </main>
    </div>
  )
}
