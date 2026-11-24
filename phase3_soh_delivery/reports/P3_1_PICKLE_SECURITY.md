# P3.1 — Kiểm tĩnh pickle và quyết định D11

**Trạng thái đường xử lý:** `P3_1_PASS`. Người dùng xác nhận reviewer đã duyệt D11 cho `LOCAL_DOCKER_HARDENED` với image d11-r1. Docker Desktop đã khởi động và kết nối được Linux engine.

## Bằng chứng kiểm tĩnh

- `pickletools.genops` đọc đủ **77/77** tệp pickle, tất cả dùng protocol 4. Scanner ghi nhận **10 global** của NumPy, pandas và `builtins.slice`. Cả 770 lệnh `STACK_GLOBAL` được nhận diện trong dạng mà scanner hỗ trợ. Có các opcode `REDUCE`, `BUILD` và `NEWOBJ`.
- **0/77** tệp bị scanner gắn cờ theo danh sách dự kiến của lần kiểm này. Danh sách được lập từ các lớp NumPy/pandas quan sát trong mẫu kiểm tĩnh đầu tiên và cần reviewer đối chiếu với thư viện, mã nguồn và phiên bản đã khóa trước khi duyệt. Bằng chứng đối chiếu image bên dưới. Scan kiểm kê opcode và tham chiếu global. Tính tương thích của dependency, đồ thị đối tượng khi nạp và độ an toàn của mã khi giải tuần tự vẫn cần đường xử lý cô lập.
- SHA-256 ZIP là `071d24617153693b0d29059568525e620f6af6512acc9d00c98c7adcf15125db`. SHA-256 scanner là `1a38af6591714bf5886f6379d86e243b2ffe5e280775534000cf649b6dd3ab22`. Lượt kiểm tĩnh không thực thi deserializer. Bằng chứng chuyển đổi sau phê duyệt nằm ở cuối báo cáo.

Bằng chứng: [inventory từng tệp và opcode](../manifests/p3_pickle_opcode_inventory.json), [quyết định đường xử lý](../manifests/p3_conversion_route.json), [repo tác giả](https://github.com/HAIRLAB/Health_status_prediction), [tài liệu Python về pickle](https://docs.python.org/3/library/pickle.html).

## Đối chiếu nguồn cho reviewer D11

Ngày kiểm tra 20/11/2026. `docker version` trả về Docker Desktop **4.43.2**, Engine **28.3.2**, **linux/amd64**. Kết quả này xác nhận Docker Server Linux đã sẵn sàng.

Repo HAIRLAB ghi môi trường Python 3.8.8, NumPy 1.20.1 và pandas 1.2.4. Bảng dưới đối chiếu **10/10** tham chiếu quan sát trong ZIP với nguồn các phiên bản tác giả công bố. Phiên bản tác giả công bố là căn cứ đối chiếu. Phiên bản trong image ứng viên và bằng chứng round-trip nằm ở phần trình duyệt bên dưới. [Yêu cầu thư viện HAIRLAB](https://github.com/HAIRLAB/Health_status_prediction/blob/main/requirements.txt), [môi trường HAIRLAB](https://github.com/HAIRLAB/Health_status_prediction#environment-setup).

| Global | Vai trò / định nghĩa đã đối chiếu |
|---|---|
| `builtins.slice` | Kiểu biểu diễn lát cắt tích hợp của Python. Đã kiểm trực tiếp bằng Python 3.11 trên máy. [Python](https://docs.python.org/3/library/functions.html#slice) |
| `numpy.core.multiarray._reconstruct` | Hàm dựng lại mảng. NumPy đặt tên module này để giữ khả năng đọc pickle. [NumPy 1.20.1](https://github.com/numpy/numpy/blob/v1.20.1/numpy/core/multiarray.py#L44-L47) |
| `numpy.core.multiarray.scalar` | Hàm dựng giá trị NumPy vô hướng. Module được đặt cùng đường tương thích pickle. [NumPy 1.20.1](https://github.com/numpy/numpy/blob/v1.20.1/numpy/core/multiarray.py#L44-L47) |
| `numpy.dtype` | Kiểu mô tả phần tử mảng, được xuất từ `numeric` qua `core` lên package. [numeric](https://github.com/numpy/numpy/blob/v1.20.1/numpy/core/numeric.py#L9-L43), [core](https://github.com/numpy/numpy/blob/v1.20.1/numpy/core/__init__.py#L70-L74), [package](https://github.com/numpy/numpy/blob/v1.20.1/numpy/__init__.py#L141-L150) |
| `numpy.ndarray` | Kiểu mảng, được xuất qua cùng chuỗi module. [NumPy 1.20.1](https://github.com/numpy/numpy/blob/v1.20.1/numpy/core/numeric.py#L9-L43) |
| `pandas.core.frame.DataFrame` | Kiểu bảng tín hiệu theo cycle. [pandas 1.2.4](https://github.com/pandas-dev/pandas/blob/v1.2.4/pandas/core/frame.py#L394) |
| `pandas.core.indexes.base.Index` | Kiểu chỉ mục tổng quát của pandas. [pandas 1.2.4](https://github.com/pandas-dev/pandas/blob/v1.2.4/pandas/core/indexes/base.py#L150) |
| `pandas.core.indexes.base._new_Index` | Hàm dựng lại chỉ mục trong quá trình đọc pickle. [pandas 1.2.4](https://github.com/pandas-dev/pandas/blob/v1.2.4/pandas/core/indexes/base.py#L127) |
| `pandas.core.indexes.range.RangeIndex` | Kiểu chỉ mục dãy số nguyên gọn. [pandas 1.2.4](https://github.com/pandas-dev/pandas/blob/v1.2.4/pandas/core/indexes/range.py#L38) |
| `pandas.core.internals.managers.BlockManager` | Kiểu nội bộ quản lý các block dữ liệu của pandas. [pandas 1.2.4](https://github.com/pandas-dev/pandas/blob/v1.2.4/pandas/core/internals/managers.py#L63) |

**Gợi ý schema từ mã tác giả.** `common.py` đọc `data` theo cycle cùng với `dq` và `rul`. Bảng tín hiệu được tham chiếu bằng `Status`, `Time (s)`, `Voltage (V)`, `Current (mA)` và `Capacity (mAh)`. Khi chuẩn bị bộ chuyển đổi, giữ thứ tự hàng, cycle ID và dấu giá trị thô. Kiểm chứng ý nghĩa của `dq`, dấu dòng và thứ tự sạc–xả bằng staging tại P3.2. [Mã xử lý dữ liệu HAIRLAB](https://github.com/HAIRLAB/Health_status_prediction/blob/main/common.py#L70-L88).

## Image chuyển đổi trình duyệt D11

**Revision ứng viên** `d11-r1` · **Đường đề xuất** `LOCAL_DOCKER_HARDENED` · **D11** `APPROVED_AS_REPORTED_BY_REQUESTER`

Image local Linux/amd64 `pbl5-rtbatt-converter:d11-r1` có ID `sha256:611d52fe746196d5a771e5fb2b38e7660c623bb045f09933d3525796ced69eaa`. Image dùng Python 3.11.18, NumPy 1.26.4, pandas 2.3.3 và PyArrow 22.0.0. Image nền được khóa bằng digest, các gói trực tiếp và phụ thuộc được khóa bằng SHA-256 wheel. Reviewer dùng đúng ID này khi phê duyệt.

- **10/10 global** trong inventory phân giải được trong image ứng viên. Test dùng dữ liệu tổng hợp theo cấu trúc `BlockManager` cũ và kiểm tra lại Parquet/JSON. pandas 1.2.4 ghi trạng thái tương thích `0.14.1` và pandas 2.3.3 có đường đọc trạng thái đó. [Mã ghi pandas 1.2.4](https://github.com/pandas-dev/pandas/blob/v1.2.4/pandas/core/internals/managers.py), [mã đọc pandas 2.3.3](https://github.com/pandas-dev/pandas/blob/v2.3.3/pandas/_libs/internals.pyx), [NumPy 1.26.4](https://github.com/numpy/numpy/blob/v1.26.4/numpy/core/multiarray.py).
- **9/9 kiểm thử tổng hợp** đạt. Container thử đã được kiểm tra có chế độ không mạng, root filesystem chỉ đọc, UID/GID 1000:1000, 4 GiB RAM, 2 CPU, giới hạn 128 tiến trình, bỏ mọi Linux capability và bật `no-new-privileges`. Mount duy nhất là tệp kiểm thử chỉ đọc. Lệnh chuyển đổi dừng khi thiếu biên bản D11. [Nhật ký kiểm thử image](P3_1_D11_CANDIDATE_TEST_LOG.txt)
- Bộ chuyển đổi xác minh ZIP bằng size/SHA-256 chính thức, giới hạn các lớp có thể nạp, lưu dấu dòng và thứ tự thô trong Parquet, giữ `dq` ở JSON để kiểm tra ý nghĩa sau. Nhật ký staging sẽ ghi liên kết từng member, số dòng, schema và SHA-256 từng đầu ra. Dữ liệu thử kiểm tương thích và luồng đọc/ghi. Khả năng đọc đầy đủ 77 tệp thật chỉ được xác minh sau khi D11 cho phép.
- Rủi ro còn lại là giải tuần tự pickle vẫn xử lý hành vi của thư viện và các đối tượng được cho phép. Lần chạy thật cần giữ đúng các giới hạn trên, chỉ gắn ZIP và biên bản D11 ở chế độ chỉ đọc, dùng mount đầu ra riêng và không đưa thông tin đăng nhập vào container.

| Căn cứ trình duyệt | SHA-256 |
|---|---|
| [Bộ chuyển đổi](../conversion/secure_source_converter.py) | `64e56ef00e724fbde068553e3d4ac31e0729b48c1728577f379814a275601ea7` |
| [Danh sách dependency](../conversion/requirements-linux-amd64.lock) | `b45604177f2f90a25494ebe8642d82dd49c7e10a00af79ae32d8cc79e5a9f9ff` |
| [Dockerfile](../conversion/Dockerfile) | `2e3ab4ec82abefc291e23fc3e7b60cef25f7bb01a7a77829059c80e5747b7d0e` |
| [Scanner/kiểm tra ZIP](../scripts/audit_rt_batt_source.py) | `1a38af6591714bf5886f6379d86e243b2ffe5e280775534000cf649b6dd3ab22` |

Người duyệt ghi tên và vai trò, thời gian kèm múi giờ, revision `d11-r1`, image ID, kết luận và bằng chứng vào [quyết định D11](../manifests/p3_conversion_route.json). Ở thời điểm trình duyệt, chưa nạp pickle thô và chưa tạo staging.

## Điều kiện trước khi chuyển đổi

**Local Docker.** Xác nhận engine local, image và dependency đã khóa; chạy container không có mạng, filesystem chỉ đọc, người dùng không có đặc quyền, mount ZIP chỉ đọc, mount đích riêng và áp giới hạn tài nguyên theo spec. Reviewer ghi quyết định D11, tên, ngày giờ và bằng chứng.

**Hosted Colab nếu dùng phương án có điều kiện.** Cần reviewer ghi `APPROVED_CONDITIONAL_COLAB`. Dùng runtime trắng và không gắn Drive hoặc cấp token. Sau khi validate và export staging, hủy runtime chuyển đổi rồi đưa staging vào môi trường sạch. Hosted Colab có thể có mạng và quyền root, là rủi ro còn lại cần ghi trong quyết định.

P3-DT-02 đạt cho đường Docker sau khi đối chiếu lượt chuyển đổi thật và đọc lại toàn bộ staging. P3-DT-04 dành cho Colab không áp dụng trong lượt này.

## Chuyển đổi và kiểm tra staging

D11 được ghi từ phản hồi của người dùng xác nhận reviewer đã chấp thuận. Thời gian trong manifest là thời điểm ghi nhận phản hồi. Tên, vai trò, thời điểm duyệt thực tế và biên bản gốc của reviewer chưa được cung cấp. [Bản ghi phê duyệt dùng trong lần chạy](../manifests/p3_d11_approval_snapshot.json)

Lần chạy thật dùng image d11-r1 theo ID đã kiểm, network tắt, root filesystem và hai mount đầu vào chỉ đọc, UID/GID 1000:1000, giới hạn RAM/CPU/PID, bỏ capability và một mount đầu ra riêng. Bộ chuyển đổi xử lý đủ 77 tệp. Container đọc lại riêng chỉ gắn Parquet/JSON và các hồ sơ kiểm, đều chỉ đọc. Nó xác minh toàn bộ schema, nguồn từng tệp, mã băm và số lượng, gồm **91.736.659 hàng tín hiệu** từ **146.122 chu kỳ trong staging**. [Bằng chứng container chuyển đổi](../manifests/p3_conversion_execution.json) · [Bằng chứng đọc lại](../manifests/p3_staging_readback.json) · [Ánh xạ và SHA-256 đầu ra](../data/staging/rt_batt_v2/conversion_manifest.json)
