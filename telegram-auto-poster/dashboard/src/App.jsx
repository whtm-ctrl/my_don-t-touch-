import React, { useState } from 'react'
import { Routes, Route, Link, useLocation } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import axios from 'axios'

const API_BASE = '/api'

// API helpers
const api = axios.create({ baseURL: API_BASE })

// Components
function StatsCard({ title, value }) {
  return (
    <div className="stat-card">
      <div className="value">{value}</div>
      <div className="label">{title}</div>
    </div>
  )
}

function SourceChannels() {
  const queryClient = useQueryClient()
  const [newChannel, setNewChannel] = useState('')
  
  const { data: channels } = useQuery({
    queryKey: ['sourceChannels'],
    queryFn: () => api.get('/source-channels').then(r => r.data)
  })

  const addMutation = useMutation({
    mutationFn: (username) => api.post('/source-channels', { username }),
    onSuccess: () => {
      queryClient.invalidateQueries(['sourceChannels'])
      setNewChannel('')
    }
  })

  const deleteMutation = useMutation({
    mutationFn: (id) => api.delete(`/source-channels/${id}`),
    onSuccess: () => queryClient.invalidateQueries(['sourceChannels'])
  })

  const handleSubmit = (e) => {
    e.preventDefault()
    if (newChannel.trim()) {
      addMutation.mutate(newChannel.trim())
    }
  }

  return (
    <div className="card">
      <h2>Source Channels</h2>
      <form onSubmit={handleSubmit} style={{ marginBottom: '20px' }}>
        <input
          type="text"
          className="input"
          placeholder="@channel_username"
          value={newChannel}
          onChange={(e) => setNewChannel(e.target.value)}
        />
        <button type="submit" className="btn" disabled={addMutation.isPending}>
          Add Channel
        </button>
      </form>

      <table className="table">
        <thead>
          <tr>
            <th>Username</th>
            <th>Status</th>
            <th>Messages</th>
            <th>Last Scraped</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {channels?.map(channel => (
            <tr key={channel.id}>
              <td>{channel.username}</td>
              <td>
                <span className={`status-badge ${channel.is_active ? 'status-active' : 'status-inactive'}`}>
                  {channel.is_active ? 'Active' : 'Inactive'}
                </span>
              </td>
              <td>{channel.messages_count}</td>
              <td>{channel.last_scraped_at ? new Date(channel.last_scraped_at).toLocaleString() : 'Never'}</td>
              <td>
                <button 
                  className="btn btn-danger" 
                  onClick={() => deleteMutation.mutate(channel.id)}
                >
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Posts() {
  const { data: posts } = useQuery({
    queryKey: ['posts'],
    queryFn: () => api.get('/posts?limit=50').then(r => r.data)
  })

  return (
    <div className="card">
      <h2>Recent Posts</h2>
      <table className="table">
        <thead>
          <tr>
            <th>ID</th>
            <th>Text</th>
            <th>Status</th>
            <th>Quality</th>
            <th>Created</th>
          </tr>
        </thead>
        <tbody>
          {posts?.map(post => (
            <tr key={post.id}>
              <td>{post.id.slice(0, 8)}...</td>
              <td style={{ maxWidth: '300px', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {post.text?.slice(0, 100) || '(media only)'}
              </td>
              <td>
                <span className={`status-badge status-${post.status}`}>
                  {post.status}
                </span>
              </td>
              <td>{(post.quality_score * 100).toFixed(0)}%</td>
              <td>{new Date(post.created_at).toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Dashboard() {
  const { data: stats } = useQuery({
    queryKey: ['stats'],
    queryFn: () => api.get('/stats/summary').then(r => r.data),
    refetchInterval: 30000
  })

  return (
    <>
      <div className="stats-grid">
        <StatsCard title="Source Channels" value={stats?.source_channels || 0} />
        <StatsCard title="Posts Today" value={stats?.posts_today || 0} />
        <StatsCard title="Pending" value={stats?.posts_by_status?.pending || 0} />
        <StatsCard title="Processed" value={stats?.posts_by_status?.processed || 0} />
      </div>
      
      <SourceChannels />
      <Posts />
    </>
  )
}

function Navigation() {
  const location = useLocation()
  
  return (
    <nav className="nav">
      <Link to="/" className={`nav-link ${location.pathname === '/' ? 'active' : ''}`}>
        Dashboard
      </Link>
      <Link to="/channels" className={`nav-link ${location.pathname === '/channels' ? 'active' : ''}`}>
        Channels
      </Link>
      <Link to="/settings" className={`nav-link ${location.pathname === '/settings' ? 'active' : ''}`}>
        Settings
      </Link>
    </nav>
  )
}

function App() {
  return (
    <div className="container">
      <header className="header">
        <h1>Telegram Auto Poster</h1>
      </header>
      
      <Navigation />
      
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/channels" element={<SourceChannels />} />
        <Route path="/settings" element={
          <div className="card">
            <h2>Settings</h2>
            <p>Scheduler and filter settings can be configured via the API.</p>
          </div>
        } />
      </Routes>
    </div>
  )
}

export default App
