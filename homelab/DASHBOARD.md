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
