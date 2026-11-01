# Domain cho dashboard, không phải website PHP

## Cài một lần

1. Cập nhật dashboard bằng bộ cài mới, mode --update-dashboard. Xác minh HTTP/agent readiness.
2. Chọn `panel.maychu247.uk` để không tranh hostname website chính.
3. Cloudflare Access: tạo Self-hosted Application cho **toàn bộ hostname** panel.maychu247.uk,
   không giới hạn path. Policy chỉ Allow email quản trị cụ thể, không Everyone/Bypass. Bật MFA
   ở nhà cung cấp danh tính được dùng. Email OTP đơn thuần không mặc nhiên là MFA.
4. Tạo **Tunnel mới riêng** (không tái dùng token tunnel cũ). Không chuyển DNS cũ khi chưa backup
   route. Lấy token mới tại Cloudflare, chỉ nhập ở prompt Ubuntu, không gửi vào chat.
5. Trên Ubuntu:

```bash
sudo bash /opt/maychu247-v2/scripts/configure-public.sh panel.maychu247.uk
```

Script yêu cầu ACCESS-READY do người quản trị xác nhận; **không tự xác minh Access qua API**.
Nó tạo /etc/maychu247-ui/public.env, tunnel.env và tunnel.yaml root-only. Không tự tạo route/DNS.
Connector Docker mới dùng network_mode host trên Ubuntu Linux, nên 127.0.0.1 bên connector là
loopback của host thật. Dashboard vẫn bind 127.0.0.1:18000, không mở firewall hoặc Docker port.
Giữ cả connector cũ và stack cũ nguyên trạng để tránh ngắt website hiện có.

6. Trong **Tunnel mới**, thêm đúng một Published Application:

| Mục | Giá trị |
|---|---|
| Subdomain | panel |
| Domain | maychu247.uk |
| Path | trống |
| Type | HTTP |
| URL | 127.0.0.1:18000 |

Không dùng HTTPS cho origin, không đổi HTTP Host Header sang localhost, không No TLS Verify.
Nếu hostname/DNS đã thuộc tunnel cũ: ghi lại cấu hình, bỏ riêng route/DNS trùng hostname đó
có kiểm soát, rồi tạo lại trong tunnel mới; không xóa toàn bộ domain hoặc tunnel.

7. Mở https://panel.maychu247.uk bằng cửa sổ riêng tư: phải thấy Access trước, sau xác thực mới
   thấy login dashboard. Thử một email không được phép: phải bị chặn. Password dashboard cũ giữ
   nguyên, không phải password Access/Ubuntu. Chỉ sau nghiệm thu mới bỏ route dashboard sai cũ.

## Cơ chế và giới hạn

- Server chỉ cho phép đúng public origin HTTPS đã cấu hình và hai host loopback cũ.
- POST Origin phải khớp Host tương ứng; CSRF giữ nguyên; cookie domain public có Secure,
  HttpOnly, SameSite=Strict. Không tin X-Forwarded-Host/Proto từ client.
- Dashboard tự xác thực bằng password/session; chưa xác minh JWT Access tại backend.
  Kiểm soát danh tính Access phụ thuộc chính sách edge và tài khoản Cloudflare. Bất kỳ user
  có quyền mạng host/SSH phù hợp đều có thể gọi origin loopback: máy chủ phải tin cậy.
- SQL/File Browser vẫn là app riêng, KHÔNG được reverse proxy hay auto-login trong bản này.
  Các link localhost trên giao diện domain bị vô hiệu để không gọi nhầm PC người xem.
  Dùng SSH forwarding nếu cần các công cụ này. Không tuyên bố SSO toàn hệ thống.
- Connector image cần update/pin sau khi nghiệm thu; không hứa chống hack/HA tuyệt đối.
- Không thể chứng minh Access, DNS hoặc tunnel thực hoạt động từ unit tests cục bộ.

## Kiểm tra / rollback

```bash
sudo systemctl status maychu247-dashboard --no-pager
sudo docker compose -p maychu247-dashboard-tunnel -f /etc/maychu247-ui/tunnel.yaml ps
sudo docker compose -p maychu247-dashboard-tunnel -f /etc/maychu247-ui/tunnel.yaml logs --tail 40
curl -H 'Host: panel.maychu247.uk' http://127.0.0.1:18000/
```

Không chia sẻ token.env, public credentials hoặc toàn bộ docker inspect/config. Nếu script lỗi
sau khi ghi file, không chạy lại bằng cách xóa bừa config. Sửa lỗi theo journal/log. Có thể dừng
connector mới để ngắt public mà không đụng dữ liệu:

```bash
sudo docker compose -p maychu247-dashboard-tunnel -f /etc/maychu247-ui/tunnel.yaml stop
```

Để quay về SSH-only: dừng connector mới trước, giữ bản sao cấu hình root-only, di chuyển
/etc/maychu247-ui/public.env khỏi đường dẫn đó rồi restart dashboard. SSH loopback tiếp tục
được hỗ trợ kể cả khi public origin được bật. Không xóa .env, DB, volume hoặc connector cũ.

## Chốt domain gốc maychu247.uk (không dùng subdomain tự đề xuất)

Với bộ đã cài connector riêng và code hỗ trợ public origin, script standalone `scripts/repair-domain.sh`
chuẩn hóa origin về **https://maychu247.uk**, giữ token/password/data, sao lưu public.env, restart
UI và xác minh HTTP thật bằng Host maychu247.uk. Connector dùng network_mode host đã có được
khởi chạy qua Compose riêng. Không tự sửa Cloudflare vì không có API credentials; chỉ xác nhận
backend, không tuyên bố Internet/Access đã khỏe. Route/Access phải cùng hostname maychu247.uk.

```bash
sudo bash /opt/maychu247-v2/scripts/repair-domain.sh
```

Hoặc tải riêng script repair-domain.sh về ~/MayChu247-Fix.sh rồi chạy sudo bash. Script cần cấu
hình public/tunnel đã tồn tại; từ chối cài đè khi thiếu. Chạy trong giờ không backup/deploy, có SSH
cứu hộ. Nếu backend không lên, phục hồi public.env cũ nếu có và in log; không tự kill process,
remove container hoặc xóa dữ liệu. Agent/connector vẫn phải được nghiệm thu riêng.

Lỗi localhost trên Windows có thể do tunnel PC đã đóng. Dùng domain đã cấu hình đúng sẽ tránh
phụ thuộc tunnel PC cho dashboard, nhưng không loại trừ sự cố server, mạng hay Cloudflare.
Không công khai toàn bộ domain gốc nếu nó còn phục vụ website khác; đổi route là chuyển mục
đích domain từ website sang dashboard quản trị và bắt buộc có Access phù hợp.
