# MayChu247 v2 — Bộ triển khai độc lập cho Ubuntu

**Đây là cấu hình khởi điểm cần nghiệm thu, không phải chứng nhận production/HA.**
Không sửa hệ thống `/opt/stack` cũ; không nhập các mật khẩu đã lộ trong chat.
Chưa triển khai lên máy 192.168.1.11 và chưa đo tải thực tế. Cần Ubuntu 22.04/24.04,
Docker Engine + Compose v2, Python 3, `flock`, tar, SHA256, khoảng 4 GB RAM trở lên,
đĩa đủ chứa dữ liệu + ít nhất hai lần dung lượng backup. Chạy lệnh tại thư mục bộ cài.

## 1. Cài song song, không phá máy đang dùng

Từ máy đang có thư mục này, chép lên Ubuntu bằng tài khoản SSH của bạn:

```bash
scp -r homelab kimdaihai@192.168.1.11:~/maychu247-v2
ssh kimdaihai@192.168.1.11
# Chỉ chạy nếu /opt/maychu247-v2 chưa tồn tại:
sudo test ! -e /opt/maychu247-v2 && sudo cp -a ~/maychu247-v2 /opt/maychu247-v2
sudo chown -R "$USER:$USER" /opt/maychu247-v2
cd /opt/maychu247-v2
docker version
docker compose version
bash scripts/setup.sh
```

Nếu Docker yêu cầu quyền root: dùng `sudo bash scripts/setup.sh` và `sudo docker compose ...`.
Không tự động cài/upgrade Docker vì máy cũ đang chạy dịch vụ; cài Docker Engine/Compose
plugin từ hướng dẫn chính thức Docker cho Ubuntu nếu chưa có. Đừng chạy `docker system prune`
hoặc `docker compose down -v` trên máy có dữ liệu.

Bộ cài sinh `.env` 0600 và mật khẩu MQTT băm trong `secrets/`; không commit chúng.
Mật khẩu MQTT có thể xuất hiện ngắn trong argv của công cụ tạo mật khẩu bên trong container;
chỉ chạy trên máy tin cậy. Nếu bước pull/build lỗi, kiểm tra `.env`, `secrets/mqtt.passwd`;
không xóa chúng để sinh lại bừa bãi. Sau khi sửa lỗi, dùng `docker compose up -d --build`.

## 2. Mở giao diện an toàn (giống bộ công cụ XAMPP)

Mặc định **tất cả cổng chỉ bind 127.0.0.1**, SQL không publish cổng host.
Trên PC mở terminal (giữ kết nối):

```bash
ssh -L 18000:127.0.0.1:18000 -L 18080:127.0.0.1:18080 -L 18081:127.0.0.1:18081 -L 18082:127.0.0.1:18082 -L 13001:127.0.0.1:13001 kimdaihai@192.168.1.11
```

Mở `http://localhost:18000` trên PC:

| Công cụ | Cổng host | Dùng để |
|---|---:|---|
| Portal | 18000 | Liên kết công cụ, không có quyền điều khiển Docker |
| PHP + Nginx | 18080 | PHP-FPM + OPcache, mẫu kiểm tra DB |
| Adminer | 18081 | MariaDB server `db`, database `appdb`, user `appuser`, mật khẩu trong `.env` |
| File Browser | 18082 | Upload/chỉnh sửa trong `projects/` (chỉ cấp cho admin tin cậy) |
| Uptime Kuma | 13001 | Giám sát và thông báo, tạo admin ngay lần đầu |

File Browser bản được dùng sinh mật khẩu ban đầu trong log: `docker compose logs files`.
Nếu không có mật khẩu sinh tự động, kiểm tra hướng dẫn phiên bản image trước khi mở truy cập;
không mặc định rằng có bảo vệ. Đổi mật khẩu, tắt đăng ký và hoàn thành thiết lập Kuma qua SSH
**trước khi** bật tunnel. File Browser chạy root trong container để ghi bind mount: có thể tạo file
root-owned; chỉ mount thư mục projects, không mount Docker socket/host root. Không cho người lạ dùng.

### Thêm dự án PHP

Mã public ở `projects/demo/public`; secret ứng dụng ở ngoài public. Nginx đọc mã read-only,
File Browser có quyền ghi. Dự án cần thư mục upload/cache phải thêm mount writable riêng và
quyền phù hợp UID container; không `chmod 777` toàn cây. Composer/framework dependencies
nên build vào image riêng, không cài package tùy tiện mỗi lần khởi động.

Để có nhiều website, thêm server block vào `config/nginx.conf` theo `server_name` và root
`/var/www/projects/<ten>/public`, tạo database/user riêng với quyền tối thiểu bằng Adminer
(root chỉ dùng quản trị). Sau đó `docker compose restart web`. Không phục vụ nguyên thư mục
chứa `.env`, vendor config hay backup. Web hiện dùng `appdb`, không tự nhập SQL dự án cũ.

## 3. MQTT và worker

Mosquitto có persistence, anonymous bị tắt. Tài khoản `mqttuser` dùng mật khẩu mới trong `.env`.
TCP trong Docker `mqtt:1883`, WS `mqtt:9001`. Thiết bị LAN cần thay **BIND_IP thành IP LAN máy
chủ** rồi `docker compose up -d`; thao tác này cũng mở các UI trên LAN — chỉ làm khi firewall
đã giới hạn đúng IP quản trị. Tốt hơn: chỉnh riêng binding MQTT về IP LAN trong compose.
Host MQTT dùng **1884** để không tranh cổng 1883 của hệ thống cũ. Không port-forward ra WAN.

Dùng MQTT Explorer trên PC (SSH forward cổng 1884 hoặc LAN bảo vệ) để quản lý topic/publish:
`home/sensor/data`, payload `{"device_id":"ESP32_01","temp":30.5,"hum":70}`.
Thiết bị quan trọng cần mỗi thiết bị một user + ACL topic riêng, TLS/VPN cho TCP qua mạng không tin cậy,
QoS 1, giới hạn payload, reconnect/backoff, lưu đệm offline và chống ghi trùng database.
Cấu hình mẫu có **một user chung, chưa có ACL theo thiết bị**, không phải broker đa khách hàng.

Worker MQTT→SQL phụ thuộc code dự án, **chưa được kèm/tự chạy**. Không sao chép lệnh
`docker exec -d` cũ. Thêm service worker dùng image PHP có thư viện MQTT của dự án,
command `php /app/worker.php`, `restart: unless-stopped`, healthcheck/heartbeat và DB credentials
riêng. Worker phải kiểm tra JSON, dùng prepared statements và xử lý idempotency/transaction.

## 4. Cloudflare và chuyển đổi

Tunnel **không thay thế đăng nhập**. Cấu hình Cloudflare Access chỉ cho email quản trị vào
portal/files/adminer/kuma; web public theo chính sách ứng dụng. MQTT client WebSocket có thể
không hỗ trợ màn đăng nhập Access: dùng hostname/policy riêng và xác thực broker, không tắt
bảo vệ toàn bộ nhóm admin. WS public dùng `wss://mqtt-v2.maychu247.uk`.

Nếu dùng tunnel mới trong bộ này: đặt TUNNEL_TOKEN trong `.env` (không gửi chat), rồi:

```bash
docker compose --profile tunnel up -d
```

Trong Cloudflare đặt hostname thử nghiệm:

| Host ví dụ | Origin trong tunnel mới |
|---|---|
| v2.maychu247.uk | http://web:8080 |
| panel-v2.maychu247.uk | http://portal:80 |
| sql-v2.maychu247.uk | http://adminer:8080 |
| files-v2.maychu247.uk | http://files:80 |
| status-v2.maychu247.uk | http://kuma:3001 |
| mqtt-v2.maychu247.uk | http://mqtt:9001 |

Sửa các link portal sang hostname tương ứng khi dùng tunnel. Tunnel cũ ở network khác
**không tự phân giải** `web/db/mqtt` mới: dùng tunnel mới riêng (khuyến nghị) hoặc origin tới
host/cổng phù hợp sau khi thiết kế mạng. Không dùng chung token để vô tình đưa connector cũ
và mới vào cùng tunnel với cấu hình origin khác nhau.

Migration: backup stack cũ và SQL → import vào database mới qua Adminer → chép mã nguồn →
kiểm tra uploads, cron, worker, MQTT ACL → thử hostname v2 → đổi origin hostname chính.
Giữ nguyên stack cũ để rollback origin. Không cho hai worker cùng ghi một luồng nếu chưa chống
trùng. Không chạy hai tác vụ scheduled/email/payment đồng thời. Bộ này **không tự migrate** dữ liệu.

## 5. Giám sát và vận hành

Trong Kuma tạo monitor HTTP `http://web:8080` (PHP mẫu trả 503 nếu DB lỗi), TCP `db:3306`,
MQTT `mqtt:1883` với credentials/topic thử, HTTP `http://portal:80`; cấu hình email/Telegram
và thử cảnh báo thật. Không chỉ theo dõi trang chủ 200: cần heartbeat worker và độ trễ xử lý.
Kuma cùng máy không báo được khi cả máy mất điện/mạng: thêm monitor từ bên ngoài.

```bash
docker compose ps
docker compose logs --tail 100 web db mqtt
free -h; df -h
systemctl list-timers maychu247-backup.timer
journalctl -u maychu247-backup.service -n 80
```

MariaDB buffer pool mặc định 256MB, chỉnh theo RAM sau khi đo. OPcache được cài, xác minh
cấu hình thực tế của image trước khi tối ưu. Không hứa tốc độ khi chưa load-test: đo p95 latency,
CPU/RAM/IO, query chậm, MQTT throughput/QoS với tải dự án. Không tự update image; trước nâng
cấp: backup, thử trên bản sao, pin image digest đã nghiệm thu và có kế hoạch rollback.
Tags hiện là baseline tiện triển khai, không phải lockfile bất biến.

## 6. Backup tự động + khôi phục

```bash
sudo bash scripts/backup.sh                 # chạy thử trước
sudo bash scripts/install-backup-timer.sh   # mỗi ngày 03:15 giờ máy chủ, giữ 14 ngày
```

Backup có SQL toàn bộ, source, cấu hình/secret, MQTT persistence, Kuma, File Browser DB.
Script **dừng web/MQTT/Kuma/File Browser trong lúc chụp**, DB dump transactional khi không
có DDL/writer ngoài stack. Có gián đoạn; lịch cần tránh giờ cao điểm. Nếu cần RPO vài phút,
zero downtime hoặc point-in-time recovery phải bổ sung binlog, replica và thiết kế HA riêng.
Timer chạy bù sau downtime. Không tự restore production định kỳ vì có thể xóa dữ liệu mới.

Snapshot `backups/<UTC timestamp>/` có checksum, chỉ báo thành công khi đủ file.
Giữ 14 ngày trên cùng ổ **không chống mất ổ/ransomware**. Phải thêm bản sao offsite:
mã hóa bằng restic/Borg hoặc kho backup tin cậy, giữ khóa giải mã ngoài máy, kiểm tra mỗi ngày
bản mới nhất đã upload. Offsite chưa cấu hình do chưa biết đích lưu/credentials.
Không đưa `.env`, snapshot hay token lên Git/Drive công khai. Checksum chỉ phát hiện hỏng,
không xác thực snapshot do người lạ cung cấp.

### Diễn tập restore hàng tháng (máy thử, không phải production)

1. Chép nguyên thư mục bộ triển khai và snapshot sang VM Ubuntu riêng có Docker.
2. Không bật tunnel trên máy thử, không gắn worker/thiết bị thật. Chỉ restore backup bạn tin cậy.
3. Với stack thử mới/chưa có data volume: chạy lệnh dưới, database được khởi tạo bằng secret snapshot.
4. Nếu restore tại chỗ, mật khẩu root của volume DB hiện có phải trùng snapshot; nếu khác,
   dừng và xử lý quyền truy cập có kiểm soát. Script không xóa volume DB tự động.

```bash
sudo bash scripts/restore.sh /duong/dan/snapshot --confirm-overwrite
```

Restore dừng stack, ghi đè cấu hình/source, import SQL và thay nội dung các volume phụ.
SQL toàn bộ từ dump không xóa những database/bảng phát sinh ngoài dump trong volume hiện tại;
khôi phục sạch nên dùng VM/volume mới. Script giữ bản cấu hình trước restore, **không phải
backup đầy đủ dữ liệu hiện tại**: chạy backup.sh trước mọi restore thực tế. Nếu lỗi giữa chừng,
stack có thể vẫn dừng; không tự bật traffic. Kiểm tra log, sửa lỗi và thử lại có kiểm soát.
Sau restore thử: kiểm tra số bản ghi, file upload, đăng nhập UI, retained MQTT, publish/subscribe,
thông báo và thời gian khôi phục. Ghi lại RTO/RPO đo thực tế. Chỉ sau đó mới coi backup đạt.

## Phạm vi

Không có quyền SSH từ môi trường phát triển này; chưa chạy Docker trên máy chủ của bạn.
Không có shell web/Portainer toàn quyền vì cần Docker socket tương đương root. Giao diện
quản lý gồm PHP files, SQL, giám sát và MQTT qua MQTT Explorer; start/stop container qua SSH.
Đây là một máy chủ đơn, không tự failover; dự án quan trọng cần UPS, offsite và giám sát ngoài.

## 7. Security Center và hosting nhiều domain

- Portal có **Security Center** tại `/security.html`: liên kết Cockpit, hướng dẫn firewall,
  MFA và cách ly; không giả lập trạng thái “an toàn” hay thực thi lệnh root từ web.
- Đọc [SECURITY.md](SECURITY.md) trước khi cài Cockpit hoặc thay firewall trên máy cũ.
- Đọc [MULTISITE.md](MULTISITE.md) để tạo website/database riêng theo gói starter/business/critical,
  gắn domain và backup từng site. Script `create-site.py` chỉ tạo sau `--write`, không tự chạy Docker.
- Timer mới gọi `backup-all.sh` bao gồm stack chính + sites. Timer đã cài trước cần chỉnh unit
  có kiểm soát theo MULTISITE.md. Site snapshot dùng quy trình restore riêng, không dùng restore.sh.

## 8. Bộ cài một file

File tải về: `downloads/MayChu247-Install.sh` (build lại từ source bằng
`python3 scripts/build-installer.py`). Chỉ chứa file cấu hình/code được cho phép, không có
mật khẩu, token, backup hoặc site đang vận hành. Embedded checksum kiểm tra hỏng file,
không thay thế chữ ký/xác thực nguồn phát hành. Chỉ chạy file từ nguồn bạn tin cậy.

```powershell
# Windows PowerShell tại thư mục Downloads của PC:
scp .\MayChu247-Install.sh kimdaihai@192.168.1.11:~/
ssh kimdaihai@192.168.1.11
```

Trên Ubuntu:

```bash
bash ~/MayChu247-Install.sh --check
sudo bash ~/MayChu247-Install.sh --install
```

Đọc kế hoạch rồi gõ `CAI-SONG-SONG` để xác nhận. Bộ cài từ chối target đã tồn tại,
project/container/volume trùng tên và port bị chiếm. Không ghi đè `/opt/stack`, không cài
Docker/host packages, không sửa SSH/firewall/domain, không tự nhập dữ liệu. Docker pull/build
cần Internet và tài nguyên dự phòng. Nếu lỗi giữa chừng, giữ nguyên cấu hình/secret để kiểm tra,
không tự xóa `.env`, volume hoặc chạy lại bằng cách xóa thư mục. Dịch vụ đang khởi động chưa
đồng nghĩa đã khỏe: kiểm tra health/log và ứng dụng trước khi chuyển traffic.

### Sửa lỗi build PHP ở bản cài ban đầu

Image `trafex/php-nginx:3.8.0` dùng PHP **8.4**, `/etc/php84` và socket
`/run/php-fpm.sock`. Bản cấu hình ban đầu nhầm PHP 8.3/TCP 9000; đã sửa cả Dockerfile,
Nginx và route ping cho healthcheck. Nếu bộ cài dừng tại bước build, **không xóa `.env`,
secrets hoặc volume và không chạy lại setup để sinh mật khẩu mới**. Sao lưu hai file
`php/Dockerfile`, `config/nginx.conf`, thay bằng bản mới rồi tại thư mục stack chạy:

```bash
sudo docker compose config --quiet
sudo docker compose up -d --build
sudo docker compose ps
sudo docker compose logs --tail 80 web
curl --fail http://127.0.0.1:18080/
```

Chỉ nghiệm thu khi PHP mẫu báo kết nối DB thành công và healthcheck khỏe. Site tạo trước
bản sửa có bản sao riêng: cập nhật hai file tương ứng trong từng `sites/<ten>/` và rebuild
ở đúng thư mục site. Không thay cấu hình Nginx tùy chỉnh mà chưa sao lưu và đối chiếu.
Đã xác minh hợp đồng qua source upstream 3.8.0 và static tests; chưa build Docker tại sandbox.
