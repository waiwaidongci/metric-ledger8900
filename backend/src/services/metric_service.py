from fastapi import HTTPException
from ..models import Metric,MetricVersion,MetricDefinition,SourceRow
from ..utils.serialize import record
from .expression_service import compile_metrics
from .pivot_service import build_report
from .audit_service import log
def current_version(db):
    return db.query(MetricVersion).order_by(MetricVersion.id.desc()).first()
def ensure_version(db,actor="system"):
    """既有部署只有 metrics 表时，把当前定义固化为基线版本。"""
    version=current_version(db)
    if version:return version
    rows=db.query(Metric).order_by(Metric.id).all()
    if not rows:return None
    version=MetricVersion(note="基线版本：既有定义迁移",published_by=actor)
    db.add(version);db.flush()
    for position,m in enumerate(rows):
        db.add(MetricDefinition(version_id=version.id,position=position,key=m.key,name=m.name,expression=m.expression,unit=m.unit,description=m.description))
    db.flush()
    return version
def definitions_for_version(db,version_id):
    """报表计算固定使用创建时冻结的版本；历史运行缺版本时回退到当前定义。"""
    if version_id:
        defs=db.query(MetricDefinition).filter_by(version_id=version_id).order_by(MetricDefinition.position).all()
        if defs:return defs
    return db.query(Metric).order_by(Metric.id).all()
def list_metrics(db):
    rows=db.query(Metric).order_by(Metric.id).all()
    _,order,deps=compile_metrics(rows)
    version=current_version(db)
    return {"items":[dict(record(m),dependencies=deps[m.key]) for m in rows],"evaluation_order":order,"version":record(version) if version else None}
def list_versions(db):
    versions=db.query(MetricVersion).order_by(MetricVersion.id.desc()).limit(50).all()
    counts={}
    for row in db.query(MetricDefinition.version_id,MetricDefinition.key).all():counts[row[0]]=counts.get(row[0],0)+1
    return [dict(record(v),metric_count=counts.get(v.id,0)) for v in versions]
class _Draft:
    """与 Metric 同形的轻量对象，供编译与试算。"""
    def __init__(self,key,name,expression,unit,description):
        self.key,self.name,self.expression,self.unit,self.description=key,name,expression,unit,description
def _drafts(items):
    keys=[m["key"] for m in items]
    if len(set(keys))!=len(keys):raise HTTPException(422,"指标标识在一组发布内重复")
    return [_Draft(m["key"],m["name"],m["expression"],m["unit"],m["description"]) for m in items]
def _validate(db,drafts):
    """环路、缺失依赖、覆盖来源字段或试算失败时抛出，调用方不得提交事务。"""
    try:
        compile_metrics(drafts)
        sources=db.query(SourceRow).order_by(SourceRow.id).all()
        if sources:
            build_report(sources,drafts,["channel","month"])
            build_report(sources,drafts,["region","month"])
    except ValueError as e:raise HTTPException(422,str(e))
def _apply_publish(db,items,user,note):
    """校验通过后原子替换现行定义并固化新版本；失败抛出则回滚，原定义保留。"""
    drafts=_drafts(items)
    _validate(db,drafts)
    version=MetricVersion(note=note,published_by=user.name)
    db.add(version);db.flush()
    for position,m in enumerate(drafts):
        db.add(MetricDefinition(version_id=version.id,position=position,key=m.key,name=m.name,expression=m.expression,unit=m.unit,description=m.description))
    db.query(Metric).delete()
    for m in drafts:db.add(Metric(key=m.key,name=m.name,expression=m.expression,unit=m.unit,description=m.description,owner=user.name))
    db.flush()
    return version
def publish_metrics(db,data,user):
    # 锁定最新版本行：并发发布串行化，后到者重读基线后按409拒绝覆盖。
    version=db.query(MetricVersion).order_by(MetricVersion.id.desc()).with_for_update().first()
    if version is None:version=ensure_version(db,user.email)
    if (version and data.base_version!=version.id) or (version is None and data.base_version!=0):
        raise HTTPException(409,"他人已发布新版本，请刷新后以最新定义为基线重新提交")
    version=_apply_publish(db,[m.model_dump() for m in data.metrics],user,data.note)
    log(db,user.email,"metric.publish",version.id);db.commit()
    return record(version)
def create_metric(db,data,user):
    if db.query(Metric).filter_by(key=data.key).first():raise HTTPException(409,"指标标识已存在")
    items=[{"key":m.key,"name":m.name,"expression":m.expression,"unit":m.unit,"description":m.description} for m in db.query(Metric).order_by(Metric.id).all()]
    _apply_publish(db,items+[data.model_dump()],user,"登记 "+data.key)
    log(db,user.email,"metric.register",data.key);db.commit()
    return record(db.query(Metric).filter_by(key=data.key).first())
