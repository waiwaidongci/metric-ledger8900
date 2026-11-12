import {FormEvent,useState} from 'react';
import {Plus,Trash2,X} from 'lucide-react';
import {useLedgerData} from '../hooks/useLedger';
import {useAuth} from '../stores/auth';
import {useAction} from '../hooks/useAction';
import {publishMetrics} from '../api/metrics';
import {Notice} from '../components/common/Notice';
import {MetricFormula} from '../components/MetricFormula';
import {MetricDraft} from '../types/domain';
import {time} from '../utils/format';
const emptyRow=():MetricDraft=>({key:'',name:'',expression:'',unit:'元',description:''});
export function Metrics(){
  const s=useLedgerData(),{user}=useAuth(),action=useAction();
  const [editing,setEditing]=useState(false),[draft,setDraft]=useState<MetricDraft[]>([]),[base,setBase]=useState(0),[note,setNote]=useState(''),[conflict,setConflict]=useState(false);
  const isAdmin=user?.role==='admin';
  function start(){setDraft(s.metrics.map(m=>({key:m.key,name:m.name,expression:m.expression,unit:m.unit,description:m.description})));setBase(s.version?.id??0);setNote('');setConflict(false);setEditing(true)}
  function update(i:number,field:keyof MetricDraft,value:string){setDraft(d=>d.map((r,j)=>j===i?{...r,[field]:value}:r))}
  const valid=draft.length>0&&draft.every(r=>/^[a-z][a-z0-9_]{1,39}$/.test(r.key)&&r.name.trim().length>=2&&r.expression.trim().length>0&&r.description.trim().length>=8)&&note.trim().length>=2;
  function submit(e:FormEvent){e.preventDefault();action.execute(async()=>{
    try{await publishMetrics({base_version:base,note,metrics:draft});setEditing(false);await s.refresh()}
    catch(err){if((err as Error).message.includes('他人已发布')){setConflict(true);await s.refresh()}throw err}
  })}
  if(editing)return <div className="page">
    <div className="page-title"><div><p className="eyebrow">DEFINITION RELEASE / 02</p><h1>整组编辑发布<span>以 v{base} 为基线，整组校验通过后一次性生效。</span></h1></div><span className="issue-tag">{draft.length} 项待发布</span></div>
    <Notice message={s.error||action.error} retry={s.refresh}/>
    {conflict&&<div role="alert" className="notice">基线已过期：他人发布了更新的版本，请核对最新定义后重新修改。<button onClick={start}>载入最新定义</button></div>}
    <form onSubmit={submit}>
      <div className="editor-grid editor-head"><span>指标标识</span><span>业务名称</span><span>计算表达式</span><span>单位</span><span>口径说明</span><span/></div>
      {draft.map((row,i)=><div className="editor-grid editor-row" key={i}>
        <input aria-label={`标识${i+1}`} placeholder="metric_key" value={row.key} onChange={e=>update(i,'key',e.target.value)} pattern="[a-z][a-z0-9_]{1,39}" required/>
        <input aria-label={`名称${i+1}`} placeholder="业务名称" value={row.name} onChange={e=>update(i,'name',e.target.value)} minLength={2} required/>
        <input aria-label={`表达式${i+1}`} className="mono" placeholder="revenue - refunds" value={row.expression} onChange={e=>update(i,'expression',e.target.value)} required/>
        <select aria-label={`单位${i+1}`} value={row.unit} onChange={e=>update(i,'unit',e.target.value)}><option>元</option><option>元/单</option><option>比率</option></select>
        <input aria-label={`说明${i+1}`} placeholder="写清分子、分母与汇总顺序，至少8字" value={row.description} onChange={e=>update(i,'description',e.target.value)} minLength={8} required/>
        <button type="button" className="icon-button" aria-label={`删除第${i+1}行`} onClick={()=>setDraft(d=>d.filter((_,j)=>j!==i))}><Trash2 size={14}/></button>
      </div>)}
      <div className="editor-actions">
        <button type="button" className="outline" onClick={()=>setDraft(d=>[...d,emptyRow()])}><Plus size={14}/>新增指标行</button>
        <label>发布说明<input aria-label="发布说明" value={note} onChange={e=>setNote(e.target.value)} minLength={2} placeholder="例如：净收入与毛利一起改扣渠道服务费" required/></label>
        <button className="primary" disabled={action.busy||!valid}>校验并发布改版</button>
        <button type="button" className="outline" onClick={()=>setEditing(false)}><X size={14}/>取消</button>
      </div>
    </form>
    <div className="method-note editor-note"><b>原子发布</b><p>环路、未知依赖、覆盖来源字段或现有数据试算失败时，整组拒绝并保留现行定义；发布以基线版本号为并发凭据，他人先发布则本次提交被拒绝。已排队报表沿用创建时冻结的版本，新报表与定时交付采用最新版本。</p></div>
  </div>;
  return <div className="page"><div className="page-title"><div><p className="eyebrow">DEFINITION REGISTER / 02</p><h1>指标口径<span>先固定定义，再讨论差异。</span></h1></div><span className="issue-tag">{s.metrics.length} 个口径 · v{s.version?.id??'—'}</span></div><Notice message={s.error} retry={s.refresh}/><div className="metrics-layout"><section><div className="dependency-order"><span className="eyebrow">计算顺序 / 依赖拓扑</span><p>{s.order.join(' → ')}</p></div>{s.metrics.map(m=><MetricFormula key={m.id} metric={m}/>)}</section><aside className="registration"><span className="eyebrow">RELEASE CONTROL</span><h2>版本与发布</h2><div className="method-note current-version"><b>当前版本 v{s.version?.id??'—'}</b><p>{s.version?`${s.version.note} · ${s.version.published_by} · ${time(s.version.published_at)}`:'尚未发布版本'}</p></div>{isAdmin?<button className="primary release-button" onClick={start}>整组编辑发布</button>:<p className="role-note">当前角色可以阅读口径与版本。指标改版由口径负责人执行。</p>}<div className="version-history"><span className="eyebrow">RELEASE LEDGER / 版本记录</span>{s.versions.map(v=><div className="version-item" key={v.id}><b>v{v.id} · {v.note}</b><small>{v.published_by} · {time(v.published_at)} · {v.metric_count} 项指标</small></div>)}</div><div className="method-note"><b>表达式边界</b><p>仅支持数字、字段、加减乘除与括号。来源字段：revenue / cost / refunds / orders。未知依赖、环路、函数调用和零分母会明确拒绝，失败时保留现行定义。</p></div></aside></div></div>;
}
