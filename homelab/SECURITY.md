# Security Center — bảo vệ nhiều lớp, không có “an toàn tuyệt đối”

Trang `/security.html` trong portal là bảng hướng dẫn tĩnh. **Không có backend thay đổi
firewall/SSH**, không biết tình trạng live và không hiển thị huy hiệu “đã an toàn”.
Giao diện quản trị host thật là Cockpit (cài tùy chọn trên Ubuntu). Không mount Docker socket
vào web UI. Thực hiện theo thứ tự, có console VM/hypervisor cứu hộ và backup đã thử restore.

## 1. Trước khi mở thêm dịch vụ

- Thay mọi mật khẩu/token từng chia sẻ; mỗi domain/ứng dụng có secret riêng.
- Cập nhật Ubuntu sau khi kiểm tra tương thích và đặt lịch bảo trì/reboot có giám sát.
- SSH key riêng cho người quản trị, tài khoản thường + sudo. Thử key trong **phiên SSH mới**
  trước khi tắt password/root login. Không ghi đè sshd_config bằng script tải trên mạng.
- Khi chỉnh sshd_config.d: `sudo sshd -t`, xem `sudo sshd -T` (và `-C` để kiểm tra Match),
  rồi reload đúng ssh service; giữ phiên cũ, thử phiên mới, chuẩn bị rollback qua console.
- Không áp chính sách SSH/FIDO2 bắt buộc nếu chưa có key dự phòng và phương án khôi phục.
- Bật MFA/passkey tại Cloudflare, Access chỉ cho email quản trị; không public trang setup UI.
- Application-level auth vẫn cần thiết; Cloudflare Tunnel không tự tạo chính sách Access.

## 2. Cockpit — GUI quản trị host (tùy chọn)

Cockpit là quyền quản trị hệ điều hành, không cho khách thuê web truy cập. Cài riêng sau khi
người vận hành chấp thuận; **bộ cài homelab không tự cài package host**.
Trên Ubuntu dùng gói do distro cung cấp; kiểm tra nguồn và phiên bản hỗ trợ:

```bash
sudo apt update
sudo apt install cockpit
```

Cài gói có thể tự kích hoạt socket. Trước cài cần firewall/ACL hạ tầng chặn port 9090 từ LAN/WAN;
không NAT port này trên router. Ngay sau cài cấu hình socket chỉ nghe loopback:

```bash
sudo systemctl stop cockpit.socket cockpit.service
sudo mkdir -p /etc/systemd/system/cockpit.socket.d
# Nếu file này đã tồn tại: đọc và sao lưu trước, không ghi đè cấu hình cũ.
sudo test ! -e /etc/systemd/system/cockpit.socket.d/listen.conf && \
  printf '[Socket]\nListenStream=\nListenStream=127.0.0.1:9090\n' | \
  sudo tee /etc/systemd/system/cockpit.socket.d/listen.conf
sudo systemctl daemon-reload
sudo systemctl enable --now cockpit.socket
sudo ss -lntp | grep 9090
```

**Chỉ tiếp tục nếu chỉ thấy 127.0.0.1:9090, không thấy 0.0.0.0 hoặc [::].**
Nếu cấu hình trước đã tồn tại, chỉnh có kiểm soát rồi restart socket; không coi lệnh trên là
xác nhận thành công tự động. Trên PC:

```bash
ssh -L 19090:127.0.0.1:9090 kimdaihai@192.168.1.11
```

Mở `https://localhost:19090` hoặc nút Cockpit ở Security Center. Dùng tài khoản Ubuntu không
phải root; chỉ nâng quyền khi cần. Chứng chỉ mặc định tự ký: đối chiếu fingerprint tại console
hoặc cấp certificate tin cậy; không bỏ qua cảnh báo cho hostname bất kỳ. Không cấu hình
`AllowUnencrypted`, không thêm wildcard Origins và không public Cockpit qua tunnel mặc định.
Nếu bản Cockpit từ chối forwarded origin, xem cấu hình chính thức cho phiên bản đã cài,
chỉ allow đúng `https://localhost:19090` nếu cần; không vô hiệu CSRF/auth.

Cockpit quản lý dịch vụ, log, tài khoản, CPU/RAM/storage tùy module đã cài. Cockpit không
cung cấp hosting billing hay UI quản trị Docker đầy đủ. Dừng/khởi động site bằng SSH.

## 3. Firewall — có GUI, nhưng không chuyển đổi mù quáng

**Chọn một chủ sở hữu firewall:** UFW đang có thì giữ UFW; host dùng firewalld thì Cockpit
có trang Networking/Firewall khi module và quyền phù hợp. Cockpit không cung cấp UFW GUI
chính thức. Không cài/bật firewalld chồng UFW chỉ để có giao diện.

Với host cũ dùng UFW: quản lý UFW qua SSH và đọc trạng thái bằng `security-audit.sh`.
Với host mới muốn GUI firewalld: chuẩn bị qua console trực tiếp, cài các gói distro
`firewalld` và `cockpit-networkmanager` sau khi kiểm tra package availability. **Không kèm
lệnh chuyển đổi tự động** vì interface/zone/SSH port và mạng cũ chưa biết. Ghi lại rules hiện tại,
cho phép IP quản trị + SSH port thật ở đúng zone trước khi enable; thử phiên SSH thứ hai,
chặn cổng dư và kiểm thử từ LAN/WAN. Không disable firewall cũ trước khi có đường cứu hộ.

Chính sách đích:

| Dịch vụ | Truy cập |
|---|---|
| SSH | Chỉ VPN/LAN quản trị hoặc IP allowlist; key auth |
| Cockpit | Loopback + SSH forwarding |
| SQL, Redis, Docker API | Không publish ra host/WAN |
| Web public | Cloudflare Tunnel outbound; không cần mở inbound 80/443 |
| Adminer, File Browser, Kuma | SSH hoặc Access MFA; tài khoản riêng |
| MQTT TCP | Mạng IoT/VPN được phép; TLS khi qua mạng không tin cậy |
| MQTT WebSocket | WSS + xác thực broker + ACL; chính sách riêng cho client |

**Cảnh báo Docker:** published ports có thể đi qua chain NAT/FORWARD, vượt qua kỳ vọng
UFW INPUT. Không chỉ dựa vào “deny incoming”. Ưu tiên loopback binding, mạng riêng, ACL
router; nếu cần lọc traffic Docker phải thiết kế đúng DOCKER-USER với backend iptables,
hoặc chính sách nftables tương ứng với phiên bản Docker hiện có. Không paste rules tùy tiện:
có thể chặn tunnel, inter-container hoặc SSH. Kiểm thử thực từ máy khác sau mỗi thay đổi.

## 4. Website/data, chống chiếm quyền và rò rỉ chéo

- Dùng `create-site.py` thay vì dồn tất cả khách vào cùng PHP process/database user.
- Không mount host root, socket Docker, thư mục secret của site khác.
- Mỗi site có database volume/network/secret riêng; quản lý không publish SQL.
- Nginx chỉ phục vụ public root, giới hạn upload; framework phải validate file upload,
  không cho upload script thực thi. Dùng prepared statements, CSRF/session protection,
  Argon2id cho password app nếu framework hỗ trợ; không tự viết auth.
- Rate limit/bot/WAF qua Cloudflare theo gói đang có; thử rule ở chế độ log trước để tránh
  chặn nhầm. HSTS chỉ bật sau khi toàn bộ hostname hoạt động HTTPS; CSP thiết kế theo app.
- Gói critical **không tự có HA/SLA**. Với khách thuê không tin cậy/payment dữ liệu nhạy cảm,
  VM riêng, database riêng, network policy và đánh giá chuyên gia theo yêu cầu pháp lý.
- AppArmor/seccomp mặc định Docker không được tắt; rootless/userns cần thử tương thích
  với volume và networking trước. Không quảng cáo PCI/ISO đạt chuẩn chỉ từ compose này.

## 5. Phát hiện và khôi phục

Chạy `sudo bash scripts/security-audit.sh` để xem quan sát chỉ đọc. Script không quét CVE,
không đọc effective SSH policy hoặc chứng minh firewall đúng. Đừng chia sẻ output công khai
vì có địa chỉ mạng và inventory. Có thể bổ sung Trivy, auditd, Fail2ban/IDS sau khi xác định
log nguồn, tài nguyên và kênh cảnh báo; không tự cài agent quyền root từ nguồn bất kỳ.

Kiểm tra hàng ngày: backup mới nhất + offsite, disk/inode, lỗi đăng nhập, TLS và cảnh báo.
Kiểm tra hàng tháng: restore trên VM thử, revoke user/key không dùng, update staging/image scan.
Khi nghi bị xâm nhập: cô lập qua hypervisor/router, bảo toàn log/snapshot, rotate secret từ
máy sạch và rebuild từ nguồn tin cậy; không chỉ đổi password rồi bật lại máy cũ.
