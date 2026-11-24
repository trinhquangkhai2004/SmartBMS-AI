"""Render P3.4 decision reports from the static split and verified key audit."""

from collections import Counter
import json
from pathlib import Path
import sys


TICK = chr(96)


def code(value):
    return f"{TICK}{value}{TICK}"


def n(value):
    return f"{value:,}".replace(",",".")


def row(*items):
    return "| "+" | ".join(map(str,items))+" |"


def table(*items):
    return [row(*items),"|"+"|".join("---" for _ in items)+"|"]


def load(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(directory,name,lines):
    (directory/name).write_text("\n".join(lines)+"\n",encoding="utf-8")


def render(work):
    split = load(work/"p3_split_manifest.json")
    allocated = load(work/"audit/p3_cv_fold_manifest.json")
    audit = load(work/"audit/p3_4_audit_summary.json")
    replay = load(work/"p3_4_replay.json")
    if replay["status"]!="PASS" or audit["split_manifest_sha256"]!=replay["split_sha256"] or audit["cv_fold_manifest_sha256"]!=replay["fold_sha256"]:
        raise ValueError("Reports require exact split and fold replay")
    meta = split["cell_metadata"]
    totals = audit["counts"]
    dev,test = totals["development_labels"],totals["held_out_labels"]
    full = totals["labels_total"]
    balance = [
        "# P3.4 — Cân bằng protocol giữa các tập", "",
        "Phương án p34-r1 gồm 57 cell development và 19 cell held-out. D05 đang chờ duyệt.", "",
        "Tầng chỉ dùng mức dòng xả tham chiếu thứ nhất. Ba mức đầu đã khớp với số đo P3.2. "
        "Mức thứ tư nằm ngoài phép chia vì BatteryML ghi 1 C và staging đo gần 2 C. "
        "Mức thứ hai và thứ ba được báo để thấy độ cân bằng còn lại. "
        "[Chính sách chia](../configs/p3_split_policy.yaml) · [Danh mục protocol](../manifests/protocol_inventory.csv)", "",
    ]
    for i in range(1,4):
        key = f"stage_{i}_c"
        dev_levels = Counter(x[key] for x in meta if x["partition"]=="development")
        test_levels = Counter(x[key] for x in meta if x["partition"]=="held_out")
        balance += [f"## Mức dòng xả thứ {i}", ""] + table("C-rate","Tổng cell","Development","Held-out")
        for rate in sorted(set(dev_levels)|set(test_levels)):
            balance.append(row(f"{rate} C",n(dev_levels[rate]+test_levels[rate]),n(dev_levels[rate]),n(test_levels[rate])))
        balance.append("")
    shared = audit["shared_profile_first_three_c"]
    balance += [
        "## Giới hạn diễn giải", "",
        "- Tầng 2 C có một cell held-out. Kết quả của cell này có bằng chứng hạn chế cho cả nhóm 2 C.",
        "- Mức thứ nhất chỉ đại diện cho một chiều của profile xả.",
        f"- Có {n(len(shared))} tổ hợp ba mức đầu xuất hiện ở cả hai tập. "
        + ("Các tổ hợp là "+", ".join("/".join(str(rate) for rate in levels)+" C" for levels in shared)+". " if shared else "")
        + "Thiết kế đánh giá trên cell chưa từng dùng để fit trong phạm vi các profile RT-Batt. "
        "Đánh giá trên protocol hoàn toàn mới sẽ cần một revision được duyệt riêng.", "",
        "[Danh sách ID theo tập](../manifests/p3_split_manifest.json)", "",
    ]
    save(work,"P3_4_PROTOCOL_BALANCE.md",balance)

    anchor = audit["reference_cell_1_1"]
    signals = totals["signal_rows"]
    leakage = [
        "# P3.4 — Kiểm tra rò rỉ và tái lập", "",
        "**Kết quả kiểm tra** Đạt. P3.4 đang chờ phê duyệt D05.", "",
        "Bộ chọn ID chỉ nhận tệp eligibility gồm cell_id và ba mức dòng tham chiếu tĩnh. "
        "Container chọn ID chỉ được gắn bảng này, chính sách và thư mục đầu ra. "
        "Bước đối soát sau chia chỉ đọc cell_id và cycle_id của bảng nhãn và cell_id của canonical. "
        "Các trường SoH, Q_ref, dung lượng và tín hiệu đo nằm ngoài các cột được đọc.", "",
    ]
    leakage += table("Tập","Cell","Khóa nhãn","Hàng canonical") + [
        row("Development",57,n(dev),n(signals["development"])),
        row("Held-out",19,n(test),n(signals["held_out"])),
        row("Loại khỏi nhãn v1",1,0,n(signals["excluded_v1"])),
        row("Tổng nguồn",77,n(full),n(sum(signals.values()))),
    ]
    leakage += [
        "", f"Development có {100*dev/full:.2f}% số nhãn và held-out có {100*test/full:.2f}%. "
        f"Cell 1-1 thuộc {anchor['partition']} và toàn bộ {n(anchor['labels'])} khóa đi cùng nhau.",
        "Hợp hai tập bằng 76 ID được duyệt và loại trừ 7-5. Giao ID, khóa nhãn và hàng canonical giữa hai tập đều bằng 0. "
        "Mỗi hàng canonical được gán từ duy nhất một cell vật lý.", "",
        "## Năm fold development", "",
        "Dùng GroupKFold 5 lượt với groups là cell_id của từng khóa nhãn development. "
        "Mỗi cell development xuất hiện đúng một lượt validation. Giao train và validation từng fold bằng 0, "
        "và 19 cell held-out vắng mặt trong cả năm lượt. [GroupKFold 1.7.2](https://scikit-learn.org/1.7/modules/generated/sklearn.model_selection.GroupKFold.html)", "",
    ]
    leakage += table("Fold","Cell train","Cell validation","Nhãn train","Nhãn validation")+[
        row(fold["fold"],fold["train_cells"],fold["validation_cells"],n(fold["train_labels"]),n(fold["validation_labels"]))
        for fold in allocated["folds"]]
    leakage += ["", "## Tái lập", "",
        "Lượt chạy lại giữ nguyên đầu vào, thứ tự ID, phiên bản và seed 42. Cả hai manifest giống nhau từng byte.", "",
        f"- SHA-256 split {code(replay['split_sha256'])}.",
        f"- SHA-256 fold {code(replay['fold_sha256'])}.", "",
        "[Bằng chứng cấu trúc](../manifests/p3_4_audit_summary.json) · [Bằng chứng chạy lại](../manifests/p3_4_replay.json) · [Nhật ký kiểm thử](P3_4_TEST_LOG.txt)", ""]
    save(work,"P3_4_LEAKAGE_AUDIT.md",leakage)

    ledger = [
        "# Nhật ký tiếp xúc tập held-out", "",
        "**Bản chia** p34-r1. Niêm phong logic danh sách 19 ID ứng viên bằng SHA-256. "
        "D05 đang chờ reviewer duyệt bản chia và năm fold.", "",
        f"SHA-256 bản chia {code(replay['split_sha256'])}. SHA-256 bản fold {code(replay['fold_sha256'])}.", "",
    ]
    ledger += table("Mốc","Phạm vi dữ liệu ghi nhận","Mục đích và ảnh hưởng")+[
        row("P3.2 trước khi có danh tính test","Kiểm toàn bộ canonical của 77 cell","Đối soát chất lượng, phép ghép và ý nghĩa dq."),
        row("P3.3 trước khi có danh tính test","Tạo nhãn và báo phân bố toàn nguồn","Báo cáo tổng hợp đã được xem trước khi chọn 19 ID. Ghi nhận lịch sử đó cho diễn giải kết quả."),
        row("P3.4 chuẩn bị danh sách","Cột cell_id của nhãn v1 và metadata protocol tĩnh","Thu 76 ID đủ điều kiện, khóa policy quota và seed trước phép chia."),
        row(replay["first_candidate_frozen_at"],"Tệp eligibility chỉ gồm ID và metadata tĩnh","Sinh duy nhất một bản ứng viên 57/19. Chạy lặp cùng policy để đối soát byte."),
        row("P3.4 sau khi sinh danh sách","Chỉ khóa cell/cycle, số hàng và SHA-256","Xác minh giao rỗng, tái lập split/fold, kiểm phạm vi canonical. Đánh giá theo giá trị held-out chưa diễn ra."),
    ]
    ledger += ["", "## Quy tắc từ lúc khóa D05", "",
        "Dùng 57 cell development để chọn cửa sổ và đặc trưng sạc, fit mô hình và hiệu chỉnh ngưỡng. "
        "Đánh giá held-out ở P3.7 sau khi cấu hình đã đóng băng. "
        "Mỗi lượt tiếp xúc sau khóa ghi ngày giờ, người thực hiện, mục đích, các trường đọc, mã băm bản chia và quyết định liên quan.", "",
        "[Manifest ID](../manifests/p3_split_manifest.json) · [Kiểm kê rò rỉ](P3_4_LEAKAGE_AUDIT.md)", ""]
    save(work,"test_exposure_ledger.md",ledger)


if __name__=="__main__":
    render(Path(sys.argv[1]))
