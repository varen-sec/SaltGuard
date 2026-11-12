# SaltGuard RC1 — Wokwi firmware

Sử dụng đồng bộ hai file `sketch.ino` và `diagram.json` trong thư mục này. Không lấy riêng một file từ bản cũ.

## Pin quan trọng
- MASTER: GPIO36 / VP — OFF lúc khởi động; cần OFF rồi ON để cho phép vận hành.
- PAUSE: GPIO17 / TX2.
- MANUAL: GPIO15 — pull-up ngoài 10 kΩ; không giữ nút khi reset vì GPIO15 là strapping pin.
- ACK: GPIO14 — nhấn ngắn mute còi; giữ 2 giây để khôi phục latch theo quy trình an toàn.
- UART0 RX: GPIO3 / RX0 — dành riêng Serial Monitor, không đấu dây Wokwi.
- DHT22 DATA GPIO26; DS18B20 DQ GPIO13 + pull-up 4.7 kΩ.
- HC-SR04 TRIG GPIO5, ECHO GPIO27.
- Soil Z1 GPIO33, soil Z2 GPIO39/VN.
- Pump relay GPIO16; fill relay GPIO4; buzzer GPIO25.
- 74HC595: DATA18/CLOCK19/LATCH23; Q0–Q4 năm van, Q5 READY, Q6 NOTICE.
- LCD I2C: SDA21/SCL22, 0x27.

## Lệnh Serial thường dùng
- `D`: chuyển về LOCAL (Serial log nội bộ có thể hiển thị `DYNAMIC`).
- `I`: in đầu vào hiện hành.
- `S`: in trạng thái.
- `?`: trợ giúp.
- `K`: chẩn đoán nút MANUAL GPIO15.

LOCAL đọc cảm biến/biến trở Wokwi. TWIN/CUSTOM nhận đầu vào mô phỏng từ Backend qua MQTT. Trong cả hai trường hợp ESP32 vẫn giữ quyền quyết định điều khiển và khóa an toàn cuối cùng.

## Ghi chú mô phỏng
- Thể tích nước là ước tính từ lưu lượng cấu hình và thời gian bơm, không phải flowmeter.
- MASTER phải OFF khi reset; không giữ MANUAL khi reset.
- Sau khi thay đổi firmware hoặc sơ đồ, luôn nạp/khởi động với cả hai file cùng phiên bản.
- Xem `PIN_MAP.csv` và `PIN_MAP_PHASE4.md` để kiểm tra đầy đủ chân.
