# SmartBMS-AI (PBL5)

Software, SoC estimation (Phase 2), and SoH estimation (Phase 3) repository for the PBL5 Smart BMS project.

## Structure

- phase1_bms_software/ — FastAPI + SQLite telemetry ingestion backend, deterministic JSONL replay CLI, and Streamlit monitoring dashboard.
- phase2_soc_delivery/ — Phase 2 SoC estimation (Coulomb Counting + ECM/EKF), calibrated OCV/ECM artifacts, governance records, and evaluation scripts/tests.
- phase3_soh_delivery/ — Phase 3 SoH estimation (RT-Batt v2 LFP 30 °C), F3.1–F3.4 inference pipeline, frozen EvaluationGuard, F3 → F5 adapter, JSON Schema contract, conversion Dockerfile (D11), verification scripts, manifests, decisions, and reports.

## Large Datasets & Binary Artifacts

Raw datasets (RT-Batt v2 our_data.zip, DOI 10.17632/nsc7hnsg4s.2), staging/processed Parquet tables, trajectory .csv.gz archives, virtual environments, and .joblib model binaries are intentionally excluded from Git history to keep the repository lightweight. Reproducibility metadata and SHA-256 checksums are preserved under each phase's manifests/ and rtifacts/ directories.
