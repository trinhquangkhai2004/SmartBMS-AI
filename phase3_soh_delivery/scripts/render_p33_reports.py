"""Render P3.3 reviewer reports from validated draft artifacts."""

from collections import Counter
import json
from pathlib import Path
import sys


TICK = chr(96)


def code(value):
    return f"{TICK}{value}{TICK}"


def fmt(value, decimals=6):
    if value is None:
        return "—"
    formatted = f"{value:,.{decimals}f}" if isinstance(value,float) else f"{value:,}"
    return formatted.replace(",","_").replace(".",",").replace("_",".")


def row(*values):
    return "| "+" | ".join(str(value).replace("|",r"\|") for value in values)+" |"


def table(*headings):
    return [row(*headings),"|" + "|".join("---" for _ in headings) + "|"]


def interval(pair):
    numbers = [record["discharge_last_voltage_v"] for record in pair if record["discharge_last_voltage_v"] is not None]
    return f"{fmt(min(numbers),4)} đến {fmt(max(numbers),4)} V" if numbers else "—"


def event_label(point):
    if point is None:
        return "—"
    return f"cycle {point['cycle_id']}, mẫu {point['sample_index']}, {fmt(point['time_s_raw'],1)} s cục bộ"


def make_commissioning(summary):
    cells = summary["cells"]
    baseline = next(cell for cell in cells if cell["cell_id"]=="1-1")
    contested = next(cell for cell in cells if cell["cell_id"]=="7-5")
    blocked = [cell for cell in cells if cell["status"]=="QREF_COMMISSIONING_BLOCKED"]
    base = baseline["reference_probe_cycle_6"]
    early = contested["early_trace_records"]
    out = [
        "# P3.3 — Hồ sơ commissioning Q_ref", "",
        "**Trạng thái** Dự thảo trình duyệt D02/D03. Có "
        f"**{fmt(summary['totals']['cells_with_provisional_reference'])} / {fmt(summary['totals']['cells'])} cell** có Q_ref theo quy tắc đề xuất, "
        f"{fmt(len(blocked))} cell cần quyết định của reviewer.", "",
        "## Quy tắc trình duyệt", "",
        "- Kiểm đúng năm phép xả đầu theo thứ tự nguồn. Cửa sổ đang xét là cycle 1–5. "
        "Chu kỳ thiếu, trùng khóa, lỗi cặp hoặc trace mơ hồ đưa cell vào diện review.",
        "- Đối chiếu đúng bốn mức dòng xả và thứ tự nhãn với mô tả đo ở P3.2, trong dung sai so sánh "
        "0,15 C của audit P3.2. Kiểm nhịp lấy mẫu và những điểm tăng bộ đếm trong pha xả. "
        "Kiểm dung lượng bằng dq theo khóa cycle và độ giảm bộ đếm mAh. Tích phân dòng là chỉ số chẩn đoán.",
        "- Ghi điện áp ở mẫu cuối xả. Mã BatteryML ghi cutoff cài đặt 2,0 V. Điện áp mẫu cuối của từng phép xả được báo riêng "
        "và chưa có ngưỡng sai lệch chung để loại tự động. 30 °C là metadata buồng thử. Staging thiếu kênh nhiệt độ từng mẫu.",
        "- Trung vị lấy từ năm dung lượng xả hiển thị bên dưới. Q_ref chỉ có sau mẫu cuối xả thứ năm. "
        "Độ trải tương đối tính (max − min) / median × 100. Cột độ trải để reviewer đánh giá.",
        "", "## Ca chuẩn cell 1-1", "",
        f"Q_ref = **{fmt(base['q_ref_ah'],14)} Ah**. Mốc đủ tham chiếu là {event_label(baseline['qref_available_at'])}. "
        f"Cycle 6 dùng **{fmt(base['q_observed_ah'],14)} Ah** và cho **{fmt(base['soh_ref_percent'],6)}%**. "
        "Các phiên sạc cycle 1–5 thuộc giai đoạn khởi tạo.", "",
        "## Cell 7-5 cần quyết định riêng", "",
        "BatteryML bỏ cycle 1–2 khi tiền xử lý HUST_7-5. Bảng dưới đối chiếu trực tiếp bảy chu kỳ đầu từ staging. "
        "[Mã BatteryML đã khóa]("+summary["batteryml_7_5_reference"]+")", "",
    ]
    out += table("Cycle","Mẫu sạc/xả","Thời lượng sạc (s)","Bước sạc trung vị / lớn nhất (s)",
                 "Bước xả trung vị / lớn nhất (s)","Mức xả (C)","V cuối xả","dq (mAh)","Tích phân − bộ đếm (mAh)","Chỉ số mẫu xả")
    for item in early:
        trace = item["trace_discharge_samples"]
        rates = item["rates_measured_c"]
        out.append(row(item["cycle_id"],f"{fmt(item['charge_samples'])} / {fmt(item['discharge_samples'])}",
            fmt(item["charge_duration_s"],1),f"{fmt(item['charge_median_step_s'],1)} / {fmt(item['charge_max_step_s'],1)}",
            f"{fmt(item['discharge_median_step_s'],1)} / {fmt(item['discharge_max_step_s'],1)}",
            " / ".join(fmt(rate,3) for rate in rates) if rates else "—",
            fmt(item["discharge_last_voltage_v"],4),fmt(item["q_dq_mah"]),fmt(item["integral_minus_counter_mah"],4),
            f"{trace[0]}–{trace[1]}" if trace else "—"))
    cycle2 = early[1]
    current_window = early[2:5]
    if cycle2["charge_duration_s"] and all(r["charge_duration_s"] is not None for r in current_window):
        durations = [item["charge_duration_s"] for item in current_window]
        out += ["",f"Cycle 2 có pha sạc dài **{fmt(cycle2['charge_duration_s'],1)} s**, so với {fmt(min(durations),1)}–"
                f"{fmt(max(durations),1)} s ở cycle 3–5. Điện áp mẫu cuối xả của cycle 1–2 nằm trong "
                f"khoảng {interval(early[:2])}. Nhóm cycle 3–5 có khoảng {interval(current_window)}. "
                "Bốn mức dòng xả gần cùng profile và trung vị bước xả là 5 s ở các cycle đã kiểm. "
                "Các phép xả ghép theo D03 vẫn có dấu vết dung lượng.", ""]
    out += [
        f"Giữ {code('QREF_COMMISSIONING_BLOCKED')} với lý do {code('BATTERYML_EARLY_CYCLE_REVIEW')}. "
        f"Trung vị theo cửa sổ 1–5 là **{fmt(contested['window_median_for_review_ah'],12)} Ah** để đối chiếu. "
        "Hồ sơ trình duyệt giữ nguyên cửa sổ giả định 1–5. Nếu reviewer chọn 3–7, cần ghi quyết định thay đổi, "
        "giá trị Q_ref và mốc khả dụng tương ứng từ xả thứ bảy.", "",
        "## Hồ sơ từng cell", "",
        "Năm giá trị mAh dưới đây tính từ dq đã kiểm. Giá trị đầy đủ, trạng thái profile, số mẫu và chỉ số của từng trace "
        "được lưu trong [manifest commissioning và nhãn](../manifests/p3_3_audit_summary.json).", "",
    ]
    out += table("Cell","Cycle đầu","Năm dung lượng (mAh)","Q_ref dự thảo (Ah)","Min / max (Ah)",
                 "Độ trải (%)","Mẫu cuối xả (V)","Có tham chiếu tại","Trạng thái / lý do")
    for cell in cells:
        out.append(row(cell["cell_id"],", ".join(map(str,cell["source_cycle_ids"])),
            " / ".join(fmt(q*1000,6) if q is not None else "—" for q in cell["early_discharge_ah"]),
            fmt(cell["q_ref_ah"],12),f"{fmt(cell['min_ah'],9)} / {fmt(cell['max_ah'],9)}",
            fmt(cell["relative_spread_percent"],5),interval(cell["early_trace_records"][:5]),
            event_label(cell["qref_available_at"]),", ".join(map(code,cell["reasons"])) or code(cell["status"])))
    out += ["", "[Chính sách dự thảo](../configs/p3_soh_reference_policy.yaml) · [Kiểm định bảng nhãn](P3_3_LABEL_AUDIT.md)", ""]
    return "\n".join(out)


def make_label_audit(summary):
    total = summary["totals"]
    cases = total["disposition"]
    benchmark = total["d03_pairs"] - 5 * total["cells"]
    diff = benchmark - total["labels"]
    out = [
        "# P3.3 — Kiểm định nhãn SoH dự thảo", "",
        f"Đã đọc lại **{fmt(total['source_cycles'])} khóa truy vết** trên **{fmt(total['cells'])} cell**. "
        f"Có **{fmt(total['d03_pairs'])} cặp** đạt quy tắc D03 đề xuất và **{fmt(total['labels'])} nhãn dự thảo** "
        f"sau commissioning. Trạng thái phát hành {code(summary['release_status'])}.", "",
        "## Nguồn dung lượng và trật tự sự kiện", "",
        "- Dự đoán đứng tại mẫu cuối sạc. Nhãn dùng dq của lần xả kế tiếp duy nhất cùng cell, cùng cycle trong RT-Batt v2. "
        "Mốc biết dung lượng là mẫu cuối xả.",
        "- Q_observed_ah bằng paired_dq_raw chia 1000. Độ giảm bộ đếm xác minh đơn vị mAh. Tích phân dòng–thời gian để chẩn đoán.",
        "- Các sự kiện giữa chu kỳ được so bằng (cycle_source_order, sample_index). "
        "Giây nguồn chỉ so trong cùng cycle vì đồng hồ đã reset ở 146.045 ranh giới.",
        "- " + code("qref_available_at <= feature_available_at < label_observed_at") +
        " được kiểm cho mỗi nhãn. Chỉ tiêu là " + code(summary["target_semantics"]) +
        " trong điều kiện xả của từng cell. Vẫn còn khác biệt profile và cutoff khi so sánh giữa cell.",
        "- Q_ref, Q_observed và SoH là dữ liệu nhãn ngoại tuyến. Chế độ " + code("zero_commissioning_features") +
        " sẽ chỉ dùng tín hiệu có sẵn tại cuối sạc. Giữ nguyên các nhãn trên 100%.", "",
        "## Đối soát số lượng", "",
    ]
    out += table("Kết quả xét điều kiện","Số khóa")+[row(code(key),fmt(value)) for key,value in sorted(cases.items())]
    out += [
        "", f"Mốc giả định khi toàn bộ 77 cell dùng cycle 1–5 là **{fmt(benchmark)}** nhãn. "
        f"Bản dự thảo có ít hơn **{fmt(diff)}** nhãn."
    ]
    contested = next(cell for cell in summary["cells"] if cell["cell_id"]=="7-5")
    if diff==contested["d03_pairs"]-5 and cases.get("QREF_COMMISSIONING_BLOCKED")==contested["input_cycles"]:
        out[-1] += (f" Phần chênh là {fmt(contested['input_cycles'])} khóa của cell 7-5 đang chờ commissioning, "
                    "trừ năm khóa vốn thuộc khởi tạo trong mốc giả định.")
    out += [
        "", "Bốn khóa P3.2 bị REVIEW do timestamp trùng ở pha xả vẫn có trong bảng truy vết và giữ lý do gốc. "
        "Các khóa bị loại có giá trị nhãn rỗng.", "", "## Phân bố SoH dự thảo", "",
        f"Có **{fmt(total['above_100_percent'])} nhãn lớn hơn 100%**. Công thức tỷ lệ không cắt ngưỡng.", "",
    ]
    out += table("Thống kê","SoH (%)")+[
        row(key,fmt(value)) for key,value in summary["target_distribution_percent"].items()]
    out += ["", "## Số lượng theo cell", ""]
    out += table("Cell","Chu kỳ nguồn","Cặp D03","Khởi tạo","Chờ tham chiếu","Kiểm lại cặp","Nhãn","Cycle nhãn đầu",">100%")
    for cell in summary["cells"]:
        c = Counter(cell["label_counts"])
        out.append(row(cell["cell_id"],fmt(cell["input_cycles"]),fmt(cell["d03_pairs"]),
             fmt(c["COMMISSIONING_WARMUP"]),fmt(c["QREF_COMMISSIONING_BLOCKED"]),fmt(c["P32_PAIR_REVIEW"]+c["D03_PAIR_INVALID"]),
             fmt(c["LABEL_DRAFT_READY"]),fmt(cell["first_label_cycle_id"]),fmt(cell["count_over_100"])))
    out += ["", "## Trạng thái bàn giao", "",
        "Đã chạy kiểm thử đơn vị và ca thật. Lượt đọc lại xác minh tất cả khóa, công thức, trật tự thời gian, nguồn dung lượng "
        "và sự tương ứng giữa hai bảng Parquet. P3.3 chờ reviewer khóa D02/D03 gồm cửa sổ tham chiếu, xử lý cell 7-5, cutoff, "
        "nguồn Q_observed và cách diễn giải nhãn. Bản phát hành hiện tại phục vụ review quy tắc nhãn.", "",
        "[Bảng truy vết đầy đủ](../manifests/cycle_label_pairing.parquet) · [Nhãn dự thảo](../data/processed/soh_labels.parquet) · "
        "[Đọc lại và SHA-256](../manifests/p3_3_readback.json) · [Nhật ký kiểm thử](P3_3_TEST_LOG.txt)", "",
    ]
    return "\n".join(out)


def main():
    summary = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8-sig"))
    evidence = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8-sig"))
    if evidence["status"]!="PASS" or evidence["labels"]!=summary["totals"]["labels"]:
        raise ValueError("Verified draft readback is required to render reports")
    destination = Path(sys.argv[3])
    (destination/"P3_3_COMMISSIONING.md").write_text(make_commissioning(summary),encoding="utf-8")
    (destination/"P3_3_LABEL_AUDIT.md").write_text(make_label_audit(summary),encoding="utf-8")


if __name__=="__main__":
    main()
