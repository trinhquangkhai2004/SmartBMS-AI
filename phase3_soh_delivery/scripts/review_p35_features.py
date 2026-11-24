"""Audit p35-r1 availability and compare fully observed windows using development cells only."""
from pathlib import Path
import hashlib
import json
import sys
import numpy as np
import pyarrow.parquet as pq

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.build_p35_features import SPLIT_HASH, FOLD_HASH, SCHEMA, manifest, REVIEW
from scripts.audit_p35_gate import audit_reports
from src.soh.feature_extractor import BAND_NAMES, BANDS, STAGE_NAMES, FEATURE_NAMES, FAST, TOP, extract_charge


def save(path, content):
    p=ROOT/path
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(content,encoding="utf-8")


def evaluate(x, y, group, fold):
    errors=[]
    fold_scores=[]
    for k in range(1,6):
        train=fold!=k
        val=~train
        # Equal cell weight across the fitting set. Fit scale, offset and coefficients only on train.
        freq=np.bincount(group[train])
        w=1.0/freq[group[train]]
        w*=len(w)/w.sum()
        avg=np.average(x[train],axis=0,weights=w)
        scale=np.sqrt(np.average((x[train]-avg)**2,axis=0,weights=w))
        scale[scale==0]=1
        a=(x[train]-avg)/scale
        center=np.average(y[train],weights=w)
        coef=np.linalg.solve(a.T@(w[:,None]*a)+np.eye(x.shape[1]),a.T@(w*(y[train]-center)))
        err=np.abs((x[val]-avg)/scale@coef+center-y[val])
        scores=[float(np.mean(err[group[val]==g])) for g in np.unique(group[val])]
        errors.extend(scores)
        fold_scores.append(float(np.mean(scores)))
    return float(np.mean(errors)),fold_scores


def main():
    ids=manifest("p3_split_manifest.json",SPLIT_HASH)["development_cell_ids"]
    assert len(ids)==len(set(ids))==57
    folds=manifest("p3_cv_fold_manifest.json",FOLD_HASH)["folds"]
    fidx={c:f["fold"] for f in folds for c in f["validation_cell_ids"]}
    p=ROOT/"data/features/soh_feature_table.parquet"
    tab=pq.read_table(p)
    assert tab.schema==SCHEMA and tab.num_rows==106733
    cells=np.asarray(tab["cell_id"].to_pylist())
    assert set(cells)==set(ids)
    cycles=tab["cycle_id"].to_numpy()
    groups=np.zeros(len(cells),int)
    fold=tab["validation_fold"].to_numpy()
    y=np.empty(len(cells))
    for g,cell in enumerate(ids):
        mask=cells==cell
        summary=json.loads((ROOT/f"data/staging/rt_batt_v2/{cell}.json").read_bytes())
        assert summary["cell_id"]==cell
        q={r["cycle_id"]:r["value"] for r in summary["dq_by_cycle_raw"]}
        expected={k for k in q if k>5 and (cell,k) not in REVIEW}
        assert len(expected)==mask.sum() and set(cycles[mask])==expected and np.all(fold[mask]==fidx[cell])
        groups[mask]=g
        # Offline evaluation only. Never pass these values to the feature extractor.
        ref=np.median([q[k] for k in range(1,6)])
        y[mask]=[100*q[k]/ref for k in cycles[mask]]
    values={n:tab[n].to_numpy() for n in FEATURE_NAMES}
    base=["q_cc_ah","q_cv_ah","q_cv_over_q_cc"]
    scores={}
    for band in BAND_NAMES:
        cols=base+[band]
        x=np.column_stack([values[n] for n in cols])
        if np.isfinite(x).all():
            scores[band]=evaluate(x,y,groups,fold)
    if not scores: raise ValueError("No complete development window")
    best=min(scores,key=lambda n:scores[n][0])
    primary=[best]+base
    # Independent runtime parity with one complete real charge from a development cell.
    probe=ids[0]
    i=int(np.flatnonzero(cells==probe)[0])
    source=pq.read_table(ROOT/f"data/staging/rt_batt_v2/{probe}.parquet",columns=["time_s_raw","voltage_v_raw","current_ma_raw","raw_status","sample_index"],
        filters=[("cycle_id","=",int(cycles[i])),("raw_status","in",[FAST,TOP])])
    assert source["sample_index"][-1].as_py()==tab["end_charge_sample_index"][i].as_py()
    rt,why=extract_charge(source["time_s_raw"].to_numpy(),source["voltage_v_raw"].to_numpy(),-source["current_ma_raw"].to_numpy()/1000,source["raw_status"].to_pylist())
    assert all(rt[n]==tab[n][i].as_py() for n in FEATURE_NAMES) and why==json.loads(tab["missing_reasons"][i].as_py())

    desc={name:("Điện lượng sạc"+" trong đoạn sạc dòng thấp CC–CV, nội suy tuyến tính biên điện áp và dòng.", "Ah") for name in BAND_NAMES}
    desc.update({
        "q_cc_fast_ah":("Tích phân dòng sạc dương theo độ lớn trên đoạn CC nhanh đã kiểm.","Ah"),
        "q_cc_topup_ah":("Tích phân trên đoạn CC dòng thấp trước mẫu đầu của CV đã kiểm.","Ah"),
        "q_cc_ah":("Tổng q_cc_fast_ah và q_cc_topup_ah.","Ah"),
        "q_cv_ah":("Tích phân từ mẫu đầu CV đã xác minh tới cuối sạc.","Ah"),
        "q_cv_over_q_cc":("q_cv_ah / q_cc_ah khi mẫu số > 1e-8 Ah.","1"),
        "q_cv_fraction_total":("q_cv_ah / (q_cv_ah + q_cc_ah) trên các khoảng quan sát được.","1"),
        "cv_duration_s":("Thời điểm mẫu cuối trừ mẫu đầu CV.","s"),
        "charge_duration_s":("Thời điểm cuối trừ đầu sạc. Biến đối chứng.","s"),
        "start_charge_voltage_v":("Điện áp mẫu sạc đầu tiên. Biến đối chứng.","V")})
    features=[]
    for name in FEATURE_NAMES:
        band=BANDS[BAND_NAMES.index(name)] if name in BAND_NAMES else None
        features.append(dict(name=name,units=desc[name][1],formula=desc[name][0],voltage_band=band,
                            charge_stage="CC_TOPUP/CV" if band else ("see_formula"),available_at="end_of_valid_charge",
                            missing_rule="null with feature-specific reason; preserve row",
                            source_schema_version="p3.2-rt-batt-v1",required=name in primary))
    schema={"version":"p35-r1","primary_features":primary,"features":features,
            "key_columns":["cell_id","cycle_id","validation_fold","end_charge_sample_index"],
            "optional_time_ablation":["charge_duration_s","start_charge_voltage_v"],
            "omitted_modes":["thermal: no measured channel","IC: not qualified for plateau derivatives","commissioning_relative_hi: not enabled"]}
    save("artifacts/soh/feature_schema.json",json.dumps(schema,ensure_ascii=False,indent=2)+"\n")
    save("configs/p3_feature_policy.yaml",f"""revision: p35-r1
domain: RT-Batt v2
split_revision: p34-r1
split_sha256: {SPLIT_HASH}
fold_sha256: {FOLD_HASH}
mode: zero_commissioning_features
selection: complete_dev_coverage_then_lowest_macro_cell_mae_fixed_ridge_group_cv
primary: [{', '.join(primary)}]
band_phase: lower_current_combined_charge_segment
bands_v: [[3.45,3.55],[3.50,3.58],[3.45,3.60]]
integration: piecewise_linear_current_and_voltage_trapezoid
max_gap_s: max(30 seconds, 5 times median positive charge dt)
cc_fast_a: 5.5
cc_fast_tolerance_a: 0.165
cc_topup_a: 1.1
cc_topup_tolerance_a: 0.055
cv_target_v: 3.6
cv_tolerance_v: 0.005
cv_entry_max_fraction_topup_current: 0.98
cv_final_max_fraction_entry_current: 0.5
cv_minimum_nonincreasing_step_fraction_with_0_01a_slack: 0.9
ratio_epsilon_ah: 1.0e-8
unknown_transition_intervals: omit_from_stage_integrals
missing: null_and_reason
training_imputation: train_fold_only_if_needed
""")
    lines=["# P3.5 — Cửa sổ điện áp và phân đoạn sạc","","Miền kiểm tra gồm 57 cell development, 106.733 phiên đủ điều kiện nhãn. Mỗi cửa sổ áp dụng cho đoạn sạc dòng thấp có nhãn CC–CV. Tích phân hình thang chia đoạn tuyến tính tại hai biên V. Yêu cầu quan sát cả hai biên trên đoạn này.","",
          "| Cửa sổ (V) | Số phiên đủ | Macro-MAE theo cell (điểm %) | MAE trung bình theo cell ở fold 1–5 |","|---|---:|---:|---|"]
    for n,b in zip(BAND_NAMES,BANDS):
        score,folds_mae=scores.get(n,(None,[]))
        lines.append(f"| {b[0]:.2f}–{b[1]:.2f} | {np.isfinite(values[n]).sum()} | "+(f"{score:.4f}" if score is not None else "Thiếu độ phủ để so sánh cùng mẫu")+ " | "+", ".join(f"{v:.4f}" for v in folds_mae)+" |")
    lines+=["",f"Cửa sổ chọn cho v1 là {best}. Đối chiếu dùng Ridge chẩn đoán cố định alpha=1 cùng ba HI CC/CV, chuẩn hóa trên fold train và tổng trọng số ngang nhau theo cell. MAE tính riêng từng cell ngoài fold rồi lấy trung bình. Đây là điểm chọn cửa sổ trên development; ước lượng độ chính xác cuối cùng thuộc P3.7.","",
            "Pha CC nhanh và top-up yêu cầu plateau dòng quanh 5,5 A và 1,1 A. CV yêu cầu điện áp quanh 3,6 V cùng dòng suy giảm tới tối đa nửa dòng đầu CV. Mỗi đoạn tích phân chỉ dùng các khoảng đo trong cùng pha. Khe thời gian giữa hai nhãn sạc và khoảng giáp ranh CC/CV chưa phân loại bị bỏ; q_cc và q_cv mô tả phần điện lượng quan sát được. Điện lượng cửa sổ phản ánh riêng phần sạc dòng thấp. Các ngưỡng phân pha là quy tắc thực nghiệm cho RT-Batt, chưa có chuẩn pha độc lập hay xác minh trên Lishen."]
    save("reports/P3_5_HI_WINDOW_AUDIT.md","\n".join(lines)+"\n")
    lines=["# P3.5 — Độ phủ đặc trưng development","","Tử số là số phiên có giá trị hữu hạn. Mẫu số toàn development là 106.733. Các fold dưới đây là validation.","","| HI | Toàn dev | Fold 1 | Fold 2 | Fold 3 | Fold 4 | Fold 5 |","|---|---:|---:|---:|---:|---:|---:|"]
    for n in FEATURE_NAMES:
        ok=np.isfinite(values[n]);lines.append("| "+n+" | "+str(ok.sum())+" | "+" | ".join(f"{(ok&(fold==k)).sum()}/{(fold==k).sum()}" for k in range(1,6))+" |")
    lines+=["","Tất cả phiên được giữ trong bảng. Từng giá trị thiếu có lý do trong missing_reasons. Số lượng theo cell và fold có tại manifests/p3_5_development_audit.json. Nhiệt độ buồng 30 °C chỉ là metadata. Đặc trưng dQ/dV và commissioning-relative chưa đủ bằng chứng để bật trong v1."]
    save("reports/P3_5_FEATURE_AVAILABILITY.md","\n".join(lines)+"\n")
    save("reports/P3_5_FEATURE_LEAKAGE.md",f"""# P3.5 — Kiểm tra đầu vào và thời điểm khả dụng

Bảng đầu ra có {len(cycles)} khóa cell–cycle duy nhất trên {len(ids)} cell thuộc development. Mỗi cell được kiểm tra theo danh sách cho phép đã khóa trước khi mở tệp vật lý. Chỉ tệp Parquet riêng theo ID development được đọc để tính đặc trưng. Các cột thời gian, V, I và nhãn trạng thái được chọn trên hàng sạc. Hàm dùng chung nhận tín hiệu sạc đến cuối phiên và từ chối trạng thái xả. ID, fold và chỉ số cuối phiên là metadata.

Nhãn dùng để so sánh cửa sổ được tính riêng từ JSON của từng cell development theo D02/D03. Khóa được đối chiếu đủ sau năm cycle khởi tạo và các loại trừ đã ghi ở P3.2. Q_ref, dung lượng xả, nhãn, số thứ tự cycle và thống kê tương lai đều nằm ngoài vector đặc trưng. Chuẩn hóa và fit Ridge chỉ dùng cell train trong mỗi fold. Chính sách phục vụ P3.6 phải giữ việc fit imputer, scaler và selector riêng theo train fold.

Đọc lại toàn bộ bảng đã kiểm tra schema, số hàng, khóa và fold. Ca runtime đối chiếu chính xác với bảng offline trên cell {probe}, cycle {cycles[i]}, cả giá trị và lý do thiếu. SHA-256 bảng đặc trưng: `{hashlib.sha256(p.read_bytes()).hexdigest()}`. Đánh giá P3.7: UNOPENED.
""")
    audit_reports()
    print(best,scores)
if __name__=="__main__":
    main()
