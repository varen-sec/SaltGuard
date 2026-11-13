# SaltGuard IoT — Bản UI V5

## Cách chạy
1. Giải nén ZIP và giữ nguyên cấu trúc thư mục.
2. Cài Python 3.11/3.12 nếu chưa có; cần Internet cho lần cài requirements đầu tiên.
3. Trên Windows: nhấp đúp START_SALTGUARD.bat (hoặc dashboard/start_windows.bat). Trang chạy ở http://127.0.0.1:8000.
4. Chạy firmware_wokwi/sketch.ino trên dự án Wokwi Web có sơ đồ mạch tương ứng.
5. Nếu có dữ liệu cũ: dừng toàn bộ backend cũ và mới; tạo bản sao nhất quán file SQLite cũ và chép vào dashboard/data/saltguard.db trước khi mở app mới. Nếu dữ liệu nguồn đang ở chế độ WAL, phải checkpoint hoặc backup bằng SQLite, không copy file .db đang ghi.

## Thay đổi quan trọng
- Vùng 1 và Vùng 2 trong Chuyên môn mở/thu gọn riêng bằng nút mũi tên có style thống nhất.
- Định mức Vùng 1 và Vùng 2 mở riêng; nút Lưu ở ngoài khu vực thu gọn.
- Nhật ký nông dân có ba tab Tổng quan, Lịch sử tưới và Cảm biến & sự kiện; dùng báo cáo /activity và các API có sẵn.
- Thanh điều hướng Chuyên môn, Thử nghiệm gồm đúng ba mục; trang Nhật ký riêng giữ cho tương thích nhưng không hiện trong navigation.
- Giữ camera QR và chọn vùng nhận diện, chưa báo đã ghép thiết bị thành công nếu không có phần cứng/đăng ký.
- Thử nghiệm gồm khối kiểm tra lỗi và bảng điều chỉnh mô phỏng 2 cột.
- Các thay đổi logic tưới chủ đạo, ngưỡng bảo vệ và dây Wokwi không bị sửa.

## Hạn chế
- MQTT broker công khai chỉ dành cho mô phỏng, không dùng để điều khiển bơm ngoài đời thật.
- Lượng nước là số liệu ước tính, vì không có lưu lượng kế thực.
- Các ngưỡng 35/60% và 1 ppt là cấu hình mô phỏng, không phải khuyến cáo chung cho mọi cây.
- Bộ nhớ NVS trên Wokwi Web không được bảo đảm qua Stop/Start; backend chỉ lưu cấu hình nước khi đã nhận ACK và telemetry khớp.

## Thiết kế tiếp bằng Google Antigravity
Mở toàn bộ thư mục này trong Antigravity. Chỉ thay đổi HTML/CSS/JS trong dashboard/app/static; luôn kiểm tra lại farmer.js, engineer_config.js, API và các bài test trước khi chấp nhận diff.
