# SaltGuard IoT — Bản hoàn thiện giao diện (11/2026)

Phiên bản độc lập trong nhánh phát hành riêng. Nhánh main gốc không bị thay đổi.

## Sử dụng trên Windows
1. Giải nén toàn bộ file ZIP.
2. Cài Python 3.11+; lần đầu khởi chạy cần Internet để cài thư viện.
3. Chạy START_SALTGUARD.bat hoặc dashboard/start_windows.bat, mở http://127.0.0.1:8000/.
4. Chạy firmware_wokwi/sketch.ino trên Wokwi Web (tải/sao chép vào dự án Wokwi).
5. Nếu muốn mang lịch sử cũ, tắt cả hai backend, backup nhất quán DB gốc rồi chép dashboard/data/saltguard.db sang dashboard/data/ của bản này. Không copy tệp DB đang được ghi và chỉ copy DB khi WAL đã checkpoint.

## Ghi chú
- Mọi phép tính thể tích nước chỉ là ước tính; chưa có đồng hồ lưu lượng thực.
- Hệ thống hai vùng và ngưỡng canh tác là mô phỏng, cần hiệu chuẩn thực tế.
- Mã QR vẫn giữ, nhưng không được báo ghép nối cảm biến thành công nếu không có giao thức/thiết bị.
- MQTT dùng broker công khai chỉ phù hợp demo, không triển khai trực tiếp trên hệ thống bơm thật.
- Định mức chỉ được lưu trong SQLite sau ACK chấp nhận và telemetry khớp, khôi phục bằng thao tác chuyên môn.
