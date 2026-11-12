# Chân liên quan bảng điều khiển — Phase 3.8.2
| Nút | GPIO | Mức khi nhấn | Ghi chú |
|---|---:|---|---|
| PAUSE | 17 | LOW | INPUT_PULLUP |
| MANUAL | 39 | LOW | INPUT, pull-up 10 kΩ ngoài |
| ACK | 14 | LOW | INPUT_PULLUP |
| MASTER | 36 | HIGH khi ON | Công tắc SPDT 3.3V/GND |

Chỉ chuyển chức năng nút xanh LCD thành MANUAL, không di chuyển chân nối.
PIN_MAP.csv cũ trong dự án chứa thông tin của phần cứng đời đầu;
đối chiếu `diagram.json` và `sketch.ino` là chính xác nhất.
