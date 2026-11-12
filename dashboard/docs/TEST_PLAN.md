# Test Plan SaltGuard 2.5

Đọc `README.md` và `TEST_REPORT.md` ở thư mục gốc, mục **Bài kiểm thử đặc trưng 2.5**. Thử trong Wokwi với cả `sketch.ino` + `diagram.json` mới và Digital Twin Python 2.5. Không dựa vào kết quả biên dịch cú pháp để khẳng định mô phỏng đã đạt.

Core 2.5: F25-06 (tank salinity lock) DEFERRED. Verify: when tank salinity >1.0ppt and canal unavailable with enough tank volume, tank may still supply (simulation only). Verify low tank water still prevents pumping.
