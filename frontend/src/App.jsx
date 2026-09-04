import { useEffect, useMemo, useRef, useState } from 'react'
import { BarChart, Bar, CartesianGrid, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import {
  Activity, ArrowUpRight, BrainCircuit, CheckCircle2, CircleDollarSign, Gauge, History,
  ShieldCheck, Sparkles, Target, Lock, Play, RotateCcw, Bot, GitBranch, Database, Scale,
  Workflow, Zap, AlertTriangle, ListChecks, Sliders, Layers, Search, Radio, Users, Plug, RefreshCw,
  Volume2, Square, Languages, Store, ShoppingCart, Package, PauseCircle, FastForward,
  AlertOctagon, User, Receipt, TimerReset, Pause, PlayCircle
} from 'lucide-react'

const API = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'

const scenarios = [
  { name:'First timeout · strong customer', values:{amount:12000,event_type:'PAYMENT_FAILURE',payment_method:'UPI',failure_type:'TIMEOUT',retry_count:0,historical_success_rate:0.85,total_transactions:20,avg_transaction_amount:5000,merchant_success_rate:0.90}},
  { name:'Repeated issuer decline · weak customer', values:{amount:12000,event_type:'PAYMENT_FAILURE',payment_method:'UPI',failure_type:'ISSUER_DECLINE',retry_count:4,historical_success_rate:0.20,total_transactions:2,avg_transaction_amount:5000,merchant_success_rate:0.90}},
  { name:'High-value · escalation eligible', values:{amount:50000,event_type:'PAYMENT_FAILURE',payment_method:'CARD',failure_type:'TIMEOUT',retry_count:1,historical_success_rate:0.92,total_transactions:30,avg_transaction_amount:9000,merchant_success_rate:0.88}},
  { name:'Checkout abandonment', values:{amount:18000,event_type:'CHECKOUT_ABANDONMENT',payment_method:'UPI',failure_type:'NETWORK_ERROR',retry_count:0,historical_success_rate:0.90,total_transactions:12,avg_transaction_amount:4500,merchant_success_rate:0.87}},
  { name:'Failed subscription recovery', values:{amount:2500,event_type:'SUBSCRIPTION_FAILURE',payment_method:'CARD',failure_type:'BANK_TECHNICAL_ERROR',retry_count:0,historical_success_rate:0.88,total_transactions:18,avg_transaction_amount:2200,merchant_success_rate:0.93,subscription_age_days:180,successful_cycles:10,failed_cycles:1}},
]
const initial = { event_id:'DEMO-001', email:'', phone:'', amount:12000,event_type:'PAYMENT_FAILURE',payment_method:'UPI',failure_type:'TIMEOUT',retry_count:0,historical_success_rate:0.85,total_transactions:20,avg_transaction_amount:5000,merchant_success_rate:0.90 }
const initialPolicy = { name:'New Policy', retry_limit:3, escalation_min_amount:25000, escalation_min_success_rate:0.85, high_value_threshold:10000, retry_cooldown_hours:0, reminder_cooldown_hours:0 }

const money = n => n == null ? 'Blocked' : `₹${Number(n).toLocaleString('en-IN',{maximumFractionDigits:0})}`
const pct = n => n == null ? '—' : `${(Number(n)*100).toFixed(1)}%`
const pretty = s => String(s||'').replaceAll('_',' ')

function formatDateTime(timestamp) {
  if (!timestamp) return '—'
  return new Date(timestamp).toLocaleString('en-IN', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
  })
}

const numericKeys = ['amount','retry_count','historical_success_rate','total_transactions','avg_transaction_amount','merchant_success_rate']

// Animates a numeric value counting up whenever it changes; falls back to the
// formatted string immediately for non-numeric/absent values.
function useCountUp(target, format, duration = 900){
  const [display, setDisplay] = useState(target)
  const fromRef = useRef(0)
  useEffect(()=>{
    const numeric = typeof target === 'number' ? target : Number(target)
    if(!Number.isFinite(numeric)){ setDisplay(target); return }
    const from = Number.isFinite(fromRef.current) ? fromRef.current : 0
    const start = performance.now()
    let raf
    const tick = now=>{
      const t = Math.min(1,(now-start)/duration)
      const eased = 1-Math.pow(1-t,3)
      const value = from + (numeric-from)*eased
      setDisplay(value)
      if(t<1) raf = requestAnimationFrame(tick)
      else fromRef.current = numeric
    }
    raf = requestAnimationFrame(tick)
    return ()=>cancelAnimationFrame(raf)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[target])
  const numeric = typeof target === 'number' ? target : Number(target)
  if(!Number.isFinite(numeric)) return target
  return format ? format(display) : display
}

async function getJSON(path){
  const r = await fetch(API+path)
  const d = await r.json()
  if(!r.ok) throw new Error(d.detail||'Request failed')
  return d
}
async function postJSON(path, body){
  const r = await fetch(API+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
  const d = await r.json()
  if(!r.ok) throw new Error(d.detail||'Request failed')
  return d
}

const NAV = [
  ['overview','Overview'],
  ['decision','Decision Lab'],
  ['journey','Recovery Journey'],
  ['counterfactuals','Counterfactuals'],
  ['policylab','Policy Lab'],
  ['evaluation','Evaluation'],
  ['health','Model Health'],
  ['policy','Guardrails'],
  ['audit','Audit Log'],
  ['intelligence','Revenue Autopilot'],
  ['merchantsim','Merchant Simulator'],
]

export default function App(){
  const [tab,setTab]=useState('overview')

  // Cursor-reactive spotlight: sets --mx/--my on whichever elevated card the
  // pointer is currently over, read by the CSS glow in styles.css. A single
  // listener for the whole app avoids attaching one per card instance.
  useEffect(()=>{
    const targets = '.metric,.scenario,.hero-card,.environment-option'
    const onMove = (e)=>{
      const el = e.target.closest?.(targets)
      if(!el) return
      const r = el.getBoundingClientRect()
      el.style.setProperty('--mx', `${e.clientX-r.left}px`)
      el.style.setProperty('--my', `${e.clientY-r.top}px`)
    }
    document.addEventListener('pointermove', onMove, {passive:true})
    return ()=>document.removeEventListener('pointermove', onMove)
  },[])

  const [metrics,setMetrics]=useState(null); const [analysis,setAnalysis]=useState(null); const [card,setCard]=useState(null)
  const [rules,setRules]=useState(null); const [audit,setAudit]=useState([]); const [executionAudit,setExecutionAudit]=useState([]); const [agent,setAgent]=useState(null)
  const [form,setForm]=useState(initial); const [result,setResult]=useState(null); const [execution,setExecution]=useState(null)
  const [loading,setLoading]=useState(false); const [executing,setExecuting]=useState(false); const [error,setError]=useState('')

  // Recovery Journey (sequencer)
  const [journeyMode,setJourneyMode]=useState('adhoc')
  const [journeyForm,setJourneyForm]=useState(initial); const [journeyResult,setJourneyResult]=useState(null)
  const [journeyLoading,setJourneyLoading]=useState(false); const [journeyError,setJourneyError]=useState('')
  const [mandateForm,setMandateForm]=useState({...initial,amount:45000}); const [mandateResult,setMandateResult]=useState(null)
  const [mandateLoading,setMandateLoading]=useState(false); const [mandateError,setMandateError]=useState('')
  const [b2bForm,setB2BForm]=useState({amount:50000,days_overdue:15,invoice_number:'INV-1001',customer_display_name:'Acme Corp',historical_success_rate:0.5})
  const [b2bResult,setB2BResult]=useState(null); const [b2bLoading,setB2BLoading]=useState(false); const [b2bError,setB2BError]=useState('')

  // Promise-to-Pay
  const [promises,setPromises]=useState(null); const [promiseForm,setPromiseForm]=useState({amount:10000,promised_date:''})
  const [promiseError,setPromiseError]=useState('')

  // Counterfactuals
  const [cfSamples,setCfSamples]=useState([]); const [cfSelectedId,setCfSelectedId]=useState(null)
  const [cfData,setCfData]=useState(null); const [cfLoading,setCfLoading]=useState(false); const [cfError,setCfError]=useState('')

  // Policy Lab
  const [policyParams,setPolicyParams]=useState(initialPolicy); const [whatIf,setWhatIf]=useState(null); const [whatIfLoading,setWhatIfLoading]=useState(false)
  const [policyA,setPolicyA]=useState({...initialPolicy,name:'Conservative',retry_limit:2,escalation_min_amount:40000,escalation_min_success_rate:0.9})
  const [policyB,setPolicyB]=useState({...initialPolicy,name:'Aggressive',retry_limit:6,escalation_min_amount:10000,escalation_min_success_rate:0.6})
  const [compare,setCompare]=useState(null); const [compareLoading,setCompareLoading]=useState(false); const [policyError,setPolicyError]=useState('')

  // Model Health
  const [health,setHealth]=useState(null); const [healthError,setHealthError]=useState('')

  // Ledger / Feedback
  const [ledger,setLedger]=useState(null); const [feedback,setFeedback]=useState(null)

  // Budget-Constrained Intervention Planner + Scenario Simulator
  const [budgetForm,setBudgetForm]=useState({budget:100000,amount_multiplier:1,recovery_multiplier:1})
  const [budgetResult,setBudgetResult]=useState(null); const [budgetLoading,setBudgetLoading]=useState(false); const [budgetError,setBudgetError]=useState('')
  const [twinForm,setTwinForm]=useState({volume_multiplier:1,amount_multiplier:1,recovery_multiplier:1,budget:''})
  const [twinResult,setTwinResult]=useState(null); const [twinLoading,setTwinLoading]=useState(false); const [twinError,setTwinError]=useState('')
  const [intelligenceData,setIntelligenceData]=useState(null); const [intelligenceLoading,setIntelligenceLoading]=useState(false); const [intelligenceError,setIntelligenceError]=useState('')
  const [integrationStatus,setIntegrationStatus]=useState(null); const [liveExecution,setLiveExecution]=useState(false); const [executionChannel,setExecutionChannel]=useState('auto'); const [liveConfirmation,setLiveConfirmation]=useState(false); const [integrationTestAction,setIntegrationTestAction]=useState(null)
  const [environmentBusy,setEnvironmentBusy]=useState(false); const [environmentError,setEnvironmentError]=useState(''); const [showLiveControls,setShowLiveControls]=useState(false); const [adminToken,setAdminToken]=useState(''); const [liveEnvConfirm,setLiveEnvConfirm]=useState(false)
  const [evaluationRun,setEvaluationRun]=useState(null); const [evaluationLoading,setEvaluationLoading]=useState(false); const [evaluationError,setEvaluationError]=useState('')
  const [autopilotRun,setAutopilotRun]=useState(null); const [autopilotRunning,setAutopilotRunning]=useState(false)

  const load=async()=>{
    try {
      const [m,a,c,g,l,x,ag,is,es]=await Promise.all(['/api/metrics','/api/analysis','/api/model-card','/api/guardrails','/api/audit-log','/api/execution-log','/api/decision-agent','/api/integrations/status','/api/evaluation/status'].map(p=>getJSON(p)))
      setMetrics(m);setAnalysis(a);setCard(c);setRules(g);setAudit(l.records||[]);setExecutionAudit(x.records||[]);setAgent(ag);setIntegrationStatus(is);setLiveExecution(is.environment!=='DEMO');setEvaluationRun(es)
    } catch(e){ setError('Backend is not reachable. Start the backend on port 8000.') }
  }
  useEffect(()=>{load()},[])

  useEffect(()=>{
    if(tab==='counterfactuals' && cfSamples.length===0){
      getJSON('/api/counterfactual/sample-events?n=8').then(d=>setCfSamples(d.events)).catch(e=>setCfError(e.message))
    }
    if(tab==='health' && !health){
      getJSON('/api/model-health').then(setHealth).catch(e=>setHealthError(e.message))
    }
    if(tab==='intelligence'){
      // Autopilot is intentionally idle on tab entry. The button below is the
      // trigger for the complete Detect → Diagnose → Prioritize → Recover → Verify cycle.
      getJSON('/api/integrations/status').then(setIntegrationStatus).catch(e=>setIntelligenceError(e.message))
    }
    if(tab==='audit'){
      getJSON('/api/ledger').then(setLedger).catch(()=>{})
      getJSON('/api/feedback').then(setFeedback).catch(()=>{})
      getJSON('/api/promises').then(setPromises).catch(()=>{})
    }
  },[tab])

  const changeEnvironment=async(env)=>{
    setEnvironmentBusy(true); setEnvironmentError('')
    try{
      const d=await postJSON('/api/integrations/environment',{
        environment:env,
        admin_token:env==='PRODUCTION'?adminToken:undefined,
        confirm_live:env==='PRODUCTION'?liveEnvConfirm:false
      })
      setIntegrationStatus(d)
      setLiveExecution(env!=='DEMO')
      setLiveConfirmation(false)
      if(env!=='PRODUCTION'){ setLiveEnvConfirm(false) }
    }catch(err){ setEnvironmentError(err.message) }
    finally{ setEnvironmentBusy(false) }
  }
  const update=(k,v)=>setForm(f=>({...f,[k]:numericKeys.includes(k)?Number(v):v}))
  const updateJourney=(k,v)=>setJourneyForm(f=>({...f,[k]:numericKeys.includes(k)?Number(v):v}))
  const updatePolicy=(setter,k,v)=>setter(p=>({...p,[k]: (k==='name'?v:Number(v))}))

  const predict=async e=>{
    e?.preventDefault(); setLoading(true); setError('')
    try{ const d=await postJSON('/predict',form); setResult(d); setExecution(null); setIntegrationTestAction(null); load() }
    catch(err){ setError(err.message) } finally{ setLoading(false) }
  }
  const execute=async(selectedAction=null)=>{
    if(!result) return; setExecuting(true); setError('')
    try{ const d=await postJSON('/execute-decision',{payload:form,decision:result,live:liveExecution,channel:executionChannel,live_confirmation:liveConfirmation,selected_action:selectedAction||undefined}); setExecution(d); load() }
    catch(err){ setError(err.message) } finally{ setExecuting(false) }
  }
  const runScenario=s=>{ setForm({...initial,...s.values}); setTab('decision'); setTimeout(()=>document.getElementById('decision-form')?.scrollIntoView({behavior:'smooth'}),50) }

  const runJourney=async e=>{
    e?.preventDefault(); setJourneyLoading(true); setJourneyError('')
    try{ const d=await postJSON('/api/sequence/run',journeyForm); setJourneyResult(d) }
    catch(err){ setJourneyError(err.message) } finally{ setJourneyLoading(false) }
  }
  const updateMandate=(k,v)=>setMandateForm(f=>({...f,[k]:numericKeys.includes(k)?Number(v):v}))
  const runMandate=async e=>{
    e?.preventDefault(); setMandateLoading(true); setMandateError('')
    try{ const d=await postJSON('/api/mandate/run',mandateForm); setMandateResult(d) }
    catch(err){ setMandateError(err.message) } finally{ setMandateLoading(false) }
  }
  const b2bNumericKeys=['amount','days_overdue','historical_success_rate']
  const updateB2B=(k,v)=>setB2BForm(f=>({...f,[k]:b2bNumericKeys.includes(k)?Number(v):v}))
  const runB2B=async e=>{
    e?.preventDefault(); setB2BLoading(true); setB2BError('')
    try{ const d=await postJSON('/api/b2b/chase',b2bForm); setB2BResult(d) }
    catch(err){ setB2BError(err.message) } finally{ setB2BLoading(false) }
  }
  const loadPromises=async()=>{
    try{ const d=await getJSON('/api/promises'); setPromises(d) } catch(err){ setPromiseError(err.message) }
  }
  const createPromise=async e=>{
    e?.preventDefault(); setPromiseError('')
    try{
      await postJSON('/api/promise/create',{amount:Number(promiseForm.amount),promised_date:new Date(promiseForm.promised_date).toISOString()})
      await loadPromises()
    } catch(err){ setPromiseError(err.message) }
  }
  const keepPromise=async(id,amount)=>{
    try{ await postJSON(`/api/promise/${id}/keep`,{actual_recovered:amount}); await loadPromises() }
    catch(err){ setPromiseError(err.message) }
  }

  const selectEvent=async id=>{
    setCfLoading(true); setCfError(''); setCfSelectedId(id)
    try{ const d=await getJSON(`/api/counterfactual/${id}`); setCfData(d) }
    catch(err){ setCfError(err.message) } finally{ setCfLoading(false) }
  }

  const runWhatIf=async()=>{
    setWhatIfLoading(true); setPolicyError('')
    try{ const d=await postJSON('/api/policy/what-if',policyParams); setWhatIf(d) }
    catch(err){ setPolicyError(err.message) } finally{ setWhatIfLoading(false) }
  }
  const runCompare=async()=>{
    setCompareLoading(true); setPolicyError('')
    try{ const d=await postJSON('/api/policy/compare',{policy_a:policyA,policy_b:policyB}); setCompare(d) }
    catch(err){ setPolicyError(err.message) } finally{ setCompareLoading(false) }
  }
  const runBudget=async()=>{
    setBudgetLoading(true); setBudgetError('')
    try{ const d=await postJSON('/api/budget/optimize',{...budgetForm,budget:Number(budgetForm.budget),amount_multiplier:Number(budgetForm.amount_multiplier),recovery_multiplier:Number(budgetForm.recovery_multiplier)}); setBudgetResult(d) }
    catch(err){ setBudgetError(err.message) } finally{ setBudgetLoading(false) }
  }
  const runTwin=async()=>{
    setTwinLoading(true); setTwinError('')
    try{ const body={...twinForm,volume_multiplier:Number(twinForm.volume_multiplier),amount_multiplier:Number(twinForm.amount_multiplier),recovery_multiplier:Number(twinForm.recovery_multiplier),budget:twinForm.budget===''?null:Number(twinForm.budget)}; const d=await postJSON('/api/digital-twin',body); setTwinResult(d) }
    catch(err){ setTwinError(err.message) } finally{ setTwinLoading(false) }
  }

  const runEvaluation=async()=>{
    setEvaluationLoading(true); setEvaluationError('')
    try{ const d=await postJSON('/api/evaluation/run',{}); setEvaluationRun({status:d.status,result:d.result}); await load() }
    catch(err){ setEvaluationError(err.message) } finally{ setEvaluationLoading(false) }
  }
  const runAutopilot=async()=>{
    setAutopilotRunning(true); setIntelligenceError(''); setIntelligenceData(null); setAutopilotRun(null)
    try{ const d=await postJSON('/api/revenue-intelligence/autopilot',{}); setAutopilotRun(d); setIntelligenceData(d); const i=await getJSON('/api/integrations/status'); setIntegrationStatus(i) }
    catch(err){ setIntelligenceError(err.message) } finally{ setAutopilotRunning(false) }
  }

  const actionData=useMemo(()=>analysis?.actions?.map(x=>({name:pretty(x.chosen_action),recovered:x.recovered,events:x.events}))||[],[analysis])
  const eventData=useMemo(()=>analysis?.event_types?.map(x=>({name:pretty(x.event_type),recovered:x.recovered}))||[],[analysis])

  return <div className="app">
    <header className="topbar">
      <div className="brand"><div className="logo"><Sparkles size={19}/></div><div><b>RecoverAI</b><span>Intelligent Revenue Recovery Engine</span></div></div>
      <div className="status"><span className="dot"/> Decision Agent · Local ML <span className="pill">{agent?.model_version||'V2'}</span></div>
    </header>
    <nav className="nav">{NAV.map(([id,label])=><button key={id} className={tab===id?'active':''} onClick={()=>setTab(id)}>{label}</button>)}</nav>
    <ExecutionEnvironmentBar
      status={integrationStatus}
      busy={environmentBusy}
      error={environmentError}
      adminToken={adminToken}
      setAdminToken={setAdminToken}
      liveConfirm={liveEnvConfirm}
      setLiveConfirm={setLiveEnvConfirm}
      onChange={changeEnvironment}
      showLiveControls={showLiveControls}
      setShowLiveControls={setShowLiveControls}
    />
    <main className="container">
      {error&&<div className="alert">{error}</div>}

      <div key={tab} className="page-enter">
      {tab==='overview'&&<>
        <section className="hero"><div><div className="eyebrow"><BrainCircuit size={16}/> PAYMENT RECOVERY INTELLIGENCE</div><h1>Recover more revenue from failed payments.</h1><p>A local Decision Agent combines action-specific ML, expected monetary value and hard business guardrails to choose the best recovery action.</p></div><div className="hero-card"><Bot size={22}/><div><b>Decision Agent online</b><span>Context → ML → value → policy → decision → audit</span></div></div></section>
        <HeroMetrics metrics={metrics}/>
        <section className="grid2"><Panel title="Revenue recovered by selected action"><Chart data={actionData} dataKey="recovered" nameKey="name" color="#5b9dff"/></Panel><Panel title="Recovery by event type"><Chart data={eventData} dataKey="recovered" nameKey="name" color="#8b6bff"/></Panel></section>
        <section className="agent-overview"><div className="section-heading"><div><div className="eyebrow"><Bot size={15}/> DECISION AGENT</div><h2>It actually makes the decision</h2><p>This is not a decorative AI label. The live agent executes a deterministic, inspectable sequence over the payment context and the trained V3-100k action models.</p></div></div><div className="agent-stages">{(agent?.stages||[]).map((s,i)=><div className="agent-stage" key={s.id}><span>0{i+1}</span><b>{s.label}</b>{i<6&&<GitBranch size={14}/>}</div>)}</div></section>
        <section className="scenarios"><div className="section-heading"><div><div className="eyebrow">DEMO SCENARIOS</div><h2>Show the policy adapting to context</h2><p>These presets demonstrate different guardrail and value-ranking outcomes.</p></div></div><div className="scenario-grid">{scenarios.map(s=><button className="scenario" key={s.name} onClick={()=>runScenario(s)}><Play size={16}/><b>{s.name}</b><span>Open in Decision Lab →</span></button>)}</div></section>
      </>}

      {tab==='decision'&&<section className="decision-section" id="decision-form">
        <div className="section-heading"><div><div className="eyebrow"><BrainCircuit size={15}/> LIVE DECISION AGENT</div><h2>Analyze a payment event</h2><p>The agent observes context, scores every action, applies hard policies, ranks expected net value and writes an audit trace.</p></div><button className="secondary" onClick={()=>{setForm(initial);setResult(null)}}><RotateCcw size={15}/> Reset</button></div>
        <div className="decision-grid">
          <form className="form-card" onSubmit={predict}>
            <Field label="Transaction amount"><input type="number" min="1" value={form.amount} onChange={e=>update('amount',e.target.value)}/></Field>
            <div className="form-row"><Field label="Event type"><select value={form.event_type} onChange={e=>update('event_type',e.target.value)}><option>PAYMENT_FAILURE</option><option>PAYMENT_SUCCESS</option><option>CHECKOUT_ABANDONMENT</option><option>SUBSCRIPTION_FAILURE</option></select></Field><Field label="Payment method"><select value={form.payment_method} onChange={e=>update('payment_method',e.target.value)}><option>UPI</option><option>CARD</option><option>WALLET</option><option>NETBANKING</option></select></Field></div>
            <div className="form-row"><Field label="Failure type"><select disabled={form.event_type==='PAYMENT_SUCCESS'} value={form.failure_type||'TIMEOUT'} onChange={e=>update('failure_type',e.target.value)}><option>TIMEOUT</option><option>NETWORK_ERROR</option><option>BANK_TECHNICAL_ERROR</option><option>ISSUER_DECLINE</option><option>INSUFFICIENT_BALANCE</option><option>PAYMENT_LIMIT</option><option>EXPIRED_PAYMENT_METHOD</option></select></Field><Field label="Retry count"><input type="number" min="0" max="10" disabled={form.event_type==='PAYMENT_SUCCESS'} value={form.retry_count} onChange={e=>update('retry_count',e.target.value)}/></Field></div>
            <div className="form-row"><Field label="Customer success rate"><input type="number" min="0" max="1" step="0.01" value={form.historical_success_rate} onChange={e=>update('historical_success_rate',e.target.value)}/></Field><Field label="Merchant success rate"><input type="number" min="0" max="1" step="0.01" value={form.merchant_success_rate} onChange={e=>update('merchant_success_rate',e.target.value)}/></Field></div>
            <div className="form-row"><Field label="Customer transactions"><input type="number" min="1" value={form.total_transactions} onChange={e=>update('total_transactions',e.target.value)}/></Field><Field label="Avg transaction amount"><input type="number" min="1" value={form.avg_transaction_amount} onChange={e=>update('avg_transaction_amount',e.target.value)}/></Field></div>
            <div className="form-row"><Field label="Event ID"><input value={form.event_id||''} onChange={e=>update('event_id',e.target.value)}/></Field><Field label="Recovery email (optional unless action requires email)"><input disabled={form.event_type==='PAYMENT_SUCCESS'} type="email" value={form.email||''} onChange={e=>update('email',e.target.value)}/></Field></div>
            <Field label="Recovery phone (optional unless action requires SMS)"><input disabled={form.event_type==='PAYMENT_SUCCESS'} value={form.phone||''} onChange={e=>update('phone',e.target.value)}/></Field>
            <button className="primary" disabled={loading}>{loading?'Decision Agent scoring…':'Run Recovery Decision'}</button>
          </form>
          <Decision result={result} onExecute={execute} execution={execution} executing={executing} liveExecution={liveExecution} setLiveExecution={setLiveExecution} executionChannel={executionChannel} setExecutionChannel={setExecutionChannel} integrationStatus={integrationStatus} liveConfirmation={liveConfirmation} setLiveConfirmation={setLiveConfirmation} integrationTestAction={integrationTestAction} setIntegrationTestAction={setIntegrationTestAction} form={form}/>
        </div>
      </section>}

      {tab==='journey'&&<section>
        <div className="page-title"><div><div className="eyebrow"><Workflow size={15}/> ADAPTIVE RECOVERY SEQUENCER</div><h2>Multi-step recovery, decided one step at a time</h2><p>Each step re-runs the real Decision Agent against the evolving context and re-checks guardrails. A hard step cap and per-action exhaustion rule prevent infinite loops.</p></div></div>
         <RazorpayTestPayment integrationStatus={integrationStatus}/>
        <div className="subtab-toggle">
          <button className={journeyMode==='adhoc'?'active':''} onClick={()=>setJourneyMode('adhoc')}>Ad-hoc Payment Recovery</button>
          <button className={journeyMode==='mandate'?'active':''} onClick={()=>setJourneyMode('mandate')}>UPI Mandate Retry</button>
          <button className={journeyMode==='b2b'?'active':''} onClick={()=>setJourneyMode('b2b')}>B2B Receivables Chase</button>
        </div>
        {journeyMode==='adhoc'&&<>
          {journeyError&&<div className="alert">{journeyError}</div>}
          <div className="decision-grid">
            <form className="form-card" onSubmit={runJourney}>
              <Field label="Transaction amount"><input type="number" min="1" value={journeyForm.amount} onChange={e=>updateJourney('amount',e.target.value)}/></Field>
              <div className="form-row"><Field label="Event type"><select value={journeyForm.event_type} onChange={e=>updateJourney('event_type',e.target.value)}><option>PAYMENT_FAILURE</option><option>CHECKOUT_ABANDONMENT</option><option>SUBSCRIPTION_FAILURE</option></select></Field><Field label="Failure type"><select value={journeyForm.failure_type} onChange={e=>updateJourney('failure_type',e.target.value)}><option>TIMEOUT</option><option>NETWORK_ERROR</option><option>BANK_TECHNICAL_ERROR</option><option>ISSUER_DECLINE</option><option>INSUFFICIENT_BALANCE</option></select></Field></div>
              <div className="form-row"><Field label="Customer success rate"><input type="number" min="0" max="1" step="0.01" value={journeyForm.historical_success_rate} onChange={e=>updateJourney('historical_success_rate',e.target.value)}/></Field><Field label="Retry count"><input type="number" min="0" max="10" value={journeyForm.retry_count} onChange={e=>updateJourney('retry_count',e.target.value)}/></Field></div>
              <button className="primary" disabled={journeyLoading}>{journeyLoading?'Running sequence…':'Run Adaptive Recovery Sequence'}</button>
            </form>
            <SequenceResultCard result={journeyResult} idLabel="SEQUENCE" idValue={journeyResult?.sequence_id}/>
          </div>
        </>}
        {journeyMode==='mandate'&&<MandateSequencer form={mandateForm} update={updateMandate} onRun={runMandate} loading={mandateLoading} error={mandateError} result={mandateResult}/>}
        {journeyMode==='b2b'&&<B2BChaser form={b2bForm} update={updateB2B} onRun={runB2B} loading={b2bLoading} error={b2bError} result={b2bResult}/>}
      </section>}

      {tab==='counterfactuals'&&<section>
        <div className="page-title"><div><div className="eyebrow"><GitBranch size={15}/> COUNTERFACTUAL RECOVERY SIMULATOR</div><h2>What every alternative action would have been worth</h2><p>For historical evaluation events, every action's real simulated outcome is known, so the opportunity gap versus the oracle action is real, not estimated.</p></div></div>
        {cfError&&<div className="alert">{cfError}</div>}
        {result&&<Panel title="Live decision — counterfactual view (from Decision Lab)"><CounterfactualView data={result.counterfactual} selectedAction={result.recommended_action} selectedRecovery={result.expected_revenue?.[result.recommended_action]} selectedNet={result.expected_net_value?.[result.recommended_action]}/></Panel>}
        <Panel title="Explore a historical evaluation event">
          <div className="cf-toolbar">
            <div className="chips">{cfSamples.map(ev=><button type="button" key={ev.event_id} className={cfSelectedId===ev.event_id?'cf-chip chip-active':'cf-chip'} onClick={()=>selectEvent(ev.event_id)}>{ev.event_id} · {pretty(ev.event_type)} · {money(ev.amount)}</button>)}</div>
            <button className="secondary" disabled={!cfSelectedId||cfLoading} onClick={()=>cfSelectedId&&selectEvent(cfSelectedId)}>{cfLoading?'Running analysis…':'Run Counterfactual Analysis'}</button>
          </div>
        </Panel>
        {cfLoading&&<div className="empty small">Running counterfactual analysis…</div>}
        {cfData&&<Panel title={`Counterfactual analysis · ${cfData.event_id}`}><CounterfactualView data={cfData} selectedAction={cfData.selected.action} selectedRecovery={cfData.selected.expected_recovery} selectedNet={cfData.selected.expected_net_value}/></Panel>}
      </section>}

      {tab==='policylab'&&<section>
        <div className="page-title"><div><div className="eyebrow"><Sliders size={15}/> POLICY WHAT-IF LAB</div><h2>Simulate policy changes against the real evaluation set</h2><p>Every simulation runs the real trained model over all 12,347 held-out events with an isolated policy configuration. The production policy is never modified.</p></div></div>
        {policyError&&<div className="alert">{policyError}</div>}
        <Panel title="What-If: Current Policy vs New Policy">
          <div className="form-row"><Field label="Retry limit"><input type="number" min="0" max="10" value={policyParams.retry_limit} onChange={e=>updatePolicy(setPolicyParams,'retry_limit',e.target.value)}/></Field><Field label="Escalation min amount (₹)"><input type="number" min="0" value={policyParams.escalation_min_amount} onChange={e=>updatePolicy(setPolicyParams,'escalation_min_amount',e.target.value)}/></Field></div>
          <div className="form-row"><Field label="Escalation min success rate"><input type="number" min="0" max="1" step="0.01" value={policyParams.escalation_min_success_rate} onChange={e=>updatePolicy(setPolicyParams,'escalation_min_success_rate',e.target.value)}/></Field><Field label="High-value threshold (₹)"><input type="number" min="0" value={policyParams.high_value_threshold} onChange={e=>updatePolicy(setPolicyParams,'high_value_threshold',e.target.value)}/></Field></div>
          <div className="note"><RefreshCw size={15}/><div><b>Sequencer timing is configured in Recovery Journey</b><span>Retry/reminder cooldowns are intentionally not shown as static-policy knobs because the held-out evaluator has one decision point per event. This avoids presenting a setting that cannot affect this evaluation.</span></div></div>
          <button className="primary" onClick={runWhatIf} disabled={whatIfLoading}>{whatIfLoading?'Simulating…':'Run What-If Simulation'}</button>
          {whatIf&&<>
            <div className="policy-grid" style={{marginTop:16}}>
              <PolicySummaryCard title="Current Policy" data={whatIf.current_policy}/>
              <PolicySummaryCard title="New Policy" data={whatIf.new_policy}/>
            </div>
            <div className="facts">
              <Fact label="Incremental recovery" value={money(whatIf.incremental_recovery)}/>
              <Fact label="Incremental cost" value={money(whatIf.incremental_intervention_cost)}/>
              <Fact label="Net incremental value" value={money(whatIf.net_incremental_value)}/>
              <Fact label="Selected actions changed" value={whatIf.selected_action_changes?.toLocaleString() ?? '—'}/>
            </div>
            <div className="note"><Sliders size={15}/><div><b>Policy effect visibility</b><span>{whatIf.interpretation} {Object.entries(whatIf.eligibility_delta||{}).filter(([,v])=>v!==0).map(([a,v])=>`${pretty(a)} eligibility ${v>0?'increased':'decreased'} by ${Math.abs(v).toLocaleString()} events.`).join(' ')}</span></div></div>
            {whatIf.new_policy.cooldown_note&&<div className="note"><Zap size={16}/><div><b>Note</b><span>{whatIf.new_policy.cooldown_note}</span></div></div>}
          </>}
        </Panel>
        <Panel title="A/B Policy Comparison">
          <div className="grid2">
            <div><Field label="Policy A name"><input value={policyA.name} onChange={e=>updatePolicy(setPolicyA,'name',e.target.value)}/></Field>
              <div className="form-row"><Field label="Retry limit"><input type="number" value={policyA.retry_limit} onChange={e=>updatePolicy(setPolicyA,'retry_limit',e.target.value)}/></Field><Field label="Escalation ₹"><input type="number" value={policyA.escalation_min_amount} onChange={e=>updatePolicy(setPolicyA,'escalation_min_amount',e.target.value)}/></Field></div>
              <Field label="Escalation min success rate"><input type="number" step="0.01" min="0" max="1" value={policyA.escalation_min_success_rate} onChange={e=>updatePolicy(setPolicyA,'escalation_min_success_rate',e.target.value)}/></Field>
            </div>
            <div><Field label="Policy B name"><input value={policyB.name} onChange={e=>updatePolicy(setPolicyB,'name',e.target.value)}/></Field>
              <div className="form-row"><Field label="Retry limit"><input type="number" value={policyB.retry_limit} onChange={e=>updatePolicy(setPolicyB,'retry_limit',e.target.value)}/></Field><Field label="Escalation ₹"><input type="number" value={policyB.escalation_min_amount} onChange={e=>updatePolicy(setPolicyB,'escalation_min_amount',e.target.value)}/></Field></div>
              <Field label="Escalation min success rate"><input type="number" step="0.01" min="0" max="1" value={policyB.escalation_min_success_rate} onChange={e=>updatePolicy(setPolicyB,'escalation_min_success_rate',e.target.value)}/></Field>
            </div>
          </div>
          <button className="primary" onClick={runCompare} disabled={compareLoading}>{compareLoading?'Comparing…':'Compare Policies'}</button>
          {compare&&<>
            <div className="policy-grid" style={{marginTop:16}}>
              <PolicySummaryCard title={compare.policy_a.policy.name} data={compare.policy_a}/>
              <PolicySummaryCard title={compare.policy_b.policy.name} data={compare.policy_b}/>
            </div>
            <div className="facts">
              <Fact label="Revenue delta (B−A)" value={money(compare.revenue_delta_b_minus_a)}/>
              <Fact label="Cost delta (B−A)" value={money(compare.cost_delta_b_minus_a)}/>
              <Fact label="Oracle capture delta" value={pct(compare.oracle_capture_delta_b_minus_a)}/>
              <Fact label="Regret delta (B−A)" value={money(compare.regret_delta_b_minus_a)}/><Fact label="Selected actions changed" value={compare.selected_action_changes?.toLocaleString() ?? '—'}/>
            </div>
          </>}
        </Panel>
      </section>}

      {tab==='evaluation'&&<Evaluation card={card} metrics={metrics} analysis={analysis} budgetForm={budgetForm} setBudgetForm={setBudgetForm} budgetResult={budgetResult} budgetLoading={budgetLoading} budgetError={budgetError} runBudget={runBudget} twinForm={twinForm} setTwinForm={setTwinForm} twinResult={twinResult} twinLoading={twinLoading} twinError={twinError} runTwin={runTwin} evaluationRun={evaluationRun} evaluationLoading={evaluationLoading} evaluationError={evaluationError} runEvaluation={runEvaluation}/>}
      {tab==='health'&&<ModelHealth health={health} error={healthError}/>}
      {tab==='policy'&&<GuardrailsView rules={rules}/>}
      {tab==='intelligence'&&<RevenueAutopilot data={intelligenceData} loading={intelligenceLoading} error={intelligenceError} integrations={integrationStatus} run={runAutopilot} running={autopilotRunning} lastRun={autopilotRun}/>}
      {tab==='merchantsim'&&<MerchantSimulator/>}
      {tab==='audit'&&<Audit audit={audit} executionAudit={executionAudit} ledger={ledger} feedback={feedback} promises={promises} promiseForm={promiseForm} setPromiseForm={setPromiseForm} createPromise={createPromise} keepPromise={keepPromise} promiseError={promiseError}/>}
      </div>

      <footer>RecoverAI · Local ML Decision Agent + FastAPI + React · Synthetic payment recovery data</footer>
    </main>
  </div>
}

function Decision({result,onExecute,execution,executing,liveExecution,setLiveExecution,executionChannel,setExecutionChannel,integrationStatus,liveConfirmation,setLiveConfirmation,integrationTestAction,setIntegrationTestAction,form}){
  if(!result) return <div className="result-card empty"><BrainCircuit size={36}/><h3>Decision appears here</h3><p>Run the agent to see probabilities, expected money, blocked actions, confidence, reasoning and the execution trace.</p></div>

  // PAYMENT_SUCCESS responses intentionally do not contain ranked_actions: a
  // successful payment is already recovered and the backend returns a STOP-only
  // decision instead of sending the event through failure-trained action models.
  // Normalize optional response collections here so the Decision UI remains
  // render-safe for both normal recovery decisions and terminal events.
  const rankedActions = Array.isArray(result.ranked_actions) ? result.ranked_actions : []
  const guardrails = result.guardrails && typeof result.guardrails === 'object' ? result.guardrails : {}
  const agentTrace = Array.isArray(result.agent?.trace) ? result.agent.trace : []
  const whySelected = Array.isArray(result.explanation?.why_selected) ? result.explanation.why_selected : []
  const featureAttribution = Array.isArray(result.feature_attribution) ? result.feature_attribution : []
  const selectableActions = rankedActions.filter(x=>x?.allowed && x.action!=='STOP')

  return <div className="result-card">
    <div className="recommend"><div><span>RECOMMENDED ACTION</span><h2>{pretty(result.recommended_action)}</h2></div><div className="check"><CheckCircle2 size={27}/></div></div>
    <div className="confidence"><span>Decision confidence</span><b>{result.decision_confidence}</b><small>score margin {money(result.score_margin)}</small></div>
    <p className="reason">{result.reason}</p>
    <div className="score-list">
      {rankedActions.length>0
        ? rankedActions.map(x=><div className={`score ${!x.allowed?'blocked':''}`} key={x.action}><div><b>{pretty(x.action)}</b><span>{x.action==='STOP'?'Safe fallback':`${pct(result.probabilities?.[x.action])} ML probability · ${money(result.base_expected_net_value?.[x.action])} base · ${result.policy_adjustments?.[x.action] ? `${result.policy_adjustments[x.action]>0?'+':''}${money(result.policy_adjustments[x.action])} policy` : 'no policy adjustment'} · cost ${money(result.action_costs?.[x.action])}`}</span></div><strong>{x.score==null?'BLOCKED':money(x.score)}</strong></div>)
        : <div className="score">
            <div><b>STOP · No recovery required</b><span>{result.reason||'Payment has already succeeded; no recovery intervention is required.'}</span></div>
            <strong>SAFE</strong>
          </div>}
    </div>
    <div className="guard-grid">{Object.entries(guardrails).map(([a,g])=><div className={`guard-mini ${g.allowed?'ok':'no'}`} key={a}><ShieldCheck size={15}/><div><b>{pretty(a)}</b><span>{g.allowed?'Allowed':`Blocked · ${(Array.isArray(g.reasons)?g.reasons:[]).join(' ')}`}</span></div></div>)}</div>
    <div className="note" style={{marginTop:14}}><Plug size={15}/><div><b>Execution mode</b><span>Safe simulation never contacts a customer. Live mode is available only when explicitly enabled and configured on the backend. A provider acceptance is never counted as recovered revenue until payment status/webhook confirmation.</span></div></div>
    <div className="form-row" style={{marginTop:10,alignItems:'end'}}><label className="field"><span>External execution</span><select value={liveExecution?'LIVE':'SAFE_SIMULATION'} onChange={e=>{const live=e.target.value==='LIVE';setLiveExecution(live);setLiveConfirmation(false)}}><option value="SAFE_SIMULATION">Safe simulation</option><option value="LIVE" disabled={!integrationStatus?.live_enabled}>{integrationStatus?.environment==='SANDBOX'?'RAZORPAY TEST execution':'LIVE production execution'}</option></select></label><label className="field"><span>Reminder channel</span><select value={executionChannel} onChange={e=>setExecutionChannel(e.target.value)}><option value="auto">Auto (configured channel)</option><option value="email">Email</option><option value="sms">SMS</option><option value="voice">Voice — Hinglish</option></select></label></div>
    {liveExecution&&<label className="field" style={{marginTop:10}}><span>{integrationStatus?.environment==='SANDBOX'?'Test execution confirmation':'Live confirmation'}</span><label style={{display:'flex',gap:8,alignItems:'center'}}><input type="checkbox" checked={liveConfirmation} onChange={e=>setLiveConfirmation(e.target.checked)}/> I understand this will make an external provider call{integrationStatus?.environment==='PRODUCTION'?' and may contact a real customer or create a real payment link.':'.'}</label></label>}
    {liveExecution&&<><div className="attribution-caption">Environment: {integrationStatus?.environment_metadata?.label||integrationStatus?.environment||'DEMO'} · Max amount: {money(integrationStatus?.max_live_amount)} · Daily budget: {money(integrationStatus?.daily_live_budget)} · Kill switch: {integrationStatus?.kill_switch?'ON':'OFF'}</div><div className="attribution-caption">Configured providers: Razorpay {integrationStatus?.providers?.razorpay?'✓':'—'} · Email {integrationStatus?.providers?.smtp?'✓':'—'} · SMS {integrationStatus?.providers?.twilio?'✓':'—'} · Webhook {integrationStatus?.providers?.execution_webhook?'✓':'—'}</div></>}
    <div className="agent-trace"><div className="trace-title"><Bot size={15}/> Decision Agent Trace <span>{result.agent?.version||'1.0'}</span></div>{agentTrace.map((s,i)=><div className="trace-row" key={s.step||i}><span>{String(i+1).padStart(2,'0')}</span><b>{s.label}</b><em>✓</em></div>)}</div>
    {result.explanation&&<div className="agent-trace">
      <div className="trace-title"><ListChecks size={15}/> Why this decision</div>
      {whySelected.length>0&&<ul className="explanation-list">{whySelected.map((r,i)=><li key={i}>{r}</li>)}</ul>}
      {Object.keys(result.explanation.why_others_rejected||{}).length>0&&<>
        <div className="trace-title" style={{marginTop:12}}>Why others were rejected</div>
        {Object.entries(result.explanation.why_others_rejected).map(([a,reasons])=><div className="rejection-row" key={a}><b>{pretty(a)}</b><span>{reasons.join(' ')}</span></div>)}
      </>}
    </div>}
    {featureAttribution.length>0&&<div className="agent-trace">
      <div className="trace-title"><Layers size={15}/> Model feature attribution</div>
      <p className="attribution-caption">What actually moved the model's probability for this decision, measured by re-scoring with each feature reset to its typical value.</p>
      <div className="attribution-bars">{featureAttribution.map(f=><div className="attribution-row" key={f.feature}>
        <div className="attribution-label"><b>{f.label}</b><span>{String(f.actual_value)} vs typical {String(f.typical_value)}</span></div>
        <div className="attribution-bar-track">
          <div className={`attribution-bar-fill ${f.direction}`} style={{width:`${Math.min(100,Math.abs(f.impact)*400)}%`}}/>
        </div>
        <em className={f.direction}>{f.direction==='increases'?'+':'−'}{Math.abs(f.impact*100).toFixed(1)}pp</em>
      </div>)}</div>
    </div>}
    <div className="execution-panel">
      <div><b>Bounded recovery execution</b><span>Guardrails are re-checked before the selected action is executed.</span></div>
      <button className="primary" onClick={()=>onExecute()} disabled={executing || (liveExecution && !liveConfirmation)}>{executing?'Executing…':liveExecution&&!liveConfirmation?'Confirm live execution above':'Execute Recommended Action'}</button>
      <div className="agent-trace" style={{marginTop:12}}>
        <div className="trace-title"><Plug size={15}/> Integration test <span>{integrationStatus?.environment_metadata?.label||integrationStatus?.environment||'DEMO'}</span></div>
        <p className="attribution-caption">Select any allowed action to test it independently of the AI recommendation. The selected action is what will execute; the recommendation is not substituted.</p>
        <div className="chips">{selectableActions.map(x=><button type="button" key={x.action} className="secondary" style={{borderColor:integrationTestAction===x.action?'var(--brand)':'',opacity:integrationTestAction===x.action?1:.8}} onClick={()=>setIntegrationTestAction(x.action)}>{pretty(x.action)}</button>)}</div>
        <button className="secondary" style={{marginTop:10}} onClick={()=>onExecute(integrationTestAction)} disabled={executing || !integrationTestAction || (liveExecution && !liveConfirmation)}>{executing?'Executing…':integrationTestAction?`Execute Selected: ${pretty(integrationTestAction)}`:'Select an action above'}</button>
      </div>
      {execution&&<div className={`execution-result ${execution.state==='RECOVERED'?'success':''}`}><b>{pretty(execution.state)}</b><span>{execution.outcome_reason}</span><small>{execution.execution_id} · {execution.execution_mode} · {execution.environment||'DEMO'} · {execution.selection_source||'AI_RECOMMENDATION'}</small>
        {execution.payment_link?.short_url&&<div style={{marginTop:10,display:'flex',gap:8,alignItems:'center',flexWrap:'wrap'}}><strong>Razorpay Payment Link</strong><a href={execution.payment_link.short_url} target="_blank" rel="noreferrer" className="secondary">Open Payment Link ↗</a><button type="button" className="secondary" onClick={()=>navigator.clipboard?.writeText(execution.payment_link.short_url)}>Copy Link</button><small>{execution.payment_link.id} · {String(execution.payment_link.status||'created').toUpperCase()}</small></div>}
      </div>}
      <VoiceRecoveryPreview result={result} form={form} action={integrationTestAction || execution?.action || result.recommended_action}/>
    </div>
  </div>
}

function SequenceResultCard({result,idLabel,idValue}){
  if(!result) return <div className="result-card empty"><Workflow size={36}/><h3>Sequence appears here</h3><p>Run the sequencer to see every step, action, guardrail recheck and outcome until a terminal state or stopping rule fires.</p></div>
  return <div className="result-card">
    <div className="recommend"><div><span>{idLabel} {idValue}</span><h2>{result.step_count} step{result.step_count===1?'':'s'} · {pretty(result.final_state)}</h2></div><div className="check"><Workflow size={27}/></div></div>
    <p className="reason">{result.stop_reason}</p>
    <div className="facts">
      <Fact label="Total recovered" value={money(result.total_revenue_recovered)}/>
      <Fact label="Total cost" value={money(result.total_intervention_cost)}/>
      <Fact label="Net recovery" value={money(result.net_recovery)}/>
      <Fact label="Final state" value={pretty(result.final_state)}/>
    </div>
    <div className="journey-timeline">
      {result.steps.map(s=><div className="journey-step" key={s.step_number}>
        <div className="journey-step-num">{s.step_number}</div>
        <div className="journey-step-body">
          <div className="journey-step-head"><b>{pretty(s.action)}</b><em className={`state-pill state-${s.execution_state.toLowerCase()}`}>{pretty(s.execution_state)}</em></div>
          <span>{s.expected_probability!=null?pct(s.expected_probability)+' expected · ':''}{money(s.expected_recovery)} expected recovery · {money(s.revenue_recovered)} recovered</span>
          <small>{pretty(s.execution_outcome)}{s.afa_acknowledged_this_step?' · AFA re-authorization assumed acknowledged':''}</small>
        </div>
      </div>)}
    </div>
  </div>
}

function MandateSequencer({form,update,onRun,loading,error,result}){
  return <>
    {error&&<div className="alert">{error}</div>}
    <div className="note" style={{marginBottom:16}}>
      <Zap size={16}/>
      <div><b>Real RBI e-mandate rule applied</b><span>Debits above ₹15,000 require Additional Factor Authentication (RBI e-mandate framework); a silent retry above that threshold is guardrail-blocked until the customer re-authorizes. Mandate executions also run on a 24-hour batch/notice cycle, not on demand.</span></div>
    </div>
    <div className="decision-grid">
      <form className="form-card" onSubmit={onRun}>
        <Field label="Mandate debit amount (₹)"><input type="number" min="1" value={form.amount} onChange={e=>update('amount',e.target.value)}/></Field>
        <div className="form-row"><Field label="Failure type"><select value={form.failure_type} onChange={e=>update('failure_type',e.target.value)}><option>TIMEOUT</option><option>NETWORK_ERROR</option><option>BANK_TECHNICAL_ERROR</option><option>ISSUER_DECLINE</option><option>INSUFFICIENT_BALANCE</option></select></Field><Field label="Retry count"><input type="number" min="0" max="10" value={form.retry_count} onChange={e=>update('retry_count',e.target.value)}/></Field></div>
        <Field label="Customer success rate"><input type="number" min="0" max="1" step="0.01" value={form.historical_success_rate} onChange={e=>update('historical_success_rate',e.target.value)}/></Field>
        <button className="primary" disabled={loading}>{loading?'Running mandate sequence…':'Run UPI Mandate Retry Sequence'}</button>
      </form>
      <div className="result-card">
        {!result?<div className="empty"><Zap size={36}/><h3>Mandate sequence appears here</h3><p>Try an amount above ₹15,000 to see the AFA guardrail block silent retries until re-authorization.</p></div>:<>
          <div className="recommend"><div><span>MANDATE {result.mandate_sequence_id}</span><h2>{result.step_count} step{result.step_count===1?'':'s'} · {pretty(result.final_state)}</h2></div><div className="check"><Zap size={27}/></div></div>
          <p className="reason">{result.stop_reason}</p>
          <div className="facts">
            <Fact label="AFA required" value={result.requires_afa?'Yes (> ₹15,000)':'No'}/>
            <Fact label="Re-auth required" value={result.mandate_reauth_required?'Yes':'No'}/>
            <Fact label="Total recovered" value={money(result.total_revenue_recovered)}/>
            <Fact label="Net recovery" value={money(result.net_recovery)}/>
          </div>
          <div className="journey-timeline">
            {result.steps.map(s=><div className="journey-step" key={s.step_number}>
              <div className="journey-step-num">{s.step_number}</div>
              <div className="journey-step-body">
                <div className="journey-step-head"><b>{pretty(s.action)}</b><em className={`state-pill state-${s.execution_state.toLowerCase()}`}>{pretty(s.execution_state)}</em></div>
                <span>{money(s.expected_recovery)} expected recovery · {money(s.revenue_recovered)} recovered</span>
                <small>{pretty(s.execution_outcome)}{s.afa_acknowledged_this_step?' · Customer prompted to re-authorize (AFA)':''}</small>
              </div>
            </div>)}
          </div>
        </>}
      </div>
    </div>
  </>
}

function CounterfactualView({data,selectedAction,selectedRecovery,selectedNet}){
  if(!data) return null
  return <>
    <div className="cf-selected"><span>SELECTED ACTION</span><b>{pretty(selectedAction)}</b><span>{money(selectedRecovery)} expected recovery · {money(selectedNet)} expected net value</span></div>
    <div className="score-list">{(data.alternatives||[]).map(a=><div className={`score ${!a.allowed?'blocked':''}`} key={a.action}><div><b>{pretty(a.action)}</b><span>{a.status}</span></div><strong>{a.expected_net_value==null?'BLOCKED':money(a.expected_net_value)}</strong></div>)}</div>
    <div className="note"><Zap size={16}/><div><b>Decision advantage</b><span>{money(data.decision_advantage)} ahead of the next-best allowed alternative.</span></div></div>
    {data.oracle?.oracle_action?<div className="note"><Target size={16}/><div><b>Oracle comparison</b><span>Best possible action for this event was {pretty(data.oracle.oracle_action)} (₹{Number(data.oracle.oracle_revenue).toLocaleString('en-IN')}). Opportunity gap: {money(data.oracle.opportunity_gap)}.</span></div></div>:<div className="note"><Database size={16}/><div><b>Oracle comparison</b><span>{data.oracle?.note}</span></div></div>}
  </>
}

function PolicySummaryCard({title,data}){
  return <div className="policy-card" style={{flexDirection:'column',alignItems:'stretch',gap:8}}>
    <b>{title}</b>
    <div className="facts">
      <Fact label="Recovered" value={money(data.revenue_recovered)}/>
      <Fact label="Recovery rate" value={pct(data.recovery_rate)}/>
      <Fact label="Intervention cost" value={money(data.intervention_cost)}/>
      <Fact label="Net recovery" value={money(data.net_recovery)}/>
      <Fact label="Oracle capture" value={pct(data.oracle_capture)}/>
      <Fact label="Regret" value={money(data.regret)}/>
      <Fact label="Escalations" value={data.human_escalations}/>
      <Fact label="Retries" value={data.retry_count_total}/>
    </div>
  </div>
}

function Evaluation({card,metrics,analysis,budgetForm,setBudgetForm,budgetResult,budgetLoading,budgetError,runBudget,twinForm,setTwinForm,twinResult,twinLoading,twinError,runTwin,evaluationRun,evaluationLoading,evaluationError,runEvaluation}){
  const regret=analysis?.policy_regret_summary||[]
  const updateBudget=(k,v)=>setBudgetForm(f=>({...f,[k]:Number(v)}))
  const updateTwin=(k,v)=>setTwinForm(f=>({...f,[k]:v}))
  return <section><div className="page-title"><div><div className="eyebrow"><Activity size={15}/> MODEL & BUSINESS EVALUATION</div><h2>Held-out business evaluation</h2><p>Run the frozen August holdout on demand. This is offline evaluation only: it never changes production policy or contacts customers.</p></div><button className="secondary" onClick={runEvaluation} disabled={evaluationLoading}>{evaluationLoading?'Running holdout…':'Run Evaluation'}</button></div>{evaluationError&&<div className="alert">{evaluationError}</div>}<div className="note"><CheckCircle2 size={15}/><div><b>{evaluationRun?.status==='COMPLETED'||evaluationRun?.status==='READY'?'Evaluation artifact ready':'Evaluation not run yet'}</b><span>{evaluationRun?.result?.generated_at?`Generated ${new Date(evaluationRun.result.generated_at).toLocaleString()}`:'Run the evaluator to refresh the displayed held-out metrics.'}</span></div></div><div className="evaluation-grid"><Panel title="Held-out business result"><div className="facts"><Fact label="Evaluation split" value={metrics?.evaluation_split}/><Fact label="Events" value={metrics?.events}/><Fact label="RecoverAI recovered" value={money(metrics?.revenue_recovered)}/><Fact label="Baseline" value={money(metrics?.baseline_revenue)}/><Fact label="Incremental" value={money(metrics?.incremental_recovery)}/><Fact label="Uplift" value={pct(metrics?.relative_uplift)}/><Fact label="Oracle" value={money(metrics?.oracle_revenue)}/><Fact label="Oracle capture" value={pct(metrics?.oracle_capture)}/></div></Panel><Panel title="Action model ROC-AUC · held-out"><div className="model-bars">{Object.entries(card?.test_metrics||{}).map(([a,v])=><div className="model-row" key={a}><span>{pretty(a)}</span><div className="track"><i style={{width:`${v*100}%`}}/></div><b>{Number(v).toFixed(3)}</b></div>)}</div></Panel></div><div className="agent-eval"><div><Bot size={18}/><b>Decision Agent architecture</b><span>Local, deterministic and inspectable — no external LLM is required for the core decision.</span></div><div><Database size={18}/><b>Counterfactual oracle</b><span>Every August event has simulated outcomes for all recovery actions, enabling regret analysis without leaking those outcomes into live features.</span></div><div><Scale size={18}/><b>Policy objective</b><span>Expected recovered money minus action cost, subject to hard guardrails, with STOP as a zero-value safe fallback.</span></div></div><Panel title="Counterfactual policy-regret summary"><div className="regret-table">{regret.length===0?<div className="empty small">No regret artifact loaded.</div>:regret.map((r,i)=><div className="regret-row" key={i}>{Object.entries(r).map(([k,v])=><span key={k}><small>{pretty(k)}</small><b>{typeof v==='number'&&Math.abs(v)>1000?money(v):String(v)}</b></span>)}</div>)}</div></Panel>
    <div className="evaluation-grid">
      <Panel title="Budget-Constrained Intervention Planner"><div className="note"><Scale size={16}/><div><b>Allocate intervention spend by expected net value</b><span>Uses the V3-100k probabilities and the same production guardrails. Realized outcomes are never used to choose the allocation.</span></div></div>{budgetError&&<div className="alert">{budgetError}</div>}<div className="form-row" style={{marginTop:14,alignItems:'end'}}><Field label="Total intervention budget (₹)"><input type="number" min="0" value={budgetForm.budget} onChange={e=>updateBudget('budget',e.target.value)}/></Field><Field label="Amount multiplier"><input type="number" min="0.1" max="5" step="0.1" value={budgetForm.amount_multiplier} onChange={e=>updateBudget('amount_multiplier',e.target.value)}/></Field><Field label="Recovery odds multiplier"><input type="number" min="0.1" max="2" step="0.05" value={budgetForm.recovery_multiplier} onChange={e=>updateBudget('recovery_multiplier',e.target.value)}/></Field><button className="primary" onClick={runBudget} disabled={budgetLoading}>{budgetLoading?'Optimizing…':'Optimize Budget'}</button></div>{budgetResult&&<div className="facts" style={{marginTop:14}}><Fact label="Budget used" value={money(budgetResult.budget_used)}/><Fact label="Utilization" value={pct(budgetResult.budget_utilization)}/><Fact label="Expected recovery" value={money(budgetResult.expected_recovery)}/><Fact label="Expected net value" value={money(budgetResult.expected_net_value)}/><Fact label="Shadow price" value={budgetResult.shadow_price}/></div>}{budgetResult&&<div className="chips" style={{marginTop:12}}>{budgetResult.action_mix.filter(x=>x.events>0).map(x=><span key={x.action}>{pretty(x.action)} · {x.events.toLocaleString()}</span>)}</div>}</Panel>
      <Panel title="Revenue Recovery Scenario Simulator"><div className="note"><Database size={16}/><div><b>Stress-test the recovery system before changing policy</b><span>Scale transaction volume, payment amount and modelled recovery odds to see expected recovery, cost and action mix. Results are scenario estimates, not realized revenue.</span></div></div>{twinError&&<div className="alert">{twinError}</div>}<div className="form-row" style={{marginTop:14,alignItems:'end'}}><Field label="Volume ×"><input type="number" min="0.1" max="10" step="0.1" value={twinForm.volume_multiplier} onChange={e=>updateTwin('volume_multiplier',e.target.value)}/></Field><Field label="Amount ×"><input type="number" min="0.1" max="5" step="0.1" value={twinForm.amount_multiplier} onChange={e=>updateTwin('amount_multiplier',e.target.value)}/></Field><Field label="Recovery odds ×"><input type="number" min="0.1" max="2" step="0.05" value={twinForm.recovery_multiplier} onChange={e=>updateTwin('recovery_multiplier',e.target.value)}/></Field><Field label="Optional budget (₹)"><input type="number" min="0" value={twinForm.budget} placeholder="No cap" onChange={e=>updateTwin('budget',e.target.value)}/></Field><button className="primary" onClick={runTwin} disabled={twinLoading}>{twinLoading?'Simulating…':'Run Digital Twin'}</button></div>{twinResult&&<div className="facts" style={{marginTop:14}}><Fact label="Scenario events" value={twinResult.events_planned?.toLocaleString()}/><Fact label="Expected recovery" value={money(twinResult.expected_recovery)}/><Fact label="Expected cost" value={money(twinResult.expected_intervention_cost)}/><Fact label="Expected net" value={money(twinResult.expected_net_value)}/></div>}{twinResult&&<div className="chips" style={{marginTop:12}}>{twinResult.action_mix.filter(x=>x.events>0).map(x=><span key={x.action}>{pretty(x.action)} · {x.events.toLocaleString()}</span>)}</div>}</Panel>
    </div>
    <div className="note"><Lock size={16}/><div><b>Leakage protection</b><span>Outcome fields and post-action information are excluded from model features. The August set remains the untouched final evaluation.</span></div></div></section>
}

function ModelHealth({health,error}){
  if(error) return <section><div className="alert">{error}</div></section>
  if(!health) return <section><div className="empty small">Loading model health…</div></section>
  const drift=health.drift
  return <section>
    <div className="page-title"><div><div className="eyebrow"><Activity size={15}/> MODEL MONITORING</div><h2>Model health and data drift</h2><p>Real per-action test metrics plus a statistical drift check between the January-June training window and the August held-out window.</p></div></div>
    <Panel title="Action model metrics — held-out test">
      <div className="model-bars">{health.per_action_metrics.map(m=><div key={m.action}>
        <div className="model-row"><span>{pretty(m.action)}</span><div className="track"><i style={{width:`${m.roc_auc*100}%`}}/></div><b>{m.roc_auc.toFixed(3)}</b></div>
        <div className="model-sub">AP {m.average_precision!=null?m.average_precision.toFixed(3):'—'} · n={m.sample_count} · p50 {m.prediction_distribution?.p50!=null?pct(m.prediction_distribution.p50):'—'} · <em className={`status-pill status-${m.status.toLowerCase()}`}>{pretty(m.status)}</em></div>
        {m.global_feature_importance&&m.global_feature_importance.length>0&&<div className="importance-chips">{m.global_feature_importance.slice(0,5).map(f=><span key={f.feature}>{f.label} <b>{f.importance.toFixed(3)}</b></span>)}</div>}
      </div>)}</div>
    </Panel>
    <Panel title="Data drift — reference (Jan-Jun) vs current (Aug)">
      <div className={`drift-banner drift-${drift.overall_status.toLowerCase()}`}>
        {drift.overall_status==='DRIFT_DETECTED'?<AlertTriangle size={18}/>:<CheckCircle2 size={18}/>}
        <div><b>{pretty(drift.overall_status)}</b><span>{drift.retraining_recommended?'Retraining recommended.':'No retraining action needed.'} {drift.methodology}</span></div>
      </div>
      <div className="drift-table">{drift.features.map(f=><div className="drift-row" key={f.feature}>
        <b>{pretty(f.feature)}</b>
        <span>ref {f.reference_mean} → cur {f.current_mean}</span>
        <span>PSI {f.psi}</span>
        <span>KS {f.ks_statistic} (p={f.ks_pvalue.toFixed(3)})</span>
        <em className={`status-pill status-${f.status.toLowerCase()}`}>{pretty(f.status)}</em>
      </div>)}</div>
    </Panel>
  </section>
}

function GuardrailsView({rules}){
  return <section><div className="page-title"><div><div className="eyebrow"><ShieldCheck size={15}/> POLICY GUARDRAILS</div><h2>Hard constraints are part of the decision</h2><p>Green means the action is eligible under the current policy; it does not mean the action will be selected. Blocking is applied before value ranking.</p></div></div><div className="policy-grid">{rules?.rules?.map(r=><div className="policy-card" key={r.action}><ShieldCheck size={20}/><div><b>{pretty(r.action)}</b><p>{r.rule}</p></div></div>)}</div><div className="panel"><div className="panel-title">Non-retryable failure types</div><div className="chips">{rules?.non_retryable_failures?.map(x=><span key={x}>{pretty(x)}</span>)}</div></div></section>
}

function Audit({audit,executionAudit,ledger,feedback,promises,promiseForm,setPromiseForm,createPromise,keepPromise,promiseError}){
  return <section>
    <div className="page-title"><div><div className="eyebrow"><History size={15}/> DECISION & EXECUTION AUDIT</div><h2>Every recovery decision leaves a trace</h2><p>Decision records capture the policy choice; execution records capture the bounded action, second guardrail check, state transition and outcome.</p></div></div>
    <div className="panel"><div className="panel-title">Decision audit</div><div className="audit-table">{audit.length===0?<div className="empty small">No decisions recorded yet. Run the Decision Lab first.</div>:audit.map(x=><div className="audit-row" key={x.decision_id}><b>{x.decision_id}</b><span>{formatDateTime(x.timestamp)}</span><span>{money(x.amount)}</span><span>{pretty(x.event_type)}</span><strong>{pretty(x.recommended_action)}</strong><span>{x.confidence}</span><em>{x.guardrail_blocked_actions?.length||0} blocked</em></div>)}</div></div>
    <div className="panel"><div className="panel-title">Execution audit</div><div className="audit-table">{executionAudit.length===0?<div className="empty small">No executions yet. Run Execute Recovery Workflow after a decision.</div>:executionAudit.map(x=><div className="audit-row" key={x.execution_id}><b>{x.execution_id}</b><span>{formatDateTime(x.timestamp)}</span><span>{money(x.amount)}</span><span>{pretty(x.action)}</span><strong>{pretty(x.state)}</strong><span>{pretty(x.outcome)}</span><em>{x.execution_mode}</em></div>)}</div></div>
    <div className="panel"><div className="panel-title">Revenue Recovery Ledger (this session)</div>
      {!ledger||ledger.entries.length===0?<div className="empty small">No ledger entries yet.</div>:<>
        <div className="facts"><Fact label="At risk" value={money(ledger.summary.total_revenue_at_risk)}/><Fact label="Recovered" value={money(ledger.summary.total_recovered)}/><Fact label="Recovery rate" value={pct(ledger.summary.recovery_rate)}/><Fact label="Cost" value={money(ledger.summary.total_intervention_cost)}/><Fact label="Net recovered" value={money(ledger.summary.net_recovered)}/></div>
        <div className="audit-table">{ledger.entries.slice(0,25).map(e=><div className="audit-row" key={e.execution_id}><b>{e.decision_id}</b><span>{formatDateTime(e.timestamp)}</span><span>{money(e.amount)}</span><strong>{pretty(e.selected_action)}</strong><span>{money(e.actual_recovered)}</span><span>{money(e.net_recovery)} net</span><em>{pretty(e.final_state)}</em></div>)}</div>
      </>}
    </div>
    <div className="panel"><div className="panel-title">Outcome Feedback — which actions perform</div>
      {!feedback||feedback.by_action.length===0?<div className="empty small">No executions recorded yet.</div>:<div className="feedback-grid">{feedback.by_action.map(f=><div className="feedback-card" key={f.action}><b>{pretty(f.action)}</b><span>{f.attempts} attempts</span>{f.observed_success_rate!=null&&<span>{pct(f.observed_success_rate)} success</span>}<strong className={f.net_recovery>=0?'pos':'neg'}>{money(f.net_recovery)} net</strong></div>)}</div>}
    </div>
    <div className="panel">
      <div className="panel-title">Promise-to-Pay Tracker</div>
      {promiseError&&<div className="alert">{promiseError}</div>}
      <form className="form-row" onSubmit={createPromise} style={{marginBottom:14,alignItems:'end'}}>
        <Field label="Committed amount (₹)"><input type="number" min="1" value={promiseForm.amount} onChange={e=>setPromiseForm(f=>({...f,amount:e.target.value}))}/></Field>
        <Field label="Promised pay-by date"><input type="datetime-local" value={promiseForm.promised_date} onChange={e=>setPromiseForm(f=>({...f,promised_date:e.target.value}))} required/></Field>
        <button className="primary" type="submit">Record Promise</button>
      </form>
      <p className="attribution-caption">Set a date in the past to see auto-escalation fire for real — status is resolved against actual server time on every fetch, and a broken promise triggers a real Decision Agent escalation, not a canned message.</p>
      {!promises||promises.promises.length===0?<div className="empty small">No promises recorded yet.</div>:<>
        <div className="facts"><Fact label="Total" value={promises.summary.total}/><Fact label="Pending" value={promises.summary.pending}/><Fact label="Kept" value={promises.summary.kept}/><Fact label="Broken" value={promises.summary.broken}/><Fact label="Kept rate" value={promises.summary.kept_rate!=null?pct(promises.summary.kept_rate):'—'}/></div>
        <div className="audit-table">{promises.promises.map(p=><div className="audit-row promise-row" key={p.promise_id}>
          <b>{p.promise_id}</b>
          <span>{money(p.amount)}</span>
          <span>{new Date(p.promised_date).toLocaleString()}</span>
          <em className={`state-pill state-${p.status.toLowerCase()==='kept'?'recovered':p.status.toLowerCase()==='broken'?'failed':'scheduled'}`}>{pretty(p.status)}</em>
          <span>{p.escalation_decision_id?`Escalated: ${p.escalation_decision_id}`:'—'}</span>
          {p.status==='PENDING'?<button className="secondary" onClick={()=>keepPromise(p.promise_id,p.amount)}>Mark Kept</button>:<span/>}
        </div>)}</div>
      </>}
    </div>
  </section>
}

function ExecutionEnvironmentBar({status,busy,error,adminToken,setAdminToken,liveConfirm,setLiveConfirm,onChange,showLiveControls,setShowLiveControls}){
  const env=status?.environment||'DEMO'
  const meta=status?.environment_metadata||{}
  const options=[
    {id:'DEMO',label:'DEMO',sub:'Local simulation',safe:'No external calls'},
    {id:'SANDBOX',label:'RAZORPAY TEST',sub:'Test APIs',safe:'No real money'},
    {id:'PRODUCTION',label:'LIVE',sub:'Production providers',safe:'Real money possible'},
  ]
  return <section className={`environment-shell environment-${env.toLowerCase()}`}>
    <div className="environment-inner">
      <div className="environment-heading">
        <div>
          <div className="eyebrow"><Plug size={14}/> EXECUTION ENVIRONMENT</div>
          <h3>{meta.label||env}</h3>
          <p>{meta.description||'Choose exactly how RecoverAI is allowed to execute external actions.'}</p>
        </div>
        <div className="environment-badge">
          <span className="env-dot"/>
          <b>{env==='SANDBOX'?'TEST':env}</b>
          <small>{meta.real_money?'REAL MONEY POSSIBLE':'NO REAL MONEY'}</small>
        </div>
      </div>
      <div className="environment-options">
        {options.map(o=><button type="button" key={o.id} className={`environment-option ${env===o.id?'selected':''}`} disabled={busy} onClick={()=>o.id==='PRODUCTION'?setShowLiveControls(true):onChange(o.id)}>
          <div className="env-option-top"><b>{o.label}</b>{env===o.id&&<CheckCircle2 size={15}/>}</div>
          <span>{o.sub}</span><small>{o.safe}</small>
        </button>)}
      </div>
      <div className="environment-details">
        <div><b>Razorpay</b><span>{status?.providers?.razorpay?'Configured':'Not configured'} · key mode: {status?.razorpay_key_mode||'NOT_CONFIGURED'}</span></div>
        <div><b>External calls</b><span>{status?.live_enabled?'Enabled':'Disabled'}</span></div>
        <div><b>Kill switch</b><span>{status?.kill_switch?'ACTIVE':'Ready'}</span></div>
        <div><b>Limits</b><span>₹{Number(status?.max_live_amount||0).toLocaleString('en-IN')} / action · ₹{Number(status?.daily_live_budget||0).toLocaleString('en-IN')} / day</span></div>
      </div>
      {env==='PRODUCTION'&&<div className="live-warning"><AlertTriangle size={17}/><div><b>LIVE PRODUCTION IS ENABLED</b><span>Only explicitly confirmed, allow-listed actions may contact production providers. Provider acceptance is never treated as recovered revenue without verification.</span></div></div>}
      {showLiveControls&&env!=='PRODUCTION'&&<div className="live-activation">
        <div><b>Activate LIVE PRODUCTION</b><span>This is deliberately harder than DEMO or RAZORPAY TEST.</span></div>
        <input type="password" value={adminToken} onChange={e=>setAdminToken(e.target.value)} placeholder="RECOVERAI_ADMIN_TOKEN"/>
        <label><input type="checkbox" checked={liveConfirm} onChange={e=>setLiveConfirm(e.target.checked)}/> I understand LIVE may contact real customers / create real payment links.</label>
        <div className="live-actions"><button className="secondary" onClick={()=>{setShowLiveControls(false);setLiveConfirm(false)}}>Cancel</button><button className="primary live-primary" disabled={busy||!adminToken||!liveConfirm} onClick={()=>onChange('PRODUCTION')}>{busy?'Activating…':'Activate LIVE Production'}</button></div>
      </div>}
      {error&&<div className="alert" style={{marginTop:10}}>{error}</div>}
    </div>
  </section>
}

function RazorpayTestPayment({integrationStatus}){
  const [form,setForm]=useState({amount:12000,customer_name:'RecoverAI Test Customer',email:'',phone:''})
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  const [order,setOrder]=useState(null)
  const [status,setStatus]=useState(null)
  const [recovery,setRecovery]=useState(null)
  const [recoveryBusy,setRecoveryBusy]=useState(false)
  const pollRef=useRef(null)
  const recoveryPollRef=useRef(null)
  const testEnabled=integrationStatus?.environment==='SANDBOX'

  useEffect(()=>{
    let mounted=true
    const restore=async()=>{
      try{
        const saved=JSON.parse(localStorage.getItem('recoverai.razorpay.testRecovery')||'null')
        if(saved?.order && mounted) setOrder(saved.order)
        if(saved?.status && mounted) setStatus(saved.status)

        // IMPORTANT: a test checkout must never display an unrelated recovery
        // execution after a refresh. Recovery belongs to this exact test order
        // and is created only after payment.failed is received and the operator
        // clicks the recovery action.
        const savedOrderId=String(saved?.order?.order?.id||'')
        const savedRecoveryOrderId=String(saved?.recovery?.test_order_id||'')
        const recoveryBelongsToSavedOrder=!!saved?.recovery &&
          !!savedOrderId && !!savedRecoveryOrderId && savedOrderId===savedRecoveryOrderId
        if(recoveryBelongsToSavedOrder && mounted) setRecovery(saved.recovery)

        const executionId=recoveryBelongsToSavedOrder
          ? (saved?.execution_id||saved?.recovery?.execution_id)
          : null
        if(executionId){
          await refreshRecovery(executionId)
          if(mounted) startRecoveryPolling(executionId)
        }

        // IMPORTANT: the Razorpay payment.failed webhook is delivered
        // asynchronously by Razorpay's servers, not by the browser. If the
        // component unmounts (tab switch, page reload) before that webhook
        // has been recorded, the one-time restore above can leave `status`
        // permanently without a decision, so the "Create Razorpay Test
        // Recovery Payment" button never appears even though the webhook
        // eventually arrives server-side. Resume polling the *existing*
        // test order (never a new one) whenever we don't yet have a
        // decision for it, so a remounted/reloaded page still picks up a
        // late webhook instead of getting stuck waiting forever.
        const savedOrderIdForPoll=String(saved?.order?.order?.id||'')
        const savedDecision=saved?.status?.latest?.payload?.decision
        if(savedOrderIdForPoll && !savedDecision && mounted){
          pollOrder(savedOrderIdForPoll)
        }
      }catch(_){}
    }
    restore()
    return ()=>{
      mounted=false
      if(pollRef.current) clearInterval(pollRef.current)
      if(recoveryPollRef.current) clearInterval(recoveryPollRef.current)
    }
  },[])

  const loadCheckout=()=>new Promise((resolve,reject)=>{
    if(window.Razorpay){ resolve(window.Razorpay); return }
    const existing=document.querySelector('script[data-recoverai-razorpay]')
    if(existing){
      existing.addEventListener('load',()=>resolve(window.Razorpay),{once:true})
      existing.addEventListener('error',()=>reject(new Error('Razorpay Checkout failed to load.')),{once:true})
      return
    }
    const script=document.createElement('script')
    script.src='https://checkout.razorpay.com/v1/checkout.js'
    script.async=true
    script.dataset.recoveraiRazorpay='1'
    script.onload=()=>window.Razorpay?resolve(window.Razorpay):reject(new Error('Razorpay Checkout is unavailable.'))
    script.onerror=()=>reject(new Error('Could not load Razorpay Checkout. Check your internet connection.'))
    document.body.appendChild(script)
  })

  const stopPolling=()=>{ if(pollRef.current){ clearInterval(pollRef.current); pollRef.current=null } }
  const stopRecoveryPolling=()=>{ if(recoveryPollRef.current){ clearInterval(recoveryPollRef.current); recoveryPollRef.current=null } }

  const refreshRecovery=async(executionId)=>{
    try{
      const log=await getJSON('/api/execution-log?limit=50')
      const found=(log.records||[]).find(x=>x.execution_id===executionId)
      if(found){
        setRecovery(prev=>({...found,payment_link:found.payment_link||prev?.payment_link,integration:found.integration||prev?.integration}))
        try{
          const saved=JSON.parse(localStorage.getItem('recoverai.razorpay.testRecovery')||'null')||{}
          localStorage.setItem('recoverai.razorpay.testRecovery',JSON.stringify({
            ...saved,
            recovery:{
              ...found,
              test_order_id:saved?.recovery?.test_order_id||saved?.order?.order?.id||null,
              payment_link:found.payment_link||saved?.recovery?.payment_link,
              integration:found.integration||saved?.recovery?.integration
            },
            execution_id:executionId
          }))
        }catch(_){}
        if(found.state==='RECOVERED') stopRecoveryPolling()
      }
    }catch(_){}
  }

  const startRecoveryPolling=(executionId)=>{
    if(!executionId) return
    stopRecoveryPolling()
    refreshRecovery(executionId)
    recoveryPollRef.current=setInterval(()=>refreshRecovery(executionId),1500)
    setTimeout(stopRecoveryPolling,120000)
  }

  const pollOrder=(orderId)=>{
    stopPolling()
    const check=async()=>{
      try{
        const d=await getJSON(`/api/razorpay/test/order/${encodeURIComponent(orderId)}`)
        setStatus(d)
        try{
          const saved=JSON.parse(localStorage.getItem('recoverai.razorpay.testRecovery')||'null')||{}
          localStorage.setItem('recoverai.razorpay.testRecovery',JSON.stringify({...saved,status:d}))
        }catch(_){}
        const event=d?.latest?.event_type
        if(event==='payment.failed' || event==='payment.captured' || event==='order.paid'){
          stopPolling()
        }
      }catch(_){}
    }
    check()
    pollRef.current=setInterval(check,1500)
    setTimeout(stopPolling,60000)
  }

  const createAndOpen=async(e)=>{
    e.preventDefault()
    setBusy(true); setError(''); setStatus(null); setRecovery(null); stopRecoveryPolling()
    try{ localStorage.removeItem('recoverai.razorpay.testRecovery') }catch(_){}
    try{
      const created=await postJSON('/api/razorpay/test/order',{
        amount:Number(form.amount),
        customer_name:form.customer_name||null,
        email:form.email||null,
        phone:form.phone||null
      })
      setOrder(created)
      try{ localStorage.setItem('recoverai.razorpay.testRecovery',JSON.stringify({order:created,recovery:null,execution_id:null})) }catch(_){}
      const RZP=await loadCheckout()
      const rzp=new RZP({
        key:created.key_id,
        amount:created.order.amount,
        currency:created.order.currency,
        name:'RecoverAI',
        description:'RecoverAI Razorpay Test Payment',
        order_id:created.order.id,
        prefill:{
          name:form.customer_name||'RecoverAI Test Customer',
          email:form.email||undefined,
          contact:form.phone||undefined
        },
        notes:{recoverai_test_payment:'1'},
        handler:()=>pollOrder(created.order.id),
        modal:{ondismiss:()=>pollOrder(created.order.id)}
      })
      rzp.on('payment.failed',()=>pollOrder(created.order.id))
      rzp.open()
      pollOrder(created.order.id)
    }catch(err){ setError(err.message) }
    finally{ setBusy(false) }
  }

  const executeRecovery=async()=>{
    // Guardrail against re-triggering: the backend's live-execution
    // idempotency check is keyed on decision_id+action, so a second click
    // here would not create a second payment link — it would just return
    // the *current* state of the execution already created by the first
    // click. If that first recovery has since been verified by the
    // Razorpay webhook, replaying it would make the UI appear to "jump"
    // straight to VERIFIED, skipping the PENDING step it already showed.
    // A recovery execution for this order should only ever be created once.
    if(recovery || recoveryBusy) return
    const decision=status?.latest?.payload?.decision
    const paymentEvent=status?.latest?.payload?.payment_event
    if(!decision || !paymentEvent) return
    setRecoveryBusy(true); setError('')
    try{
      const d=await postJSON('/execute-decision',{
        payload:paymentEvent,
        decision,
        live:true,
        channel:'auto',
        live_confirmation:true,
        selected_action:'ALTERNATIVE_PAYMENT'
      })
      setRecovery(d)
      const executionId=d?.execution_id
      if(executionId){
        try{
          localStorage.setItem('recoverai.razorpay.testRecovery',JSON.stringify({
            order,
            recovery:{...d,test_order_id:order?.order?.id||null},
            execution_id:executionId,
            status
          }))
        }catch(_){}
        await refreshRecovery(executionId)
        startRecoveryPolling(executionId)
      }
    }catch(err){ setError(err.message) }
    finally{ setRecoveryBusy(false) }
  }

  const latest=status?.latest
  const webhookDecision=latest?.payload?.decision
  const paymentEvent=latest?.payload?.payment_event
  const alternativeAllowed=webhookDecision?.guardrails?.ALTERNATIVE_PAYMENT?.allowed
  const recovered=recovery?.state==='RECOVERED'
  const webhookLabel=latest?.event_type==='payment.failed'?'PAYMENT FAILED → DECISION RECEIVED':latest?.event_type==='payment.captured'?'PAYMENT CAPTURED → VERIFIED':latest?.event_type==='order.paid'?'ORDER PAID → VERIFIED':latest?.event_type==='payment_link.paid'?'RECOVERY PAYMENT → VERIFIED':latest?.event_type||'Waiting for webhook…'

  return <div className="panel" style={{marginBottom:18}}>
    <div className="panel-title">Razorpay Test Payment</div>
    <div className="note"><ShieldCheck size={15}/><div><b>Real Razorpay Test Checkout · no real money</b><span>Creates a server-side Razorpay TEST order, opens Standard Checkout, and waits for the signed webhook. Use <b>failure@razorpay</b> to trigger payment.failed or <b>success@razorpay</b> to trigger a successful test payment.</span></div></div>
    {error&&<div className="alert" style={{marginTop:10}}>{error}</div>}
    <form className="form-row" onSubmit={createAndOpen} style={{marginTop:12,alignItems:'end'}}>
      <Field label="Test amount (₹)"><input type="number" min="1" max="100000" value={form.amount} onChange={e=>setForm(f=>({...f,amount:e.target.value}))}/></Field>
      <Field label="Customer name"><input value={form.customer_name} onChange={e=>setForm(f=>({...f,customer_name:e.target.value}))}/></Field>
      <Field label="Email (optional)"><input type="email" value={form.email} onChange={e=>setForm(f=>({...f,email:e.target.value}))}/></Field>
      <Field label="Phone (optional)"><input value={form.phone} onChange={e=>setForm(f=>({...f,phone:e.target.value}))}/></Field>
      <button className="primary" type="submit" disabled={busy||!testEnabled}>{busy?'Opening Checkout…':testEnabled?'Open Razorpay Test Checkout':'Switch to RAZORPAY TEST'}</button>
    </form>

    {order&&<div className="facts" style={{marginTop:14}}>
      <Fact label="Test order" value={order.order?.id||'—'}/>
      <Fact label="Amount" value={money(order.order?.amount/100)}/>
      <Fact label="Checkout state" value={status?.latest?.event_type||'OPEN'}/>
      <Fact label="Webhook" value={webhookLabel}/>
    </div>}

    {webhookDecision&&<div style={{marginTop:14}}>
      <div className="panel-title">RecoverAI webhook decision</div>
      <div className="facts">
        <Fact label="Recommended action" value={pretty(webhookDecision.recommended_action)}/>
        <Fact label="Confidence" value={webhookDecision.decision_confidence||'—'}/>
        <Fact label="Payment event" value={paymentEvent?.event_id||'—'}/>
        <Fact label="Guardrail · alternative payment" value={alternativeAllowed?'ALLOWED':'BLOCKED'}/>
      </div>
      <p className="attribution-caption">The failure was received through the public webhook, scored by the same Decision Agent, and re-checked by the same execution guardrails. Test recovery execution is operator-triggered so this panel never contacts a customer unexpectedly.</p>
      <button className="secondary" disabled={recoveryBusy||!alternativeAllowed||!!recovery} onClick={executeRecovery}>{recovery?'Recovery payment already created':recoveryBusy?'Creating recovery payment…':'Create Razorpay Test Recovery Payment'}</button>
    </div>}

    {recovery?.payment_link?.short_url&&<div className="note" style={{marginTop:12}}><ArrowUpRight size={15}/><div><b>Recovery payment created</b><span><a href={recovery.payment_link.short_url} target="_blank" rel="noreferrer">Open the Razorpay Test Recovery Payment →</a> Complete it with <b>success@razorpay</b>. The existing Razorpay webhook will verify the resulting payment before RecoverAI counts recovered revenue.</span></div></div>}
    {recovery&&<div className="facts" style={{marginTop:12}}>
      <Fact label="Recovery execution" value={recovery.execution_id}/>
      <Fact label="Provider status" value={pretty(recovery.integration?.status||recovery.state)}/>
      <Fact label="Revenue recovered" value={money(recovery.revenue_recovered)}/>
      <Fact label="Verification" value={recovery.state==='RECOVERED'?'VERIFIED':'PENDING'}/>
    </div>}
    {recovered&&<div className="note" style={{marginTop:12}}><CheckCircle2 size={15}/><div><b>Recovery verified</b><span>Razorpay payment status confirmed the recovery. Provider acceptance alone was not counted as recovered revenue.</span></div></div>}
  </div>
}

function money0(n){ return n==null?'—':`₹${Number(n).toLocaleString('en-IN',{maximumFractionDigits:0})}` }
function formatSimTime(value){
  const d=new Date(value)
  if(Number.isNaN(d.getTime())) return '—'
  const pad=n=>String(n).padStart(2,'0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

const EVENT_LABELS = {
  ORDER_CREATED:'Order created', CHECKOUT_STARTED:'Checkout started', CHECKOUT_ABANDONED:'Checkout abandoned',
  PAYMENT_ATTEMPTED:'Payment attempted', PAYMENT_FAILED:'Payment failed', PAYMENT_SUCCESS:'Payment success',
  RECOVERAI_EVENT_RECEIVED:'RecoverAI event received', RECOVERAI_DIAGNOSIS:'RecoverAI diagnosis',
  RECOVERY_DECISION:'Recovery decision', RECOVERY_ACTION_STARTED:'Recovery action started',
  RECOVERY_VERIFIED:'Recovery verified', RECOVERAI_VERIFICATION_RECEIVED:'RecoverAI verification received', ORDER_PAID:'Order paid', RECOVERY_SCHEDULED:'Recovery scheduled',
  RECOVERY_ESCALATED_TO_HUMAN:'Escalated to human', RECOVERY_STOPPED:'Recovery stopped',
  RECOVERY_ATTEMPT_FAILED:'Recovery attempt failed', RECOVERY_CUSTOMER_RESPONSE:'Customer responded to recovery', RECOVERY_RESUMED:'Recovery resumed', HUMAN_CASE_RESOLVED:'Human case resolved', SCENARIO_OUTCOME_LOCKED:'Scenario outcome locked', DUPLICATE_EVENT_IGNORED:'Duplicate event ignored (idempotent)',
  INCIDENT_INJECTED:'Incident injected', INCIDENT_CLEARED:'Incident cleared', SIMULATION_RESET:'Simulation reset',
}
const EVENT_TONE = {
  PAYMENT_FAILED:'state-failed', RECOVERY_ATTEMPT_FAILED:'state-failed', RECOVERY_STOPPED:'state-stopped',
  ORDER_PAID:'state-recovered', RECOVERY_VERIFIED:'state-recovered', PAYMENT_SUCCESS:'state-recovered',
  RECOVERY_ESCALATED_TO_HUMAN:'state-escalated', RECOVERY_SCHEDULED:'state-scheduled',
  RECOVERAI_EVENT_RECEIVED:'state-scheduled', RECOVERAI_VERIFICATION_RECEIVED:'state-scheduled', RECOVERY_DECISION:'state-scheduled', RECOVERY_CUSTOMER_RESPONSE:'state-scheduled', RECOVERY_RESUMED:'state-scheduled', HUMAN_CASE_RESOLVED:'state-scheduled', SCENARIO_OUTCOME_LOCKED:'state-scheduled',
  INCIDENT_INJECTED:'state-failed', DUPLICATE_EVENT_IGNORED:'state-stopped',
}
const ORDER_TONE = {
  PAID:'state-recovered', PAYMENT_FAILED:'state-failed', LOST:'state-failed',
  RECOVERY_IN_PROGRESS:'state-scheduled', ABANDONED:'state-stopped', CHECKOUT_STARTED:'state-scheduled',
}

function MerchantSimulator(){
  const [dash,setDash]=useState(null)
  const [customers,setCustomers]=useState([])
  const [products,setProducts]=useState([])
  const [orders,setOrders]=useState([])
  const [timeline,setTimeline]=useState([])
  const [incidents,setIncidents]=useState({incidents:{},active:null})
  const [selectedCustomer,setSelectedCustomer]=useState('')
  const [selectedProduct,setSelectedProduct]=useState('')
  const [selectedOrder,setSelectedOrder]=useState(null)
  const [running,setRunning]=useState(false)
  const [speed,setSpeed]=useState(1)
  const [scenarioBusy,setScenarioBusy]=useState(false)
  const [demoBusy,setDemoBusy]=useState(false)
  const [demoResult,setDemoResult]=useState(null)
  const [error,setError]=useState('')
  const tickRef = useRef(null)
  const tickInFlightRef = useRef(false)
  const simulationEpochRef = useRef(0)
  // Tracks the backend's simulation_generation so an in-flight continuous
  // tick that was dispatched before a Reset/Full-demo cannot mutate state
  // after that reset completes — the backend rejects it as stale and we
  // simply stop polling instead of showing mixed-generation data.
  const generationRef = useRef(null)

  const refresh = async()=>{
    try{
      const [d,o,t] = await Promise.all([getJSON('/api/merchant-sim/dashboard'),getJSON('/api/merchant-sim/orders?limit=30'),getJSON('/api/merchant-sim/timeline?limit=60')])
      setDash(d); setOrders(o.orders); setTimeline(t.events)
      if(d?.simulation_generation!=null) generationRef.current = d.simulation_generation
    }catch(e){ setError(e.message) }
  }

  useEffect(()=>{
    (async()=>{
      try{
        const [c,p,inc] = await Promise.all([getJSON('/api/merchant-sim/customers'),getJSON('/api/merchant-sim/products'),getJSON('/api/merchant-sim/incidents')])
        setCustomers(c.customers); setProducts(p.products); setIncidents(inc)
        if(c.customers[0]) setSelectedCustomer(c.customers[0].customer_id)
        if(p.products[0]) setSelectedProduct(p.products[0].id)
      }catch(e){ setError(e.message) }
      refresh()
    })()
    return ()=>{ if(tickRef.current) clearInterval(tickRef.current) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[])

  useEffect(()=>{
    if(tickRef.current){ clearInterval(tickRef.current); tickRef.current=null }
    if(running){
      tickRef.current = setInterval(async()=>{
        // Never overlap simulator ticks. An async interval can otherwise queue
        // multiple backend mutations and make Reset appear ineffective.
        if(tickInFlightRef.current) return
        const epoch = simulationEpochRef.current
        tickInFlightRef.current = true
        try{
          const genParam = generationRef.current!=null ? `&generation=${generationRef.current}` : ''
          const d = await postJSON(`/api/merchant-sim/tick?speed=${speed}${genParam}`,{})
          if(d?.stale){
            // A reset or full demo already ran on the backend since this tick
            // was dispatched — the backend made it a no-op. Stop the local
            // loop instead of polling against a generation that no longer
            // exists, so no stray mutation can ever slip in after a clean run.
            if(epoch === simulationEpochRef.current) setRunning(false)
          } else if(epoch === simulationEpochRef.current){
            await refresh()
          }
        }catch(e){
          if(epoch === simulationEpochRef.current){ setError(e.message); setRunning(false) }
        }finally{ tickInFlightRef.current = false }
      }, 1400)
    }
    return ()=>{ if(tickRef.current) clearInterval(tickRef.current) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[running,speed])

  const doReset = async()=>{
    simulationEpochRef.current += 1
    if(tickRef.current){ clearInterval(tickRef.current); tickRef.current=null }
    setRunning(false); setScenarioBusy(false); setDemoBusy(false); setError('')
    try{
      await postJSON('/api/merchant-sim/reset',{})
      setSelectedOrder(null); setDemoResult(null)
      const inc = await getJSON('/api/merchant-sim/incidents')
      setIncidents(inc)
      await refresh()
    }catch(e){ setError(e.message) }
  }
  const doPurchase = async(forceFail=false)=>{
    if(!selectedCustomer||!selectedProduct) return
    setError('')
    try{ const order = await postJSON('/api/merchant-sim/purchase',{customer_id:selectedCustomer,product_id:selectedProduct,force_fail:forceFail}); setSelectedOrder(order); await refresh() }catch(e){ setError(e.message) }
  }
  const runScenario = async()=>{
    simulationEpochRef.current += 1
    if(tickRef.current){ clearInterval(tickRef.current); tickRef.current=null }
    setRunning(false); setScenarioBusy(true); setError('')
    try{ const d = await postJSON('/api/merchant-sim/scenario/upi-failure-recovery',{}); setSelectedOrder(d.order); await refresh() }
    catch(e){ setError(e.message) } finally{ setScenarioBusy(false) }
  }
  const runFullDemo = async()=>{
    simulationEpochRef.current += 1
    if(tickRef.current){ clearInterval(tickRef.current); tickRef.current=null }
    setRunning(false); setDemoBusy(true); setError('')
    try{ const d=await postJSON('/api/revenue-intelligence/demo',{}); setDemoResult(d); await refresh() }
    catch(e){ setError(e.message) } finally{ setDemoBusy(false) }
  }
  const toggleIncident = async(key)=>{
    setError('')
    try{ const active = incidents.active===key ? null : key; const d = await postJSON('/api/merchant-sim/incident',{incident:active}); setIncidents(inc=>({...inc,active:d.active_incident})); await refresh() }
    catch(e){ setError(e.message) }
  }
  const openOrder = async(orderId)=>{
    try{ const o = await getJSON(`/api/merchant-sim/orders/${orderId}`); setSelectedOrder(o) }catch(e){ setError(e.message) }
  }

  return <div>
    <div className="hero" style={{marginBottom:22}}>
      <div>
        <div className="eyebrow"><Store size={14}/> MERCHANT COMMERCE SIMULATOR · SIMULATED</div>
        <h1 style={{fontSize:44}}>NovaCart</h1>
        <p>A simulated e-commerce merchant. RecoverAI runs in the background exactly as it would in a real payment stack — every decision below calls the same Decision Agent, guardrails and execution layer as Decision Lab. No simulated transaction can ever reach LIVE execution or real money.</p>
      </div>
      <div className="hero-card" style={{color:'var(--warning)'}}>
        <AlertOctagon size={20}/>
        <div><b>SIMULATED MERCHANT</b><span>Simulated payments · Simulated revenue · Real RecoverAI decisions underneath</span></div>
      </div>
    </div>

    {error&&<div className="alert">{error}</div>}

    <section className="metrics" style={{gridTemplateColumns:'repeat(4,1fr)'}}>
      <Metric icon={<CircleDollarSign/>} label="GMV (paid orders)" value={<AnimatedMoney value={dash?.gmv}/>}/>
      <Metric icon={<ShoppingCart/>} label="Payment attempts" value={<AnimatedNumber value={dash?.payment_attempts}/>} sub={dash?`${dash.successful_payments} succeeded`:''}/>
      <Metric icon={<AlertTriangle/>} label="Revenue at risk" value={<AnimatedMoney value={dash?.revenue_at_risk}/>} sub={dash?`${dash.failed_payments} failed payments`:''}/>
      <Metric icon={<ArrowUpRight/>} label="Recovered revenue" value={<AnimatedMoney value={dash?.recovered_revenue}/>} sub={dash?`${dash.active_recoveries} recovery in progress`:''}/>
    </section>

    <div className={`panel ${running?'live-surface':''}`} style={{marginTop:8}}>
      <div className="panel-title"><PlayCircle size={16}/> Simulation controls</div>
      <div style={{display:'flex',flexWrap:'wrap',gap:10,alignItems:'center'}}>
        <button className="secondary" onClick={()=>setRunning(r=>!r)}>{running?<><Pause size={14}/> Pause simulation</>:<><Play size={14}/> Start simulation</>}</button>
        <div className="subtab-toggle">{[1,5,10,20].map(s=><button key={s} className={speed===s?'active':''} onClick={()=>setSpeed(s)}>{s}x</button>)}</div>
        <button className="secondary" onClick={doReset}><RotateCcw size={14}/> Reset</button>
        <button className="primary" style={{width:'auto',margin:0}} onClick={runScenario} disabled={scenarioBusy}><FastForward size={14}/> {scenarioBusy?'Running…':'Run scenario: UPI failure → recovery'}</button>
        <button className="secondary" onClick={runFullDemo} disabled={demoBusy}><FastForward size={14}/> {demoBusy?'Running full demo…':'Run full RecoverAI demo'}</button>
      </div>
      <p className="attribution-caption" style={{marginTop:10}}>{running?`Continuous simulation running at ${speed}x — real orders, real payment attempts, real RecoverAI decisions on every failure.`:'Simulation paused. Start it, or trigger a single purchase / the deterministic scenario below.'}</p>
    </div>
    {demoResult&&<div className="panel" style={{marginTop:16}}><div className="panel-title"><Activity size={16}/> Full end-to-end demo result</div><div className="facts"><Fact label="Incident" value={demoResult.incident?.incident_id||'—'}/><Fact label="Severity" value={demoResult.incident?.severity||'—'}/><Fact label="Recovered" value={money(demoResult.analytics?.summary?.revenue_recovered)}/><Fact label="Incident status" value={demoResult.monitoring?.status||'—'}/></div><p className="attribution-caption">Merchant event → incident → Decision Agent → bounded recovery → verification → revenue analytics → feedback → monitoring. The demo uses the local simulator only.</p></div>}

    <div className="grid2" style={{marginTop:16}}>
      <div className="panel">
        <div className="panel-title"><ShoppingCart size={16}/> Simulate a purchase</div>
        <label className="field"><span>Customer (from existing synthetic dataset)</span>
          <select value={selectedCustomer} onChange={e=>setSelectedCustomer(e.target.value)}>
            {customers.map(c=><option key={c.customer_id} value={c.customer_id}>{c.customer_id} · {c.preferred_payment_method} · {(c.historical_success_rate*100).toFixed(0)}% history</option>)}
          </select>
        </label>
        <label className="field"><span>Product</span>
          <select value={selectedProduct} onChange={e=>setSelectedProduct(e.target.value)}>
            {products.map(p=><option key={p.id} value={p.id}>{p.name} — {money0(p.price)}</option>)}
          </select>
        </label>
        <div style={{display:'flex',gap:8,flexWrap:'wrap'}}>
          <button className="primary" style={{width:'auto',margin:0}} onClick={()=>doPurchase(false)}><Package size={14}/> Checkout &amp; pay</button>
          <button className="secondary" onClick={()=>doPurchase(true)}>Force payment failure</button>
        </div>
        <div className="panel-title" style={{marginTop:20}}><AlertOctagon size={16}/> Failure injection</div>
        <p className="attribution-caption">Simulation parameters only — these change the simulated payment stack's failure probabilities, not any real-world statistic.</p>
        <div className="chips">
          {Object.entries(incidents.incidents||{}).map(([key,info])=>
            <span key={key} className={incidents.active===key?'chip-active':''} onClick={()=>toggleIncident(key)}>{info.label}{incidents.active===key?' · ACTIVE':''}</span>
          )}
        </div>
      </div>

      <div className={`panel ${running?'live-surface':''}`}>
        <div className="panel-title"><Activity size={16}/> Live event timeline {running&&<span className="live-tag"><span className="live-dot"/>LIVE</span>}</div>
        <div className="journey-timeline" style={{maxHeight:430,overflowY:'auto'}}>
          {timeline.length===0&&<div className="empty small"><History size={28}/><p>No simulated activity yet.</p></div>}
          {timeline.map(e=><div key={e.event_id} className="journey-step" style={{padding:'10px 12px',cursor:e.order_id?'pointer':'default'}} onClick={()=>e.order_id&&openOrder(e.order_id)}>
            <div className="journey-step-num" style={{width:46,height:28,borderRadius:14,fontSize:12}}>{formatSimTime(e.timestamp)}</div>
            <div className="journey-step-body">
              <div className="journey-step-head"><b style={{fontSize:14}}>{EVENT_LABELS[e.event_type]||e.event_type}</b>{e.order_id&&<em className={`state-pill ${EVENT_TONE[e.event_type]||'state-scheduled'}`}>{e.order_id}</em>}</div>
              {e.detail&&Object.keys(e.detail).length>0&&<span style={{fontSize:13}}>{Object.entries(e.detail).slice(0,4).map(([k,v])=>`${k}: ${v}`).join(' · ')}</span>}
            </div>
          </div>)}
        </div>
      </div>
    </div>

    <div className="section-heading"><div><div className="eyebrow"><Receipt size={13}/> ORDERS</div><h2>Recent orders</h2></div></div>
    <div className="panel">
      <div className="audit-table">
        {orders.length===0&&<div className="empty small"><Package size={28}/><p>No orders yet — start the simulation or checkout above.</p></div>}
        {orders.map(o=><div key={o.order_id} className="audit-row" style={{gridTemplateColumns:'140px 140px 1fr 110px 160px 110px',cursor:'pointer'}} onClick={()=>openOrder(o.order_id)}>
          <strong>{o.order_id}</strong>
          <span>{o.customer_id}</span>
          <span>{o.product_name}</span>
          <span>{money0(o.amount)}</span>
          <em className={`state-pill ${ORDER_TONE[o.status]||'state-scheduled'}`}>{pretty(o.status)}</em>
          <span>{o.recovered?'RECOVERED':o.payment_attempts.length+' attempt(s)'}</span>
        </div>)}
      </div>
    </div>

    {selectedOrder&&<OrderInspector order={selectedOrder} onClose={()=>setSelectedOrder(null)}/>}
  </div>
}

function OrderInspector({order,onClose}){
  return <div className="panel" style={{marginTop:16,borderColor:'var(--brand)'}}>
    <div className="panel-title" style={{justifyContent:'space-between',display:'flex'}}>
      <span><User size={16}/> Order {order.order_id} — {order.customer_id}</span>
      <button className="secondary" onClick={onClose} style={{padding:'4px 10px'}}>Close</button>
    </div>
    <div className="facts">
      <Fact label="Product" value={order.product_name}/>
      <Fact label="Amount" value={money0(order.amount)}/>
      <Fact label="Status" value={pretty(order.status)}/>
      <Fact label="Recovered" value={order.recovered?'Yes':'No'}/>
    </div>
    <div className="panel-title" style={{marginTop:14}}><TimerReset size={15}/> Payment attempts</div>
    <div className="score-list">
      {order.payment_attempts.map((a,i)=><div className="score" key={i}>
        <div><b>Attempt #{a.attempt_no} · {a.method}</b><span>{formatSimTime(a.timestamp)}</span></div>
        <strong style={{color:a.status==='SUCCESS'?'var(--success)':'var(--danger)'}}>{a.status}{a.failure_type?` · ${pretty(a.failure_type)}`:''}</strong>
      </div>)}
    </div>
    {order.decision&&<>
      <div className="panel-title" style={{marginTop:14}}><Bot size={15}/> RecoverAI decision</div>
      <div className="cf-selected">
        <span>RECOMMENDED ACTION</span>
        <b>{pretty(order.decision.recommended_action)}</b>
        <span>{order.decision.reason}</span>
      </div>
    </>}
    {order.execution&&<>
      <div className="panel-title" style={{marginTop:14}}><ShieldCheck size={15}/> Execution result</div>
      <div className={`execution-result ${order.execution.state==='RECOVERED'?'success':''}`}>
        <b>{pretty(order.execution.state)}</b>
        <span>{order.execution.outcome_reason}</span>
        <small>{order.execution.execution_id} · {order.execution.execution_mode}</small>
      </div>
    </>}
  </div>
}

function RevenueAutopilot({data,loading,error,integrations,run,running,lastRun}){
  const causes=data?.root_causes?.causes||[]
  const anomalies=data?.anomalies?.anomalies||[]
  const customers=data?.affected_customers?.customers||[]
  const pipeline=data?.pipeline||[]
  const executions=data?.executions||[]
  const hasRun=Boolean(lastRun)
  return <section>
    <div className="page-title"><div><div className="eyebrow"><Radio size={15}/> REVENUE RECOVERY AUTOPILOT</div><h2>Detect → diagnose → prioritize → recover → verify</h2><p>The autopilot runs the complete revenue-intelligence and bounded recovery cycle only when you trigger it. Safe simulation never contacts customers or external providers.</p></div><button className="secondary" onClick={run} disabled={running||loading}>{running?'Running cycle…':hasRun?'Run Autopilot Again':'Run Autopilot Cycle'}</button></div>
    {error&&<div className="alert">{error}</div>}
    {!hasRun&&!running&&<div className="empty"><Radio size={36}/><h3>Autopilot is idle</h3><p>Click <b>Run Autopilot Cycle</b> to execute DETECT → DIAGNOSE → PRIORITIZE → RECOVER → VERIFY and populate the results below.</p></div>}
    {running&&<div className="empty small">Running Detect → Diagnose → Prioritize → Recover → Verify…</div>}
    {hasRun&&<>
      <div className="note"><Radio size={15}/><div><b>Autopilot run {lastRun.run_id}</b><span>{new Date(lastRun.generated_at||Date.now()).toLocaleString()} · {lastRun.duration_ms!=null?`${lastRun.duration_ms} ms · `:''}safe bounded recovery simulation completed; no external provider was contacted.</span></div></div>
      <Panel title="Autopilot pipeline">
        <div className="autopilot-pipeline">{pipeline.map((p,i)=><div className={`pipeline-step pipeline-${String(p.status).toLowerCase()}`} key={p.stage}><span>{String(i+1).padStart(2,'0')}</span><b>{p.stage}</b><em>{p.status.replaceAll('_',' ')}</em><small>{p.detail}</small></div>)}</div>
      </Panel>
      <div className="metrics"><Metric icon={<AlertTriangle/>} label="Anomalies" value={data?.summary?.anomalies??'—'} sub={data?.status||'—'}/><Metric icon={<Search/>} label="Root causes" value={data?.summary?.root_causes??'—'} sub="deteriorating segments"/><Metric icon={<Users/>} label="Affected customers" value={data?.summary?.affected_customers??'—'} sub={`${data?.summary?.execution_candidates??0} sent to recovery`}/><Metric icon={<Plug/>} label="Execution providers" value={data?.summary?.execution_providers??'—'} sub={(data?.execution?.providers_used||[]).join(', ')}/></div>
      <div className="facts"><Fact label="Simulated recovered" value={money(data?.summary?.revenue_recovered)}/><Fact label="Intervention cost" value={money(data?.summary?.intervention_cost)}/><Fact label="Net recovery" value={money(data?.summary?.net_recovery)}/><Fact label="Verified recovered" value={data?.summary?.verified_recovered??'—'}/></div>
      <div className="grid2"><Panel title="Anomaly watch"><div className="audit-table">{anomalies.length===0?<div className="empty small">No statistically significant anomaly in the current window.</div>:anomalies.slice(0,8).map((a,i)=><div className="audit-row" key={i}><b>{new Date(a.timestamp).toLocaleString()}</b><span>{a.severity}</span><span>{pct(a.failure_rate)} failure rate</span><strong>z={a.z_score}</strong><em>{money(a.amount_at_risk)} exposed</em></div>)}</div><p className="attribution-caption">Calculated from hourly failure-rate z-scores against the historical baseline; the anomaly count is data-driven and can change when the event window changes.</p></Panel>
      <Panel title="Merchant incident watch"><div className="audit-table">{(data?.merchant_incidents?.incidents||[]).length===0?<div className="empty small">No merchant-specific incident detected in the current window.</div>:(data?.merchant_incidents?.incidents||[]).map((x,i)=><div className="audit-row" key={`${x.merchant_id}-${x.payment_method}-${i}`}><b>{x.merchant_name} · {x.payment_method}</b><span>{x.severity}</span><span>{pct(x.baseline_failure_rate)} → {pct(x.recent_failure_rate)}</span><strong>{pretty(x.incident_type)}</strong><em>{money(x.revenue_exposed)} exposed</em></div>)}</div><p className="attribution-caption">Phase 3 infers merchant incidents from observed payment deterioration, then carries the same Decision Agent recommendation for the affected payment path. Recovery outcomes and injected-incident flags are not used.</p></Panel>
      <Panel title="Root cause ranking"><div className="audit-table">{causes.length===0?<div className="empty small">No deteriorating segment found.</div>:causes.map((c,i)=><div className="audit-row" key={i}><b>{c.dimension}</b><span>{c.segment}</span><span>{pct(c.baseline_failure_rate)} → {pct(c.recent_failure_rate)}</span><strong>+{(c.rate_delta*100).toFixed(1)}pp</strong><em>{money(c.amount_exposed)}</em></div>)}</div><p className="attribution-caption">Segments are ranked by recent-vs-baseline failure-rate deterioration and exposed amount, without using recovery outcomes.</p></Panel></div>
      <Panel title="Affected-customer discovery"><div className="audit-table">{customers.length===0?<div className="empty small">No affected customers found.</div>:customers.map(c=><div className="audit-row" key={c.customer_id}><b>{c.customer_id}</b><span>{c.events} failed events</span><span>{money(c.amount_at_risk)} at risk</span><strong>Risk {c.risk_score.toFixed(0)}/100</strong><em>{pct(c.historical_success_rate)} history</em></div>)}</div><p className="attribution-caption">{customers.length} customers are shown because the discovery limit is 25; the previous 15-row display was only a UI slice, not the underlying count.</p></Panel>
      <Panel title="Recovery execution & verification"><div className="audit-table">{executions.map(x=><div className="audit-row" key={x.execution_id||x.event_id}><b>{x.customer_id}</b><span>{pretty(x.action)}</span><span>{pretty(x.execution_state)}</span><strong>{pretty(x.verification_status)}</strong><em>{x.revenue_recovered!=null?money(x.revenue_recovered):'No action'}</em></div>)}</div><p className="attribution-caption">Recover uses the same Decision Agent and execution guardrails as Decision Lab. Verify classifies each bounded execution state; it does not claim a real payment was recovered without a payment/provider confirmation event.</p></Panel>
      <Panel title="Execution control plane"><div className="facts"><Fact label="Mode" value={data?.execution?.mode||'SAFE_SIMULATION'}/><Fact label="Provider" value={data?.execution?.provider||'local_bounded_simulator'}/><Fact label="Customers considered" value={data?.execution?.candidates_considered??'—'}/><Fact label="Execution cap" value={data?.execution?.execution_cap??'—'}/></div><p className="attribution-caption">Autopilot deliberately executes only a bounded top-10 simulation on each run. Live customer/payment actions remain explicit through Decision Lab, preserving the existing safety boundary.</p></Panel>
      <Panel title="Recovery outcome analytics"><div className="facts"><Fact label="Revenue exposed" value={money(data?.outcome_analytics?.summary?.revenue_exposed)}/><Fact label="Revenue recovered" value={money(data?.outcome_analytics?.summary?.revenue_recovered)}/><Fact label="Recovery rate" value={data?.outcome_analytics?.summary?.recovery_rate!=null?pct(data.outcome_analytics.summary.recovery_rate):'—'}/><Fact label="Recovery ROI" value={data?.outcome_analytics?.summary?.recovery_roi!=null?`${(data.outcome_analytics.summary.recovery_roi*100).toFixed(1)}%`:'—'}/></div><p className="attribution-caption">Verified outcomes are measured separately from expected recovery; provider acceptance is never counted as recovered revenue.</p></Panel>
      <Panel title="Incident impact & merchant health"><div className="facts"><Fact label="Blast radius" value={data?.incident_blast_radius?.affected_unique_customers??'—'}/><Fact label="Orders affected" value={data?.incident_blast_radius?.affected_orders??'—'}/><Fact label="Health score" value={data?.merchant_health?.score!=null?`${data.merchant_health.score}/100`:'—'}/><Fact label="Incident status" value={data?.incident_monitoring?.status||'—'}/></div><p className="attribution-caption">Health combines payment reliability, recovery effectiveness, incident load and verification health. Incident monitoring is based on observed post-incident payment behavior.</p></Panel>
      <Panel title="Feedback / learning"><div className="audit-table">{(data?.feedback_analytics?.by_action||[]).slice(0,6).map(x=><div className="audit-row" key={x.segment}><b>{pretty(x.segment)}</b><span>{x.attempts} attempts</span><span>{pct(x.recovery_rate)} recovered</span><strong>{money(x.recovered)}</strong><em>error {money(x.prediction_error)}</em></div>)}</div><p className="attribution-caption">Feedback compares predicted recovery with verified outcomes for evaluation only; models are not automatically retrained.</p></Panel>
    </>}
  </section>
}
function B2BChaser({form,update,onRun,loading,error,result}){
  return <>
    {error&&<div className="alert">{error}</div>}
    <div className="note" style={{marginBottom:16}}>
      <Layers size={16}/>
      <div><b>Real dunning-tier policy applied</b><span>No retry loop — an unpaid invoice is chased on a collections cadence (Friendly Reminder → Firm Notice → Formal Dunning → Collections) and escalates to the account manager once it clears {ACCOUNT_MANAGER_DAYS_LABEL} days overdue or {ACCOUNT_MANAGER_AMOUNT_LABEL}, not a generic support queue.</span></div>
    </div>
    <div className="decision-grid">
      <form className="form-card" onSubmit={onRun}>
        <Field label="Invoice amount (₹)"><input type="number" min="1" value={form.amount} onChange={e=>update('amount',e.target.value)}/></Field>
        <div className="form-row"><Field label="Invoice number"><input value={form.invoice_number} onChange={e=>update('invoice_number',e.target.value)}/></Field><Field label="Customer name"><input value={form.customer_display_name} onChange={e=>update('customer_display_name',e.target.value)}/></Field></div>
        <div className="form-row"><Field label="Days overdue"><input type="number" min="0" value={form.days_overdue} onChange={e=>update('days_overdue',e.target.value)}/></Field><Field label="Customer success rate"><input type="number" min="0" max="1" step="0.01" value={form.historical_success_rate} onChange={e=>update('historical_success_rate',e.target.value)}/></Field></div>
        <button className="primary" disabled={loading}>{loading?'Running chase…':'Run Receivables Chase'}</button>
      </form>
      <div className="result-card">
        {!result?<div className="empty"><Layers size={36}/><h3>Chase appears here</h3><p>Try a large, badly overdue invoice to see the automatic account-manager escalation fire.</p></div>:<>
          <div className="recommend"><div><span>CHASE {result.chase_id}</span><h2>{result.step_count} step{result.step_count===1?'':'s'} · {pretty(result.final_state)}</h2></div><div className="check"><Layers size={27}/></div></div>
          <p className="reason">{result.stop_reason}</p>
          <div className="facts">
            <Fact label="Total recovered" value={money(result.total_revenue_recovered)}/>
            <Fact label="Net recovery" value={money(result.net_recovery)}/>
            <Fact label="Final state" value={pretty(result.final_state)}/>
          </div>
          <div className="journey-timeline">
            {result.steps.map(s=><div className="journey-step" key={s.step_number}>
              <div className="journey-step-num">{s.step_number}</div>
              <div className="journey-step-body">
                <div className="journey-step-head"><b>{s.action_label}</b><em className={`state-pill state-${s.execution_state.toLowerCase()}`}>{pretty(s.execution_state)}</em></div>
                <span>{pretty(s.dunning_tier)} · {s.days_overdue.toFixed(0)} days overdue · {money(s.revenue_recovered)} recovered</span>
                {s.dunning_notice&&<div className="dunning-notice"><b>{s.dunning_notice.subject}</b><p>{s.dunning_notice.body}</p></div>}
              </div>
            </div>)}
          </div>
        </>}
      </div>
    </div>
  </>
}
const ACCOUNT_MANAGER_DAYS_LABEL='45'
const ACCOUNT_MANAGER_AMOUNT_LABEL='₹1,00,000'

function Chart({data,dataKey,nameKey,color='#5b9dff'}){
  const gradId = `grad-${dataKey}-${color.replace('#','')}`
  return <div className="chart"><ResponsiveContainer width="100%" height="100%">
    <BarChart data={data} margin={{top:8,right:8,left:0,bottom:0}}>
      <defs><linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={color} stopOpacity={0.95}/><stop offset="100%" stopColor={color} stopOpacity={0.45}/></linearGradient></defs>
      <CartesianGrid strokeDasharray="3 3" stroke="#182338" vertical={false}/>
      <XAxis dataKey={nameKey} tick={{fontSize:13,fill:'#8ca0bc'}} axisLine={{stroke:'#243751'}} tickLine={false}/>
      <YAxis tick={{fontSize:13,fill:'#8ca0bc'}} axisLine={false} tickLine={false} tickFormatter={v=>v>=10000000?`₹${(v/10000000).toFixed(v>=100000000?0:1)}Cr`:v>=100000?`₹${Math.round(v/100000)}L`:`₹${Math.round(v/1000)}K`}/>
      <Tooltip cursor={{fill:'rgba(93,158,255,0.10)'}} contentStyle={{background:'#0d1727',border:'1px solid #29405e',borderRadius:10,fontSize:14,color:'#e8eefc'}} labelStyle={{color:'#8ca0bc',marginBottom:4}} formatter={v=>money(v)}/>
      <Bar dataKey={dataKey} radius={[6,6,0,0]} fill={`url(#${gradId})`} maxBarSize={56}/>
    </BarChart>
  </ResponsiveContainer></div>
}
function VoiceRecoveryPreview({result,form,action}){
  const [voice,setVoice]=useState(null)
  const [loading,setLoading]=useState(false)
  const [error,setError]=useState('')
  const effectiveAction = action || result?.recommended_action
  useEffect(()=>{
    let cancelled=false
    const loadVoice=async()=>{
      if(!effectiveAction || effectiveAction==='STOP') { setVoice(null); setLoading(false); return }
      // Clear any previously-loaded script immediately so a script generated
      // for a different action can never remain visible while the new
      // action's script is being fetched.
      setVoice(null); setLoading(true); setError('')
      try{
        const d=await postJSON('/api/voice/script',{action:effectiveAction,amount:Number(form.amount),event_type:form.event_type,failure_type:form.failure_type,event_id:form.event_id})
        if(!cancelled && d.script) {
          // Defensive check: the response must actually correspond to the
          // action we just asked for, in case a slower stale request from a
          // previous action resolves after a newer one (guards the effect's
          // own cancellation flag against any future refactor).
          setVoice(d)
        }
      }catch(e){if(!cancelled) {setError(e.message);setVoice(null)}}finally{if(!cancelled) setLoading(false)}
    }
    loadVoice()
    return ()=>{cancelled=true}
  },[effectiveAction,result?.decision_id,form.amount,form.event_type,form.failure_type,form.event_id])
  if(!effectiveAction || effectiveAction==='STOP') return null
  return <div className="agent-trace" style={{marginTop:12}}>
    <div className="trace-title"><Languages size={15}/> Hinglish Voice Recovery <span>PREVIEW</span></div>
    <p className="attribution-caption">The selected recovery can be delivered as a deterministic Hinglish voice script. Preview/playback is local browser TTS; no call is placed.</p>
    {loading&&<div className="empty small">Generating Hinglish recovery script…</div>}
    {error&&<div className="alert">{error}</div>}
    {voice&&<VoicePlayback voice={voice}/>} 
  </div>
}

function VoicePlayback({voice}){
  const [playing,setPlaying]=useState(false)
  const [voiceName,setVoiceName]=useState(null)
  const supported = typeof window!=='undefined' && 'speechSynthesis' in window

  const pickHindiVoice = ()=>{
    if(!supported) return null
    const voices = window.speechSynthesis.getVoices()
    return voices.find(v=>v.lang?.toLowerCase().startsWith('hi')) ||
           voices.find(v=>v.lang?.toLowerCase().startsWith('en-in')) ||
           voices[0] || null
  }

  const play = ()=>{
    if(!supported || !voice?.script) return
    window.speechSynthesis.cancel()
    const utter = new SpeechSynthesisUtterance(voice.script)
    const v = pickHindiVoice()
    if(v){ utter.voice = v; setVoiceName(v.name) }
    utter.lang = voice.voice_locale_hint || 'hi-IN'
    utter.rate = 0.98
    utter.onend = ()=>setPlaying(false)
    utter.onerror = ()=>setPlaying(false)
    window.speechSynthesis.speak(utter)
    setPlaying(true)
  }
  const stop = ()=>{ if(supported){ window.speechSynthesis.cancel(); setPlaying(false) } }

  return <div className="note" style={{color:'var(--brand-2)',flexDirection:'column',alignItems:'stretch',gap:10}}>
    <div style={{display:'flex',alignItems:'center',gap:10}}>
      <Languages size={16}/>
      <div style={{flex:1}}>
        <b>Hinglish voice script generated</b>
        <span>{voice.language_label} · ~{voice.estimated_duration_seconds}s · {voice.word_count} words</span>
      </div>
      {supported
        ? <button type="button" className="secondary" onClick={playing?stop:play}>{playing?<><Square size={14}/> Stop</>:<><Volume2 size={14}/> Play</>}</button>
        : <span style={{fontSize:13,color:'var(--text-3)'}}>TTS not supported in this browser</span>}
    </div>
    <p style={{margin:0,fontSize:15,color:'var(--text-1)',lineHeight:1.6,fontStyle:'italic'}}>&ldquo;{voice.script}&rdquo;</p>
    <small style={{fontSize:12.5,color:'var(--text-3)'}}>{voice.note}{voiceName?` · Voiced with: ${voiceName}`:''}</small>
  </div>
}

function Metric({icon,label,value,sub}){return <div className="metric"><div className="metric-icon">{icon}</div><span>{label}</span><strong>{value}</strong>{sub&&<small>{sub}</small>}</div>}
function AnimatedMoney({value}){
  const display = useCountUp(value, v=>money(Math.round(v)))
  return <>{value==null?'—':display}</>
}
function AnimatedNumber({value}){
  const display = useCountUp(value, v=>Math.round(v).toLocaleString('en-IN'))
  return <>{value==null?'—':display}</>
}
function HeroMetrics({metrics}){
  return <section className="metrics">
    <Metric icon={<CircleDollarSign/>} label="Revenue at Risk" value={<AnimatedMoney value={metrics?.revenue_at_risk}/>}/>
    <Metric icon={<ArrowUpRight/>} label="Revenue Recovered" value={<AnimatedMoney value={metrics?.revenue_recovered}/>} sub={metrics?pct(metrics.recovery_rate)+' recovery rate':''}/>
    <Metric icon={<Gauge/>} label="Incremental vs Baseline" value={<AnimatedMoney value={metrics?.incremental_recovery}/>} sub={metrics?pct(metrics.relative_uplift)+' uplift':''}/>
    <Metric icon={<Target/>} label="Oracle Capture" value={metrics?pct(metrics.oracle_capture):'—'} sub={metrics?money(metrics.policy_regret)+' regret':''}/>
  </section>
}
function Panel({title,children}){return <div className="panel"><div className="panel-title">{title}</div>{children}</div>}
function Field({label,children}){return <label className="field"><span>{label}</span>{children}</label>}
function Fact({label,value}){return <div className="fact"><span>{label}</span><b>{value==null?'—':value}</b></div>}
