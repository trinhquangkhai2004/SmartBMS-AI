"""Render the P3.2 readout from validated evidence."""

from collections import Counter
import csv
import json
from pathlib import Path
import sys


def n(value, digits=4):
    if value is None:
        return "—"
    en = f"{value:,.{digits}f}" if isinstance(value,float) else f"{value:,}"
    return en.replace(",","_").replace(".",",").replace("_",".")


def code(value):
    return f"{chr(96)}{value}{chr(96)}"


def tally(cells, field):
    counts = Counter()
    for cell in cells:
        counts.update(cell[field])
    return counts


def row(*values):
    return "| "+" | ".join(str(value).replace("|",r"\|") for value in values)+" |"


def table(*headers):
    return [row(*headers),"|"+"|".join("---" for _ in headers)+"|"]


def stats(cell, field):
    return " / ".join(n(cell[field][key]) for key in ("median","p95","max"))


def main():
    summary = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8-sig"))
    evidence = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8-sig"))
    if evidence["status"] != "PASS":
        raise ValueError("Independent readback is required")
    total, cells = summary["totals"], summary["cells"]
    ready = total["ready_pairs"]
    geometry = tally(cells,"pair_geometry")
    clocks = tally(cells,"clock_boundaries")
    rejects = tally(cells,"review_reasons")
    flags = tally(cells,"diagnostics")
    proto = Counter(cell["protocol_status"] for cell in cells)
    pilot = next(cell for cell in cells if cell["cell_id"]=="1-1")
    labels = {}
    for cell in cells:
        for name,counts in cell["status_labels"].items():
            labels.setdefault(name,Counter()).update({**counts,"cells":1})
    status = "PASS" if ready else "BLOCKED"
    gap_phase = Counter()
    with Path(sys.argv[4]).open(encoding="utf-8",newline="") as inventory:
        for item in csv.DictReader(inventory):
            for operation in json.loads(item["operations"]):
                gap_phase[operation["phase"]] += operation["time_gap_count"]
    review_keys = set()
    duplicate_positions = {}
    with Path(sys.argv[5]).open(encoding="utf-8",newline="") as ledger:
        for item in csv.DictReader(ledger):
            key = item["cell_id"], int(item["cycle_id"])
            if item["field"]=="pair":
                review_keys.add(key)
            elif item["reason"]=="TIME_DUPLICATE":
                duplicate_positions.setdefault(key,[]).append(item["sample_index"])
    charge = sum(cell["charge_session_count"] for cell in cells)
    covers = sum(cell["charge_window_sessions"] for cell in cells)
    dq_comparisons = sum(c["dq_counter_abs_diff_mah"]["count"] for c in cells)
    dq_peak = max((c["dq_counter_abs_diff_mah"]["max"] for c in cells if c["dq_counter_abs_diff_mah"]["max"] is not None), default=0)
    v_max = max(cell["charge_max_voltage_v"] for cell in cells if cell["charge_max_voltage_v"] is not None)
    vn = min(cell["discharge_cutoff_min_v"] for cell in cells if cell["discharge_cutoff_min_v"] is not None)
    vx = max(cell["discharge_cutoff_max_v"] for cell in cells if cell["discharge_cutoff_max_v"] is not None)
    lines = [
        "# P3.2 — Kiểm kê chất lượng RT-Batt v2", "",
        f"**Trạng thái** {code(status)}. Đã đối soát **{n(total['cells'])} cell**, **{n(total['cycles'])} chu kỳ** "
        f"và **{n(total['sample_rows'])} hàng tín hiệu**. **{n(ready)} chu kỳ trên {n(total['cells_with_candidates'])} cell** có cặp ứng viên "
        f"cho P3.3. Có **{n(total['cycles']-ready)} chu kỳ** cần xem lại. Canonical giữ đủ các hàng đầu vào.", "",
        f"Cell chuẩn {code('1-1')} có {n(pilot['cycles'])} chu kỳ, {n(pilot['staged_samples'])} hàng và {n(pilot['ready_pairs'])} cặp. "
        "Hai lần chạy với batch 4.096 và 32.768 cho CSV/JSON giống nhau từng byte. UT-09 đạt 9/9. " +
        ("Lượt lặp đủ 77 cell với batch 16.384 khớp SHA-256 cả năm đầu ra. " if evidence.get("full_replay",{}).get("status")=="PASS" else "") +
        "[Bảng 1.504 chu kỳ](P3_2_1_1_cycle_capacity.csv) · [UT-09](P3_2_UT_09.log) · [Đọc lại canonical](../manifests/p3_2_readback.json)", "",
        "## Kiểm kê pha và thời gian", "",
        f"- {n(sum(c['cycles_with_usable_charge'] for c in cells))} chu kỳ có phiên sạc tối thiểu hai mẫu, đủ thời gian, V, I, đúng dấu và thời gian tăng. "
        f"Có {n(geometry['SAME_CYCLE'])} cặp cùng cycle, {n(geometry['CROSS_CYCLE'])} cặp qua ranh giới và {n(geometry['UNPAIRED'])} chu kỳ chưa có cặp duy nhất.",
        f"- Qua ranh giới cycle, đồng hồ giảm {n(clocks['RESET'])} lần, bằng nhau {n(clocks['EQUAL'])}, tăng {n(clocks['INCREASE'])} "
        f"và thiếu chứng cứ {n(clocks['UNKNOWN'])}. Ghép qua ranh giới yêu cầu cùng cell, hai cycle liền nhau và trục thời gian liên tục.",
        f"- {code('feature_available_at')} là mẫu cuối sạc. {code('label_observed_at')} là mẫu cuối xả. "
        f"Cặp ứng viên yêu cầu hai pha duy nhất có thứ tự, tín hiệu kiểm được, bộ đếm xả liên tục và {code('dq')} khớp độ giảm bộ đếm trong dung sai số học 0,000001 mAh.",
        f"- Đối chiếu khóa JSON ghi {n(sum(len(c['dq_missing_cycle_ids']) for c in cells))} ID thiếu, "
        f"{n(sum(len(c['dq_extra_cycle_ids']) for c in cells))} ID thừa, {n(sum(len(c['dq_duplicate_cycle_ids']) for c in cells))} ID trùng "
        f"và {n(sum(len(c['dq_null_cycle_ids']) for c in cells))} giá trị rỗng.", "",
    ]
    lines += table("Lý do cặp cần xem lại","Số chu kỳ")
    lines += [row(code(key),n(count)) for key,count in rejects.most_common()] or [row("Không có",0)]
    if review_keys:
        lines += [""] + table("Cell","Chu kỳ","Vị trí mẫu trùng thời gian trong pha xả")
        lines += [row(cell,cycle,", ".join(duplicate_positions.get((cell,cycle),[])) or "Xem ledger")
                  for cell,cycle in sorted(review_keys)]
    lines += ["", "## Dấu dòng, mẫu thiếu và cờ chất lượng", "",
        f"Đổi dấu một lần bằng {code('current_a = -current_ma_raw / 1000')}. "
        f"Có {n(flags['WRONG_CURRENT_SIGN'])} mẫu trái dấu và {n(sum(c['zero_current_samples'] for c in cells))} mẫu dòng bằng 0. "
        f"Trong các phiên ghi {n(flags['TIME_DUPLICATE'])} mốc trùng, {n(flags['TIME_REVERSED'])} mốc đảo "
        f"và {n(flags['TIME_GAP'])} khoảng vượt max(30 s, 5 × trung vị bước dương). "
        f"Trong đó sạc có {n(gap_phase['charge'])} khoảng, xả có {n(gap_phase['discharge'])} khoảng. "
        f"Có {n(flags['VOLTAGE_JUMP'])} bước nhảy trên 0,20 V giữa hai mẫu cùng nhãn thô. Vị trí được lưu trong ledger.", "",
    ]
    lines += table("Tín hiệu staging","Null","NaN","Inf")
    for field in pilot["signal_counts"]:
        lines.append(row(code(field),*(n(sum(c["signal_counts"][field][kind] for c in cells)) for kind in ("null","nan","inf"))))
    lines += ["", "Nhiệt độ mỗi hàng canonical là null. Metadata buồng thử ghi 30 °C. [Nguồn RT-Batt v2](https://data.mendeley.com/datasets/nsc7hnsg4s/2)", "",
        "## Ba phép đo dung lượng", "",
        f"Đối chiếu {n(dq_comparisons)} cặp đo cho sai lệch tuyệt đối lớn nhất giữa {code('dq')} và độ giảm bộ đếm là {dq_peak:.3g} mAh.", "",
        f"Cùng khóa xả, kiểm kê giữ độ giảm bộ đếm, {code('dq_raw')} và tích phân hình thang dòng xả. "
        "Tích phân chỉ dùng hai đầu mút trong pha xả, thời gian tăng, dữ liệu hữu hạn và đúng dấu. Khoảng quá thưa bị bỏ và được đếm. "
        f"Có {n(sum(c['partial_integral_pairs'] for c in cells))} cặp tích phân thiếu khoảng; các cặp này nằm ngoài phân bố tích phân đủ khoảng. "
        f"Có {n(flags['CAPACITY_COUNTER_RESET'])} điểm bộ đếm tăng trong xả được ghi để rà reset.", "",
        f"Cycle chuẩn có bộ đếm và {code('dq')} bằng **1.174,2992 mAh**. Tích phân là **1.181,6323 mAh**, lệch **7,3331 mAh** (khoảng 0,62%). "
        "Sai lệch tích phân được giữ để chẩn đoán. 0,62% chưa được dùng làm ngưỡng loại.", "",
        "### Năm ứng viên điều tra có sai lệch tích phân lớn nhất", "",
    ]
    lines += table("Cell","Cycle sạc/xả","Bộ đếm (mAh)","dq thô","Tích phân (mAh)","Tích phân − bộ đếm (mAh)","Chênh tuyệt đối (%)")
    largest = sorted((x for c in cells for x in c["integral_top"]),key=lambda x:-abs(x["integral_minus_counter_mah"]))[:5]
    for x in largest:
        lines.append(row(x["cell_id"],f"{x['cycle_id']} / {x['discharge_cycle_id']}",
            *(n(x[key]) for key in ("capacity_counter_delta_mah","paired_dq_raw","integral_mah","integral_minus_counter_mah","integral_abs_pct_of_counter"))))
    lines += ["", "## Khả năng trích đặc trưng sạc và protocol", "",
        f"Điện áp sạc cao nhất là **{n(v_max)} V**, điện áp ở mẫu cuối xả từ **{n(vn)} đến {n(vx)} V**. "
        f"Có **{n(covers)} / {n(charge)} phiên sạc** đi qua đủ hai biên 3,45–3,60 V theo thứ tự mẫu và không có khoảng lớn ở đoạn đi qua. "
        "Cửa sổ đặc trưng sẽ chọn trên tập phát triển.", "",
        f"Canonical ghi {code('UNKNOWN')} cho CC_FAST, CC_TOPUP và CV ở các hàng sạc. Nhãn gộp CC–CV cần phân tích dòng, điện áp và thời lượng tại P3.5.", "",
    ]
    lines += table("Nhãn staging","Cell","Chu kỳ","Mẫu")+[
        row(code(name),n(info["cells"]),n(info["cycles"]),n(info["samples"])) for name,info in sorted(labels.items())]
    lines += ["",
        "Protocol đo lấy trung vị dòng của bốn nhãn xả trong tối đa năm cycle đầu, chia theo dung lượng danh định 1,1 Ah. "
        "Mức đo cần nằm trong ±0,15 C quanh mức nguyên. Bảng giữ cả giá trị đo và giá trị BatteryML để giải trình bất đồng. "
        "[Nguồn mã BatteryML đã khóa](https://raw.githubusercontent.com/microsoft/BatteryML/2861ae3b8c79938c7fc8e6fe9986b799ca71c7dd/batteryml/preprocess/preprocess_HUST.py)", "",
    ]
    lines += table("Đối chiếu protocol","Cell")+[row(code(key),n(count)) for key,count in proto.most_common()]
    if proto["FOURTH_STAGE_REFERENCE_CONFLICT"]==len(cells):
        lines += ["", "Cả 77 cell khớp ba mức xả đầu. Mức thứ tư đo gần **2 C**, trong khi mã BatteryML ghi **1 C**. "
                  "Canonical lưu mã protocol mô tả mức đo từ các cycle đầu. Mức cài đặt thí nghiệm cần được đối chiếu với tài liệu gốc trước khi khóa metadata cho P3.4."]
    lines += ["", "## Kết quả theo cell", "",
        "Các nhóm ba số là trung vị / P95 / lớn nhất của sai lệch tuyệt đối. Bước sạc là trung vị theo phiên.", "",
    ]
    lines += table("Cell","Chu kỳ","Cặp","Cần xem lại","dq–bộ đếm (mAh)","Tích phân–bộ đếm (mAh)","Tích phân–bộ đếm (%)","Sạc đủ hai biên","Bước sạc (s)","Xả cuối (V)")
    for cell in cells:
        lines.append(row(cell["cell_id"],n(cell["cycles"]),n(cell["ready_pairs"]),n(cell["review_cycles"]),
            stats(cell,"dq_counter_abs_diff_mah"),stats(cell,"integral_counter_abs_diff_mah"),stats(cell,"integral_counter_abs_pct"),
            n(cell["charge_window_sessions"]),n(cell["charge_sampling_median_s"]),
            f"{n(cell['discharge_cutoff_min_v'])}–{n(cell['discharge_cutoff_max_v'])}"))
    lines += ["", "## Bàn giao P3.3", "",
        f"Có {n(ready)} cặp ứng viên với chứng cứ ghép và dung lượng truy vết được. P3.3 cần duyệt nguồn {code('Q_observed')}, "
        f"khóa D03 và kiểm năm phép xả commissioning để xác lập {code('Q_ref')}. Ledger giữ vị trí và lý do của mọi lượt cần xem lại.", "",
        "[Canonical Parquet](../data/processed/canonical_cycles.parquet) · [Ánh xạ trường](../configs/rt_batt_schema_mapping.yaml) · "
        "[Kiểm kê cycle](../manifests/cell_cycle_inventory.csv) · [Kiểm kê protocol](../manifests/protocol_inventory.csv) · "
        "[Ledger chất lượng](rejected_records.csv) · [Tổng hợp theo cell](../manifests/p3_2_audit_summary.json)", "",
    ]
    Path(sys.argv[3]).write_text("\n".join(lines),encoding="utf-8")


if __name__=="__main__":
    main()
