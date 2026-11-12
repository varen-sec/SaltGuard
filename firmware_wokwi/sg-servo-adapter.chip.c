/* SaltGuard Servo V1 test adapter (Wokwi simulation only).
 * Mirrors the existing 74HC595 Q0 valve command; DOES NOT alter ESP32 firmware.
 * Q0 LOW -> 1000us pulse/20ms (0 degrees, CLOSED)
 * Q0 HIGH -> 1500us pulse/20ms (about 90 degrees, OPEN)
 * Servo's PWM pin is an INPUT and MUST NOT connect directly to 74HC595 Q0.
 * No physical-water simulation or safety proof is implied.
 */
#include "wokwi-api.h"
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>

typedef struct {
  pin_t command;
  pin_t pwm;
  timer_t period_timer;
  timer_t low_timer;
} servo_adapter_t;

static void finish_pulse(void *user_data) {
  servo_adapter_t *a = (servo_adapter_t *)user_data;
  pin_write(a->pwm, LOW);
}

static void begin_pulse(void *user_data) {
  servo_adapter_t *a = (servo_adapter_t *)user_data;
  /* Snapshot the logical valve command at the start of each 20-ms cycle. */
  uint32_t width_us = pin_read(a->command) == HIGH ? 1500 : 1000;
  pin_write(a->pwm, HIGH);
  timer_start(a->low_timer, width_us, false);
}

void chip_init(void) {
  servo_adapter_t *a = (servo_adapter_t *)calloc(1, sizeof(servo_adapter_t));
  if (!a) return;
  a->command = pin_init("IN", INPUT);
  a->pwm = pin_init("OUT", OUTPUT_LOW);
  const timer_config_t high_cfg = {.callback = begin_pulse, .user_data = a};
  const timer_config_t low_cfg = {.callback = finish_pulse, .user_data = a};
  a->period_timer = timer_init((timer_config_t *)&high_cfg);
  a->low_timer = timer_init((timer_config_t *)&low_cfg);
  /* Periodic 50Hz servo command: runs in SIMULATION time. */
  timer_start(a->period_timer, 20000, true);
}
