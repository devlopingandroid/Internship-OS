import { useEffect, useMemo, useState } from 'react'

const API = 'http://127.0.0.1:8000'

const blankJob = {
  url: '',
  title: '',
  company: '',
  description: '',
  location: '',
  pay_status: 'unknown',
  source: 'Manual',
  source_work_mode: 'unknown',
}

const defaultPreferences = {
  primary_role: 'Full-Stack Engineer',
  preferred_roles: [
    'Full-Stack Engineer',
    'Software Engineer',
    'Backend Engineer',
    'Python/AI Engineer',
    'DevOps Engineer',
    'Android Developer',
  ],
  preferred_locations: [
    'Delhi',
    'Noida',
    'Gurugram/Gurgaon',
    'Outside Delhi NCR / other Indian cities',
    'Outside India',
  ],
  work_modes: ['On-site', 'Hybrid', 'Remote'],
  salary_preference: 'paid_preferred',
  minimum_score: 50, freshness_days: 0, refresh_hours: 6,
  ranking_weights: {role:40, skills:10, internship:10, location:10, compensation:15, freshness:5, availability:5, completeness:5},
}

const ALL_ROLES = [
  'Full-Stack Engineer',
  'Software Engineer',
  'Backend Engineer',
  'Python/AI Engineer',
  'DevOps Engineer',
  'Android Developer',
]

const ALL_LOCATIONS = [
  'Delhi',
  'Noida',
  'Gurugram/Gurgaon',
  'Outside Delhi NCR / other Indian cities',
  'Outside India',
]

const ALL_WORK_MODES = ['On-site', 'Hybrid', 'Remote']

const statuses = ['saved', 'shortlisted', 'prepared', 'applied', 'interview', 'rejected', 'closed']

function roleMatches(targetRole, matchedRoles) {
  if (!targetRole || targetRole === 'all') return true
  if (!Array.isArray(matchedRoles) || !matchedRoles.length) return false
  const targetNorm = targetRole.toLowerCase().replace(/[\s\-_/]+/g, '')
  return matchedRoles.some((r) => {
    if (!r) return false
    const rNorm = String(r).toLowerCase().replace(/[\s\-_/]+/g, '')
    if (targetNorm === rNorm) return true
    if (targetNorm.includes('backend') && rNorm.includes('backend')) return true
    if (targetNorm.includes('fullstack') && rNorm.includes('fullstack')) return true
    if (targetNorm.includes('software') && (rNorm.includes('software') || rNorm.includes('swe'))) return true
    if (targetNorm.includes('devops') && rNorm.includes('devops')) return true
    if (targetNorm.includes('android') && rNorm.includes('android')) return true
    return false
  })
}

export default function App() {
  const [jobs, setJobs] = useState([])
  const [prefs, setPrefs] = useState(defaultPreferences)
  const [platforms, setPlatforms] = useState([])
  const [profile, setProfile] = useState({
    full_name: '',
    email: '',
    phone: '',
    linkedin_url: '',
    github_url: '',
    portfolio_url: '',
  })
  const [stats, setStats] = useState({
    total: 0,
    eligible: 0,
    paid_eligible: 0,
    review_required: 0,
    ineligible: 0,
    prepared: 0,
    applied: 0,
    interview: 0,
  })
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(50)
  const [totalJobsCount, setTotalJobsCount] = useState(0)
  const [preparingIds, setPreparingIds] = useState(new Set())

  const [showPreferences, setShowPreferences] = useState(false)
  const [showProfileModal, setShowProfileModal] = useState(false)
  const [showPlatformsModal, setShowPlatformsModal] = useState(false)
  const [showAddJob, setShowAddJob] = useState(false)
  const [form, setForm] = useState(blankJob)
  const [prefForm, setPrefForm] = useState(defaultPreferences)
  const [newRoleInput, setNewRoleInput] = useState('')

  // Section navigation
  const [activeSection, setActiveSection] = useState('best_matches')

  // Detailed filters
  const [query, setQuery] = useState('')
  const [roleFilter, setRoleFilter] = useState('all')
  const [locationFilter, setLocationFilter] = useState('all')
  const [workModeFilter, setWorkModeFilter] = useState('all')
  const [salaryFilter, setSalaryFilter] = useState('all')
  const [eligibilityFilter, setEligibilityFilter] = useState('all')
  const [statusFilter, setStatusFilter] = useState('all')

  const [run, setRun] = useState(null)
  const [loading, setLoading] = useState(true)
  const [extra, setExtra] = useState({company:'',country:'',source:'',type:'',minScore:'',publishedAfter:''})
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [discovering, setDiscovering] = useState(false)
  const [savingPrefs, setSavingPrefs] = useState(false)
  const [savingProfile, setSavingProfile] = useState(false)

  async function fetchStats() {
    try {
      const r = await fetch(`${API}/api/statistics`)
      if (r.ok) {
        const data = await r.json()
        setStats(data)
      }
    } catch {
      // Ignore statistics fetch errors
    }
  }

  async function fetchJobs() {
    try {
      const params = new URLSearchParams({
        section: activeSection,
        limit: String(pageSize),
        offset: String((page - 1) * pageSize),
        paginate: 'true',
      })
      if (roleFilter !== 'all') params.append('role', roleFilter)
      if (workModeFilter !== 'all') params.append('work_mode', workModeFilter)
      if (salaryFilter !== 'all') params.append('pay_status', salaryFilter)
      if (eligibilityFilter !== 'all') params.append('eligibility', eligibilityFilter)
      if (statusFilter !== 'all') params.append('status', statusFilter)
      if (query.trim()) params.append('query', query.trim())

      const rJobs = await fetch(`${API}/api/jobs?${params.toString()}`)
      if (!rJobs.ok) throw new Error('Could not fetch jobs')
      const jobsData = await rJobs.json()
      if (Array.isArray(jobsData)) {
        setJobs(jobsData)
        setTotalJobsCount(jobsData.length)
      } else {
        setJobs(jobsData.items || [])
        setTotalJobsCount(jobsData.total ?? 0)
      }
    } catch {
      setError('Could not load jobs from server.')
    }
  }

  // Load static resources, preferences, profile, platform integrations, stats, and jobs
  async function load() {
    try {
      const [rPrefs, rProf, rPlat, rStats] = await Promise.all([
        fetch(`${API}/api/preferences`),
        fetch(`${API}/api/profile`),
        fetch(`${API}/api/platforms`),
        fetch(`${API}/api/statistics`),
      ])

      if (rPrefs.ok) {
        const prefsData = await rPrefs.json()
        setPrefs(prefsData)
        setPrefForm(prefsData)
      }
      if (rProf.ok) {
        const profData = await rProf.json()
        setProfile(profData)
      }
      if (rPlat.ok) {
        const platData = await rPlat.json()
        setPlatforms(platData)
      }
      if (rStats.ok) {
        const statsData = await rStats.json()
        setStats(statsData)
      }
      const latest = await fetch(`${API}/api/discovery/latest`)
      if (latest.ok) {
        const value = await latest.json()
        setRun(value)
        setDiscovering(['running', 'cancelling'].includes(value?.status))
      }
      await fetchJobs()
      setError('')
    } catch {
      setError('Could not load dashboard. Check the backend on port 8000 and retry.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  useEffect(() => {
    fetchJobs()
  }, [page, pageSize, activeSection, roleFilter, workModeFilter, salaryFilter, eligibilityFilter, statusFilter, query])

  useEffect(() => {
    setPage(1)
  }, [activeSection, roleFilter, workModeFilter, salaryFilter, eligibilityFilter, statusFilter, query])

  useEffect(() => {
    if (!run || !['running','cancelling'].includes(run.status)) return
    let stopped = false, timer
    async function poll() {
      try {
        const response = await fetch(`${API}/api/discovery/${run.id}`)
        if (!response.ok) throw new Error('Could not read discovery progress')
        const value = await response.json()
        if (stopped) return
        setRun(value)
        if (['running','cancelling'].includes(value.status)) timer = setTimeout(poll, 3000)
        else { setDiscovering(false); load() }
      } catch (e) {
        if (!stopped) { setError(e.message + '. Reconnecting to the active run…'); timer = setTimeout(poll, 15000) }
      }
    }
    timer = setTimeout(poll, 1500)
    return () => { stopped = true; clearTimeout(timer) }
  }, [run?.id, run?.status])

  useEffect(() => {
    if (!(showPreferences || showProfileModal || showPlatformsModal || showAddJob)) return
    const previous = document.activeElement
    const dialog = document.querySelector('[role="dialog"]')
    const selectors = 'button:not([disabled]),input,select,textarea,a[href]'
    dialog?.querySelector(selectors)?.focus()
    function keyboard(e) {
      if (e.key === 'Escape') { setShowPreferences(false); setShowProfileModal(false); setShowPlatformsModal(false); setShowAddJob(false) }
      if (e.key === 'Tab') {
        const elements = [...dialog.querySelectorAll(selectors)].filter(x => x.offsetParent !== null)
        const first = elements[0], last = elements.at(-1)
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus() }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus() }
      }
    }
    document.addEventListener('keydown', keyboard)
    return () => { document.removeEventListener('keydown', keyboard); previous?.focus() }
  }, [showPreferences,showProfileModal,showPlatformsModal,showAddJob])

  // Section job counts from authoritative database statistics across all records
  const counts = useMemo(() => {
    return {
      best_matches: stats.eligible || 0,
      needs_review: stats.review_required || 0,
      other: stats.ineligible || 0,
    }
  }, [stats])

  // Filtered jobs for current section + active filters
  const displayedJobs = useMemo(() => {
    return jobs.filter((j) => {
      // Must match active section
      const jobSec = j.section || 'other'
      if (jobSec !== activeSection) return false

      // Text search (preserved as separate feature)
      if (query) {
        const q = query.toLowerCase()
        const text = `${j.title} ${j.company} ${j.description} ${j.source} ${j.location} ${(j.reasons || []).join(' ')}`.toLowerCase()
        if (!text.includes(q)) return false
      }

      // Role filter using authoritative backend matched_roles
      if (roleFilter !== 'all') {
        const matched = Array.isArray(j.matched_roles) ? j.matched_roles : []
        if (!roleMatches(roleFilter, matched)) return false
      }

      // Location filter
      if (locationFilter !== 'all') {
        const loc = (j.location || '').toLowerCase()
        if (locationFilter === 'Delhi NCR') {
          if (!loc.includes('delhi') && !loc.includes('noida') && !loc.includes('gurugram') && !loc.includes('gurgaon') && !loc.includes('ncr')) return false
        } else if (locationFilter === 'Other Indian cities') {
          if (!loc.includes('india') && !loc.includes('bengaluru') && !loc.includes('bangalore') && !loc.includes('pune') && !loc.includes('mumbai') && !loc.includes('hyderabad')) return false
        } else if (locationFilter === 'Outside India') {
          if (loc.includes('delhi') || loc.includes('noida') || loc.includes('gurugram') || loc.includes('gurgaon') || loc.includes('ncr') || loc.includes('india')) return false
        }
      }

      // Work mode filter
      if (workModeFilter !== 'all' && j.work_mode !== workModeFilter) return false

      // Salary filter
      if (salaryFilter !== 'all' && j.pay_status !== salaryFilter) return false

      // Eligibility filter
      if (eligibilityFilter !== 'all' && j.eligibility !== eligibilityFilter) return false

      // Application status filter
      if (statusFilter !== 'all' && j.status !== statusFilter) return false

      if (extra.company && !(j.company || '').toLowerCase().includes(extra.company.toLowerCase())) return false
      if (extra.country && !(j.country || '').toLowerCase().includes(extra.country.toLowerCase())) return false
      if (extra.source && !(j.source_references || [{source:j.source}]).some(x => x.source === extra.source)) return false
      if (extra.type && j.job_type !== extra.type) return false
      if (extra.minScore !== '' && j.score < Number(extra.minScore)) return false
      if (extra.publishedAfter && (!j.publication_date || j.publication_date.slice(0,10) < extra.publishedAfter)) return false
      return true
    })
  }, [jobs, activeSection, query, roleFilter, locationFilter, workModeFilter, salaryFilter, eligibilityFilter, statusFilter, extra])

  // Reset filters
  function resetFilters() {
    setQuery('')
    setRoleFilter('all')
    setLocationFilter('all')
    setWorkModeFilter('all')
    setSalaryFilter('all')
    setEligibilityFilter('all')
    setStatusFilter('all')
    setExtra({company:'',country:'',source:'',type:'',minScore:'',publishedAfter:''})
  }

  // Add manual job
  async function addJob(e) {
    e.preventDefault()
    try {
      const r = await fetch(`${API}/api/jobs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      })
      const d = await r.json()
      if (!r.ok) throw new Error(d.detail || 'Save failed')
      setShowAddJob(false)
      setForm(blankJob)
      setNotice(`Job "${d.title}" saved and classified into ${formatSectionName(d.section)}.`)
      load()
    } catch (e) {
      setError(e.message)
    }
  }

  // Delete single job
  async function deleteJob(j) {
    if (!window.confirm(`Delete "${j.title}" from ${j.company || 'listing'}?`)) return
    try {
      const r = await fetch(`${API}/api/jobs/${j.id}`, { method: 'DELETE' })
      if (!r.ok) throw new Error('Delete failed')
      setNotice(`Job deleted.`)
      load()
    } catch (e) {
      setError('Delete error: ' + e.message)
    }
  }

  // Clear all jobs
  async function clearAllJobs() {
    if (!window.confirm('Are you sure you want to delete ALL job listings? This action cannot be undone.')) return
    try {
      const r = await fetch(`${API}/api/jobs`, { method: 'DELETE' })
      if (!r.ok) throw new Error('Clear failed')
      setNotice('All job listings have been removed. Dashboard reset.')
      load()
    } catch (e) {
      setError('Clear error: ' + e.message)
    }
  }

  // Save preferences
  async function savePreferencesHandler(e) {
    e.preventDefault()
    setSavingPrefs(true)
    setError('')
    try {
      const r = await fetch(`${API}/api/preferences`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(prefForm),
      })
      const d = await r.json()
      if (!r.ok) throw new Error(Array.isArray(d.detail) ? d.detail.map(x=>x.msg).join('; ') : d.detail || 'Failed to save preferences')
      setPrefs(d.preferences)
      setShowPreferences(false)
      const c = d.counts || {}
      setNotice(`Preferences saved! Jobs reclassified: ${c.best_matches || 0} Best Matches, ${c.needs_review || 0} Needs Review, ${c.other || 0} Other Jobs.`)
      load()
    } catch (e) {
      setError('Save preferences error: ' + e.message)
    } finally {
      setSavingPrefs(false)
    }
  }

  // Save profile
  async function saveProfileHandler(e) {
    e.preventDefault()
    setSavingProfile(true)
    setError('')
    try {
      const r = await fetch(`${API}/api/profile`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(profile),
      })
      const d = await r.json()
      if (!r.ok) throw new Error(d.detail || 'Failed to save profile')
      setProfile(d)
      setShowProfileModal(false)
      setNotice('Autofill Profile saved successfully! Real details will now be filled by browser agent.')
    } catch (e) {
      setError('Save profile error: ' + e.message)
    } finally {
      setSavingProfile(false)
    }
  }

  // Update job status
  async function updateStatus(j, s) {
    try {
      const response = await fetch(`${API}/api/jobs/${j.id}/status`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: s }),
      })
      if (!response.ok) throw new Error('Server rejected the status change')
      load()
    } catch (e) {
      setError('Status update failed: ' + e.message)
    }
  }

  // Launch browser preparation
  async function prepare(j) {
    if (preparingIds.has(j.id)) return
    setPreparingIds((prev) => new Set(prev).add(j.id))
    setError('')
    setNotice(`Launching visible browser for "${j.title}". Form fields will be autofilled from your profile. Inspect every field and submit manually.`)
    try {
      const r = await fetch(`${API}/api/jobs/${j.id}/prepare`, { method: 'POST' })
      const res = await r.json().catch(() => ({}))
      if (!r.ok) {
        throw new Error(res.detail || 'Preparation failed')
      }
      load()
      if (res.message) setNotice(res.message)
    } catch (e) {
      setError(e.message || 'Could not launch browser. Check Playwright installation.')
    } finally {
      setPreparingIds((prev) => {
        const next = new Set(prev)
        next.delete(j.id)
        return next
      })
    }
  }

  // Multi-source internship discovery
  async function discover() {
    if (discovering) return
    setDiscovering(true); setError(''); setNotice('')
    try {
      const r = await fetch(`${API}/api/jobs/discover?background=true`, {method:'POST'})
      const value = await r.json()
      if (!r.ok) throw new Error(value.detail || 'Discovery could not start')
      setRun(value)
    } catch(e) { setError(e.message); setDiscovering(false) }
  }

  function formatSectionName(sec) {
    if (sec === 'best_matches') return 'Best Matches'
    if (sec === 'needs_review') return 'Needs Review'
    return 'Other Jobs'
  }

  // Preference helpers
  function toggleLocation(loc) {
    const cur = prefForm.preferred_locations || []
    if (cur.includes(loc)) {
      setPrefForm({ ...prefForm, preferred_locations: cur.filter((x) => x !== loc) })
    } else {
      setPrefForm({ ...prefForm, preferred_locations: [...cur, loc] })
    }
  }

  function toggleWorkMode(m) {
    const cur = prefForm.work_modes || []
    if (cur.includes(m)) {
      setPrefForm({ ...prefForm, work_modes: cur.filter((x) => x !== m) })
    } else {
      setPrefForm({ ...prefForm, work_modes: [...cur, m] })
    }
  }

  function removeRole(roleToRemove) {
    const cur = prefForm.preferred_roles || []
    const updated = cur.filter((r) => r !== roleToRemove)
    let primary = prefForm.primary_role
    if (primary === roleToRemove) {
      primary = updated[0] || 'Full-Stack Engineer'
    }
    setPrefForm({ ...prefForm, preferred_roles: updated, primary_role: primary })
  }

  function addRole(roleToAdd) {
    const trimmed = (roleToAdd || '').trim()
    if (!trimmed) return
    const cur = prefForm.preferred_roles || []
    if (!cur.includes(trimmed)) {
      setPrefForm({ ...prefForm, preferred_roles: [...cur, trimmed] })
    }
    setNewRoleInput('')
  }

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 pb-12">
      {/* Header */}
      <header className="bg-white border-b sticky top-0 z-20 shadow-sm">
        <div className="max-w-7xl mx-auto px-5 py-3 flex flex-wrap justify-between items-center gap-3">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-indigo-600 flex items-center justify-center text-white font-bold text-lg shadow-sm">
              IO
            </div>
            <div>
              <h1 className="font-bold text-lg leading-tight">Internship OS</h1>
              <p className="text-xs text-slate-500">Multi-Platform Internship Discovery & Application Assistant</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => setShowPlatformsModal(true)}
              className="border border-indigo-200 bg-indigo-50/70 hover:bg-indigo-100/70 text-indigo-700 rounded-lg px-3 py-2 text-sm font-semibold flex items-center gap-1.5 shadow-sm transition"
              title="View all 6 configured API adapters and 7 manual search portals"
            >
              <span>🌐</span> Platforms Hub
            </button>
            <button
              onClick={() => setShowProfileModal(true)}
              className="border border-slate-300 hover:border-slate-400 bg-white text-slate-700 rounded-lg px-3 py-2 text-sm font-medium flex items-center gap-1.5 shadow-sm transition"
              title="Configure candidate name, email, phone, links for autofill"
            >
              <span>👤</span> Autofill Profile
            </button>
            <button
              onClick={() => {
                setPrefForm(prefs)
                setShowPreferences(true)
              }}
              className="border border-slate-300 hover:border-slate-400 bg-white text-slate-700 rounded-lg px-3 py-2 text-sm font-medium flex items-center gap-1.5 shadow-sm transition"
            >
              <span>⚙</span> Preferences
            </button>
            <button
              onClick={discover}
              disabled={discovering}
              className="border border-indigo-600 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg px-3.5 py-2 text-sm font-medium disabled:opacity-50 transition shadow-sm"
              title="Discovers internships across Greenhouse, Lever, Ashby, Arbeitnow, Remotive, and Jobicy"
            >
              {discovering ? 'Discovering…' : '⬇ Discover Internships'}
            </button>
            <button
              onClick={() => setShowAddJob(true)}
              className="border border-slate-300 hover:border-slate-400 bg-white text-slate-800 rounded-lg px-3 py-2 text-sm font-medium shadow-sm transition"
            >
              + Add Internship
            </button>
            {jobs.length > 0 && (
              <button
                onClick={clearAllJobs}
                className="text-red-600 hover:text-red-800 border border-red-200 hover:bg-red-50 rounded-lg px-2.5 py-2 text-xs font-medium transition ml-1"
                title="Wipe all jobs from database"
              >
                Clear
              </button>
            )}
          </div>
        </div>
      </header>

      {/* Main Body */}
      <main className="max-w-7xl mx-auto px-5 pt-6">
        {loading && <p role="status">Loading jobs and preferences…</p>}
        {run && <section aria-label="Discovery progress" aria-live="polite" className="bg-white border rounded-xl p-4 mb-4 text-sm space-y-2">
          <strong>Discovery: {run.status} · {run.sources_completed}/{run.sources_attempted} sources finished</strong>
          <p>Fetched {run.total_fetched} · New {run.imported} · Updated {run.updated} · Duplicates skipped {run.duplicates_skipped}</p>
          <p>Processed: {run.eligible} eligible · {run.review_required} review required · {run.ineligible} ineligible</p>
          <p>Sources with results or a valid empty response: {(run.sources || []).filter(x=>x.status !== 'failed').length} · Failed: {(run.sources || []).filter(x=>x.status === 'failed').length}</p>
          {run.status === 'failed' && <p role="alert">Discovery failed. No successful completion is claimed; inspect source errors below.</p>}
          {run.status === 'interrupted' && <p>The server restarted. Imported records were retained; start a new run to continue.</p>}
          <details><summary>Source details and coverage</summary>{(run.sources || []).map(x=><div key={x.source} className="border-t py-2"><strong>{x.source}: {x.status}</strong> · {x.fetched} fetched · {x.imported} new · {x.updated} updated · {x.duplicates_skipped} duplicate · {x.failed} malformed/failed · {x.cached_requests} cached requests<p>{x.errors.join('; ')}</p>{x.boards.filter(b=>b.truncated).map(b=><p key={b.board}>{b.board}: configured page limit reached; coverage is partial.</p>)}</div>)}</details>
          {discovering && <button className="border rounded px-3 py-1" onClick={async()=>{const r=await fetch(`${API}/api/discovery/${run.id}/cancel`,{method:'POST'}); if(r.ok)setRun(await r.json()); else setError('Cancellation failed')}} disabled={run.status==='cancelling'}>Cancel discovery</button>}
        </section>}
        <p className="text-xs text-slate-600 mb-4">Stored records: {stats.paid_eligible} paid eligible · {stats.prepared} prepared · {stats.applied} applied · {stats.interview} interview-stage. New and duplicate counts above refer to the latest run.</p>
        {/* Banner notifications */}
        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-xl mb-4 flex justify-between items-center shadow-sm">
            <span>{error}</span>
            <button onClick={() => setError('')} className="text-red-500 hover:text-red-700 font-bold ml-2">✕</button>
          </div>
        )}
        {notice && (
          <div className="bg-indigo-50 border border-indigo-200 text-indigo-800 px-4 py-3 rounded-xl mb-4 flex justify-between items-center shadow-sm">
            <span>{notice}</span>
            <button onClick={() => setNotice('')} className="text-indigo-500 hover:text-indigo-700 font-bold ml-2">✕</button>
          </div>
        )}

        <details className="bg-white border rounded-xl p-3 mb-4"><summary>Additional filters</summary><div className="grid sm:grid-cols-3 gap-2 mt-2">
          <Field label="Company"><input value={extra.company} onChange={e=>setExtra({...extra,company:e.target.value})}/></Field>
          <Field label="Country (source-provided)"><input value={extra.country} onChange={e=>setExtra({...extra,country:e.target.value})}/></Field>
          <Field label="Source"><select value={extra.source} onChange={e=>setExtra({...extra,source:e.target.value})}><option value="">All sources</option>{[...new Set(jobs.flatMap(j=>(j.source_references||[{source:j.source}]).map(x=>x.source)))].map(x=><option key={x}>{x}</option>)}</select></Field>
          <Field label="Job type"><select value={extra.type} onChange={e=>setExtra({...extra,type:e.target.value})}><option value="">All types</option>{['internship','graduate','full_time','part_time','contract','unknown'].map(x=><option key={x}>{x}</option>)}</select></Field>
          <Field label="Minimum score"><input type="number" min="0" max="100" value={extra.minScore} onChange={e=>setExtra({...extra,minScore:e.target.value})}/></Field>
          <Field label="Published on or after"><input type="date" value={extra.publishedAfter} onChange={e=>setExtra({...extra,publishedAfter:e.target.value})}/></Field>
          <button onClick={resetFilters}>Reset all filters</button>
        </div></details>
        {/* Top Stats Overview */}
        <div className="grid gap-3 grid-cols-2 md:grid-cols-4 mb-6">
          <div className="bg-white border rounded-xl p-4 shadow-sm">
            <p className="text-xs font-medium text-slate-500 uppercase tracking-wider">Total Tracked</p>
            <p className="text-2xl font-bold mt-1 text-slate-800">{stats.total}</p>
          </div>
          <div className="bg-white border border-emerald-200 rounded-xl p-4 shadow-sm bg-gradient-to-br from-emerald-50/50 to-white">
            <p className="text-xs font-medium text-emerald-700 uppercase tracking-wider">🌟 Best Matches</p>
            <p className="text-2xl font-bold mt-1 text-emerald-800">{counts.best_matches}</p>
          </div>
          <div className="bg-white border border-amber-200 rounded-xl p-4 shadow-sm bg-gradient-to-br from-amber-50/50 to-white">
            <p className="text-xs font-medium text-amber-700 uppercase tracking-wider">⚠️ Needs Review</p>
            <p className="text-2xl font-bold mt-1 text-amber-800">{counts.needs_review}</p>
          </div>
          <div className="bg-white border rounded-xl p-4 shadow-sm">
            <p className="text-xs font-medium text-slate-500 uppercase tracking-wider">📋 Other Jobs</p>
            <p className="text-2xl font-bold mt-1 text-slate-600">{counts.other}</p>
          </div>
        </div>

        {/* Multi-Platform Quick Banner */}
        <div className="mb-6 bg-gradient-to-r from-indigo-900 to-slate-900 text-white rounded-2xl p-5 shadow-sm flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xs bg-indigo-500/30 text-indigo-200 border border-indigo-400/30 px-2 py-0.5 rounded-full font-bold uppercase tracking-wider">
                Multi-Platform Engine
              </span>
              <span className="text-xs text-slate-400">6 API adapters · 7 manual portals</span>
            </div>
            <h2 className="text-lg font-bold mt-1.5">Automated Discovery across Greenhouse, Lever, Ashby & Top Startups</h2>
            <p className="text-xs text-slate-300 mt-1 max-w-2xl leading-relaxed">
              Discover from configured public job feeds. Each run reports successful sources, failures, and cached results. Manual portals open searches for you to explore and add listings.
            </p>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => setShowPlatformsModal(true)}
              className="bg-white/10 hover:bg-white/20 text-white border border-white/20 rounded-xl px-4 py-2 text-xs font-semibold whitespace-nowrap transition backdrop-blur-sm"
            >
              Open Platforms Hub ↗
            </button>
            <button
              onClick={discover}
              disabled={discovering}
              className="bg-indigo-500 hover:bg-indigo-400 text-white rounded-xl px-4 py-2 text-xs font-semibold whitespace-nowrap transition shadow-sm"
            >
              {discovering ? 'Scanning…' : '⬇ Discover Internships'}
            </button>
          </div>
        </div>

        {/* Section Tabs Navigation */}
        <div className="flex border-b border-slate-200 mb-6 bg-white rounded-t-xl px-2 pt-2 border-t border-x">
          <button
            onClick={() => setActiveSection('best_matches')}
            className={`flex items-center gap-2 py-3 px-5 font-semibold text-sm border-b-2 transition -mb-[1px] ${
              activeSection === 'best_matches'
                ? 'border-emerald-600 text-emerald-700 bg-emerald-50/40 rounded-t-lg'
                : 'border-transparent text-slate-500 hover:text-slate-800'
            }`}
          >
            <span>🌟 Best Matches</span>
            <span className={`text-xs px-2 py-0.5 rounded-full font-bold ${
              activeSection === 'best_matches' ? 'bg-emerald-200 text-emerald-900' : 'bg-slate-100 text-slate-600'
            }`}>
              {counts.best_matches}
            </span>
          </button>
          <button
            onClick={() => setActiveSection('needs_review')}
            className={`flex items-center gap-2 py-3 px-5 font-semibold text-sm border-b-2 transition -mb-[1px] ${
              activeSection === 'needs_review'
                ? 'border-amber-600 text-amber-700 bg-amber-50/40 rounded-t-lg'
                : 'border-transparent text-slate-500 hover:text-slate-800'
            }`}
          >
            <span>⚠️ Needs Review</span>
            <span className={`text-xs px-2 py-0.5 rounded-full font-bold ${
              activeSection === 'needs_review' ? 'bg-amber-200 text-amber-900' : 'bg-slate-100 text-slate-600'
            }`}>
              {counts.needs_review}
            </span>
          </button>
          <button
            onClick={() => setActiveSection('other')}
            className={`flex items-center gap-2 py-3 px-5 font-semibold text-sm border-b-2 transition -mb-[1px] ${
              activeSection === 'other'
                ? 'border-slate-600 text-slate-800 bg-slate-50 rounded-t-lg'
                : 'border-transparent text-slate-500 hover:text-slate-800'
            }`}
          >
            <span>📋 Other Jobs</span>
            <span className={`text-xs px-2 py-0.5 rounded-full font-bold ${
              activeSection === 'other' ? 'bg-slate-200 text-slate-800' : 'bg-slate-100 text-slate-600'
            }`}>
              {counts.other}
            </span>
          </button>
        </div>

        {/* Section Context Explainer */}
        <div className="mb-4 text-xs px-4 py-2.5 rounded-lg border bg-slate-50 text-slate-600 flex items-center justify-between">
          {activeSection === 'best_matches' && (
            <span>
              <strong>Best Matches:</strong> Verified paid internships matching your preferred roles (Full-Stack, Python/AI, Backend, etc.), location rules, and open to India candidates.
            </span>
          )}
          {activeSection === 'needs_review' && (
            <span>
              <strong>Needs Review:</strong> Potentially relevant internships with unverified salary, unknown international India eligibility, or missing work mode.
            </span>
          )}
          {activeSection === 'other' && (
            <span>
              <strong>Other Jobs:</strong> Listings excluded due to non-internship title, non-NCR physical work location, unselected work mode, or explicit non-India restrictions.
            </span>
          )}
          <button
            onClick={() => {
              setPrefForm(prefs)
              setShowPreferences(true)
            }}
            className="text-indigo-600 hover:underline font-medium text-xs ml-3 whitespace-nowrap"
          >
            Configure Rules →
          </button>
        </div>

        {/* Filters Bar */}
        <div className="bg-white border rounded-xl p-4 mb-6 shadow-sm space-y-3">
          <div className="flex flex-wrap gap-3 items-center">
            {/* Search */}
            <div className="flex-1 min-w-[240px]">
              <input
                className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                aria-label="Search internships" placeholder="Search internships, skills, companies, reasons..."
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>

            {/* Role filter */}
            <select
              className="border rounded-lg px-3 py-2 text-sm bg-white"
              value={roleFilter}
              onChange={(e) => setRoleFilter(e.target.value)}
            >
              <option value="all">All Roles</option>
              {(prefs.preferred_roles || ALL_ROLES).map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>

            {/* Location category filter */}
            <select
              className="border rounded-lg px-3 py-2 text-sm bg-white"
              value={locationFilter}
              onChange={(e) => setLocationFilter(e.target.value)}
            >
              <option value="all">All Locations</option>
              <option value="Delhi NCR">Delhi NCR</option>
              <option value="Other Indian cities">Other Indian cities</option>
              <option value="Outside India">Outside India</option>
            </select>

            {/* Work mode filter */}
            <select
              className="border rounded-lg px-3 py-2 text-sm bg-white"
              value={workModeFilter}
              onChange={(e) => setWorkModeFilter(e.target.value)}
            >
              <option value="all">All Modes</option>
              <option value="Remote">Remote</option>
              <option value="Hybrid">Hybrid</option>
              <option value="On-site">On-site</option>
              <option value="unknown">Mode unknown</option>
            </select>

            {/* Compensation filter */}
            <select
              className="border rounded-lg px-3 py-2 text-sm bg-white"
              value={salaryFilter}
              onChange={(e) => setSalaryFilter(e.target.value)}
            >
              <option value="all">All Compensation</option>
              <option value="paid">Paid only</option>
              <option value="unknown">Unknown / unverified</option>
              <option value="unpaid">Unpaid</option>
            </select>

            {/* Eligibility filter */}
            <select
              className="border rounded-lg px-3 py-2 text-sm bg-white"
              value={eligibilityFilter}
              onChange={(e) => setEligibilityFilter(e.target.value)}
            >
              <option value="all">All Eligibility</option>
              <option value="eligible">Eligible (India)</option>
              <option value="unknown">Eligibility unknown</option>
              <option value="ineligible">Ineligible</option>
            </select>

            {/* Application Status filter */}
            <select
              className="border rounded-lg px-3 py-2 text-sm bg-white"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
            >
              <option value="all">All Statuses</option>
              {statuses.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>

            {(query || roleFilter !== 'all' || locationFilter !== 'all' || workModeFilter !== 'all' || salaryFilter !== 'all' || eligibilityFilter !== 'all' || statusFilter !== 'all') && (
              <button
                onClick={resetFilters}
                className="text-xs text-indigo-600 hover:text-indigo-800 font-medium px-2 py-1.5"
              >
                Reset filters ✕
              </button>
            )}
          </div>
        </div>

        {/* Opportunities List */}
        <section className="bg-white border rounded-xl overflow-hidden shadow-sm">
          <div className="p-4 border-b bg-slate-50 flex justify-between items-center">
            <h3 className="font-semibold text-slate-800 text-sm">
              {formatSectionName(activeSection)} ({totalJobsCount})
            </h3>
            <span className="text-xs text-slate-500">
              Strict Internship Filter Active
            </span>
          </div>

          {!displayedJobs.length ? (
            <div className="p-12 text-center">
              <div className="w-12 h-12 rounded-full bg-slate-100 flex items-center justify-center mx-auto text-xl mb-3 text-slate-400">
                🎓
              </div>
              <p className="font-semibold text-slate-700 text-base">No listings currently in {formatSectionName(activeSection)}</p>
              <p className="text-sm text-slate-500 mt-2 max-w-md mx-auto">
                {activeSection === 'best_matches'
                  ? 'No internships currently meet all Best Matches criteria. Click "Discover Internships" to scan Greenhouse, Lever, and Ashby, or use the Platforms Hub to find and add internships.'
                  : 'No internships match this section.'}
              </p>
              <div className="flex justify-center gap-3 mt-5">
                <button
                  className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg px-4 py-2 text-sm font-medium shadow-sm transition"
                  onClick={discover}
                  disabled={discovering}
                >
                  {discovering ? 'Scanning…' : '⬇ Discover Internships'}
                </button>
                <button
                  className="border border-indigo-600 text-indigo-600 hover:bg-indigo-50 rounded-lg px-4 py-2 text-sm font-medium transition"
                  onClick={() => setShowPlatformsModal(true)}
                >
                  Explore Platforms Hub ↗
                </button>
                <button
                  className="border border-slate-300 hover:bg-slate-50 rounded-lg px-4 py-2 text-sm font-medium transition"
                  onClick={() => setShowAddJob(true)}
                >
                  + Add Internship
                </button>
              </div>
            </div>
          ) : (
            displayedJobs.map((j) => (
              <article key={j.id} className="p-5 border-b last:border-0 hover:bg-slate-50/60 transition">
                <p className="text-xs text-slate-500 mb-2">{j.job_type || 'Type unknown'} · Published: {j.publication_date?.slice(0,10) || 'Unknown'} · Verified: {j.last_verified_at?.slice(0,10) || 'Unknown'} · Availability: {j.availability || 'unknown'}</p>
                <details className="text-xs mb-3"><summary>View source details and score components</summary><p>{j.compensation_text || 'No original compensation text supplied'}</p><pre className="whitespace-pre-wrap">{JSON.stringify(j.score_components || {},null,2)}</pre>{(j.source_references||[{source:j.source,url:j.url}]).map((x,i)=><p key={i}><a className="text-indigo-700 underline" href={x.url} target="_blank" rel="noreferrer">{x.source}: original listing</a></p>)}{j.application_url && <a className="text-indigo-700 underline" href={j.application_url} target="_blank" rel="noreferrer">Open application page</a>}</details>
                <div className="flex flex-col lg:flex-row gap-4 lg:justify-between">
                  <div className="flex-1 min-w-0">
                    {/* Header line with Title & Badges */}
                    <div className="flex flex-wrap gap-2 items-center">
                      <h4 className="font-semibold text-base text-slate-900">{j.title}</h4>

                      {/* Score badge */}
                      <span
                        className={`text-xs rounded-full px-2.5 py-0.5 font-bold ${
                          j.score >= 80
                            ? 'bg-emerald-100 text-emerald-800'
                            : j.score >= 60
                            ? 'bg-amber-100 text-amber-800'
                            : 'bg-slate-100 text-slate-700'
                        }`}
                      >
                        {j.score}/100
                      </span>

                      {/* Internship tag */}
                      <span className="text-xs bg-indigo-50 text-indigo-700 border border-indigo-200 rounded-full px-2 py-0.5 font-semibold">
                        🎓 Internship
                      </span>

                      {/* Section badge */}
                      {j.section === 'best_matches' && (
                        <span className="text-xs bg-emerald-50 text-emerald-700 border border-emerald-200 rounded-full px-2 py-0.5 font-medium">
                          Best Match
                        </span>
                      )}
                      {j.section === 'needs_review' && (
                        <span className="text-xs bg-amber-50 text-amber-800 border border-amber-200 rounded-full px-2 py-0.5 font-medium">
                          Needs Review
                        </span>
                      )}

                      {/* Work Mode badge */}
                      <span className="text-xs bg-slate-100 text-slate-700 rounded-full px-2 py-0.5 font-medium">
                        {j.work_mode || 'Mode unverified'}
                      </span>

                      {/* Compensation badge */}
                      <span
                        className={`text-xs rounded-full px-2 py-0.5 font-medium ${
                          j.pay_status === 'paid'
                            ? 'bg-green-100 text-green-800 font-semibold'
                            : j.pay_status === 'unpaid'
                            ? 'bg-red-100 text-red-800'
                            : 'bg-slate-100 text-slate-600'
                        }`}
                      >
                        {j.pay_status === 'paid'
                          ? '✓ Paid (Verified)'
                          : j.pay_status === 'unpaid'
                          ? 'Unpaid'
                          : 'Pay unverified'}
                      </span>

                      {/* Eligibility badge */}
                      <span
                        className={`text-xs rounded-full px-2 py-0.5 font-medium ${
                          j.eligibility === 'eligible'
                            ? 'bg-blue-50 text-blue-700 border border-blue-200'
                            : j.eligibility === 'ineligible'
                            ? 'bg-red-50 text-red-700 border border-red-200'
                            : 'bg-amber-50 text-amber-700 border border-amber-200'
                        }`}
                      >
                        {j.eligibility === 'eligible'
                          ? '🇮🇳 Eligible (India)'
                          : j.eligibility === 'ineligible'
                          ? '🚫 Ineligible'
                          : '❓ Eligibility unknown'}
                      </span>

                      {/* Source tag */}
                      <span className="text-xs bg-slate-100 text-slate-500 rounded-full px-2 py-0.5">
                        {j.source}
                      </span>
                    </div>

                    {/* Company & Location info */}
                    <p className="text-sm text-slate-600 mt-1.5 font-medium">
                      {j.company || 'Company not set'} · <span className="text-slate-500">{j.location || 'Location unverified'}</span>
                    </p>

                    {/* Description snippet */}
                    <p className="text-xs text-slate-600 mt-2.5 line-clamp-3 leading-relaxed">
                      {j.description ? j.description.slice(0, 320) : 'No description provided.'}
                    </p>

                    {/* Match & Rule Reasons */}
                    <div className="flex gap-1.5 flex-wrap mt-3">
                      {(j.reasons || []).map((r, i) => {
                        const isMatch = r.startsWith('Role match') || r.startsWith('Best match') || r.startsWith('Confirmed paid') || r.startsWith('Eligibility: Based in India') || r.startsWith('Internship title')
                        const isWarn = r.startsWith('Needs review') || r.startsWith('Compensation unverified') || r.startsWith('Eligibility: Eligibility unknown')
                        const isReject = r.startsWith('Rule violation') || r.startsWith('Irrelevant role') || r.startsWith('Unpaid') || r.startsWith('Eligibility: Ineligible') || r.startsWith('Non-internship')
                        return (
                          <span
                            key={i}
                            className={`text-xs rounded px-2 py-0.5 font-medium ${
                              isMatch
                                ? 'bg-emerald-50 text-emerald-800 border border-emerald-200'
                                : isWarn
                                ? 'bg-amber-50 text-amber-800 border border-amber-200'
                                : isReject
                                ? 'bg-red-50 text-red-700 border border-red-200'
                                : 'bg-slate-100 text-slate-600'
                            }`}
                          >
                            {r}
                          </span>
                        )
                      })}
                    </div>
                  </div>

                  {/* Actions Column */}
                  <div className="flex lg:flex-col gap-2 items-start lg:items-end justify-start pt-1">
                    <div className="flex items-center gap-2">
                      <a
                        className="border border-slate-300 hover:border-slate-400 bg-white rounded-lg px-3 py-1.5 text-xs font-medium text-slate-700 transition"
                        href={j.url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Open ↗
                      </a>
                      <button
                        onClick={() => prepare(j)}
                        disabled={preparingIds.has(j.id)}
                        className={`rounded-lg px-3 py-1.5 text-xs font-medium shadow-sm transition ${
                          preparingIds.has(j.id)
                            ? 'bg-indigo-300 text-white cursor-not-allowed'
                            : 'bg-indigo-600 hover:bg-indigo-700 text-white'
                        }`}
                        title={
                          preparingIds.has(j.id)
                            ? 'Browser preparation in progress...'
                            : 'Opens Playwright browser, navigates to application page, and autofills your details'
                        }
                      >
                        {preparingIds.has(j.id) ? 'Preparing…' : 'Prepare & Autofill'}
                      </button>
                      <button
                        onClick={() => deleteJob(j)}
                        className="text-slate-400 hover:text-red-600 p-1 rounded hover:bg-red-50 transition"
                        title="Delete listing"
                      >
                        ✕
                      </button>
                    </div>
                    <select
                      className="border border-slate-300 rounded-lg px-2.5 py-1.5 text-xs bg-white text-slate-700 font-medium"
                      value={j.status}
                      onChange={(e) => updateStatus(j, e.target.value)}
                    >
                      {statuses.map((s) => (
                        <option key={s} value={s}>
                          Status: {s}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
              </article>
            ))
          )}

          {/* Pagination Controls */}
          {totalJobsCount > 0 && (
            <div className="flex flex-wrap items-center justify-between gap-3 p-4 border-t bg-slate-50">
              <div className="text-xs text-slate-600">
                Showing <strong>{Math.min(totalJobsCount, (page - 1) * pageSize + 1)}</strong> to{' '}
                <strong>{Math.min(totalJobsCount, page * pageSize)}</strong> of{' '}
                <strong>{totalJobsCount}</strong> listings
              </div>
              <div className="flex items-center gap-2">
                <label className="text-xs text-slate-500 flex items-center gap-1">
                  Per page:
                  <select
                    value={pageSize}
                    onChange={(e) => {
                      setPageSize(Number(e.target.value))
                      setPage(1)
                    }}
                    className="border rounded px-2 py-1 text-xs bg-white text-slate-700"
                  >
                    <option value={25}>25</option>
                    <option value={50}>50</option>
                    <option value={100}>100</option>
                  </select>
                </label>
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1}
                  className="border rounded px-3 py-1 text-xs font-medium bg-white text-slate-700 disabled:opacity-40 disabled:cursor-not-allowed hover:bg-slate-100 transition"
                >
                  Previous
                </button>
                <span className="text-xs font-medium text-slate-700 px-2">
                  Page {page} of {Math.max(1, Math.ceil(totalJobsCount / pageSize))}
                </span>
                <button
                  onClick={() => setPage((p) => Math.min(Math.max(1, Math.ceil(totalJobsCount / pageSize)), p + 1))}
                  disabled={page >= Math.max(1, Math.ceil(totalJobsCount / pageSize))}
                  className="border rounded px-3 py-1 text-xs font-medium bg-white text-slate-700 disabled:opacity-40 disabled:cursor-not-allowed hover:bg-slate-100 transition"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </section>
      </main>

      {/* ────────────────────────────────────────────────────────── */}
      {/* 1. Platforms Hub Modal */}
      {/* ────────────────────────────────────────────────────────── */}
      {showPlatformsModal && (
        <div role="dialog" aria-modal="true" aria-label="Internship OS dialog" className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4 backdrop-blur-sm">
          <div className="bg-white rounded-2xl shadow-xl p-6 w-full max-w-4xl max-h-[90vh] overflow-y-auto space-y-5">
            <div className="flex justify-between items-center border-b pb-4">
              <div>
                <h3 className="text-xl font-bold text-slate-900">Platforms & Portals Hub</h3>
                <p className="text-xs text-slate-500 mt-0.5">
                  Multi-source discovery architecture: 6 configured API adapters + 7 manual search links
                </p>
              </div>
              <button
                type="button"
                aria-label="Close dialog"
                onClick={() => setShowPlatformsModal(false)}
                className="text-slate-400 hover:text-slate-600 text-xl font-bold p-1"
              >
                ✕
              </button>
            </div>

            {/* Section 1: Automated API Feeds */}
            <div>
              <div className="flex items-center gap-2 mb-3">
                <span className="w-2.5 h-2.5 rounded-full bg-emerald-500"></span>
                <h4 className="text-sm font-bold text-slate-800 uppercase tracking-wider">
                  Automated Public API Feeds (Connected & Verified)
                </h4>
              </div>
              <div className="grid md:grid-cols-2 gap-3">
                {platforms
                  .filter((p) => p.status === 'configured')
                  .map((p) => (
                    <div key={p.name} className="border border-emerald-200 bg-emerald-50/20 rounded-xl p-3.5 shadow-xs">
                      <div className="flex justify-between items-start gap-2">
                        <h5 className="font-bold text-sm text-slate-900">{p.name}</h5>
                        <span className="text-[10px] bg-emerald-100 text-emerald-800 font-bold px-2 py-0.5 rounded-full whitespace-nowrap">
                          {p.last_run ? `Last run: ${p.last_run.status}` : 'Not yet live-tested'}
                        </span>
                      </div>
                      <p className="text-xs text-slate-600 mt-1">{p.description}</p>
                      <p className="text-[11px] text-slate-500 mt-2 font-medium">
                        <strong>Companies:</strong> {p.companies}
                      </p>
                      <p className="text-[11px] text-indigo-700 mt-1 font-semibold">
                        Mode: {p.mode}
                      </p>
                    </div>
                  ))}
              </div>
            </div>

            {/* Section 2: Permitted Direct Search Hub */}
            <div className="border-t pt-4">
              <div className="flex items-center gap-2 mb-3">
                <span className="w-2.5 h-2.5 rounded-full bg-indigo-500"></span>
                <h4 className="text-sm font-bold text-slate-800 uppercase tracking-wider">
                  Permitted Pre-Filtered Portals (Direct Exploration Hub)
                </h4>
              </div>
              <p className="text-xs text-slate-500 mb-3">
                Platforms protected by login walls, Cloudflare, or user agreements (no unauthorized scraping). Open pre-filtered search results directly, copy any target internship URL, and paste it into "+ Add Internship" to score and auto-fill!
              </p>
              <div className="grid md:grid-cols-2 gap-3">
                {platforms
                  .filter((p) => p.status === 'permitted_links')
                  .map((p) => (
                    <div key={p.name} className="border border-slate-200 bg-white hover:border-slate-300 rounded-xl p-3.5 shadow-xs transition">
                      <div className="flex justify-between items-start gap-2">
                        <div>
                          <h5 className="font-bold text-sm text-slate-900">{p.name}</h5>
                          <span className="text-[10px] text-slate-500">{p.category}</span>
                        </div>
                        <a
                          href={p.url}
                          target="_blank"
                          rel="noreferrer"
                          className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg px-2.5 py-1 text-xs font-semibold whitespace-nowrap shadow-xs transition flex items-center gap-1"
                        >
                          Explore ↗
                        </a>
                      </div>
                      <p className="text-xs text-slate-600 mt-2">{p.description}</p>
                      <p className="text-[11px] text-slate-500 mt-1.5 font-medium">
                        <strong>Coverage:</strong> {p.companies}
                      </p>
                    </div>
                  ))}
              </div>
            </div>

            <div className="flex justify-end border-t pt-4">
              <button
                type="button"
                aria-label="Close dialog"
                onClick={() => setShowPlatformsModal(false)}
                className="bg-slate-800 hover:bg-slate-900 text-white rounded-lg px-5 py-2 text-sm font-semibold transition"
              >
                Close Hub
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ────────────────────────────────────────────────────────── */}
      {/* 2. Autofill Profile Modal */}
      {/* ────────────────────────────────────────────────────────── */}
      {showProfileModal && (
        <div role="dialog" aria-modal="true" aria-label="Internship OS dialog" className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4 backdrop-blur-sm">
          <form
            onSubmit={saveProfileHandler}
            className="bg-white rounded-2xl shadow-xl p-6 w-full max-w-xl max-h-[90vh] overflow-y-auto space-y-4"
          >
            <div className="flex justify-between items-center border-b pb-3">
              <div>
                <h3 className="text-xl font-bold text-slate-900">Autofill Profile</h3>
                <p className="text-xs text-slate-500 mt-0.5">
                  Enter your details so the Prepare button automatically fills application forms.
                </p>
              </div>
              <button
                type="button"
                aria-label="Close dialog"
                onClick={() => setShowProfileModal(false)}
                className="text-slate-400 hover:text-slate-600 text-xl font-bold p-1"
              >
                ✕
              </button>
            </div>

            <div className="grid sm:grid-cols-2 gap-3">
              <Field label="Full Name *">
                <input
                  required
                  value={profile.full_name || ''}
                  onChange={(e) => setProfile({ ...profile, full_name: e.target.value })}
                  placeholder="e.g. Rahul Sharma"
                />
              </Field>
              <Field label="Email *">
                <input
                  required
                  type="email"
                  value={profile.email || ''}
                  onChange={(e) => setProfile({ ...profile, email: e.target.value })}
                  placeholder="rahul@example.com"
                />
              </Field>
            </div>

            <div className="grid sm:grid-cols-2 gap-3">
              <Field label="Phone / Mobile">
                <input
                  value={profile.phone || ''}
                  onChange={(e) => setProfile({ ...profile, phone: e.target.value })}
                  placeholder="+91 9876543210"
                />
              </Field>
              <Field label="LinkedIn Profile URL">
                <input
                  type="url"
                  value={profile.linkedin_url || ''}
                  onChange={(e) => setProfile({ ...profile, linkedin_url: e.target.value })}
                  placeholder="https://linkedin.com/in/username"
                />
              </Field>
            </div>

            <div className="grid sm:grid-cols-2 gap-3">
              <Field label="GitHub Profile URL">
                <input
                  type="url"
                  value={profile.github_url || ''}
                  onChange={(e) => setProfile({ ...profile, github_url: e.target.value })}
                  placeholder="https://github.com/username"
                />
              </Field>
              <Field label="Portfolio / Website URL">
                <input
                  type="url"
                  value={profile.portfolio_url || ''}
                  onChange={(e) => setProfile({ ...profile, portfolio_url: e.target.value })}
                  placeholder="https://myportfolio.dev"
                />
              </Field>
            </div>

            <div className="flex justify-end gap-2 border-t pt-4">
              <button
                type="button"
                aria-label="Close dialog"
                onClick={() => setShowProfileModal(false)}
                className="border rounded-lg px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={savingProfile}
                className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg px-5 py-2 text-sm font-semibold shadow-sm disabled:opacity-50 transition"
              >
                {savingProfile ? 'Saving…' : 'Save Profile'}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* ────────────────────────────────────────────────────────── */}
      {/* 3. Job Preferences Modal */}
      {/* ────────────────────────────────────────────────────────── */}
      {showPreferences && (
        <div role="dialog" aria-modal="true" aria-label="Internship OS dialog" className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4 backdrop-blur-sm">
          <form
            onSubmit={savePreferencesHandler}
            className="bg-white rounded-2xl shadow-xl p-6 w-full max-w-2xl max-h-[90vh] overflow-y-auto space-y-6"
          >
            <div className="flex justify-between items-center border-b pb-4">
              <div>
                <h3 className="text-xl font-bold text-slate-900">Job Preferences</h3>
                <p className="text-xs text-slate-500 mt-0.5">
                  Configure preferred roles, work locations, work modes, and salary rules
                </p>
              </div>
              <button
                type="button"
                aria-label="Close dialog"
                onClick={() => setShowPreferences(false)}
                className="text-slate-400 hover:text-slate-600 text-xl font-bold p-1"
              >
                ✕
              </button>
            </div>

            {/* Field 1: Preferred Roles */}
            <div className="space-y-3">
              <div className="flex justify-between items-center">
                <label className="block text-sm font-bold text-slate-800">
                  Field 1 — Preferred Roles
                </label>
                <span className="text-xs text-slate-500">Primary role boosts match fit</span>
              </div>

              {/* Primary Role Selector */}
              <div>
                <label className="text-xs text-slate-600 block mb-1 font-medium">Primary Role:</label>
                <select
                  value={prefForm.primary_role || 'Full-Stack Engineer'}
                  onChange={(e) => setPrefForm({ ...prefForm, primary_role: e.target.value })}
                  className="w-full border rounded-lg p-2 text-sm bg-white"
                >
                  {(prefForm.preferred_roles || ALL_ROLES).map((r) => (
                    <option key={r} value={r}>
                      {r} (Primary)
                    </option>
                  ))}
                </select>
              </div>

              {/* Active Roles Pills */}
              <div>
                <label className="text-xs text-slate-600 block mb-1.5 font-medium">Active Preferred Roles:</label>
                <div className="flex flex-wrap gap-2">
                  {(prefForm.preferred_roles || []).map((r) => (
                    <span
                      key={r}
                      className="bg-indigo-50 border border-indigo-200 text-indigo-800 text-xs font-medium px-2.5 py-1 rounded-full flex items-center gap-1.5"
                    >
                      <span>{r}</span>
                      <button
                        type="button"
                        aria-label={`Remove ${r}`} onClick={() => removeRole(r)}
                        className="text-indigo-400 hover:text-indigo-700 font-bold ml-1 text-sm leading-none"
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              </div>

              {/* Add custom or standard role */}
              <div className="flex gap-2 pt-1">
                <input
                  type="text"
                  placeholder="Add custom role (e.g. AI Engineer)..."
                  value={newRoleInput}
                  onChange={(e) => setNewRoleInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault()
                      addRole(newRoleInput)
                    }
                  }}
                  className="flex-1 border rounded-lg px-3 py-1.5 text-xs"
                />
                <button
                  type="button"
                  onClick={() => addRole(newRoleInput)}
                  className="bg-slate-800 text-white rounded-lg px-3 py-1.5 text-xs font-medium"
                >
                  + Add Role
                </button>
              </div>

              {/* Quick Add standard roles */}
              <div className="text-xs text-slate-500 pt-1">
                <span>Quick add standard roles: </span>
                <div className="inline-flex flex-wrap gap-1 mt-1">
                  {ALL_ROLES.filter((r) => !(prefForm.preferred_roles || []).includes(r)).map((r) => (
                    <button
                      key={r}
                      type="button"
                      onClick={() => addRole(r)}
                      className="text-xs border border-dashed rounded px-1.5 py-0.5 text-indigo-600 hover:bg-indigo-50"
                    >
                      + {r}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Field 2: Preferred Work Locations */}
            <div className="space-y-2 border-t pt-4">
              <label className="block text-sm font-bold text-slate-800">
                Field 2 — Preferred Work Locations
              </label>
              <p className="text-xs text-slate-500">
                Multiple selections allowed. Delhi/Noida/Gurugram allow on-site, hybrid, & remote. Other Indian cities & Outside India accept remote only.
              </p>
              <div className="grid sm:grid-cols-2 gap-2 pt-1">
                {ALL_LOCATIONS.map((loc) => {
                  const checked = (prefForm.preferred_locations || []).includes(loc)
                  return (
                    <label
                      key={loc}
                      className={`flex items-center gap-2.5 p-2.5 rounded-lg border text-xs font-medium cursor-pointer transition ${
                        checked ? 'bg-indigo-50 border-indigo-300 text-indigo-900' : 'bg-white text-slate-700 hover:bg-slate-50'
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleLocation(loc)}
                        className="rounded text-indigo-600 focus:ring-indigo-500"
                      />
                      <span>{loc}</span>
                    </label>
                  )
                })}
              </div>
            </div>

            {/* Field 3: Work Mode Preferences */}
            <div className="space-y-2 border-t pt-4">
              <label className="block text-sm font-bold text-slate-800">
                Field 3 — Work Mode Preferences
              </label>
              <div className="grid grid-cols-3 gap-2 pt-1">
                {ALL_WORK_MODES.map((mode) => {
                  const checked = (prefForm.work_modes || []).includes(mode)
                  return (
                    <label
                      key={mode}
                      className={`flex items-center justify-center gap-2 p-2.5 rounded-lg border text-xs font-medium cursor-pointer transition text-center ${
                        checked ? 'bg-indigo-50 border-indigo-300 text-indigo-900' : 'bg-white text-slate-700 hover:bg-slate-50'
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleWorkMode(mode)}
                        className="rounded text-indigo-600 focus:ring-indigo-500"
                      />
                      <span>{mode}</span>
                    </label>
                  )
                })}
              </div>
            </div>

            {/* Field 4: Salary Preference */}
            <div className="space-y-2 border-t pt-4">
              <label className="block text-sm font-bold text-slate-800">
                Field 4 — Salary Preference
              </label>
              <div className="space-y-2 pt-1">
                {[
                  { id: 'paid_only', label: 'Paid only', desc: 'Only confirmed paid internships in Best Matches' },
                  {
                    id: 'paid_preferred',
                    label: 'Paid preferred, unknown salary allowed in a separate section',
                    desc: 'Paid in Best Matches; unverified compensation routed to Needs Review',
                  },
                  { id: 'exclude_unpaid', label: 'Exclude unpaid internships', desc: 'Allow unknown pay in Best Matches when all other checks pass; exclude unpaid'  },
                ].map((opt) => (
                  <label
                    key={opt.id}
                    className={`block p-3 rounded-lg border text-xs cursor-pointer transition ${
                      prefForm.salary_preference === opt.id
                        ? 'bg-indigo-50 border-indigo-300 text-indigo-900 font-medium'
                        : 'bg-white text-slate-700 hover:bg-slate-50'
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <input
                        type="radio"
                        name="salary_preference"
                        value={opt.id}
                        checked={prefForm.salary_preference === opt.id}
                        onChange={() => setPrefForm({ ...prefForm, salary_preference: opt.id })}
                        className="text-indigo-600 focus:ring-indigo-500"
                      />
                      <span className="font-semibold">{opt.label}</span>
                    </div>
                    <p className="text-[11px] text-slate-500 mt-1 ml-5">{opt.desc}</p>
                  </label>
                ))}
              </div>
            </div>

            <div className="grid sm:grid-cols-3 gap-3">
              <Field label="Minimum match score"><input type="number" min="0" max="100" value={prefForm.minimum_score ?? 50} onChange={e=>setPrefForm({...prefForm,minimum_score:Number(e.target.value)})}/></Field>
              <Field label="Maximum age in days (0 = any)"><input type="number" min="0" max="3650" value={prefForm.freshness_days ?? 0} onChange={e=>setPrefForm({...prefForm,freshness_days:Number(e.target.value)})}/></Field>
              <Field label="Refresh cache hours"><input type="number" min="1" max="168" value={prefForm.refresh_hours ?? 6} onChange={e=>setPrefForm({...prefForm,refresh_hours:Number(e.target.value)})}/></Field>
            </div>
            <p className="text-xs text-slate-500">Remotive always uses at least six hours. No automatic discovery runs.</p>
            <details><summary>Ranking weights</summary>{Object.entries(prefForm.ranking_weights || defaultPreferences.ranking_weights).map(([key,value])=><Field key={key} label={key}><input type="number" min="0" max="100" value={value} onChange={e=>setPrefForm({...prefForm,ranking_weights:{...prefForm.ranking_weights,[key]:Number(e.target.value)}})}/></Field>)}</details>
            <button type="button" className="border rounded px-3 py-2" onClick={async()=>{const r=await fetch(`${API}/api/preferences/defaults`); if(r.ok)setPrefForm(await r.json()); else setError('Could not load defaults')}}>Reset Preferences (save to apply)</button>
            {/* Modal Actions */}
            <div className="flex justify-end gap-2 border-t pt-4">
              <button
                type="button"
                aria-label="Close dialog"
                onClick={() => setShowPreferences(false)}
                className="border rounded-lg px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={savingPrefs}
                className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg px-5 py-2 text-sm font-semibold shadow-sm disabled:opacity-50 transition"
              >
                {savingPrefs ? 'Saving…' : 'Save Preferences & Reclassify'}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* ────────────────────────────────────────────────────────── */}
      {/* 4. Add Job Modal (Preserved & Enhanced) */}
      {/* ────────────────────────────────────────────────────────── */}
      {showAddJob && (
        <div role="dialog" aria-modal="true" aria-label="Internship OS dialog" className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4 backdrop-blur-sm">
          <form
            onSubmit={addJob}
            className="bg-white rounded-2xl shadow-xl p-6 w-full max-w-2xl max-h-[90vh] overflow-y-auto space-y-4"
          >
            <div className="flex justify-between items-center border-b pb-3">
              <h3 className="text-xl font-bold text-slate-900">Add Internship Opportunity</h3>
              <button
                type="button"
                aria-label="Close dialog"
                onClick={() => setShowAddJob(false)}
                className="text-slate-400 hover:text-slate-600 text-xl font-bold p-1"
              >
                ✕
              </button>
            </div>

            <Field label="Job URL *">
              <input
                required
                type="url"
                value={form.url}
                onChange={(e) => setForm({ ...form, url: e.target.value })}
                placeholder="https://company.com/jobs/internship"
              />
            </Field>

            <div className="grid sm:grid-cols-2 gap-3">
              <Field label="Job Title *">
                <input
                  required
                  value={form.title}
                  onChange={(e) => setForm({ ...form, title: e.target.value })}
                  placeholder="e.g. Full-Stack Engineer Intern"
                />
              </Field>
              <Field label="Company">
                <input
                  value={form.company}
                  onChange={(e) => setForm({ ...form, company: e.target.value })}
                  placeholder="e.g. Acme Tech"
                />
              </Field>
              <Field label="Location">
                <input
                  value={form.location}
                  onChange={(e) => setForm({ ...form, location: e.target.value })}
                  placeholder="e.g. Noida / Remote India"
                />
              </Field>
              <Field label="Work mode"><select value={form.source_work_mode} onChange={e=>setForm({...form,source_work_mode:e.target.value})}>{['unknown','On-site','Hybrid','Remote'].map(x=><option key={x}>{x}</option>)}</select></Field>
              <Field label="Compensation">
                <select
                  value={form.pay_status}
                  onChange={(e) => setForm({ ...form, pay_status: e.target.value })}
                >
                  <option value="paid">Paid (verified stipend/salary)</option>
                  <option value="unknown">Unknown / unverified</option>
                  <option value="unpaid">Unpaid</option>
                </select>
              </Field>
              <Field label="Source">
                <select
                  value={form.source}
                  onChange={(e) => setForm({ ...form, source: e.target.value })}
                >
                  {[
                    'Manual',
                    'Greenhouse',
                    'Lever',
                    'Ashby',
                    'LinkedIn',
                    'Wellfound',
                    'YC Jobs',
                    'Internshala',
                    'Cutshort',
                    'Indeed',
                    'Glassdoor',
                    'Company Careers',
                    'Other',
                  ].map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </Field>
            </div>

            <Field label="Job Description">
              <textarea
                rows="4"
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                placeholder="Paste key responsibilities and required tech stack..."
              />
            </Field>

            <p className="text-xs text-slate-500">
              Only mark "Paid" after verifying explicit stipend or salary details. Words like "paid leave" do not count.
            </p>

            <div className="flex justify-end gap-2 border-t pt-3">
              <button
                type="button"
                aria-label="Close dialog"
                onClick={() => setShowAddJob(false)}
                className="border rounded-lg px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg px-5 py-2 text-sm font-semibold shadow-sm transition"
              >
                Save and Score
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  )
}

function Field({ label, children }) {
  return (
    <label className="block text-sm font-medium text-slate-700">
      {label}
      <div className="mt-1 [&_input]:w-full [&_input]:border [&_input]:rounded-lg [&_input]:p-2 [&_input]:text-sm [&_select]:w-full [&_select]:border [&_select]:rounded-lg [&_select]:p-2 [&_select]:text-sm [&_textarea]:w-full [&_textarea]:border [&_textarea]:rounded-lg [&_textarea]:p-2 [&_textarea]:text-sm">
        {children}
      </div>
    </label>
  )
}
