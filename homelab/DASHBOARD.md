# MayChu247 — dashboard quản trị cá nhân

## Phạm vi hiện tại

Đây là bản tiếp tục dashboard tự viết, **không cài aaPanel**, không thay Tunnel/DNS đang chạy. Có URL chạy thử qua container Quick Tunnel riêng, chỉ khi admin xác nhận công khai.
Source/payload được kiểm thử ở môi trường phát triển không đồng nghĩa đã cài hoặc nghiệm thu
trên server Ubuntu. Push GitHub không tự cập nhật server; chưa có web updater tự động.
Cài/cập nhật ban đầu vẫn do quản trị viên có quyền trên máy thực hiện. Người dùng hằng ngày
quản lý các chức năng bên dưới bằng GUI, không SSH hay lấy password từ terminal.

| Tab | Thao tác thực sự có | Giới hạn quan trọng |
|---|---|---|
| Tổng quan | CPU/RAM/đĩa/uptime, trạng thái Compose, job | CPU mẫu đầu chưa có kết quả; không phải chứng nhận an toàn |
| Dịch vụ | Start/stop/restart web, db, mqtt, adminer, files của stack chính | Có gián đoạn, không xóa container/volume |
| Website & Domain | Tạo cấu hình, bật DB riêng, triển khai/build/start, dừng, kiểm tra origin, tạo/dừng URL tạm | Không tự tạo DNS/Tunnel; không xác minh HTTPS/public domain |
| File | Chọn stack/site, browse/upload file/thư mục, ZIP extract, create/edit/download, trash/chmod | Không symlink/hidden/system path; chưa rename/restore GUI |
| SQL | Chọn stack/site, tạo/xóa database, import/export .sql, chạy SQL bằng appuser | Xóa DB vĩnh viễn; import/export <=8 MiB, chưa user/ACL riêng |
| MQTT | Publish QoS1, nhận cửa sổ ngắn, tự kiểm tra subscribe→publish→receive | Không worker MQTT→SQL, lịch sử liên tục hoặc user/ACL GUI |
| Backup | Chạy backup-all, xem snapshot stack chính có COMPLETE | Chưa GUI restore/lịch/offsite; COMPLETE không chứng minh restore |
| Giám sát | Probe cố định, sự kiện đổi trạng thái trong RAM | Không Kuma, không cảnh báo ngoài máy/IDS/HA |

Dashboard dành cho **chủ server tin cậy**, không multi-tenant/reseller. Không đưa tài khoản
quản trị cho người dùng website. Mọi website/SQL/publish có thể tác động dữ liệu thật.

## Website và domain, không dùng terminal trong luồng thường ngày

1. Website & Domain → Tạo website mới → nhập tên, domain dự kiến, gói và port 20000–29999.
2. Tạo xong mới bấm **Chạy / triển khai**. Backend chạy Compose up/build web + db của site
   đó, không start tunnel container của site, không chạy down hoặc xóa volume.
3. Theo dõi Job quản lý. Tác vụ nền tối đa 10 phút; trong lúc đó thay đổi khác bị khóa, đọc
   số liệu vẫn hoạt động. Mất kết nối/timeout không có nghĩa Docker chưa xử lý, không tự retry.
   Job ở RAM, mất khi agent restart; đọc lại trạng thái/origin sau sự cố.
4. Bấm **Kiểm tra origin**: chỉ HTTP 127.0.0.1:<port từ metadata đã xác thực>, Host là domain
   của site. Không follow redirect, không trả body/headers/secret, không nhận IP/URL tùy ý.
   HTTP 200 chỉ xác nhận origin nội bộ, không chứng minh app đầy đủ hay domain công khai.
5. Domain công khai: trong Cloudflare Zero Trust GUI, dùng **Tunnel host hiện đang chạy** →
   Published application routes → thêm hostname site → Service HTTP → origin loopback hiển thị.
   Không sửa route maychu247.uk → 127.0.0.1:18000 đang phục vụ dashboard. Kiểm tra DNS/HTTPS
   và chính sách Access phù hợp trong Cloudflare GUI. Dashboard không có API credential để tự
   làm việc này, không yêu cầu gửi token vào chat, không giả báo DNS đã nối.
6. Tab File/SQL → chọn site tương ứng để quản lý dữ liệu riêng. Mỗi site có MariaDB/network/
   secrets riêng; projects/demo/public là public root trong từng site.

Cổng origin chỉ loopback; không mở cổng/router/firewall ra Internet, không dùng localhost trên
PC để truy cập server. Đường đi công khai qua host Tunnel. Không tùy tiện đưa IP LAN vào service
của connector bridge cũ; tài liệu PUBLIC-DOMAIN.md giải thích ranh giới network.

## Luồng đưa dự án lên bằng GUI

1. File → Website / domain → tạo site, chọn domain riêng hoặc URL tạm. Tạo cấu hình chưa bật
   web/DNS. Mode tạm lưu `<name>.preview.invalid` làm metadata nội bộ, **không phải URL truy cập**.
2. Bảng website → **Mã nguồn** mở đúng site/demo/public. Tải nhiều file hoặc cả thư mục; chọn
   thư mục giữ đường dẫn con nhưng trình duyệt không gửi thư mục rỗng. Thư mục đích cấp trên
   phải chưa tồn tại; không tự trộn/ghi đè. Lỗi giữa chừng có thể để lại một phần file/thư mục.
3. ZIP: upload ZIP rồi bấm **Giải nén ZIP**, chọn thư mục đích đã có. Tối đa 8 MiB nén, 32 MiB
   giải nén, 1000 mục kể cả thư mục cha, sâu 32 cấp; chỉ Store/Deflate. Không mã hóa, symlink,
   hidden, absolute/traversal, NUL, thiết bị hoặc ghi đè. Nếu có index.php cũ phải tự xử lý trước
   bằng GUI, không tự xóa file. Preflight xung đột và rollback mục mới nếu lỗi (không crash-atomic).
   Không sửa file đồng thời bằng công cụ ngoài. Code PHP trong public có thể chạy ngay nếu web
   đang bật: nên tắt web/URL công khai trong lúc cập nhật.
4. **Tiếp: nạp dữ liệu SQL** → giữ đúng site → **Khởi động database đã chọn** (Compose up db,
   đợi healthy; không bật web). Theo dõi Job ở đầu mọi tab. Chọn appdb hoặc schema bạn tạo →
   chọn file .sql UTF-8 <=8 MiB → Nạp dữ liệu thật → xác nhận `IMPORT <database>`.
5. Tạo bảng/dữ liệu xong → Website → Chạy / triển khai → Kiểm tra origin → dùng domain riêng
   (Cloudflare GUI bên trên) hoặc **Tạo / đọc URL tạm**.

### URL tạm thật, không tên miền giả

Nút URL tạm yêu cầu `PUBLIC <site>` ở UI và agent. Chỉ site origin HTTP 200 được công khai.
Agent chạy container `maychu247-preview-<site>` với cloudflare/cloudflared, fixed loopback origin,
network host, read-only, cap-drop, CPU/RAM/PID/log limits; không token/env/mount host. Có thể tải
image nếu chưa có. Nó độc lập với connector/Tunnel chính, không thay DNS, root maychu247.uk hoặc
credential. Cần Internet tới Docker registry/Cloudflare; có thể bị giới hạn hoặc không cấp URL.

URL `https://<random>.trycloudflare.com` chỉ được lấy từ log Quick Tunnel theo regex nghiêm ngặt,
không tự đoán hostname, không trả log thô. Persist URL trong metadata nhưng ghi rõ có thể hết
hiệu lực; không xác minh HTTPS từ ngoài chỉ vì Cloudflare đã cấp URL. Tác vụ lỗi sau start có thể
để lại container công khai: dùng **Dừng URL tạm** để ngắt. Khi quản lý container có sẵn, xác minh
label sở hữu, network và command; không đụng container lạ. Docker lỗi không được coi là đã dừng.

Quick Tunnel là dịch vụ thử nghiệm bên ngoài, không domain sở hữu/SLA/địa chỉ cố định, không
được bảo vệ bởi Access của dashboard. Ai có URL có thể vào; không dùng dữ liệu nhạy cảm hoặc
production. Tắt URL tạm không đồng nghĩa tắt domain riêng khác. Không proxy app PHP dưới đường
dẫn cùng origin dashboard để tránh app đọc session/API quản trị. Chỉ URL riêng origin khác.

## File workspace

`project_files.py` dùng directory-relative fd và O_NOFOLLOW; chặn absolute/traversal, file ẩn,
control chars, symlink, FIFO/device. Chỉ dưới projects/ của stack/site đã chọn, không truy cập
.env, Compose, secrets hoặc hệ điều hành. Stack/site hợp lệ được xác thực lại phía agent;
không nhận root path từ browser và không fallback sang stack chính khi site sai/mất.

- Browse tối đa 200 mục, quét tối đa 1000; mtime, kích thước và mode thực.
- Upload mỗi file tối đa 8 MiB; read/download vẫn tối đa 1 MiB; UTF-8 edit 200 KiB.
  Tải nhiều file/thư mục tối đa 1000 file/32 MiB mỗi lần, gửi tuần tự qua cùng session/CSRF. Không upload ghi đè.
- Save kiểm tra SHA256 phiên bản, fsync và atomic replace, giữ nội dung trước ở
  .maychu247-history (ẩn, 0700/0600, tối đa 50 bản/thư mục). Không sửa đồng thời bằng công cụ
  ngoài; chưa có khóa liên tiến trình với external writer.
- **Xóa** yêu cầu nhập đúng đường dẫn; chuyển nguyên file/thư mục vào
  projects/.maychu247-trash/<random>/item, ghi info.json đường dẫn gốc. Không recursive unlink,
  không tự dọn, tối đa 100 mục, thư mục thùng rác 0700. Việc này gỡ nội dung khỏi website và
  có thể làm site ngừng hoạt động. Chưa có GUI phục hồi/xóa vĩnh viễn; quản trị viên phải xử lý
  có kiểm soát, không coi thùng rác thay backup.
- **Đổi quyền** chỉ file 0600/0644 hoặc thư mục 0700/0755, không đệ quy, không đổi owner, không
  executable/setuid/world-write; chặn chmod file hardlink. Quyền riêng tư có thể làm web lỗi.

## SQL native

Tạo schema/cấp quyền dùng câu SQL cố định với tên đã validate a-z/số/_, không database hệ
thống, không ghi đè. Grant thất bại có thể còn schema; không tự DROP để rollback. appuser được
cấp quyền dùng chung trong từng stack, không phải user riêng cho mỗi schema. Tạo schema không
đồng nghĩa tự cấu hình app PHP. Tất cả bước đọc/tạo/grant dùng đúng stack/site được chọn.

**Xóa database** là DROP vĩnh viễn qua root backend, yêu cầu đúng `DELETE <name>` và xác minh
schema tồn tại. Chặn tên hệ thống và injection trước khi gọi DB. Không xóa volume/user. Quyền
appuser trên tên schema có thể vẫn còn sau DROP; tạo lại tên cũ không tạo cách ly quyền mới.
Sao lưu và kiểm tra trước khi xác nhận; timeout có thể sau khi đã DROP, không tự retry.

Trình SQL dùng **appuser, không root**, xác nhận `RUN <name>`, SQL tối đa 8 KiB. Có thể tạo
bảng, thêm/sửa/xóa dòng, SELECT…; appuser có quyền trên các schema đã cấp trong stack này, không
chỉ schema dropdown. Browser SQL qua stdin, không shell interpolation. Fixed in-container
shell chỉ đọc credential môi trường. MYSQL_PWD không đưa password vào argv hoặc API/log.
MariaDB --binary-mode vô hiệu client commands (đặc biệt shell escape), local-infile=0,
utf8mb4, init session max_statement_time=8. User tin cậy vẫn có thể đổi session setting bằng SQL.

Kết quả TSV tối đa 256 KiB, nhận qua nonblocking bounded pipes và deadline tổng 10 giây.
Không capture vô hạn hoặc echo stderr thô có thể chứa secret/query. Vượt giới hạn/timeout
là lỗi, không hiển thị thành công một phần. Ngắt docker CLI không bảo đảm hủy server query.
DDL/autocommit hoặc nhiều statements có thể đã ghi trước lỗi; không tự retry hoặc tự rollback.
Mã trả 0 không chứng minh có dòng thay đổi hay COMMIT transaction người dùng tự mở.
Output/query dùng textContent, không render HTML.

### Import SQL

Import file qua base64 payload giới hạn 8 MiB, UTF-8 có thể có BOM, không gzip/ZIP/NUL; giới hạn
HTTP action 12 MB. Appuser, binary-mode, local-infile=0 giống console, nhập qua bounded stdin,
output <=256 KiB, deadline 60 giây, max_statement_time session 45 giây (user tin cậy có thể đổi).
Không sửa dump/DEFINER/USE tự động; dump khác schema hoặc cần quyền cao có thể thất bại. Có thể
đã nhập một phần khi lỗi/timeout; không auto-retry, không tự DROP/rollback. Chưa kiểm chứng dữ liệu
với app chỉ vì CLI trả 0. Không mở root SQL cho nội dung upload. Không log filename/SQL/payload.

### Export SQL về PC

Khu vực Nhập / xuất có hai nút Chọn file .sql để nạp và Xuất .sql về PC, dùng chung dropdown
schema và stack/site hiện tại. POST sql-export cần session/Host/Origin/CSRF và xác nhận EXPORT
đúng tên; không GET công khai hoặc đường dẫn dump tùy ý. Backend mariadb-dump **appuser**, không
root, đúng một schema đã validate; password qua MYSQL_PWD, không argv/API/log. Single-transaction,
quick, skip-lock-tables, hex-blob, utf8mb4; gồm cấu trúc, dữ liệu, triggers, không routines/events,
user/grant hoặc schema khác. Không bảo đảm snapshot MyISAM hoặc khi có DDL/external writer.
DEFINER trên view/trigger có thể cần quyền khi phục hồi; không tự sửa dữ liệu dump.

Dump dùng bounded binary pipes 60 giây/8 MiB để giữ nguyên bytes; vượt giới hạn/nonzero/empty là
lỗi, không trả dump một phần hoặc tạo file giả. Agent response cap 12 MB để đủ base64 8 MiB.
JSON no-store, audit chỉ action/time. Response có filename tên schema + UTC, bytes, SHA256 và
base64; không ghi dump vào public web hoặc lưu lịch sử SQL trên server. Browser tạo Blob tải
.sql về PC, không render nội dung, và nói rõ chỉ yêu cầu download (cần kiểm tra Downloads).
Chưa thử restore/live MariaDB ở môi trường này. Test command boundaries/mock dump, pipe bytes
thật, CSRF/scoping và DOM download thành công/thất bại; không phải kiểm thử backup server thật.

## MQTT native

`mqtt_client.py` là client MQTT 3.1.1 stdlib; chỉ 127.0.0.1:1884/mqttuser, password đọc .env phía
agent. Không browser credentials, shell, external package hoặc host/password tùy ý từ client.

- Publish UTF-8 <=16 KiB, QoS1, không retained; thành công phải có PUBACK đúng packet ID.
  PUBACK chỉ broker nhận, không chứng minh thiết bị xử lý/SQL worker. Timeout có thể sau khi
  broker đã nhận, không auto-retry tránh lệnh thiết bị trùng.
- Subscribe QoS0, bắt đầu cửa sổ 3 giây sau SUBACK; tối đa 20 tin/64 KiB; hiển thị retained
  (có thể cũ) và binary base64. Không streaming liên tục/lịch sử broker.
- **Tự kiểm tra gửi / nhận** subscribe topic maychu247/check/<random> trước, publish qua kết
  nối thứ hai, đợi PUBACK và đối chiếu payload subscriber nhận. Chỉ kiểm tra broker nội bộ.
- Nhận giữ agent lock; không publish từ tab khác đồng thời. Dùng thiết bị phát hoặc selftest.
  ID random, clean session, packet <=64 KiB, socket deadlines và close sau mỗi thao tác.

## Bảo mật, dữ liệu và triển khai

Web Python chạy user maychu247-ui, không Docker socket/sudo; agent root chỉ Unix socket có
quyền nhóm UI, không listen TCP. API session 1 giờ, cookie HttpOnly/SameSite Strict, Secure khi
HTTPS, exact Host/Origin và CSRF cho POST. Payload API allowlist trường, không API exec/command/
host tùy ý. Log mutation chỉ action/time, không SQL/topic/payload/secret. File .env và auth
không trả browser. Frontend xóa editor/query khi logout và bỏ kết quả cũ khi session thay đổi.

Đây không phải chứng nhận an toàn. Cloudflare Access/JWT, WAF/IDS, MFA và quyền truy cập live
phải được nghiệm thu; không khẳng định Access đã bảo vệ chỉ vì có hướng dẫn. Không tắt auth,
Host/Origin, TLS checks hay mở 18000/router để chữa lỗi. Root dashboard maychu247.uk không phải
PHP origin 18080 và không tự chuyển sang panel.maychu247.uk.

Quản trị viên dùng installer portable `downloads/MayChu247-Install.sh` ở chế độ update-dashboard
cho stack /opt/maychu247-v2 đã có. Kiểm tra nguồn/gói, backup và không deploy đồng thời. Updater
giữ .env, database/volume, projects/sites, credentials dashboard, public.env/tunnel.env/tunnel.yaml;
không thay PHP tùy chỉnh hay Cloudflare route. Installer explicit-copy toàn bộ runtime modules,
preflight import bằng user UI, giữ bản live/unit cũ, rollback code/unit khi cài lỗi, HTTP readiness
và agent ping. Không coi readiness là nghiệm thu mọi chức năng. Chưa web updater hoặc remote
access từ phiên phát triển này; không thể tự cập nhật máy chủ chỉ bằng push GitHub.

## Kiểm thử và nghiệm thu

Python unittest ở homelab/tests kiểm tra auth/Host/Origin/CSRF/allowlist, socket Unix HTTP thật,
filesystem file/upload/edit/hash/trash/chmod, scope không fallback, helper SQL bằng process thật
(input/output/limit/timeout/redaction), MQTT TCP framing fixture, site origin HTTP loopback thật
(no redirects), lifecycle argv/job lock và updater bind/readiness/rollback contracts.

Docker/MariaDB lifecycle/query/import và Quick Tunnel được mock trong suite; MQTT fixture không phải Mosquitto thật.
`test_dashboard_ui.cjs` dùng jsdom + mock API để kiểm tra DOM click/forms, chọn scope, ZIP/folder/import forms, text-only
output và logout. Nó không phải Chromium/browser acceptance hay kết quả trên server cài thật.
JS syntax, shell syntax và portable --check là kiểm tra tĩnh/gói, không deployment proof.

Nghiệm thu sau cài: đăng nhập HTTPS; thử upload/edit/chmod/xóa file thử; chọn site và xác minh
không chạm stack khác; tạo DB thử, CREATE/INSERT/SELECT/DROP bảng rồi xóa DB thử; tự test MQTT;
tạo site thử, triển khai, origin HTTP, thêm Cloudflare route bằng GUI và mở HTTPS từ ngoài;
dừng site giữ dữ liệu, chạy lại; backup và kiểm tra khôi phục có kiểm soát. Không dùng dữ liệu
quan trọng để thử thao tác phá hủy. Chưa có GUI quản lý cron/worker, backup restore/offsite,
quota đĩa, firewall và user/ACL MQTT/SQL riêng; không gọi hệ thống full production/HA.
