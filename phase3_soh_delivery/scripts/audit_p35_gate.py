"""Read-only audit of frozen p35-r1 signals and features. Render the D04 report appendices."""
from collections import Counter
from pathlib import Path
import hashlib
import json
import sys

import numpy as np
import pyarrow.compute as pc
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.build_p35_features import FOLD_HASH, SPLIT_HASH, SCHEMA, manifest
from src.soh.feature_extractor import FAST, TOP

PRIMARY = ("delta_q_350_358_ah", "q_cc_ah", "q_cv_ah", "q_cv_over_q_cc")
STAGING_SCHEMA = {"cell_id", "cycle_id", "cycle_source_order", "sample_index", "raw_status",
                  "time_s_raw", "voltage_v_raw", "current_ma_raw", "capacity_mah_raw"}
MARKER = "## Đối soát bổ sung cho D04"


def verify(condition, message):
    if not condition:
        raise ValueError(message)


def scan_cell(cell, table):
    path = ROOT / "data/staging/rt_batt_v2" / f"{cell}.parquet"
    verify(set(pq.read_schema(path).names) == STAGING_SCHEMA, f"Inspect staging channels: {cell}")
    charges = pq.read_table(path, columns=["cell_id", "cycle_id", "raw_status", "voltage_v_raw",
                                          "current_ma_raw", "time_s_raw", "sample_index"],
                            filters=[("raw_status", "in", [FAST, TOP])])
    verify(charges["cell_id"].unique().to_pylist() == [cell], f"Signal ID mismatch: {cell}")
    cycle = charges["cycle_id"].to_numpy()
    fast = pc.equal(charges["raw_status"], FAST).to_numpy(zero_copy_only=False)
    amps = charges["current_ma_raw"].to_numpy() / 1000
    volts = charges["voltage_v_raw"].to_numpy()
    times = charges["time_s_raw"].to_numpy()
    samples = charges["sample_index"].to_numpy()
    ends = dict(zip(table["cycle_id"].to_pylist(), table["end_charge_sample_index"].to_pylist()))
    verify(len(ends) == len(table), f"Duplicate keys: {cell}")
    counts = Counter()
    max_dev = np.zeros(3)
    edges = np.r_[0, np.flatnonzero(np.diff(cycle)) + 1, len(cycle)]
    for a, b in zip(edges[:-1], edges[1:]):
        key = int(cycle[a])
        if key not in ends:
            continue
        verify(ends.pop(key) == samples[b-1], f"Charge endpoint: {cell}/{key}")
        counts["rows"] += 1
        cut = a + np.count_nonzero(fast[a:b])
        verify(a+2 <= cut < b and fast[a:cut].all() and not fast[cut:b].any(), f"Stage order: {cell}/{key}")
        top_i, top_v = amps[cut:b], volts[cut:b]
        entry = np.flatnonzero((np.abs(top_v-3.6) <= 0.005) & (top_i <= 0.98*1.1))
        verify(len(entry) and 2 <= entry[0] <= b-cut-3, f"Unresolved CV: {cell}/{key}")
        cv = cut + entry[0]
        deviations = [np.max(np.abs(amps[a:cut]-5.5)), np.max(np.abs(amps[cut:cv]-1.1)),
                      np.max(np.abs(volts[cv:b]-3.6))]
        max_dev = np.maximum(max_dev, deviations)
        for label, deviation, tolerance in zip(("fast", "topup", "cv"), deviations, (.165, .055, .005)):
            counts[label] += int(deviation > tolerance)
        # Raw IC quotient dQ/dV on contiguous low-current CC intervals before CV.
        dv = np.diff(volts[cut:cv])
        dq = np.diff(times[cut:cv]) * (amps[cut+1:cv]+amps[cut:cv-1]) / 7200
        flat = (dv == 0) & (dq > 0)
        counts["cc_intervals"] += len(dv)
        counts["flat_positive_q"] += int(flat.sum())
        counts["sessions_flat_positive_q"] += int(flat.any())
        counts["decreasing_v"] += int((dv < 0).sum())
    verify(not ends, f"Unmatched feature keys: {cell}")
    reasons = [json.loads(v) for v in table["missing_reasons"].to_pylist()]
    available = []
    missing = []
    for name in PRIMARY:
        valid = np.isfinite(table[name].to_numpy())
        verify(int((~valid).sum()) == table[name].null_count, f"Nonfinite value: {cell}/{name}")
        distribution = Counter()
        for ok, why in zip(valid, reasons):
            verify(ok == (name not in why), f"Inconsistent missing reason: {cell}/{name}")
            if not ok:
                distribution[why[name]] += 1
        available.append(int(valid.sum()))
        missing.append(distribution)
    return counts, max_dev, available, missing


def append_section(filename, body):
    path = ROOT / "reports" / filename
    original = path.read_text(encoding="utf-8").split(MARKER, 1)[0].rstrip()
    path.write_text(f"{original}\n\n{MARKER}\n\n{body.strip()}\n", encoding="utf-8")


def audit_reports():
    dev = manifest("p3_split_manifest.json", SPLIT_HASH)["development_cell_ids"]
    folds = manifest("p3_cv_fold_manifest.json", FOLD_HASH)["folds"]
    fold_for = {c: f["fold"] for f in folds for c in f["validation_cell_ids"]}
    verify(len(dev) == len(set(dev)) == 57 and set(dev) == set(fold_for), "Frozen development set mismatch")
    path = ROOT / "data/features/soh_feature_table.parquet"
    verify(hashlib.sha256(path.read_bytes()).hexdigest() ==
           "1fd788eb75a1045f4d28ad6b87c87f3e93bf6ef2b3aa1884dd11cda338527188", "Feature table changed")
    data = pq.ParquetFile(path)
    verify(data.schema_arrow == SCHEMA, "Offline feature schema changed")
    stats = {}
    for idx in range(data.num_row_groups):
        table = data.read_row_group(idx)
        cells = table["cell_id"].unique().to_pylist()
        verify(len(cells) == 1 and cells[0] in dev and cells[0] not in stats, "Unexpected feature row group")
        cell = cells[0]
        verify(table["validation_fold"].unique().to_pylist() == [fold_for[cell]], f"Wrong fold: {cell}")
        stats[cell] = scan_cell(cell, table)
    verify(set(stats) == set(dev), "Incomplete development coverage")
    total = sum((x[0] for x in stats.values()), Counter())
    verify(total["rows"] == 106733, "Row count changed")
    lines = ["Mẫu số là số phiên đủ điều kiện nhãn v1 của từng nhóm. Bốn cột HI ghi số hữu hạn và tỷ lệ. "
             "Cột thiếu ghi phân bố mã lý do theo đúng thứ tự bốn HI (0 = không có giá trị thiếu). "
             "Đã đối chiếu từng trường null với mã riêng trong missing_reasons trên từng hàng. "
             "Ba số cuối đếm số phiên có ít nhất một mẫu vượt ngưỡng CC nhanh / CC top-up / CV.",
             "", "| Nhóm | Phiên | " + " | ".join(PRIMARY) + " | Lý do thiếu theo HI | Phiên vượt ngưỡng |",
             "|---|---:|---:|---:|---:|---:|---|---|"]

    def row(label, members):
        items = [stats[c] for c in members]
        counters = sum((x[0] for x in items), Counter())
        n = counters["rows"]
        rates, reasons = [], []
        for j in range(len(PRIMARY)):
            valid = sum(x[2][j] for x in items)
            rates.append(f"{valid} ({100*valid/n:.2f}%)")
            dist = sum((x[3][j] for x in items), Counter())
            reasons.append(", ".join(f"{k} × {v}" for k, v in sorted(dist.items())) or "0")
        breaches = " / ".join(str(counters[k]) for k in ("fast", "topup", "cv"))
        lines.append("| " + " | ".join([label, str(n), *rates, " / ".join(reasons), breaches]) + " |")

    row("Toàn dev", dev)
    for f in folds:
        row(f"Validation {f['fold']}", f["validation_cell_ids"])
    for cell in dev:
        row(f"{cell} (fold {fold_for[cell]})", [cell])
    fast, top, cv = np.max([x[1] for x in stats.values()], axis=0)
    ic_cells = sum(x[0]["flat_positive_q"] > 0 for x in stats.values())
    lines.extend(["", "### Ngưỡng tách pha", "",
                  f"Trên {total['rows']} phiên đã xác định được điểm vào CV, độ lệch tuyệt đối lớn nhất của "
                  f"một mẫu so với 5,5 A là {fast:.6f} A (ngưỡng 0,165 A), so với 1,1 A là {top:.6f} A "
                  f"(ngưỡng 0,055 A) và so với 3,6 V ở đuôi CV là {1000*cv:.6f} mV (ngưỡng 5 mV). "
                  "Quét toàn bộ mẫu của từng đoạn. Điểm vào CV là mẫu đầu đoạn dòng thấp thỏa đồng thời "
                  "|V−3,6| ≤ 0,005 V và I ≤ 1,078 A theo độ lớn. "
                  "Ngưỡng nhanh ảnh hưởng q_cc_ah và tỷ số. Hai ngưỡng top-up/CV còn ảnh hưởng q_cv_ah. "
                  "Điện lượng cửa sổ dùng riêng đoạn CC–CV dòng thấp và hai biên điện áp, độc lập với ba phép thử này. "
                  "Mẫu số ở đây chỉ gồm các phiên đủ điều kiện v1.", "",
                  "### Bằng chứng loại IC và thermal khỏi v1", "",
                  f"IC_NOT_RELIABLE: xét {total['cc_intervals']} khoảng giữa hai mẫu liên tiếp trong CC top-up. "
                  f"{total['flat_positive_q']} khoảng có ΔV = 0 dù ΔQ > 0, trải trên "
                  f"{total['sessions_flat_positive_q']} phiên và {ic_cells} cell. "
                  f"{total['decreasing_v']} khoảng có ΔV < 0. Thương ΔQ/ΔV thô không xác định ở các khoảng phẳng. "
                  "Chưa có kiểm định độ lặp lại của đỉnh IC sau làm trơn hoặc chia bin điện áp.", "",
                  "Thermal: đã đọc schema từng tệp staging của 57/57 cell dev. Các kênh đo là "
                  "time_s_raw, voltage_v_raw, current_ma_raw, capacity_mah_raw. Không có chuỗi nhiệt độ theo mẫu. "
                  "30 °C là nhiệt độ buồng trong metadata. Schema v1 loại cả đặc trưng IC và thermal."])
    append_section("P3_5_FEATURE_AVAILABILITY.md", "\n".join(lines))
    append_section("P3_5_FEATURE_LEAKAGE.md",
                   "UT-010 (UT-10) đối chiếu phiên ở hàng giữa của cell validation đầu tiên trong mỗi fold "
                   "(5 phiên thực, 5 cell, 5 fold). Với từng phiên, đọc riêng các mẫu sạc từ đúng tệp cell dev, "
                   "đổi mA thô sang A theo quy ước sạc âm và gọi hàm inference. Kiểm bằng phép so sánh chính xác "
                   "cả 12 HI với bản offline, cùng mã lý do thiếu và chỉ số mẫu cuối. Xem log reports/P3_5_UT_010.log "
                   "và tests/test_p35.py. Đây là kiểm tra tương đương hai đường gọi trên các phiên đã chọn.\n\n"
                   "Đối soát độ phủ độc lập giới hạn truy cập bằng SHA-256 của split/fold và danh sách development. "
                   "Từng hàng trong 106.733 hàng khớp cell, fold và mốc kết thúc sạc trong trace. Bộ kiểm độ phủ "
                   "chỉ đọc bảng feature development và các cột tín hiệu/khóa của 57 tệp staging development. "
                   "Trạng thái P3.7 là UNOPENED. Điểm CV dùng chọn cửa sổ là điểm phát triển nội bộ.")
    print(dict(total), "max deviations", fast, top, cv)


if __name__ == "__main__":
    audit_reports()
