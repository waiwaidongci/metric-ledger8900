from datetime import datetime,timedelta,timezone
from ..models import DeliverySchedule,ReportRun
from .report_service import queue,freeze_version
from .audit_service import log
def schedule_due(db):
    now=datetime.now(timezone.utc)
    due=db.query(DeliverySchedule).filter(DeliverySchedule.active.is_(True),DeliverySchedule.next_run_at<=now.isoformat()).all()
    for schedule in due:
        row=ReportRun(name=schedule.name+" · 定时交付",dimensions=schedule.dimensions,owner="scheduler",schedule_id=schedule.id,metric_version_id=freeze_version(db))
        db.add(row);db.flush()
        schedule.next_run_at=(now+timedelta(minutes=schedule.interval_minutes)).isoformat()
        log(db,"scheduler","schedule.due",schedule.id);db.commit()
        queue.rpush("metric:jobs",row.id)
