# Hiện tại: dùng tab Tập tin không cần lệnh hoặc đăng nhập File Browser

Trình quản lý file native đã có: mở thư mục, upload, tạo file/thư mục, soạn thảo và tải xuống
qua domain dashboard. Xem mục **Native Project Explorer** cuối tài liệu để biết ranh giới quyền,
giới hạn và bằng chứng kiểm thử. Các ghi chú File Browser/SSH ở phiên bản trước là lịch sử,
không còn là luồng quản lý file mặc định. SQL Admin vẫn là công cụ riêng.

# Mới: tạo thư mục web và database bằng nút bấm

- **Tập tin → Tạo thư mục web**: nhập `web-ca-nhan`, xác nhận. Ghi thật
  `projects/web-ca-nhan/public/index.html`; danh sách thư mục đọc trực tiếp trên server.
  File Browser sẽ thấy `/web-ca-nhan/public/`. Chưa tự tạo virtual host hoặc domain. Không tự
  cấu hình Nginx hay phục vụ tất cả thư mục qua URL để tránh public nhầm mã riêng.
- **Cơ sở dữ liệu → Tạo database SQL**: nhập `quan_ly_nha`, xác nhận. Tạo MariaDB schema thật
  UTF8MB4, cấp quyền schema cho tài khoản **appuser@% hiện có**. Dùng DB_PASSWORD đang có,
  không sinh user/password mới. Trong Adminer chọn server db, user appuser và database vừa tạo.
  Đây là stack cá nhân với tài khoản dùng chung, KHÔNG cách ly khách hàng hoặc quyền giữa app.
- Cả hai thao tác có session/CSRF, xác nhận, allowlist tên và lock cùng agent/backup. Không ghi
  đè tên đã tồn tại. Tên thư mục dùng a-z, số, dấu -, tên SQL dùng a-z, số, dấu _, tối đa 32 ký tự.
- Không có thao tác xóa tự động. Tạo schema và cấp quyền là hai DDL không transaction: nếu grant
  lỗi có thể còn database mới. UI báo chưa xác nhận và yêu cầu kiểm tra danh sách/quyền trước
  khi thử lại, không DROP để “rollback”. Chưa liên kết database mới vào code PHP tự động.
- API GET /api/resources cần đăng nhập; lỗi DB không làm mất danh sách folder. Không gửi secret
  hoặc stderr SQL qua API. UI chỉ gửi tên, không gửi SQL/path tự do; root agent chạy SQL cố định
  với identifier đã kiểm tra. Quyền root bên trong container vẫn cần quản trị đúng.
- Chỉ tạo folder dưới projects bằng no-follow directory-relative operations; từ chối symlink,
  path traversal và trùng tên. Mode 0755/0644 cho public code dù agent có umask 0007; secrets
  của site vẫn 0600/0700. Đã sửa template site để PHP container đọc được cây projects dưới umask đó.

Bản cập nhật giữ public.env, token Tunnel, dữ liệu và mật khẩu; UI restart sẽ đăng xuất phiên.
Kiểm thử filesystem/HTTP chạy thực trên môi trường phát triển, SQL dùng mock: chưa chạy thử
DDL/grant trên MariaDB hoặc systemd server của bạn. Nghiệm thu một folder và DB tên mới sau update.
Các ghi chú cũ bên dưới nói chưa có form SQL/folder được thay thế bởi phạm vi cụ thể ở trên.

---

# Mới: domain HTTPS tùy chọn cho dashboard

Xem PUBLIC-DOMAIN.md. Cần update code/systemd rồi chạy configure-public.sh với hostname cụ thể,
Tunnel MỚI RIÊNG và Access do người quản trị cấu hình. Không mở 18000 ra LAN/WAN. Các ghi chú
SSH-only ở phiên bản cũ bên dưới không còn áp dụng nếu đã bật public origin đúng quy trình.
Chức năng SQL/File Browser vẫn dùng SSH riêng, không có public proxy hoặc SSO.

# Cập nhật: workspace riêng và tạo tên dự án qua giao diện

Menu mới tách Website & Domain, Cơ sở dữ liệu, Tập tin, MQTT & Thiết bị, Giám sát, Sao lưu.
Không còn gom PHP/SQL/File Manager thành một trang. SQL/file vẫn mở ứng dụng hiện có với
đăng nhập riêng; không giả lập trình quản lý file/database mới hoặc auto-login.

**Website → Tạo website mới** mở form tên nội bộ, domain dự kiến, cấu hình tài nguyên và cổng
loopback. Submit qua session/CSRF rồi agent gọi CLI create-site.py bằng argv cố định, không shell.
Generator hiện có sở hữu validation/name/domain/port/trùng tên; không gửi raw stderr hoặc
mật khẩu qua API. Tạo file .env 0600, Compose, template PHP và metadata thật tại sites/<ten>.
Không ghi đè site cũ, không khởi động container, không tạo DNS, không mở firewall.
Danh sách đọc metadata thật nhưng **không xác minh deployment hoặc DNS**. Nút Xem lệnh triển
khai chỉ hiển thị lệnh SSH; chưa thực thi lệnh đó. Domain là domain dự kiến, không được tự coi đã
xác minh sở hữu. Không bấm lặp lại khi tác vụ chưa phản hồi; kiểm tra inventory nếu mất kết nối.

Tối đa 100 site từ API, agent tuần tự hóa với service actions/backup trong cùng tiến trình.
Không chạy CLI tạo site hoặc deploy thủ công đồng thời; chưa có khóa liên tiến trình giữa CLI và
agent. Template site kế thừa code/config ở stack hiện có; đối chiếu PHP/Nginx trước khởi động.
Nếu generator timeout, có thể còn .create-* tạm; kiểm tra qua SSH, không xóa site thành công.
Tab MQTT có nút chạy/dừng/restart broker thật nhưng chưa tạo user/ACL hoặc kiểm tra pub/sub.
Tạo database/user SQL có tên tùy chọn qua UI chưa được tích hợp. Nếu yêu cầu “tên mới” là
đổi tên database thay vì tạo dự án, cần thiết kế migration/quyền dữ liệu riêng.

Các ghi chú phiên bản cũ bên dưới về “chưa có form tạo site” đã được thay thế bởi chức năng
tạo cấu hình nói trên, không có nghĩa toàn bộ provisioning/domain management đã hoàn tất.

---

# Cập nhật: giám sát MayChu247 nội bộ, không dùng Kuma mặc định

Bản mới dùng `dashboard/monitor.py` (Python stdlib) với mục **Giám sát nội bộ**. Không cần
Kuma, tài khoản giám sát thứ hai hoặc thư viện Python ngoài. Mỗi 30 giây kiểm tra HTTP 200
của website tại 127.0.0.1:18080; kiểm tra TCP tại MQTT 1884, File Browser 18082, SQL Admin 18081.
Đây là kiểm tra khả dụng, không phải công cụ chống xâm nhập. TCP mở không chứng minh đăng nhập,
MQTT pub/sub hoặc query SQL đúng. Không có URL/port do người dùng nhập để tránh mở API quét mạng.

Mỗi dòng có thời điểm đo, độ trễ, phạm vi kiểm tra. Sự kiện đổi trạng thái giữ tối đa 100 trong
RAM, mất khi restart UI. Chưa có email/SMS/Telegram, lưu lịch sử dài hạn, hoặc monitor ngoài máy.
Số liệu chỉ cập nhật khi dashboard backend hoạt động; toàn máy ngừng thì monitor cũng ngừng.
Tự viết không đảm bảo an toàn hơn phần mềm có sẵn: vẫn cần review, vá lỗi và nghiệm thu.

Updater `--update-dashboard` dừng container Kuma của đúng project MayChu247 và đặt nó sau
profile `legacy-kuma`. Không xóa volume/dữ liệu Kuma. Bản mới không khởi chạy, điều khiển hoặc
sao lưu Kuma mặc định. Snapshot cũ có kuma.tgz vẫn giữ nguyên; restore mới không nhập archive
Kuma. Nếu restore snapshot cũ có compose cũ, phải đối chiếu cấu hình/profile trước khi mở traffic
vì cấu hình cũ có thể bật lại dịch vụ. Không dùng restore để rollback giám sát một cách mù quáng.
Backup mới chỉ bật lại web/mqtt/files vốn đang chạy trước khi chụp, không bật lại dịch vụ đã dừng.

**Phạm vi lần thay thế này chỉ là giám sát:** PHP/Nginx/MariaDB/Mosquitto và công cụ Adminer,
File Browser vẫn là các thành phần nguồn mở. Không tuyên bố đã tự viết toàn bộ hệ điều hành,
web server hay giao thức database. Các đề cập Kuma trong hướng dẫn phiên bản cũ dưới đây là
lịch sử, không phải kiến trúc mặc định mới.

---

# Personal Operations v1 — dashboard có backend thật

## Phân biệt với preview

`dashboard/` là ứng dụng thật; `preview.html` vẫn là concept cũ, không phải sản phẩm đang chạy.
Không có số liệu mẫu trong dashboard mới. Giao diện có đăng nhập, số liệu CPU/RAM/đĩa/uptime
của **Ubuntu host/VM**, trạng thái Docker Compose, start/stop/restart sáu dịch vụ cố định,
khởi chạy backup-all và danh sách 20 snapshot stack chính đã có COMPLETE.

**Chưa hoàn chỉnh “full”:** chưa có GUI tạo/sửa website/domain/DNS, user/ACL MQTT, cron/worker,
restore/download snapshot, xem log app, giám sát quota hay cấu hình firewall. Những phần này
vẫn quản lý theo tài liệu/SSH và ứng dụng chuyên dụng. Không gọi container running là dịch vụ
đã khỏe: hiển thị riêng healthcheck hoặc ghi rõ không khai báo. Backup offsite và timer chưa được
xác minh qua API. Không hứa HA, thương mại hoặc hiệu năng khi chưa nghiệm thu.

## Cấu trúc quyền

- `maychu247-dashboard.service`: user `maychu247-ui`, Python stdlib, chỉ bind 127.0.0.1:18000.
  Không quyền sudo, không Docker socket. Đọc hash scrypt ở `/etc/maychu247-ui/auth.json`.
- `maychu247-agent.service`: root, socket Unix `/run/maychu247/agent.sock`, root:maychu247-ui 0660.
  Chỉ nhận status/start/stop/restart với allowlist web/db/adminer/mqtt/kuma/files, và backup-all.
  Không cung cấp exec, shell, đường dẫn tùy chọn, tùy chỉnh Compose/env hoặc API Docker proxy.
- Agent có quyền root thực tế và Docker tương đương root. Giới hạn API giảm quyền cho UI,
  không thay thế security review. Chỉ cài source từ nguồn tin cậy; code/scripts/compose phải
  root-owned, không writable bởi user web. Không thêm user cá nhân khác vào group maychu247-ui.
- Cookie HttpOnly + SameSite Strict, session memory 1h, CSRF token + strict Host/Origin,
  10 lần thử đăng nhập/5 phút. Rate limit global phù hợp một quản trị viên, không đa khách hàng.
- HTTP chỉ trên loopback và SSH tunnel, cookie không Secure để hoạt động qua localhost HTTP.
  Chưa hỗ trợ HTTPS/reverse proxy/domain public. Không sửa kiểm tra Host/Origin để publish bừa.
- Chưa có MFA riêng trong UI; bảo vệ SSH key và quyền máy PC. Không mount socket agent vào
  app PHP/File Browser. Ai kiểm soát PC/SSH root có thể quản trị cả máy.

## Cài trên stack MayChu247 có sẵn

Không xóa database/secrets hoặc cài lại setup. Chép `dashboard/` và script mới vào
`/opt/maychu247-v2`, rồi:

```bash
sudo bash /opt/maychu247-v2/scripts/install-dashboard.sh
```

Script tạo tài khoản hệ thống riêng, cài code vào `/usr/local/lib/maychu247-dashboard`,
unit systemd và hash đăng nhập. Chỉ dừng portal Docker cùng project để nhường port 18000;
không dừng PHP/DB/MQTT hoặc `/opt/stack` cũ. Mật khẩu mới hiện một lần trên terminal: lưu riêng.
Không chạy đồng thời script cài/update và backup. Script không cài Cockpit hoặc thay firewall.
Phiên bản mới của compose để portal cũ sau profile `legacy-portal`; tuyệt đối không bật profile
đó cùng dashboard vì tranh port 18000. Không dùng hostname `portal:80` để truy cập dashboard
mới qua Cloudflare: dashboard mới chỉ hỗ trợ SSH forwarding.

Bộ cài một file mới tự gọi install-dashboard sau khi setup thành công; vẫn từ chối target cũ.
Nếu cài dashboard lỗi, PHP/SQL vẫn được giữ; xem systemctl/journal, không xóa volume để thử lại.

## Truy cập và xác minh

Trên PC:

```bash
ssh -L 18000:127.0.0.1:18000 -L 18080:127.0.0.1:18080 -L 18081:127.0.0.1:18081 -L 18082:127.0.0.1:18082 -L 13001:127.0.0.1:13001 kimdaihai@192.168.1.11
```

Mở **http://localhost:18000**, nhập mật khẩu dashboard (không phải password Ubuntu/DB).
Các ứng dụng Adminer/File Browser/Kuma vẫn có đăng nhập riêng; chưa có SSO. Tab PHP/SQL/Files
mở chúng qua những cổng SSH forward tương ứng. Kiểm tra CPU sau hai mẫu (khoảng 10 giây).
Nếu agent mất kết nối, giao diện báo dữ liệu cũ/lỗi, không hiển thị số liệu giả.

```bash
sudo systemctl status maychu247-dashboard maychu247-agent --no-pager
sudo journalctl -u maychu247-agent -u maychu247-dashboard -n 80
sudo ss -lntp | grep 18000
```

Chỉ thấy 127.0.0.1:18000. Thử đăng nhập sai, đăng xuất, kiểm tra status, thử restart riêng web
lúc chưa có dữ liệu quan trọng, chạy backup và kiểm tra COMPLETE/checksum bằng SSH. Kiểm tra
restore trên VM khác. Không xem việc nút bấm báo nhận lệnh là chứng nhận backup khôi phục được.

Backup chạy nền tuần tự, agent ghi trạng thái job trong RAM. Agent restart sẽ mất trạng thái job;
backup script có flock chống backup trùng, nhưng không được restart agent/deploy hoặc thao tác
container khi job chưa kết thúc. Không có timeout tự động cho backup: tránh để job con tiếp tục
ngầm sau timeout giả. Nếu job treo, quản trị viên kiểm tra process/log/lock qua SSH trước khi xử lý.
Backup từ timer/SSH không đồng bộ lock giao diện với service actions: không thao tác start/stop
trong lịch backup và không coi UI lock là phối hợp toàn bộ hệ thống.

## Quên mật khẩu / rollback

```bash
sudo bash /opt/maychu247-v2/scripts/reset-dashboard-password.sh
```

Sinh password mới, restart UI và thu hồi mọi phiên. Hash auth và systemd unit không nằm trong
snapshot Docker: sau phục hồi máy sạch cài lại dashboard, sinh mật khẩu mới. Không public secrets.

Rollback về portal liên kết cũ (không mất dữ liệu):

```bash
sudo systemctl disable --now maychu247-dashboard maychu247-agent
sudo bash -c 'cd /opt/maychu247-v2 && docker compose --profile legacy-portal up -d portal'
```

Nếu compose cũ chưa có profile, `docker compose up -d portal` vẫn mở lại portal cũ.
Không remove volume hoặc tài khoản/systemd một cách tự động. Chưa xác minh runtime systemd/Docker
trên server thực của bạn. Test HTTP auth/CSRF sử dụng agent giả, không chứng minh vận hành Docker.

## Nâng cấp bằng một file đã tải

File `downloads/MayChu247-Install.sh` hỗ trợ cả cài mới và nâng dashboard trên stack hiện có:

```bash
bash ~/MayChu247-Install.sh --check
sudo bash ~/MayChu247-Install.sh --update-dashboard
```

Gõ `UPDATE-DASHBOARD` sau khi đọc kế hoạch. Mode này không reset server: giữ nguyên .env,
SQL, MQTT và source dự án; sao lưu compose/scripts rồi đưa portal cũ vào profile legacy-portal,
cài UI thật. Không cập nhật PHP/Nginx tùy chỉnh. Khi đã có UI, cập nhật sẽ giữ password hiện có.
Không chạy khi backup/deploy đang hoạt động, kể cả timer hoặc lệnh SSH khác. Nếu compose đã
sửa khác baseline, updater từ chối để đối chiếu thủ công. Chưa có rollback tự động nếu cài
systemd lỗi; dùng phần rollback bên trên. Bộ cài mới (--install) vẫn từ chối thư mục đã tồn tại.

Ảnh giao diện đẹp không chứng minh tính đầy đủ; v1 ưu tiên số liệu thật, auth và ranh giới quyền.
Nghiệm thu các chức năng hiện có trước khi bổ sung GUI website/domain/MQTT ở bước tiếp theo.

## Guided workspace — hướng dẫn tiếng Việt trong giao diện

Tab **PHP / SQL / Files** có thẻ tác vụ, đường dẫn dự án, tài khoản mẫu không chứa mật khẩu
và nút đi thẳng tới đúng phần hướng dẫn. Tab **Hướng dẫn sử dụng** gồm:

1. SSH forwarding và phân biệt các tài khoản.
2. File Browser: xem log khởi tạo, đổi mật khẩu; không reset bằng cách xóa volume.
3. Tạo hello.php và kiểm tra website; không public phpinfo/.env.
4. Adminer: MySQL/db/appuser/appdb, đọc riêng DB_PASSWORD trên SSH, import/export an toàn.
5. Kuma: tạo monitor HTTP web:8080, TCP db:3306 và mqtt:1883; thông báo và kiểm tra Down/Up.
6. MQTT Explorer qua SSH, giới hạn worker/ACL chưa tích hợp.
7. Backup, timer, giới hạn COMPLETE và yêu cầu restore trên VM thử.

Nút “Sao chép” chỉ đưa nội dung vào clipboard (hoặc chọn nội dung nếu trình duyệt chặn),
**không thực thi lệnh**. Các câu lệnh đọc mật khẩu có cảnh báo, không gửi mật khẩu qua API.
Không có checklist tự nhận hoàn thành, badge giả hoặc auto-login bên thứ ba. Giao diện bên
trong các ứng dụng vẫn do từng dự án cung cấp; chọn ngôn ngữ trong ứng dụng nếu hỗ trợ.

Cập nhật qua cùng mode `--update-dashboard`, giữ nguyên mật khẩu/tài khoản hiện có.
Chỉ cập nhật source dashboard, không thay database, thiết lập Kuma hoặc theme app bên thứ ba.

## Sửa updater: TIME_WAIT và kiểm tra sau khởi động

Đã tái hiện lỗi updater cũ: dừng dashboard vừa phục vụ HTTP xong rồi dùng socket bind không
SO_REUSEADDR có thể nhận EADDRINUSE vì TIME_WAIT dù không còn process lắng nghe. Với set -e,
updater thoát sau khi dịch vụ đã dừng, gây connection refused qua SSH forwarding.

Bản sửa dùng SO_REUSEADDR giống HTTPServer, vẫn từ chối listener đang chạy thật. Trước khi
dừng dịch vụ, import server/agent/monitor và đọc auth/assets bằng user maychu247-ui. Sau khi
khởi động chờ HTTP GET / trả 200 và agent Unix ping ready=true. Nếu lỗi sau bước bắt đầu thay
live release, trap phục hồi code/unit trước đó và cố bật lại dịch vụ vốn active. Đây không phải
rollback database, không tự sửa bản cũ vốn đã hỏng và không bảo vệ mất điện giữa cập nhật.
Nguồn trong /opt có thể đã được updater thay trước đó; rollback chủ yếu phục hồi live release
ở /usr/local/lib và unit systemd. Backup compose/scripts ở backups/pre-dashboard-* vẫn giữ lại.

Updater cũng nhận diện socket cũ connection-refused khi agent không active để cho phép sửa;
nếu agent vẫn active hoặc job backup/status không rõ thì từ chối. Người quản trị vẫn phải bảo
đảm không có backup/deploy thủ công chạy ngầm. Mật khẩu, .env và volume không bị reset.

Regression test chạy chính đoạn bind của installer trên socket HTTP thực sau shutdown và
listener thực còn chạy. Các kiểm tra vị trí trap/readiness là static assertions; chưa mô phỏng
đầy đủ rollback systemd trên Ubuntu. Log server thực vẫn cần để kết luận nguyên nhân sự cố
của từng máy, không suy ra chỉ từ ảnh trình duyệt hoặc thông báo SSH channel refused.

## Native Project Explorer — file thật qua dashboard/domain

Tab **Tập tin** hiện có trình quản lý native, không cần File Browser riêng hoặc SSH cho các thao
tác được hỗ trợ. Dùng phiên dashboard hiện có, same-origin API, Host/Origin/CSRF giữ nguyên:

- Duyệt projects/, mở thư mục, breadcrumb và thư mục cha; tối đa 200 mục/lần.
- Upload file tối đa 1 MiB, không ghi đè tên trùng; không tự giải nén.
- Tạo file UTF-8 và thư mục bên trong vị trí đang mở.
- Đọc/tải xuống file tối đa 1 MiB; sửa văn bản tối đa 200 KiB, không soạn binary.
- Lưu có xác nhận và SHA256 version check, backup nội dung cũ rồi atomic replace + fsync.
  Lịch sử nằm trong .maychu247-history của cùng thư mục, tối đa 50 bản/thư mục; đến giới hạn
  sẽ từ chối sửa thay vì tăng vô hạn. Chưa có GUI phục hồi/dọn lịch sử. Không coi lịch sử cùng
  ổ đĩa là backup offsite. Không sửa đồng thời bằng app khác: version check chỉ phối hợp chắc
  chắn các lệnh đi qua agent lock, không cung cấp compare-and-swap với writer bên ngoài.

Root agent dùng directory fd + O_NOFOLLOW cho mọi thành phần; chỉ trong projects cố định,
không path tuyệt đối/.., symlink, file ẩn, socket/FIFO/device. Không có exec, đường dẫn host
tùy ý, xóa, đổi tên hoặc unpack archive. Tạo/upload/sửa code PHP là quyền triển khai ứng dụng:
chỉ cấp cho admin tin cậy, không cho khách lạ. Không thể loại trừ mọi lỗi hoặc tấn công chỉ vì
code tự viết. Code PHP vẫn chạy với quyền container, không thực thi qua shell root agent.

Luồng thường dùng: Tập tin → demo → public → File văn bản → hello.php → nhập mã → Tạo file.
Mở file để sửa và Lưu thay đổi thật; tạo folder/tải lên đều qua nút. Website chính phục vụ public
root này; folder dự án mới khác chưa tự có virtual host/domain. projects/ không bao gồm sites/
riêng và không có GUI toàn bộ filesystem. API không gửi password hoặc thực thi lệnh hướng dẫn.
File Browser cũ chưa bị xóa/dừng; luồng native không phụ thuộc nó và không yêu cầu password đó.
SQL Admin vẫn riêng, việc tạo database trực tiếp ở tab SQL không đồng nghĩa đã có native SQL editor.

Regression tests thực thi filesystem thật, bao gồm symlink/path traversal, binary/size limits,
no-overwrite, stale version, lịch sử, mode sau umask. Có HTTP test login/session/CSRF rồi qua
Unix broker thật tới filesystem tạm (không mock logic file ops). Chưa có browser visual test,
nghiệm thu systemd hoặc thao tác trên file dự án production của người dùng. SQL tests vẫn mock.

Cập nhật qua --update-dashboard giữ public.env, token và data; UI restart đăng xuất phiên cũ.
Sau cập nhật thử một file mới chưa quan trọng trong demo/public trước khi sửa code đang dùng.
