# SaltGuard RC1 — Pin map hiện hành (Wokwi)

Tài liệu này thay thế các ghi chú pin lịch sử ở các giai đoạn 3.x–4.5. Đối chiếu với `sketch.ino` và `diagram.json` trong cùng gói RC1.

## Nguyên tắc
- MANUAL dùng **GPIO15**; nút có pull-up 10 kΩ lên 3V3. GPIO15 là strapping pin, vì vậy không nhấn/giữ MANUAL trong lúc ESP32 reset.
- **GPIO3/RX0 chỉ dành cho UART0 Serial**, không có dây Wokwi kết nối tới RX0.
- NOTICE LED chuyển sang **74HC595 Q6**, READY LED vẫn ở Q5. Q0–Q4 giữ năm van V1–V5.
- DHT22 DATA GPIO26; DS18B20 DQ GPIO13; HC-SR04 TRIG GPIO5/ECHO GPIO27.
- Z1 soil GPIO33; Z2 soil GPIO39/VN (ADC input-only). Các cảm biến analog dùng ADC1.

## Các GPIO trực tiếp

| Chức năng | GPIO |
|---|---:|
| SALT / CANAL / RAIN | 34 / 35 / 32 |
| Soil Z1 / Z2 | 33 / 39 (VN) |
| DHT22 / DS18B20 | 26 / 13 |
| HC-SR04 TRIG / ECHO | 5 / 27 |
| MASTER / PAUSE / MANUAL / ACK | 36 (VP) / 17 (TX2) / 15 / 14 |
| Pump relay / Fill relay | 16 (RX2) / 4 |
| Buzzer / LED tưới / LED alarm | 25 / 2 / 12 |
| 74HC595 DATA / CLOCK / LATCH | 18 / 19 / 23 |
| LCD SDA / SCL | 21 / 22 |
| UART0 RX | 3 (RX0), dành riêng Serial |

## Ngõ ra 74HC595

| Ngõ ra | Chức năng |
|---|---|
| Q0 | V1 — CANAL → bơm tưới |
| Q1 | V2 — TANK → bơm tưới |
| Q2 | V3 — van Z1 |
| Q3 | V4 — van Z2 |
| Q4 | V5 — CANAL → bồn nạp |
| Q5 | LED READY |
| Q6 | LED NOTICE |

Xem `PIN_MAP.csv` để biết Wokwi part tương ứng và ghi chú từng chân.
