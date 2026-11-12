"""指标版本化验证：改版失败保留原定义、并发发布冲突、跨版本计算。"""
import pytest
from types import SimpleNamespace
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.config.database import Base
from src.models import Metric,MetricVersion,MetricDefinition,SourceRow,ReportRun,DeliverySchedule
from src.schemas.metric import MetricPublish,MetricInput
from src.schemas.report import ReportInput
from src.services import metric_service,report_service,scheduler_service
from src.services.metric_service import publish_metrics,create_metric,current_version,ensure_version,definitions_for_version
from src.services.report_service import create_run,compute_run
from src.services.scheduler_service import schedule_due

ADMIN=SimpleNamespace(name="陆知衡 · 口径负责人",email="admin@hengchi.demo")
OTHER=SimpleNamespace(name="另一位口径负责人",email="other@hengchi.demo")
BASE_METRICS=[
    {"key":"net_revenue","name":"净收入","expression":"revenue-refunds","unit":"元","description":"渠道收入减退款，不扣履约成本。"},
    {"key":"gross_profit","name":"贡献毛利","expression":"net_revenue-cost","unit":"元","description":"净收入扣除渠道履约成本的贡献。"},
]
class FakeQueue:
    def __init__(self):self.jobs=[]
    def rpush(self,key,value):self.jobs.append(value)
@pytest.fixture()
def db(monkeypatch):
    engine=create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session=sessionmaker(bind=engine,expire_on_commit=False)()
    fake=FakeQueue()
    monkeypatch.setattr(report_service,"queue",fake)
    monkeypatch.setattr(scheduler_service,"queue",fake)
    for i,(channel,region,day) in enumerate([("直营渠道","华东","2026-09-05"),("书店合作","华北","2026-10-11"),("数字发行","华南","2026-10-20")]):
        session.add(SourceRow(source_key=f"T-{i}",day=day,channel=channel,region=region,revenue=1000.0,refunds=100.0,cost=400.0,orders=10,reference_net=900.0))
    yield session
    session.close()
def seed_metrics(db):
    for m in BASE_METRICS:db.add(Metric(**m,owner=ADMIN.name))
    db.flush()
    version=ensure_version(db,ADMIN.email)
    db.commit()
    return version
def publish_payload(base,metrics,note="改版"):
    return MetricPublish.model_validate({"base_version":base,"note":note,"metrics":metrics})
def live(db):
    return {m.key:m.expression for m in db.query(Metric).order_by(Metric.id).all()}
def versions(db):
    return db.query(MetricVersion).count()

def test_publish_cycle_keeps_original(db):
    v1=seed_metrics(db)
    cycle=[
        {"key":"alpha_metric","name":"甲指标","expression":"beta_metric+1","unit":"元","description":"互相依赖的甲指标。"},
        {"key":"beta_metric","name":"乙指标","expression":"alpha_metric+1","unit":"元","description":"互相依赖的乙指标。"},
    ]
    with pytest.raises(HTTPException) as err:publish_metrics(db,publish_payload(v1.id,cycle),ADMIN)
    assert err.value.status_code==422 and "环路" in err.value.detail
    assert live(db)=={m["key"]:m["expression"] for m in BASE_METRICS}
    assert versions(db)==1

def test_publish_missing_dependency_keeps_original(db):
    v1=seed_metrics(db)
    broken=BASE_METRICS+[{"key":"broken","name":"缺失依赖","expression":"ghost_metric*2","unit":"元","description":"引用不存在指标的口径。"}]
    with pytest.raises(HTTPException) as err:publish_metrics(db,publish_payload(v1.id,broken),ADMIN)
    assert err.value.status_code==422 and "未知依赖" in err.value.detail
    assert live(db)=={m["key"]:m["expression"] for m in BASE_METRICS}
    assert versions(db)==1

def test_publish_trial_failure_keeps_original(db):
    v1=seed_metrics(db)
    zero=BASE_METRICS+[{"key":"bad_ratio","name":"零分母比率","expression":"net_revenue/(orders-orders)","unit":"比率","description":"分母恒为零的试算失败样例。"}]
    with pytest.raises(HTTPException) as err:publish_metrics(db,publish_payload(v1.id,zero),ADMIN)
    assert err.value.status_code==422 and "分母为零" in err.value.detail
    covered=[{"key":"revenue","name":"覆盖来源","expression":"revenue-refunds","unit":"元","description":"试图覆盖来源字段的口径。"}]
    with pytest.raises(HTTPException) as err2:publish_metrics(db,publish_payload(v1.id,covered),ADMIN)
    assert err2.value.status_code==422
    assert live(db)=={m["key"]:m["expression"] for m in BASE_METRICS}
    assert versions(db)==1

def test_publish_conflict_rejected(db):
    v1=seed_metrics(db)
    change=[dict(m,expression="revenue-refunds-1") if m["key"]=="net_revenue" else m for m in BASE_METRICS]
    publish_metrics(db,publish_payload(v1.id,change,"净收入口径减一"),ADMIN)
    assert live(db)["net_revenue"]=="revenue-refunds-1"
    stale=BASE_METRICS+[{"key":"late_metric","name":"迟到指标","expression":"revenue/orders","unit":"元/单","description":"基于旧版本提交的并发改版。"}]
    with pytest.raises(HTTPException) as err:publish_metrics(db,publish_payload(v1.id,stale,"过期基线"),OTHER)
    assert err.value.status_code==409
    assert live(db)["net_revenue"]=="revenue-refunds-1" and "late_metric" not in live(db)
    assert versions(db)==2

def test_cross_version_calculation(db):
    v1=seed_metrics(db)
    run1=db.get(ReportRun,create_run(db,ReportInput(name="旧口径报表",dimensions=["channel","month"]),ADMIN)["id"])
    assert run1.metric_version_id==v1.id
    change=[dict(m,expression="revenue-refunds-10") if m["key"]=="net_revenue" else m for m in BASE_METRICS]
    publish_metrics(db,publish_payload(v1.id,change,"净收入口径减十"),ADMIN)
    v2=current_version(db)
    assert v2.id!=v1.id
    compute_run(db,run1);db.commit()
    expected_v1=3*(1000.0-100.0)
    assert run1.result["total"]["values"]["net_revenue"]==round(expected_v1,6)
    assert {m["key"]:m["expression"] for m in run1.result["metrics"]}["net_revenue"]=="revenue-refunds"
    run2=db.get(ReportRun,create_run(db,ReportInput(name="新口径报表",dimensions=["channel","month"]),ADMIN)["id"])
    assert run2.metric_version_id==v2.id
    compute_run(db,run2);db.commit()
    assert run2.result["total"]["values"]["net_revenue"]==round(expected_v1-10,6)
    assert {m["key"]:m["expression"] for m in run2.result["metrics"]}["net_revenue"]=="revenue-refunds-10"
    db.expire_all()
    historical=db.get(ReportRun,run1.id)
    assert historical.result["total"]["values"]["net_revenue"]==round(expected_v1,6)
    assert historical.metric_version_id==v1.id

def test_scheduled_delivery_uses_latest_version(db):
    v1=seed_metrics(db)
    schedule=DeliverySchedule(name="渠道晨间校对",dimensions=["channel","month"],interval_minutes=1,next_run_at="2000-01-01T00:00:00+00:00",active=True,owner=ADMIN.name)
    db.add(schedule);db.flush()
    change=[dict(m,expression="revenue-refunds-5") if m["key"]=="net_revenue" else m for m in BASE_METRICS]
    publish_metrics(db,publish_payload(v1.id,change,"晨间改版"),ADMIN)
    schedule_due(db)
    run=db.query(ReportRun).filter_by(schedule_id=schedule.id).one()
    assert run.metric_version_id==current_version(db).id
    compute_run(db,run)
    assert run.result["total"]["values"]["net_revenue"]==round(3*(1000.0-100.0)-5,6)

def test_single_add_creates_version(db):
    seed_metrics(db)
    create_metric(db,MetricInput(key="net_per_order",name="每单净收入",expression="net_revenue/orders",unit="元/单",description="汇总净收入除以有效单数。"),ADMIN)
    assert live(db)["net_per_order"]=="net_revenue/orders"
    assert versions(db)==2
    defs=definitions_for_version(db,current_version(db).id)
    assert [d.key for d in defs]==["net_revenue","gross_profit","net_per_order"]
    legacy=definitions_for_version(db,None)
    assert [d.key for d in legacy]==["net_revenue","gross_profit","net_per_order"]
