# Nhiều website, database và domain riêng

Có thể tạo cấu hình qua **Website & Domain → Tạo website mới** hoặc CLI dưới đây.
Tạo form chỉ ghi cấu hình; sau đó có nút Chạy / triển khai (build/up web + db), Dừng và Kiểm tra origin. Không tự tạo DNS và không phải hệ thống billing/provisioning hoàn chỉnh.
Không cấp khách quyền Cockpit/File Browser của stack chính. Mỗi site là một Compose project
riêng, network riêng, MariaDB riêng, database `appdb`/user `appuser` nhưng secret khác nhau.
Không chia sẻ PHP process hoặc DB instance giữa các site.

## Chạy thử chưa có domain

Trong form tạo site chọn URL tạm. Nó chỉ tạo metadata `.preview.invalid`, không phải DNS thật.
Sau khi upload/giải nén source, bật riêng DB ở tab SQL để import .sql, rồi triển khai web và kiểm
tra origin. Bấm Tạo / đọc URL tạm, xác nhận PUBLIC để Quick Tunnel cấp URL trycloudflare.com.
Nút Dừng URL tạm ngắt container thử riêng, không thay connector chính. URL công khai, không có
Access/SLA/địa chỉ ổn định, không dùng dữ liệu nhạy cảm. Xem DASHBOARD.md để biết giới hạn và
trường hợp container có thể còn công khai sau timeout. Chưa nghiệm thu live Cloudflare từ suite.

## Gói mẫu

| Gói | PHP CPU / RAM | DB CPU / RAM | DB connections |
|---|---|---|---|
| starter | 0.5 / 256MB | 0.5 / 512MB | 30 |
| business | 1 / 512MB | 1 / 1024MB | 60 |
| critical | 2 / 1024MB | 2 / 2048MB | 100 |

Giới hạn là cgroup CPU/RAM/PID của Compose, không phải SLA hoặc reservation. OS, stack quản lý,
Docker và page cache cần RAM/CPU dự phòng. Tính tổng trước khi bán gói, không oversubscribe
RAM; OOM kill sẽ làm ứng dụng ngừng hoạt động. Giới hạn kết nối DB không phải số visitor.
Chưa có quota dung lượng đĩa/IO/network: dùng filesystem project quota hoặc VM/disk riêng
nếu cung cấp dịch vụ có quota bắt buộc. Không hứa lưu trữ vô hạn. Chưa đo throughput/latency.

## Luồng GUI khuyến nghị

Tạo website → Chạy / triển khai → theo dõi Job → Kiểm tra origin. Chọn site trong tab File/SQL
để quản lý projects/ và MariaDB riêng bằng phiên dashboard. SQL console dùng appuser; không
hiện password ra browser. Xem DASHBOARD.md về giới hạn file/trash/chmod/SQL và kiểm thử.

Domain: Cloudflare Zero Trust GUI → Tunnel **host** đang hoạt động → thêm published application
route cho hostname site → HTTP → 127.0.0.1:<port site>. Không sửa maychu247.uk → 18000.
Đây là thao tác Cloudflare GUI, không phải nút tự cấu hình DNS trong dashboard; chưa có API
credential để tự tạo route. Origin HTTP 200 không phải chứng nhận DNS/HTTPS đã hoạt động.

Các lệnh bên dưới chỉ là phương án bảo trì cho quản trị viên, không phải luồng bắt buộc của
người dùng dashboard. Không chạy chúng đồng thời với job đang chạy từ GUI.

## 1. Tạo website (phương án CLI cho quản trị viên)

```bash
cd /opt/maychu247-v2
python3 scripts/create-site.py shop --domain shop.example.com --package business --port 20001
# Đọc kế hoạch rồi mới duyệt:
python3 scripts/create-site.py shop --domain shop.example.com --package business --port 20001 --write
cd sites/shop
docker compose config --quiet
docker compose up -d --build
docker compose ps
curl --fail http://127.0.0.1:20001/
```

Chạy bằng cùng tài khoản sở hữu bộ cài (hoặc sudo phù hợp Docker). Script không đổi DNS,
không thực thi Docker và không mở firewall. Tên site/domain/port được kiểm tra, từ chối trùng
trong inventory này; vẫn cần kiểm tra xung đột với hệ thống ngoài inventory. Không chạy hai
lệnh tạo site đồng thời. `--write` không ghi đè site tồn tại. Nếu port đã bind trên máy này sẽ từ
chối, nhưng vẫn có thể bị tiến trình khác chiếm sau khi generate; kiểm tra log khi khởi động.
Thư mục sites 0700, `.env` 0600; chỉ admin được đọc. `sites/` đã được ignore khỏi Git.

Mỗi site là bản sao cấu hình lúc tạo. Thay `packages.json` chỉ ảnh hưởng site **tạo mới**;
đổi gói site cũ phải sửa cpus/mem_limit/db config có backup, kiểm tra `docker compose config`
và recreate trong lịch bảo trì. Không tự hạ RAM của DB đang chịu tải.

## 2. Mã nguồn và SQL

Thay `sites/shop/projects/demo/public/` bằng public root app. Private code/config ở ngoài public;
composer dependencies build riêng. App nhận `DB_USERNAME=appuser`, `DB_PASSWORD` từ environment,
host `db`, database `appdb`. Nếu app có schema/worker/Redis khác phải bổ sung rõ ràng.
Uploads/cache cần writable mount riêng, backup script cần bao phủ mọi mount mới.
Không dùng File Browser của stack chính để xem site khác: nó chỉ mount `homelab/projects`.
Dashboard native cho phép chọn site để quản lý projects/ và SQL riêng. Ngoài ra quản trị viên có thể dùng SFTP/pipeline tin cậy; chưa có SFTP account bị chroot theo khách.

Quản lý SQL từ PC qua SSH, không public SQL. Ví dụ thêm Adminer tạm trong đúng project:

```bash
cd /opt/maychu247-v2/sites/shop
# Chỉ khi mạng site-shop_default đã tồn tại; kiểm tra bằng docker network ls.
docker run --rm --name shop-sql-admin \
  --network site-shop_default -p 127.0.0.1:21001:8080 \
  -e ADMINER_DEFAULT_SERVER=db adminer:4
```

Mở SSH forward `-L 21001:127.0.0.1:21001` trên PC, truy cập `http://localhost:21001`.
Nhập server `db`, user `appuser`, database `appdb`, mật khẩu site `.env` (không root để làm việc
thường ngày). Dừng container Adminer khi dùng xong. Không nối network nhiều tenant vào một UI.
Không đưa credentials vào URL, shell history hay log công khai.

## 3. Gắn domain

Mỗi site có tunnel tùy chọn riêng để không gộp network DB các site:

1. Xác minh sở hữu domain và DNS trên Cloudflare (hoặc thiết kế reverse proxy khác).
2. Tạo **tunnel riêng cho site**, đặt token vào `sites/shop/.env`, không dùng token stack cũ.
3. `docker compose --profile tunnel up -d` tại site.
4. Public Hostname `shop.example.com` → HTTP `web:8080` của tunnel site đó.
5. Thử HTTPS, redirects, login, uploads, DB, app base URL; đóng hostname cũ sau nghiệm thu.

`--domain` chỉ lưu inventory, **không tạo DNS/API**. Có thể thêm www/alias ở cùng tunnel,
nhưng phải cập nhật app allowed hosts/cookie/CSRF/redirect policy. Nginx mặc định site này
chấp nhận mọi Host vì chỉ có một app; app nên kiểm tra hostname cho reset-password và URL generation.
Dùng Access MFA cho admin; website public vẫn phải có auth ứng dụng nếu cần.
Dùng tunnel riêng tiêu tốn thêm process; nếu hàng trăm site cần thiết kế ingress tập trung với
network riêng từng frontend, không đưa các database lên một shared network.

Không có domain vẫn thử qua SSH `-L 20001:127.0.0.1:20001`. Domain ở DNS khác cần quyết định
chuyển DNS/tunnel routing hoặc reverse proxy TLS trước; không tự mở 80/443 trên server cũ.

## 4. Backup mọi site

```bash
cd /opt/maychu247-v2
sudo bash scripts/backup-site.sh shop    # một site, dừng PHP ngắn để chụp
sudo bash scripts/backup-all.sh          # stack chính và từng site tuần tự
```

Timer mới cài từ `install-backup-timer.sh` gọi `backup-all.sh` mỗi ngày, giữ từng nơi 14 ngày.
Nếu timer cũ đã cài, script không ghi đè: kiểm tra `systemctl cat maychu247-backup.service`,
sao lưu unit rồi đổi ExecStart sang `/opt/maychu247-v2/scripts/backup-all.sh`, daemon-reload.
Kiểm tra `journalctl -u maychu247-backup.service` và cảnh báo nếu exit != 0/mất snapshot.
Từng site có khóa backup riêng; không chạy backup/restore thủ công đồng thời với thao tác deploy.
Snapshot site có SQL all-databases, code và secret/config; chưa bao gồm volume bổ sung ngoài mẫu.
Tunnel vẫn chạy, nhưng web tạm dừng; client có thể thấy 502 trong maintenance window.
SQL transactional chỉ an toàn khi không còn writer/DDL ngoài web được dừng; worker phải dừng
riêng trước backup hoặc thiết kế consistent snapshot cho ứng dụng.

**Offsite chưa cấu hình**: mã hóa rồi đồng bộ mỗi `sites/*/backups` cùng snapshot stack chính.
Backup-all không có nghĩa là transaction nhất quán giữa nhiều website. App phụ thuộc chéo cần
maintenance đồng bộ riêng. Không tự restore production định kỳ; chỉ diễn tập trên VM thử.

## 5. Khôi phục site lên VM thử sạch

Không dùng `restore.sh` của stack chính cho snapshot site (format khác). Quy trình quản trị,
chỉ dùng snapshot tin cậy; tar có quyền ghi file. Làm trên **VM không có traffic/tunnel thật**:

1. Chép snapshot nguyên thư mục sang VM thử, đặt biến `SNAPSHOT` tới đường dẫn tuyệt đối.
2. `(cd "$SNAPSHOT" && sha256sum -c SHA256SUMS)` và kiểm tra có COMPLETE.
3. Tạo thư mục phục hồi rỗng, `tar xzf "$SNAPSHOT/site.tgz" -C /duong/dan/site-thu`.
4. Xóa giá trị TUNNEL_TOKEN trong `.env` bản thử, không bật profile tunnel. Chạy compose trong
   thư mục phục hồi; **volume/project site cùng tên phải chưa tồn tại trên VM thử**.
5. `docker compose up -d db`; chờ `docker compose exec -T db healthcheck.sh --connect --innodb_initialized` thành công.
6. Import: `docker compose exec -T db sh -c 'exec mariadb -uroot -p"$MARIADB_ROOT_PASSWORD"' < "$SNAPSHOT/database.sql"`.
7. `docker compose up -d --build web`; thử PHP, auth, số bản ghi, file upload và business flow.

SQL dump toàn bộ không tự xóa database/bảng thừa khi import vào DB đã tồn tại; dùng volume
mới để restore sạch. Không chạy `down -v` trên production. Khi phục hồi production thật cần
backup hiện trạng trước, maintenance, kiểm tra secret, migration phiên bản, và phê duyệt chuyển
tunnel/DNS. Lưu thời gian RTO/RPO đo được, không suy ra từ việc dump hoàn thành.

## 6. Giới hạn cách ly

Docker dùng chung kernel. Một tài khoản Docker/sudo hoặc Cockpit admin đọc được tất cả site.
Tên gói critical không tạo HA, WAF riêng, offsite hay SLA. Khách hàng không tin cậy/cần cách ly
pháp lý: VM riêng + tài khoản admin/network/backup riêng. Chưa có UI cấp gói, thu tiền, quota
đĩa cứng hay tự cài certificate cho reverse proxy ngoài Cloudflare.
