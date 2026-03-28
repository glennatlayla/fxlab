import { createBrowserRouter } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import StrategyStudio from './pages/StrategyStudio'
import Runs from './pages/Runs'
import Feeds from './pages/Feeds'
import Approvals from './pages/Approvals'
import Overrides from './pages/Overrides'
import Audit from './pages/Audit'
import Queues from './pages/Queues'
import Artifacts from './pages/Artifacts'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <Layout />,
    children: [
      {
        index: true,
        element: <Dashboard />,
      },
      {
        path: 'strategy-studio',
        element: <StrategyStudio />,
      },
      {
        path: 'runs',
        element: <Runs />,
      },
      {
        path: 'feeds',
        element: <Feeds />,
      },
      {
        path: 'approvals',
        element: <Approvals />,
      },
      {
        path: 'overrides',
        element: <Overrides />,
      },
      {
        path: 'audit',
        element: <Audit />,
      },
      {
        path: 'queues',
        element: <Queues />,
      },
      {
        path: 'artifacts',
        element: <Artifacts />,
      },
    ],
  },
])
