-- 指标版本化：metric_versions / metric_definitions 新表由 SQLAlchemy metadata 自动创建。
-- 既有部署需为 report_runs 补列；首次发布或排队报表时，既有 metrics 会固化为“基线版本”。
ALTER TABLE report_runs ADD COLUMN IF NOT EXISTS metric_version_id INTEGER REFERENCES metric_versions(id);
CREATE INDEX IF NOT EXISTS metric_definitions_version_idx ON metric_definitions (version_id,position);
