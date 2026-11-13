#include <Arduino.h>
#include <WiFi.h>
#include <Preferences.h>
#include <PubSubClient.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
// 74HC595 shift register drives the five logical valve indicators.
#include <DHTesp.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <math.h>
#include <stdlib.h>

// Keep custom types before any function definition: Arduino's auto-generated
// function prototypes may otherwise reference unknown types at compile time.
enum AlarmKind : uint8_t { AL_NONE=0, AL_SALINITY, AL_REFILL, AL_NO_WATER,
                           AL_STALE, AL_FAULT, AL_EMERGENCY };
struct AlarmNote { uint16_t hz; uint16_t ms; uint16_t gapMs; };
// Declare fault type before Arduino generates automatic function prototypes.
enum VirtualFault { VF_NONE, VF_NO_FLOW, VF_VALVE_STUCK, VF_SOIL_INVALID };

// Explicit signatures for alarm functions using the custom types.
const char* alarmName(AlarmKind kind);
AlarmKind classifyAlarm();
AlarmNote alarmNote(AlarmKind kind, uint8_t index);
uint8_t alarmNoteCount(AlarmKind kind);
void alarm(unsigned long now);

// ESP32 ADC1 works even when Wi-Fi is enabled in subsequent milestones.
const int SALT_PIN=34, CANAL_PIN=35, RAIN_PIN=32;
// Dedicated LOCAL soil potentiometers on ADC1 (Wi-Fi-safe).
const int SOIL_Z1_PIN=33, SOIL_Z2_PIN=39;
// Five valve commands are output by 74HC595; Wokwi servo adapters visualize ON/OFF.
// V1=canal to irrigation; V2=tank to irrigation; V3=Z1; V4=Z2; V5=canal to tank refill.
const int SR_DATA_PIN=18, SR_CLOCK_PIN=19, SR_LATCH_PIN=23;
const int TANK_TRIG_PIN=5, TANK_ECHO_PIN=27;
const uint8_t V1=1<<0,V2=1<<1,V3=1<<2,V4=1<<3,V5=1<<4;
uint8_t valveMask=0;
// HC-SR04 mounted at tank top, with calibrated empty/full distances.
// For Wokwi, configure the sensor distance to match the water level.
const float TANK_EMPTY_CM=200.0f, TANK_FULL_CM=10.0f;
const unsigned long LEVEL_SAMPLE_MS=350UL;
float tankDistanceCm=NAN;
bool tankLevelValid=false;
unsigned long lastLevelSample=0;
// Phase 4.6.1: RX0/GPIO3 reserved solely for UART0 Serial input.
// MANUAL moves to GPIO15, freed by moving NOTICE LED to 74HC595 Q6.
// DHT22 GPIO26 / DS18B20 GPIO13 / HC-SR04 TRIG GPIO5 remain unchanged.
// GPIO15 is a strapping pin: do not hold MANUAL during ESP32 reset.
const int BUZZER_PIN=25, PAUSE_PIN=17, MANUAL_PIN=15, REFILL_PIN=14;
const int RELAY_PIN=16, FILL_RELAY_PIN=4, DHT_PIN=26, WATER_TEMP_PIN=13;
const int LED_WATER_PIN=2, LED_ALARM_PIN=12;
const uint8_t SR_READY_LED=1<<5;  // Q5: READY
const uint8_t SR_NOTICE_LED=1<<6; // Q6: NOTICE (frees GPIO15 for MANUAL)
bool readyLedState=false;
bool noticeLedState=false;
const int MASTER_SWITCH_PIN=36; // SPDT: OFF=GND, ON=3V3, no app control
// Wokwi relay transistor="npn" (active-high): HIGH -> NO closed, LOW -> NO open.
const int RELAY_OFF=LOW, RELAY_ON=HIGH;
const int SDA_PIN=21, SCL_PIN=22;

const float SALT_BLOCK=1.0f, SALT_RELEASE=0.7f;
// Phase 4.0: independently configurable hysteresis; demo defaults, not crop advice.
uint8_t soilStartPct[2]={35,35},soilStopPct[2]={60,60};
uint32_t soilConfigRevision=0;
const float CANAL_MIN=15.0f, TANK_STOP=400.0f, TANK_RESUME=500.0f;
const float TANK_CAPACITY=2000.0f; // Demo reserve 2 m3, NOT a calibrated real tank
const float REFILL_START_L=600.0f, REFILL_STOP_L=1800.0f;
const unsigned long MAX_REFILL_MS=120000UL;
const unsigned long RELEASE_MS=5000UL, REST_MS=2000UL, MASTER_RECHECK_MS=1500UL;
// Continuous irrigation: estimated litres = configured flow (L/min) * pump-on time (min).
// Defaults reproduce the previous 10-second demo (12 L/min * 10 s = 2 L).
// Values are SIMULATED estimates, not flowmeter readings or agronomic prescriptions.
float flowLpm[2]={12.0f,12.0f};
float sessionTargetL[2]={2.0f,2.0f};
const unsigned long MAX_IRRIGATION_SESSION_MS=1800000UL; // absolute per-session safety cap: 30 simulated min
unsigned long sessionBudgetMs=10000UL;
float sessionEstimatedL=0.0f;
float zoneEstimatedTotalL[2]={0.0f,0.0f};
unsigned long waterMeterAt=0;
int waterMeterZone=-1;
uint32_t irrigationConfigRevision=0;
unsigned long durationForZone(int zi) {
  if(zi<0 || zi>=2 || flowLpm[zi]<=0) return 10000UL;
  double raw=(double)sessionTargetL[zi]*60000.0/(double)flowLpm[zi];
  if(raw>MAX_IRRIGATION_SESSION_MS) return MAX_IRRIGATION_SESSION_MS;
  return (unsigned long)(raw<1000.0?1000.0:raw+0.5);
}
// Called before any pump state transition and before telemetry serialization.
// Metering stops immediately at PAUSE/FAULT/MASTER OFF. Diagnostic NO_FLOW is zero.


// Morning/afternoon are suggested DEMO windows in Vietnam local time, not crop prescriptions.
int morningStart=5*60+30, morningEnd=9*60;
int afternoonStart=16*60+30, afternoonEnd=18*60+30;
const int MAX_WINDOWS=4;
struct IrrWindow {bool enabled; int start; int end;};
IrrWindow irrigationWindows[MAX_WINDOWS]={{true,330,540},{true,990,1110},{false,720,780},{false,780,840}};
int windowCount=2;

const unsigned long CLOCK_MAX_AGE_MS=12UL*60UL*60UL*1000UL;
const unsigned long MASTER_DEBOUNCE_MS=90UL;
// Physical panel ACK: short release = mute; 2s simulated hold = recover latch, require MASTER OFF->ON before restart.
const unsigned long ACK_RECOVERY_HOLD_MS=2000UL;
// ONE-TIME OUT-OF-WINDOW IRRIGATION: time limited and moisture limited.
// This is a single farmer-authorized exception, never a second irrigation mode.
const unsigned long EXTRA_WATER_MS=120000UL; // demo: up to 2 min after each zone starts (includes REST)
const unsigned long EXTRA_QUEUE_MS=180000UL; // queued permission expires if never served
// Separate one-time permissions: both zones can be queued, but only one valve opens at once.
// A PAUSE suspends at most one active irrigation session. Volatile by design:
// reboot, MASTER OFF, emergency, stale input and fault must not auto-resume it.
bool pausedSessionPending=false;
int pausedSessionZone=-1;
unsigned long pausedSessionRemainingMs=0;
void discardPausedSession() {
  pausedSessionPending=false;
  pausedSessionZone=-1;
  pausedSessionRemainingMs=0;
}
bool manualSessionOneShot[2]={false,false};
bool extraWaterGranted[2]={false,false};
bool extraWaterStarted[2]={false,false};
unsigned long extraWaterQueuedAt[2]={0,0};
unsigned long extraWaterStartedAt[2]={0,0};
void clearOneTime(int zi) {
  if(zi<0 || zi>=2) return;
  // Any explicit zone permission cancellation invalidates its checkpoint,
  // including in-window HOLD and custom-demo cancellation.
  if(pausedSessionPending && pausedSessionZone==zi) discardPausedSession();
  extraWaterGranted[zi]=false; extraWaterStarted[zi]=false;
  manualSessionOneShot[zi]=false;
  extraWaterQueuedAt[zi]=0; extraWaterStartedAt[zi]=0;
}
void clearAllOneTime() { clearOneTime(0); clearOneTime(1); discardPausedSession(); }
const unsigned long READ_MS=250UL, WORLD_MS=1000UL, LCD_MS=250UL, PAGE_MS=1800UL, CSV_MS=2000UL;
const unsigned long AIR_MS=3000UL, WATER_MS=3000UL, WATER_CONVERSION_MS=250UL;
// MQTT demo broker: public and unauthenticated; NEVER connect real equipment to it.
const char* WIFI_SSID="Wokwi-GUEST";
const char* MQTT_HOST="broker.emqx.io";
const uint16_t MQTT_PORT=1883;
const char* MQTT_ROOT="saltguard/demo/sgfarm-19cadbfde5";
const unsigned long TWIN_INPUT_TIMEOUT_MS=12000UL;
const unsigned long MQTT_PUBLISH_MS=1200UL;
const unsigned long MQTT_RETRY_MS=7000UL;
const unsigned long WIFI_RETRY_MS=15000UL;
WiFiClient mqttTransport;
PubSubClient mqtt(mqttTransport);
String topicTelemetry, topicStatus, topicCommand, topicAck, topicTwin;
// One-shot demo markers: printed only for accepted preset input and explicit end.
int demoCase=0;
bool demoAwaitInput=false;
unsigned long lastMqttTry=0, lastWifiTry=0, lastTelemetry=0;
bool mqttWasOnline=false;
bool twinMode=false;
unsigned long lastTwinInput=0;
uint32_t twinRxCount=0; // Increments only after a valid SGT2 input frame is received.
bool refillAuto=true, refillRequested=false, refillCycle=false, refillFault=false;
// Only one irrigation method remains: automatic soil-moisture control.
// Holds are durable on ESP32; only farmer can release a held area.
bool zoneHold[2]={false,false};
Preferences irrigationPrefs;
// Total run-permission belongs ONLY to the physical slide switch.
// Boot is always OFF: if switch boots ON, an OFF->ON cycle is mandatory.
bool masterEnabled=false, masterArmed=false;
// LCD is powered for monitoring but blank and unlit whenever physical MASTER is OFF.
bool lcdVisible=false;
unsigned long masterEnabledAt=0;
int masterLastRaw=LOW;
unsigned long masterRawChangedAt=0;
// Dashboard supplies wall clock once per minute via MQTT; no RTC assumption.
unsigned long clockEpoch=0, clockAtMs=0;
bool demoWindowOverride=false;
unsigned long demoWindowUntil=0;
float tankSaltPpt=0.3f; // virtual value; NOT an independent Wokwi sensor
unsigned long refillStart=0;

LiquidCrystal_I2C lcd(0x27,16,2);

DHTesp airSensor;
OneWire oneWire(WATER_TEMP_PIN);
DallasTemperature waterSensor(&oneWire);

enum State { IDLE, CANAL_Z1, CANAL_Z2, TANK_Z1, TANK_Z2,
             REST, HOLD_NO_WATER, FAULT, PAUSE, REFILL_TANK };
State state=IDLE;

float saltPpt=0.5f, canalPct=80, rainPct=0;
float soil[2]={24,49}, tankL=1500, canalUsedL=0, tankUsedL=0;
bool demand[2]={false,false};
bool naturalDemand[2]={false,false};
const int MAX_ZONES=2;
int configuredZones=2; // DYNAMIC: Z command switches 1/2; PRESET always tests both.
float airTempC=NAN, airRH=NAN, waterTempC=NAN;
bool airReadingOK=false, waterReadingOK=false, waterPending=false;
uint8_t waterReadFailCount=0;
uint8_t airReadFailCount=0;
unsigned long lastAirDiag=0;
unsigned long lastWaterDiag=0;
unsigned long lastAirSample=0, lastWaterRequest=0, waterStarted=0;
bool canalLocked=false, tankReady=true, releaseCounting=false;
bool paused=false, injectedFault=false, testMode=false;
// Phase 4.3: explicitly VIRTUAL feedback, not readings from physical flow/valve sensors.
VirtualFault virtualFault=VF_NONE;
bool virtualFaultLatched=false;
unsigned long virtualFaultObservedAt=0;
const unsigned long VIRTUAL_FAULT_DETECT_MS=1500UL;
// Remote emergency is a latched STOP, not a pause and never an app MASTER switch.
bool emergencyLatched=false;
bool buzzerAcknowledged=false;
// Distinct nonblocking buzzer patterns. Priorities: emergency > fault >
// stale input > no safe source > refill timeout > canal salinity advisory.
AlarmKind currentAlarm=AL_NONE;
unsigned long nextAlarmAt=0;
uint8_t alarmStep=0;
// A physical MANUAL press authorizes at most one irrigation session per eligible zone.
unsigned long manualNoticeUntil=0;
char manualNoticeTop[17]="", manualNoticeBottom[17]="";
// Raw edge diagnosis helps distinguish a Wokwi button wiring problem.
int manualPinLastRaw=HIGH;
int pausePinLastRaw=HIGH;
bool customAwaitInput=false;
bool customActive=false;
const unsigned long LCD_WELCOME_MS=3500UL;
const unsigned long MANUAL_NOTICE_MS=3500UL;
State previousPanelState=IDLE;
bool eventStream=true, csvStream=false;
int activeZone=-1, lastServedZone=1; // index: 0=Z1; 1=Z2. First priority Z1.
char lastTest='-';
unsigned long releaseStart=0, sessionStart=0, restStart=0;
unsigned long lastRead=0, lastWorld=0, lastLCD=0, lastPage=0, lastCSV=0, lastAlarm=0;
uint8_t page=0;
const char* reason="START";

struct Button { int pin; int lastRaw; int stable; unsigned long edge; };
Button bPause={PAUSE_PIN,HIGH,HIGH,0};
Button bManual={MANUAL_PIN,HIGH,HIGH,0};
Button bRefill={REFILL_PIN,HIGH,HIGH,0};
unsigned long ackDownAt=0;
bool ackLongHandled=false;

// Explicit prototypes avoid Arduino auto-prototype issues with custom types.
const char* stateName(State s);
bool useCanal(State s);
bool useTank(State s);
bool watering(State s);
State wateringState(int zone,bool canal);
void enter(State next,const char* why,unsigned long now);
bool edgePressed(Button &b,unsigned long now);
void tickNetwork(unsigned long now);
void setupNetwork();
void printNetworkStatus();
void publishTelemetry(unsigned long now);
void publishAck(const char* command,bool accepted,const char* message,unsigned long now);
void setLCDVisible(bool visible);
void updateLCD();
void requestManualIrrigation(unsigned long now);
void updatePanelLeds();

const char* stateName(State s) {
  switch(s) {
    case IDLE: return "IDLE";
    case CANAL_Z1: return "CANAL_Z1"; case CANAL_Z2: return "CANAL_Z2";
    case TANK_Z1: return "TANK_Z1"; case TANK_Z2: return "TANK_Z2";
    case REST: return "REST"; case HOLD_NO_WATER: return "HOLD_NO_WATER";
    case FAULT: return "FAULT"; case PAUSE: return "PAUSE";
    case REFILL_TANK: return "REFILL_TANK";
  }
  return "UNKNOWN";
}
bool useCanal(State s) { return s==CANAL_Z1 || s==CANAL_Z2; }
bool useTank(State s) { return s==TANK_Z1 || s==TANK_Z2; }
bool watering(State s) { return useCanal(s) || useTank(s); }
float clampf(float x,float lo,float hi) { return x<lo?lo:(x>hi?hi:x); }
// Epoch seconds are sent by the local Python backend. Reject implausible clocks.
bool clockValid(unsigned long now) {
  return clockEpoch>=1700000000UL && now-clockAtMs<CLOCK_MAX_AGE_MS;
}
bool irrigationWindow(unsigned long now) {
  if(demoWindowOverride && (int32_t)(now-demoWindowUntil)<0) return true;
  if(!clockValid(now)) return false;
  unsigned long localSeconds=((clockEpoch+(now-clockAtMs)/1000UL)%86400UL+7UL*3600UL)%86400UL;
  int minutes=localSeconds/60UL;
  for(int i=0;i<windowCount;i++) {
    if(irrigationWindows[i].enabled && minutes>=irrigationWindows[i].start && minutes<irrigationWindows[i].end) return true;
  }
  return false;
}
void updateMaster(unsigned long now) {
  int raw=digitalRead(MASTER_SWITCH_PIN);
  // OFF acts immediately; arming ON requires debounce and a prior observed OFF.
  if(raw==LOW && masterEnabled) {
    masterEnabled=false;
    clearAllOneTime();
    refillRequested=false; // clear queued manual requests
    activeZone=-1;
    enter(IDLE,"MASTER_OFF",now);
    setLCDVisible(false); updatePanelLeds();
    Serial.println("MASTER OFF (physical switch): pumps stopped");
  }
  if(raw!=masterLastRaw) { masterLastRaw=raw;masterRawChangedAt=now; }
  if(now-masterRawChangedAt<MASTER_DEBOUNCE_MS) return;
  if(raw==LOW) masterArmed=true;
  else if(masterArmed && !masterEnabled) {
    masterEnabled=true;
    masterEnabledAt=now;
    masterArmed=false;
    activeZone=-1;
    enter(REST,"MASTER_ON_RECHECK",now);
    setLCDVisible(true); updatePanelLeds();
    Serial.println("MASTER ON: safety recheck 1.5s, REST 2s");
  }
}


void writeValves(uint8_t mask) {
  valveMask=mask;
  digitalWrite(SR_LATCH_PIN, LOW);
  shiftOut(SR_DATA_PIN,SR_CLOCK_PIN,MSBFIRST,mask | (readyLedState?SR_READY_LED:0) | (noticeLedState?SR_NOTICE_LED:0));
  digitalWrite(SR_LATCH_PIN, HIGH);
}
void outputsOff() {
  digitalWrite(RELAY_PIN,RELAY_OFF);
  digitalWrite(FILL_RELAY_PIN,RELAY_OFF);
  writeValves(0);
}
// LOCAL reads ultrasonic water level. SIMULATION/PRESET retain backend-owned tank values.
void sampleTankLevel(unsigned long now) {
  if (testMode || twinMode || now - lastLevelSample < LEVEL_SAMPLE_MS)
    return;

  lastLevelSample = now;

  digitalWrite(TANK_TRIG_PIN, LOW);
  delayMicroseconds(5);
  digitalWrite(TANK_TRIG_PIN, HIGH);
  delayMicroseconds(12);
  digitalWrite(TANK_TRIG_PIN, LOW);

  unsigned long duration = pulseIn(TANK_ECHO_PIN, HIGH, 30000UL);
  float distance = (float)duration * 0.0343f / 2.0f;

  bool valid = (
    duration != 0 &&
    distance >= TANK_FULL_CM - 2.0f &&
    distance <= TANK_EMPTY_CM + 2.0f
  );

  // Serial diagnostics only.
  // Do not change sensor sampling or safety behavior.
  static unsigned long lastDiagnostic = 0;
  static bool diagnosticInitialized = false;
  static bool lastDiagnosticValid = false;

  const unsigned long DIAGNOSTIC_INTERVAL_MS = 30000UL;

  bool shouldLog =
      !diagnosticInitialized ||
      valid != lastDiagnosticValid ||
      now - lastDiagnostic >= DIAGNOSTIC_INTERVAL_MS;

  if (shouldLog) {
    lastDiagnostic = now;
    lastDiagnosticValid = valid;
    diagnosticInitialized = true;
  }

  if (!valid) {
    tankLevelValid = false;
    tankDistanceCm = NAN;
    tankL = NAN;
    tankReady = false;

    // Immediately stop reservoir use if sensor is invalid.
    if (state == REFILL_TANK || useTank(state)) {
      activeZone = -1;
      enter(REST, "TANK_SENSOR_INVALID", now);
      outputsOff();
    }

    if (shouldLog) {
      Serial.printf(
        "HC-SR04 INVALID: echo=%luus raw=%.1fcm TRIG=%d ECHO=%d\n",
        duration,
        distance,
        TANK_TRIG_PIN,
        TANK_ECHO_PIN
      );
    }

    return;
  }

  tankDistanceCm = distance;

  tankL = clampf(
    (TANK_EMPTY_CM - distance) /
    (TANK_EMPTY_CM - TANK_FULL_CM) * TANK_CAPACITY,
    0.0f,
    TANK_CAPACITY
  );

  tankLevelValid = true;

  if (shouldLog) {
    Serial.printf(
      "HC-SR04 OK: echo=%luus distance=%.1fcm tank=%.0fL\n",
      duration,
      tankDistanceCm,
      tankL
    );
  }
}


void updatePanelLeds() {
  bool alarmState=(emergencyLatched || state==FAULT || state==HOLD_NO_WATER);
  bool noticeState=paused || state==PAUSE || state==REFILL_TANK || canalLocked || refillFault;
  bool ready=masterEnabled && !paused && !injectedFault && state!=FAULT && state!=HOLD_NO_WATER;
  bool notice=masterEnabled && noticeState;
  if(readyLedState!=ready || noticeLedState!=notice) {
    readyLedState=ready;
    noticeLedState=notice;
    writeValves(valveMask); // Refresh Q5/Q6 without changing Q0..Q4 valve commands.
  }
  digitalWrite(LED_WATER_PIN,(masterEnabled && watering(state))?HIGH:LOW);
  digitalWrite(LED_ALARM_PIN,(masterEnabled && alarmState)?HIGH:LOW);
}
void applyOutputs() {
  // Fail-safe on every state change; in full hardware use sequenced, feedback-checked valves.
  outputsOff();
  if(emergencyLatched || !masterEnabled || paused || injectedFault || virtualFaultLatched) return;
  if(state==REFILL_TANK) {
    if(canalOK() && tankL<REFILL_STOP_L && (testMode||twinMode||tankLevelValid)) {
      writeValves(V5);
      digitalWrite(FILL_RELAY_PIN,RELAY_ON);
    }
    return;
  }
  if (!watering(state)) return;
  if(useCanal(state)) writeValves(V1 | (activeZone==0?V3:V4));
  else if(useTank(state) && (testMode||twinMode||tankLevelValid)) writeValves(V2 | (activeZone==0?V3:V4));
  else return;
  digitalWrite(RELAY_PIN,RELAY_ON);
}
void accrueEstimatedWater(unsigned long now) {
  if(waterMeterZone<0 || !watering(state)) return;
  // Network callbacks can advance millis() beyond the cached time at the
  // beginning of loop(). A later control(now) may therefore be OLDER than
  // waterMeterAt; unsigned subtraction would turn this into ~2^32 ms and
  // produce hundreds of thousands of fictitious litres.
  if((int32_t)(now-waterMeterAt)<=0) return;
  unsigned long elapsed=now-waterMeterAt;
  waterMeterAt=now;
  if(virtualFault==VF_NO_FLOW || virtualFaultLatched || emergencyLatched || !masterEnabled) return;
  // Keep the estimate within both the live session's elapsed pump-on budget
  // and its configured volume limit, even across source changes and PAUSE.
  if((int32_t)(now-sessionStart)<0) return;
  unsigned long cumulative=now-sessionStart;
  unsigned long overflow=cumulative>sessionBudgetMs?cumulative-sessionBudgetMs:0;
  if(overflow>=elapsed) elapsed=0; else elapsed-=overflow;
  if(elapsed==0) return;
  const int zi=waterMeterZone;
  float remaining=max(0.0f,sessionTargetL[zi]-sessionEstimatedL);
  float litres=min(remaining,flowLpm[zi]*(float)elapsed/60000.0f);
  if(!isfinite(litres) || litres<=0.0f) return;
  sessionEstimatedL+=litres;
  zoneEstimatedTotalL[zi]+=litres;
}
void enter(State next,const char* why,unsigned long now) {
  if(state==next) { reason=why; return; }
  State previous=state;
  accrueEstimatedWater(now);
  if(!watering(previous) && watering(next)) {
    waterMeterZone=activeZone;
    waterMeterAt=now;
  }
  if(watering(previous) && !watering(next)) waterMeterZone=-1;
  // Keep session timer on CANAL -> TANK mid-session (or the reverse).
  if (!watering(previous) && watering(next)) sessionStart=now;
  if (next==REST) restStart=now;
  if (next==REFILL_TANK) refillStart=now;
  state=next; reason=why; applyOutputs();
  // Alarm acknowledgement resets only when the actual alarm category changes.
  // Keep the selected LCD page until timeout; safety still overrides it.
  updatePanelLeds();
  if(eventStream) {
    Serial.printf("EVENT ms=%lu state=%s source=%s zone=%d reason=%s\n",
      now,stateName(state),useCanal(state)?"CANAL":useTank(state)?"TANK":"NONE",
      watering(state)?activeZone+1:0,reason);
  }
}

const char* virtualFaultName() {
  switch(virtualFault) {case VF_NO_FLOW:return "NO_FLOW";case VF_VALVE_STUCK:return "VALVE_STUCK";case VF_SOIL_INVALID:return "SOIL_INVALID";default:return "NONE";}
}
void resetVirtualFault() {virtualFault=VF_NONE;virtualFaultLatched=false;virtualFaultObservedAt=0;}
void applyVirtualFault(VirtualFault type,unsigned long now) {
  virtualFault=type;virtualFaultLatched=false;virtualFaultObservedAt=0;
  Serial.printf("DIAG VIRTUAL INJECT %s; simulated feedback only\n",virtualFaultName());
  // Sensor invalid means the controller can no longer trust irrigation demand.
  if(type==VF_SOIL_INVALID) {virtualFaultLatched=true;clearAllOneTime();activeZone=-1;enter(FAULT,"DIAG_SOIL_INVALID",now);}
}
void tickVirtualFault(unsigned long now) {
  if(virtualFault==VF_NONE || virtualFaultLatched) return;
  if(virtualFault==VF_SOIL_INVALID) {virtualFaultLatched=true;return;}
  if(!watering(state)) {virtualFaultObservedAt=0;return;}
  if(!virtualFaultObservedAt) {virtualFaultObservedAt=now;return;}
  if(now-virtualFaultObservedAt < VIRTUAL_FAULT_DETECT_MS) return;
  virtualFaultLatched=true;clearAllOneTime();activeZone=-1;
  enter(FAULT,virtualFault==VF_NO_FLOW?"DIAG_NO_FLOW":"DIAG_VALVE_STUCK",now);
  Serial.printf("DIAG VIRTUAL DETECTED %s: outputs OFF, latched until TEST:CLEAR\n",virtualFaultName());
}


bool edgePressed(Button &b,unsigned long now) {
  int raw=digitalRead(b.pin);
  if(raw!=b.lastRaw) b.edge=now;
  b.lastRaw=raw;
  if(now-b.edge>=25 && raw!=b.stable) {
    b.stable=raw;
    if(raw==LOW) return true;
  }
  return false;
}

void readKnobs() {
  if(testMode || twinMode) return; // TC inputs or Python Twin own these signals
  saltPpt=3.0f*analogRead(SALT_PIN)/4095.0f;
  canalPct=100.0f*analogRead(CANAL_PIN)/4095.0f;
  rainPct=100.0f*analogRead(RAIN_PIN)/4095.0f;
  soil[0]=clampf(100.0f*analogRead(SOIL_Z1_PIN)/4095.0f,0.0f,100.0f);
  soil[1]=clampf(100.0f*analogRead(SOIL_Z2_PIN)/4095.0f,0.0f,100.0f);
}
void updateSafety(unsigned long now) {
  if(saltPpt>=SALT_BLOCK) { canalLocked=true; releaseCounting=false; }
  else if(canalLocked) {
    if(saltPpt<=SALT_RELEASE) {
      if(!releaseCounting) { releaseCounting=true; releaseStart=now; }
      if(now-releaseStart>=RELEASE_MS) { canalLocked=false; releaseCounting=false; }
    } else releaseCounting=false;
  }
  // v2.5 core: tank salinity is MONITORING ONLY; no salinity-based tank lock.
  // Keep the independent tank-level interlock to prevent dry pumping.
  if(tankL<=TANK_STOP) tankReady=false;
  else if(tankL>=TANK_RESUME) tankReady=true;
}
void updateDemand() {
  for(int i=0;i<MAX_ZONES;i++) {
    if(i>=configuredZones) {naturalDemand[i]=false;demand[i]=false;continue;}
    if(zoneHold[i]) {naturalDemand[i]=false;demand[i]=false;continue;}
    if(soil[i]<=soilStartPct[i]) naturalDemand[i]=true;
    else if(soil[i]>=soilStopPct[i]) naturalDemand[i]=false;
    demand[i]=naturalDemand[i];
  }
}
bool canalOK() { return !canalLocked && canalPct>CANAL_MIN; }
bool tankOK() { return (testMode||twinMode||tankLevelValid) && tankReady && tankL>TANK_STOP; } // LEVEL ONLY, not a quality certification
int selectZone() {
  if(configuredZones==2 && demand[0]&&demand[1]) return 1-lastServedZone;
  if(demand[0]) return 0;
  if(configuredZones>1 && demand[1]) return 1;
  return -1;
}
bool authorizedOutsideWindow(int zi) {
  return zi>=0 && zi<configuredZones && extraWaterGranted[zi] && demand[zi] && !testMode;
}
int selectAuthorizedZone() {
  bool z1=authorizedOutsideWindow(0), z2=authorizedOutsideWindow(1);
  if(z1 && z2) return 1-lastServedZone; // fairness across 10-second sessions
  if(z1) return 0;
  if(z2) return 1;
  return -1;
}
State wateringState(int zone,bool canal) {
  return canal?(zone==0?CANAL_Z1:CANAL_Z2):(zone==0?TANK_Z1:TANK_Z2);
}
void stopForRest(unsigned long now) {
  discardPausedSession();
  if(activeZone>=0) {
    Serial.printf("IRRIGATION SESSION END Z%d estimated=%.2fL target=%.2fL used=%lums budget=%lums reason=%s\n",
      activeZone+1,sessionEstimatedL,sessionTargetL[activeZone],now-sessionStart,sessionBudgetMs,
      demand[activeZone]?"VOLUME_OR_TIME_LIMIT":"SOIL_TARGET");
    lastServedZone=activeZone;
    // An accepted physical MANUAL request is exactly one irrigation session
    // for that zone, never an indefinite override of the stored schedule.
    if(manualSessionOneShot[activeZone]) {
      Serial.printf("PANEL MANUAL: VUNG %d HOAN THANH 1 LUOT\n",activeZone+1);
      clearOneTime(activeZone);
    }
  }
  activeZone=-1;
  enter(REST,"REST",now);
}
void tickVirtualFault(unsigned long now);
void control(unsigned long now) {
  updateSafety(now); updateDemand();
  if(emergencyLatched) {clearAllOneTime();activeZone=-1;enter(FAULT,"REMOTE_EMERGENCY_STOP",now);return;}
  tickVirtualFault(now);
  if(virtualFaultLatched) {activeZone=-1;enter(FAULT,virtualFault==VF_NO_FLOW?"DIAG_NO_FLOW":virtualFault==VF_VALVE_STUCK?"DIAG_VALVE_STUCK":"DIAG_SOIL_INVALID",now);return;}
  // Expire each permit independently. A zone waiting behind another zone
  // gets its full budget from its FIRST actual irrigation, not from the tap.
  for(int zi=0;zi<2;zi++) {
    if(!extraWaterGranted[zi]) continue;
    bool expired=extraWaterStarted[zi]
      ? now-extraWaterStartedAt[zi]>=EXTRA_WATER_MS
      : now-extraWaterQueuedAt[zi]>=EXTRA_QUEUE_MS;
    if(expired || zoneHold[zi] || zi>=configuredZones || !demand[zi]) {
      clearOneTime(zi);
      if(expired && !irrigationWindow(now) && watering(state) && activeZone==zi) {
        activeZone=-1;
        enter(REST,"ONE_TIME_LIMIT_REACHED",now);
      }
    }
  }
  if(emergencyLatched) { clearAllOneTime(); activeZone=-1; enter(FAULT,"REMOTE_EMERGENCY_STOP",now); return; }
  if(!masterEnabled) { discardPausedSession();activeZone=-1;enter(IDLE,"MASTER_OFF",now);return; }
  // PAUSE stops every output but retains the unfinished session and a still-
  // valid one-time exception. The permission's absolute expiry does NOT pause.
  if(paused) { activeZone=-1; enter(PAUSE,"USER_PAUSE",now); return; }
  if(injectedFault) { clearAllOneTime(); activeZone=-1; enter(FAULT,"SENSOR_FAULT",now); return; }
  // Stop pump if Python Digital Twin inputs stop arriving; never irrigate on stale data.
  if(twinMode && (lastTwinInput==0 || now-lastTwinInput>TWIN_INPUT_TIMEOUT_MS)) {
    clearAllOneTime(); activeZone=-1; enter(HOLD_NO_WATER,"TWIN_INPUT_STALE",now); return;
  }
  // Absolute startup guard even if D/preset was pressed immediately after ON.
  if(now-masterEnabledAt<MASTER_RECHECK_MS) {
    activeZone=-1; enter(REST,"MASTER_ON_RECHECK",now); return;
  }
  // Fill never steals capacity from irrigation (including the inter-session REST period).
  const bool needsWater=demand[0] || demand[1];
  // Finish an already running continuous session when the window closes;
  // outside the window, a new irrigation session is never initiated.
  const bool windowOpen=irrigationWindow(now);
  // Check a suspended session against CURRENT soil, hold, permission and time.
  // Never bypass master/fault/twin/source interlocks to restart it.
  if(pausedSessionPending) {
    int zi=pausedSessionZone;
    if(zi<0 || zi>=configuredZones || !demand[zi] ||
       (!windowOpen && !authorizedOutsideWindow(zi)) ||
       pausedSessionRemainingMs==0) {
      Serial.println("PAUSE SESSION CANCELLED: soil/permission/window changed");
      discardPausedSession();
    }
  }
  const bool specialAllowed=authorizedOutsideWindow(0) || authorizedOutsideWindow(1);
  const bool hasDemand=needsWater && (windowOpen || watering(state) || specialAllowed);
  if(hasDemand && state==REFILL_TANK) {
    activeZone=-1; enter(REST,"REFILL_PREEMPT_IRRIGATION",now);
  }
  if(!hasDemand) {
    discardPausedSession();
    activeZone=-1;
    if(testMode) { enter(IDLE,"SOIL_OK",now); return; }
    // Respect recovery REST before starting a different pump/flow path.
    if(state==REST && now-restStart<REST_MS) return;
    if(refillAuto && (testMode||twinMode||tankLevelValid) && tankL<=REFILL_START_L) refillCycle=true;
    // End fill at upper stop level; manual request is one fill-up, not indefinite.
    if(tankL>=REFILL_STOP_L) {refillRequested=false;refillCycle=false;}
    if(state==REFILL_TANK && (now-refillStart>=MAX_REFILL_MS)) {
      refillFault=true; refillRequested=false; refillCycle=false;
      enter(IDLE,"REFILL_TIMEOUT",now); return;
    }
    if((refillCycle||refillRequested) && !refillFault && (testMode||twinMode||tankLevelValid) && canalOK() && tankL<REFILL_STOP_L) {
      enter(REFILL_TANK,"REFILL_CANAL_TO_TANK",now); return;
    }
    enter(IDLE,refillFault?"REFILL_TIMEOUT":!canalOK()?"REFILL_CANAL_UNSAFE":needsWater?"WAIT_IRRIGATION_WINDOW":"SOIL_OK",now);
    return;
  }
  if(state==REST && now-restStart<REST_MS) return;
  if(watering(state)) {
    if(activeZone<0 || activeZone>=configuredZones || !demand[activeZone] || now-sessionStart>=sessionBudgetMs) {
      stopForRest(now); return;
    }
    // If source becomes unavailable, move to another without resetting session timer.
    if(useCanal(state) && !canalOK()) {
      if(tankOK()) enter(wateringState(activeZone,false),"SALINITY_OR_CANAL_LOW",now);
      else { activeZone=-1; enter(HOLD_NO_WATER,"NO_SAFE_SOURCE",now); }
      return;
    }
    if(useTank(state) && !tankOK()) {
      if(canalOK()) enter(wateringState(activeZone,true),"TANK_LOW_USE_CANAL",now);
      else { activeZone=-1; enter(HOLD_NO_WATER,"NO_SAFE_SOURCE",now); }
      return;
    }
    // Prefer the canal again after salinity has been safely released.
    if(useTank(state) && canalOK()) {
      enter(wateringState(activeZone,true),"CANAL_SAFE_AGAIN",now);
    }
    return;
  }
  if(!canalOK() && !tankOK()) {
    // Do not resume an interrupted session automatically after a source fault.
    discardPausedSession();
    activeZone=-1; enter(HOLD_NO_WATER,"NO_SAFE_SOURCE",now); return;
  }
  // Resume the SAME zone before normal round-robin selection, reusing ONLY
  // the remaining pump-on budget. REST and PAUSE have not consumed that budget.
  bool resuming=pausedSessionPending;
  unsigned long remaining=resuming?pausedSessionRemainingMs:0;
  activeZone=resuming?pausedSessionZone:
    ((!windowOpen && specialAllowed)?selectAuthorizedZone():selectZone());
  if(activeZone<0) { discardPausedSession();enter(IDLE,"SOIL_OK",now); return; }
  if(!resuming) {
    sessionBudgetMs=durationForZone(activeZone);
    sessionEstimatedL=0.0f;
    remaining=sessionBudgetMs;
    Serial.printf("IRRIGATION PLAN Z%d flow=%.2fLpm limit=%.2fL duration=%lums (continuous, estimated)\n",
      activeZone+1,flowLpm[activeZone],sessionTargetL[activeZone],sessionBudgetMs);
  }
  if(!windowOpen && extraWaterGranted[activeZone] && !extraWaterStarted[activeZone]) {
    extraWaterStarted[activeZone]=true;
    extraWaterStartedAt[activeZone]=now;
  }
  // enter() normally starts a fresh session timer. Restore consumed time only
  // AFTER that transition, so the final cumulative pump-on time is unchanged.
  enter(wateringState(activeZone,canalOK()),resuming?"PAUSE_RESUME_REMAINING":canalOK()?"CANAL_SAFE":"USE_TANK",now);
  if(resuming) {
    unsigned long alreadyUsed=sessionBudgetMs-remaining;
    sessionStart=now-alreadyUsed;
    Serial.printf("PAUSE SESSION RESUMED: Z%d remaining=%lums used=%lums\n",
                  activeZone+1,remaining,alreadyUsed);
    discardPausedSession();
  }
}

void tickWorld(unsigned long now) {
  if(testMode || twinMode) return; // soil and tank driven by Python when TWIN is ON
  // LOCAL moisture is measured from two knobs; never synthesize soil changes.
  // Adjust the Wokwi Z1/Z2 knobs to simulate irrigation-driven soil moisture.
  // The reserve tank is canal-fed, NOT rain-fed: no unexplained water gain.
  if(state==REFILL_TANK && canalOK() && !refillFault) {
    const float added=1.25f; // L per simulated second, demonstration only
    // In LOCAL, the sensor measurement is authoritative; no virtual level increase.
    (void)added;
  }
  if(watering(state) && activeZone>=0) {
    if(useTank(state)) { tankUsedL+=36.0f; } // Water level is sensor measured in LOCAL.
    else canalUsedL+=2.0f;
  }
  updateSafety(now); updateDemand();
}

// Read actual DHT22/DS18B20 simulator values. Neither blocks control timing.
// These readings are monitoring-only until a crop/water-specific rule is validated.
void tickEnvironment(unsigned long now) {
  if(now-lastAirSample>=AIR_MS) {
    lastAirSample=now;
    TempAndHumidity sample=airSensor.getTempAndHumidity();
    airReadingOK=isfinite(sample.temperature) && isfinite(sample.humidity)
               && sample.humidity>=0 && sample.humidity<=100;
    if(airReadingOK) {
      airTempC=sample.temperature; airRH=sample.humidity;
      if(airReadFailCount) Serial.printf("DHT22 RECOVERED pin=%d air=%.1fC RH=%.1f%%\n",DHT_PIN,airTempC,airRH);
      airReadFailCount=0;
    } else {
      airTempC=NAN; airRH=NAN;
      if(airReadFailCount<255) airReadFailCount++;
      if(lastAirDiag==0 || now-lastAirDiag>=15000UL) {
        lastAirDiag=now;
        Serial.printf("DHT22 READ FAILED pin=%d temp=%.1f rh=%.1f status=%s failures=%u\n",DHT_PIN,sample.temperature,sample.humidity,airSensor.getStatusString(),airReadFailCount);
      }
    }
  }
  if(waterPending && now-waterStarted>=WATER_CONVERSION_MS) {
    float value=waterSensor.getTempCByIndex(0);
    waterReadingOK=isfinite(value) && value!=DEVICE_DISCONNECTED_C
                && value>=-55 && value<=125;
    waterTempC=waterReadingOK?value:NAN;
    if(waterReadingOK) {
      if(waterReadFailCount>0) Serial.printf("DS18B20 RECOVERED pin=%d temp=%.1fC\n",WATER_TEMP_PIN,waterTempC);
      waterReadFailCount=0;
    } else {
      if(waterReadFailCount<255) waterReadFailCount++;
      if(now-lastWaterDiag>=15000UL || lastWaterDiag==0) {
        lastWaterDiag=now;
        Serial.printf("DS18B20 READ FAILED pin=%d raw=%.1f devices=%d failures=%u\n",
          WATER_TEMP_PIN,value,waterSensor.getDeviceCount(),waterReadFailCount);
      }
      // A disconnected/missed sensor must not be replaced with fabricated values.
      if(waterReadFailCount>=3) {
        waterSensor.begin();waterSensor.setResolution(10);
        waterSensor.setWaitForConversion(false);
        waterReadFailCount=0;
      }
    }
    waterPending=false;
  }
  if(!waterPending && now-lastWaterRequest>=WATER_MS) {
    waterSensor.requestTemperatures(); // async 10-bit conversion, avoids ~750ms delay
    lastWaterRequest=now;
    waterStarted=now;
    waterPending=true;
  }
}
void printEnvironment() {
  Serial.print("ENV airC=");
  if(airReadingOK) Serial.print(airTempC,1); else Serial.print("NA");
  Serial.print(" rhPct=");
  if(airReadingOK) Serial.print(airRH,1); else Serial.print("NA");
  Serial.print(" waterC=");
  if(waterReadingOK) Serial.print(waterTempC,1); else Serial.print("NA");
  Serial.println(" (DHT22/DS18B20 readings; monitoring only)");
}
void printInputs() {
  Serial.printf("INPUTS [%s] SALT=%.1fppt CANAL=%.0f%% RAIN=%.0f%% Z1=%.0f%% Z2=%.0f%% TANK=%.1fL\n",
    testMode?"PRESET":twinMode?"TWIN":"DYNAMIC",saltPpt,canalPct,rainPct,soil[0],soil[1],tankL);
  printEnvironment();
}
void printStatus() {
  Serial.printf("STATUS mode=%s TC=%c state=%s reason=%s source=%s zone=%d canalSafe=%s tankOK=%s pause=%s fault=%s rest=%s zones=%d pumpRelay=%s fillPump=%s tankSalt=%.2f tankSaltPolicy=MONITOR_ONLY master=%s switch=%s armed=%s clockOK=%s window=%s hold1=%s hold2=%s once1=%s once2=%s\n",
    testMode?"PRESET":twinMode?"TWIN":"DYNAMIC",lastTest,stateName(state),reason,
    useCanal(state)?"CANAL":useTank(state)?"TANK":"NONE",
    watering(state)?activeZone+1:0,canalOK()?"YES":"NO",tankOK()?"YES":"NO",
    paused?"YES":"NO",injectedFault?"YES":"NO",state==REST?"YES":"NO",
    configuredZones,watering(state)?"ON":"OFF",state==REFILL_TANK?"ON":"OFF",tankSaltPpt,
    masterEnabled?"ON":"OFF",digitalRead(MASTER_SWITCH_PIN)==HIGH?"ON":"OFF",
    masterArmed?"YES":"NO",clockValid(millis())?"YES":"NO",irrigationWindow(millis())?"YES":"NO",
    zoneHold[0]?"YES":"NO",zoneHold[1]?"YES":"NO",
    extraWaterGranted[0]?"YES":"NO",extraWaterGranted[1]?"YES":"NO");
  printEnvironment();
  printNetworkStatus();
}
void printCSV(unsigned long now) {
  Serial.printf("DATA,%lu,%.2f,%.0f,%.0f,%.0f,%.0f,%.1f,%s,%d,%s,%d,%d,%.1f,%.1f,%.1f\n",now,
    saltPpt,canalPct,rainPct,soil[0],soil[1],tankL,
    useCanal(state)?"CANAL":useTank(state)?"TANK":"NONE",
    watering(state)?activeZone+1:0,stateName(state),configuredZones,watering(state)?1:0,
    airTempC,airRH,waterTempC);
}
void showHelp() {
  Serial.println("=== SALTGUARD MVP 1.1.3 / FAIR ZONE QUEUE HELP ===");
  Serial.println("D=LOCAL sensors on Wokwi; disables SIMULATION input");
  Serial.println("SIMULATION: Use Dashboard; when data stale 12s, pump stops.");
  Serial.println("Z=toggle 1 / 2 active zones (DYNAMIC/TWIN; no extra ESP32)");
  Serial.println("ENV: DHT22 air and DS18B20 water temp from simulator parts");
  Serial.println("LOCAL Z1/Z2 soil on ADC1 GPIO33/GPIO39; tank via HC-SR04");
  Serial.println("LOCAL: turn Z1/Z2 soil knobs for changing moisture; no auto soil increase");
  Serial.println("1 2 3 7 8 9 A B C = preset TC01/02/03/07/08/09/10/11/12");
  Serial.println("TC04..TC06: 2 -> 4 -> 5 -> 6 (do not reset)");
  Serial.println("V=restore test sensor after B; C then PAUSE button for TC12");
  Serial.println("I=inputs S=status E=event ON/OFF L=CSV ON/OFF P=one CSV row ?=help");
  Serial.println("CSV off by default; event log ON. Panel YELLOW=PAUSE BLUE=MANUAL RED=ACK; K=MANUAL GPIO diagnostic.");
  Serial.println("N=network MQTT; commands STATUS ZONES:1/2 TWIN:ON/OFF; no remote master ON/OFF");
  Serial.println("FILL:REQUEST FILL:CANCEL FILL:AUTO:ON FILL:AUTO:OFF; irrigation priority");
  Serial.println("PANEL buttons: YELLOW=PAUSE BLUE=MANUAL one session/eligible dry zone RED=ACK SHORT MUTE / HOLD 2s RECOVER.");
  Serial.println("PHYSICAL MASTER: OFF at boot; switch OFF then ON to permit operation.");
  Serial.println("ZONE:1:HOLD / ZONE:1:RESUME (also Z2) via MQTT; durable on ESP32.");
  Serial.println("CLOCK:<unix>; ZONE:1:ONCE and ZONE:2:ONCE may queue together; alternating 10s/REST 2s.");
  Serial.println("T=2 min demo window (Serial only). Firmware NEVER permits remote MASTER ON.");
  Serial.println("Phase 4.3: expert TEST:FLOW:ZERO TEST:VALVE:STUCK TEST:SENSOR:BAD TEST:CLEAR");
}
void resetVirtualFault();
void resetController(unsigned long now) {
  refillRequested=false; refillCycle=false; refillFault=false;
  clearAllOneTime();
  paused=false; injectedFault=false; resetVirtualFault(); canalLocked=saltPpt>=SALT_BLOCK;
  tankReady=tankL>TANK_STOP; releaseCounting=false;
  demand[0]=false; demand[1]=false;naturalDemand[0]=false;naturalDemand[1]=false;activeZone=-1; lastServedZone=1;
  state=IDLE; reason="TEST_INIT";
  restStart=now; sessionStart=now;
  outputsOff();
  // Debounce states follow actual pins so first press is detected after switching modes.
  bPause.lastRaw=bPause.stable=digitalRead(bPause.pin); bPause.edge=now; pausePinLastRaw=bPause.stable;
  bManual.lastRaw=bManual.stable=digitalRead(bManual.pin); bManual.edge=now; manualPinLastRaw=bManual.stable;
  manualNoticeUntil=0;
  bRefill.lastRaw=bRefill.stable=digitalRead(bRefill.pin); bRefill.edge=now;
}
void preset(char c,unsigned long now) {
  testMode=true; twinMode=false; lastTwinInput=0; lastTest=c; configuredZones=2;
  saltPpt=0.5f; canalPct=75; rainPct=0;
  soil[0]=20; soil[1]=70; tankL=1000; tankSaltPpt=0.3f;
  switch(c) {
    case '1': soil[0]=70; soil[1]=75; break;
    case '3': soil[0]=70; soil[1]=20; break;
    case '7': canalPct=5; break;
    case '8': saltPpt=1.5f; tankL=100; break;
    case '9': soil[1]=20; break;
    case 'B': injectedFault=true; break;
    default: break;
  }
  resetController(now);
  if(c=='B') injectedFault=true;
  updateSafety(now); updateDemand(); control(now);
  Serial.printf("PRESET TC%s selected.\n",c=='A'?"10":c=='B'?"11":c=='C'?"12":
    c=='1'?"01":c=='2'?"02":c=='3'?"03":c=='7'?"07":c=='8'?"08":"09");
  printInputs(); printStatus();
}
void handleSerial(unsigned long now) {
  while(Serial.available()>0) {
    char c=(char)Serial.read();
    if(c=='\r'||c=='\n'||c==' ') continue;
    if(c>='a'&&c<='z') c=(char)(c-32);
    if(c=='?') showHelp();
    else if(c=='I') printInputs();
    else if(c=='N') printNetworkStatus();
    else if(c=='S') printStatus();
    else if(c=='T') {demoWindowOverride=true;demoWindowUntil=now+120000UL;
      Serial.println("DEMO WINDOW 120s (Serial only; MASTER switch and safety still mandatory)");}
    else if(c=='P') printCSV(now);
    else if(c=='Z') {
      if(testMode) {Serial.println("Z only in DYNAMIC: enter D first.");}
      else {
        configuredZones=(configuredZones==2?1:2);
        if(configuredZones==1) clearOneTime(1);
        updateDemand();
        if(activeZone>=configuredZones) {activeZone=-1;enter(REST,"ZONE_DISABLED",now);}
        control(now);
        Serial.printf("CONFIG activeZones=%d (Z2 %s)\n",configuredZones,
                      configuredZones==2?"ENABLED":"DISABLED");
        printStatus();
      }
    }
    else if(c=='M') {
      Serial.println("MANUAL: use the BLUE physical pushbutton; no serial pump override.");
    }
    else if(c=='K') {
      Serial.printf("PANEL DIAG MANUAL GPIO%d=%d lastRaw=%d stable=%d 3V3 PULLUP=EXTERNAL\n",
                    MANUAL_PIN,
                    digitalRead(MANUAL_PIN),bManual.lastRaw,bManual.stable);
      Serial.printf("PANEL DIAG PAUSE GPIO17=%d lastRaw=%d stable=%d\n",
                    digitalRead(PAUSE_PIN),bPause.lastRaw,bPause.stable);
    }
    else if(c=='L') { csvStream=!csvStream; Serial.println(csvStream?"CSV ON":"CSV OFF"); }
    else if(c=='E') { eventStream=!eventStream; Serial.println(eventStream?"EVENT ON":"EVENT OFF"); }
    else if(c=='D') {
      testMode=false;twinMode=false;lastTwinInput=0;lastTest='-';configuredZones=2;saltPpt=0.5f;canalPct=80;rainPct=0;
      soil[0]=24;soil[1]=49;tankL=1500;tankSaltPpt=0.3f;canalUsedL=tankUsedL=0;
      readKnobs();resetController(now);control(now);
      Serial.println("LOCAL mode: knobs SALT/CANAL/RAIN/SOIL_Z1/SOIL_Z2 and tank sensor.");
      printInputs();
    } else if(c=='V') {
      if(testMode&&lastTest=='B') {
        injectedFault=false; activeZone=-1; enter(REST,"FAULT_RECOVERY",now);
        Serial.println("Fault restored; REST 2s then recheck.");
      } else Serial.println("V only for TC11 after B.");
    } else if(c=='4'||c=='5'||c=='6') {
      bool ok=testMode && ((c=='4'&&lastTest=='2')||
        (c=='5'&&lastTest=='4')||(c=='6'&&lastTest=='5'));
      if(!ok) { Serial.println("Use ordered sequence 2 -> 4 -> 5 -> 6."); continue; }
      saltPpt=(c=='4'?1.5f:c=='5'?0.8f:0.5f); lastTest=c;
      updateSafety(now);control(now);
      Serial.printf("PRESET TC0%c changed salinity; history preserved.\n",c);
      printInputs();printStatus();
    } else if(c=='1'||c=='2'||c=='3'||c=='7'||c=='8'||c=='9'||
              c=='A'||c=='B'||c=='C') preset(c,now);
    else Serial.println("Unknown command; enter ? for help.");
  }
}
// Physical MANUAL button is deliberately not a remote pump/valve override.
void manualNotice(unsigned long now, const char* line1, const char* line2) {
  snprintf(manualNoticeTop,sizeof(manualNoticeTop),"%.16s",line1);
  snprintf(manualNoticeBottom,sizeof(manualNoticeBottom),"%.16s",line2);
  manualNoticeUntil=now+MANUAL_NOTICE_MS;
  updateLCD();
}
void requestManualIrrigation(unsigned long now) {
  updateSafety(now);
  updateDemand();
  const char* reject=nullptr;
  if(!masterEnabled) reject="MASTER DANG TAT";
  else if(emergencyLatched) reject="DUNG KHAN CAP";
  else if(paused || state==PAUSE) reject="DANG TAM DUNG";
  else if(testMode || injectedFault || state==FAULT) reject="DANG CO LOI";
  else if(twinMode && (lastTwinInput==0 || now-lastTwinInput>TWIN_INPUT_TIMEOUT_MS))
    reject="DU LIEU QUA HAN";
  else if(!clockValid(now)) reject="CHUA CO GIO";
  else if(irrigationWindow(now)) reject="DANG TRONG LICH";
  else if(watering(state)) reject="DANG TUOI";
  else if(!canalOK() && !tankOK()) reject="KHONG CO NGUON";
  bool eligible[2]={false,false};
  if(!reject) {
    for(int zi=0;zi<configuredZones && zi<2;zi++) {
      eligible[zi]=!zoneHold[zi] && demand[zi] && !extraWaterGranted[zi];
    }
    if(!eligible[0] && !eligible[1]) {
      reject=(demand[0] || demand[1])?"VUNG DANG KHOA":"DAT KHONG CAN";
    }
  }
  if(reject) {
    Serial.printf("PANEL MANUAL REJECTED: %s (state=%s)\n",reject,stateName(state));
    manualNotice(now,"MANUAL TU CHOI",reject);
    return;
  }
  for(int zi=0;zi<2;zi++) if(eligible[zi]) {
    extraWaterGranted[zi]=true;
    extraWaterStarted[zi]=false;
    extraWaterQueuedAt[zi]=now;
    extraWaterStartedAt[zi]=0;
    manualSessionOneShot[zi]=true;
  }
  Serial.printf("PANEL MANUAL ACCEPTED: Z1=%s Z2=%s (one session/zone; safety and REST retained)\n",
                eligible[0]?"QUEUED":"NO",eligible[1]?"QUEUED":"NO");
  control(now);
  manualNotice(now,"MANUAL DA NHAN",eligible[0]&&eligible[1]?"CHO TUOI Z1 + Z2":eligible[0]?"CHO TUOI VUNG 1":"CHO TUOI VUNG 2");
}
void handleButtons(unsigned long now) {
  int rawPause=digitalRead(PAUSE_PIN);
  if(rawPause!=pausePinLastRaw) {
    Serial.printf("PANEL PAUSE GPIO17 %s\n",rawPause==LOW?"LOW / pressed":"HIGH / released");
    pausePinLastRaw=rawPause;
  }
  int rawManual=digitalRead(MANUAL_PIN);
  if(rawManual!=manualPinLastRaw) {
    Serial.printf("PANEL MANUAL GPIO%d %s\n",MANUAL_PIN,rawManual==LOW?"LOW / pressed":"HIGH / released");
    manualPinLastRaw=rawManual;
  }
  if(edgePressed(bPause,now)) {
    if(!paused) {
      accrueEstimatedWater(now);
      discardPausedSession();
      if(watering(state) && activeZone>=0 && activeZone<configuredZones) {
        unsigned long used=now-sessionStart;
        if(used<sessionBudgetMs) {
          pausedSessionPending=true;
          pausedSessionZone=activeZone;
          pausedSessionRemainingMs=sessionBudgetMs-used;
          Serial.printf("PAUSE SESSION SAVED: Z%d remaining=%lums used=%lums\n",
                        activeZone+1,pausedSessionRemainingMs,used);
        }
      }
      paused=true;
    } else {
      paused=false;
      // Leave actuators OFF through REST. Do NOT clear one-time permission.
      activeZone=-1;
      enter(REST,"RESUME_RECHECK",now);
    }
    Serial.printf("PANEL PAUSE=%s (mode=%s)\n",paused?"ON":"OFF",twinMode?"SIMULATION":"LOCAL");
    control(now);
  }
  // Blue: one-shot physical request, never drives a pump or valve directly.
  if(edgePressed(bManual,now)) {
    requestManualIrrigation(now);
  }
  // Red ACK, debounced: short press/release mutes buzzer; long hold requests
  // local emergency recovery, then requires physical OFF -> ON re-arm.
  bool ackWasDown=(bRefill.stable==LOW);
  bool ackPressed=edgePressed(bRefill,now);
  bool ackIsDown=(bRefill.stable==LOW);
  if(ackPressed) {
    ackDownAt=now;
    ackLongHandled=false;
    Serial.println("ACK PRESS: hold 2s of Wokwi simulation time to recover emergency");
  }
  if(ackIsDown && !ackLongHandled && ackDownAt!=0 &&
     now-ackDownAt>=ACK_RECOVERY_HOLD_MS) {
    ackLongHandled=true;
    if(!emergencyLatched) {
      Serial.println("ACK HOLD: no emergency latch to recover");
    } else {
      // ACK recovery works regardless of current MASTER position.  This is
      // a SAFE controller recovery, not an automatic pump restart: require a
      // fresh physical MASTER OFF -> ON cycle after the latch is cleared.
      outputsOff();
      masterEnabled=false;
      masterArmed=false;
      masterLastRaw=digitalRead(MASTER_SWITCH_PIN);
      masterRawChangedAt=now;
      clearAllOneTime();
      refillRequested=false;
      refillCycle=false;
      activeZone=-1;
      emergencyLatched=false;
      irrigationPrefs.putBool("emergency",false);
      enter(IDLE,"ACK_HOLD_RECOVER_WAIT_MASTER_CYCLE",now);
      applyOutputs();
      updatePanelLeds();
      Serial.println("ACK HOLD: emergency recovered; turn MASTER OFF then ON to resume");
      publishTelemetry(now);
    }
  }
  if(ackWasDown && !ackIsDown) {
    unsigned long heldMs=(ackDownAt!=0 && now>=ackDownAt)?now-ackDownAt:0;
    if(!ackLongHandled) {
      buzzerAcknowledged=true;
      noTone(BUZZER_PIN); // Immediate silence; does not clear safety state.
      Serial.printf("PANEL ALARM ACK SHORT: held=%lu ms (need %lu ms); buzzer muted; safety unchanged\n",
        heldMs, ACK_RECOVERY_HOLD_MS);
    }
    ackDownAt=0;
  }
}


// LCD1602 HD44780 does not have Vietnamese accents in its ROM.
// Use concise, readable Vietnamese WITHOUT diacritics; 16 columns maximum.
void writeLCD(int row,const char* message) {
  char buf[17];snprintf(buf,sizeof(buf),"%-16.16s",message);
  lcd.setCursor(0,row);lcd.print(buf);
}
void setLCDVisible(bool visible) {
  if(lcdVisible==visible) return;
  lcdVisible=visible;
  if(visible) {
    lcd.display();
    lcd.backlight();
    page=0;
    lastPage=millis();
  } else {
    lcd.clear();
    lcd.noDisplay();
    lcd.noBacklight();
  }
}
void updateLCD() {
  if(!masterEnabled || !lcdVisible) return;
  char a[32]={0},b[32]={0};
  const unsigned long now=millis();
  const bool showManualNotice=(int32_t)(manualNoticeUntil-now)>0;
  // Safety states always override MANUAL feedback.
  if(emergencyLatched) {
    snprintf(a,sizeof(a),"DUNG KHAN CAP"); snprintf(b,sizeof(b),"GIU ACK 2s MO");
  } else if(injectedFault||state==FAULT) {
    snprintf(a,sizeof(a),"LOI HE THONG"); snprintf(b,sizeof(b),"BOM + VAN DA TAT");
  } else if(state==HOLD_NO_WATER && strcmp(reason,"TWIN_INPUT_STALE")==0) {
    snprintf(a,sizeof(a),"MAT DL MO PHONG"); snprintf(b,sizeof(b),"BOM + VAN DA TAT");
  } else if(state==HOLD_NO_WATER) {
    snprintf(a,sizeof(a),"KHONG CO NGUON"); snprintf(b,sizeof(b),"KENH %.1f BON %.0fL",saltPpt,tankL);
  } else if(paused||state==PAUSE) {
    snprintf(a,sizeof(a),"DA TAM DUNG"); snprintf(b,sizeof(b),"NUT VANG: TIEP");
  } else if(showManualNotice) {
    snprintf(a,sizeof(a),"%s",manualNoticeTop);
    snprintf(b,sizeof(b),"%s",manualNoticeBottom);
  } else if(now-masterEnabledAt<LCD_WELCOME_MS) {
    // Power-on greeting, only when MASTER is turned ON and no safety issue is active.
    snprintf(a,sizeof(a),"SALTGUARD IOT");
    snprintf(b,sizeof(b),"HE THONG SAN SANG");
  } else if(watering(state)) {
    snprintf(a,sizeof(a),"DANG TUOI VUNG %d",activeZone+1);
    snprintf(b,sizeof(b),"NGUON: %s",useCanal(state)?"NUOC KENH":"NUOC BON");
  } else if(state==REFILL_TANK) {
    snprintf(a,sizeof(a),"DANG NAP BON");snprintf(b,sizeof(b),"MUC BON: %.0fL",tankL);
  } else if(state==REST) {
    snprintf(a,sizeof(a),"DANG NGHI AN TOAN");
    snprintf(b,sizeof(b),"CHO KIEM TRA LAI");
  } else if(strcmp(reason,"WAIT_IRRIGATION_WINDOW")==0) {
    snprintf(a,sizeof(a),"DAT CAN NUOC");snprintf(b,sizeof(b),"CHO GIO UU TIEN");
  } else if(strcmp(reason,"REFILL_CANAL_UNSAFE")==0 && tankL<=REFILL_START_L) {
    snprintf(a,sizeof(a),"CHUA THE NAP BON");snprintf(b,sizeof(b),"KENH KHONG AN");
  } else if(canalLocked && (page%2==0)) {
    snprintf(a,sizeof(a),"KENH NHIEM MAN");snprintf(b,sizeof(b),"DO MAN: %.1fppt",saltPpt);
  } else if(page%2==0) {
    snprintf(a,sizeof(a),"DAT DU AM - CHO");
    snprintf(b,sizeof(b),"Z1 %.0f%%  Z2 %.0f%%",soil[0],soil[1]);
  } else {
    snprintf(a,sizeof(a),"DANG GIAM SAT");
    snprintf(b,sizeof(b),"BON: %.0f/2000L",tankL);
  }
  writeLCD(0,a);writeLCD(1,b);
}

// Distinct audible codes; sequences are scheduled without blocking the loop so MQTT,
// local safety checks and the physical buttons continue to run normally.
// A tone sequence is feedback only: it must NEVER change pump/valve outputs.
const char* alarmName(AlarmKind kind) {
  switch(kind) {
    case AL_EMERGENCY: return "EMERGENCY";
    case AL_FAULT: return "SENSOR_FAULT";
    case AL_STALE: return "TWIN_STALE";
    case AL_NO_WATER: return "NO_SAFE_SOURCE";
    case AL_REFILL: return "REFILL_TIMEOUT";
    case AL_SALINITY: return "SALINITY_USE_TANK";
    default: return "SILENT";
  }
}
AlarmKind classifyAlarm() {
  if(!masterEnabled) return AL_NONE;
  if(emergencyLatched) return AL_EMERGENCY;
  if(injectedFault || state==FAULT) return AL_FAULT;
  if(state==HOLD_NO_WATER) {
    if(strcmp(reason,"TWIN_INPUT_STALE")==0 || strcmp(reason,"WAIT_TWIN_INPUT")==0)
      return AL_STALE;
    return AL_NO_WATER;
  }
  if(refillFault) return AL_REFILL;
  // A gentle advisory only when actually watering from the tank because
  // the canal is salinity-locked. No sound for normal safe source switches.
  if(canalLocked && useTank(state) && watering(state)) return AL_SALINITY;
  return AL_NONE;
}
// gapMs is the silence after each note. The final gap sets repetition cadence.
AlarmNote alarmNote(AlarmKind kind,uint8_t index) {
  switch(kind) {
    case AL_EMERGENCY:
      if(index==0) return {2400,130,110};
      if(index==1) return {1750,130,110};
      return {2400,260,1800};
    case AL_FAULT:
      if(index==0) return {2050,300,130};
      return {1550,300,2500};
    case AL_STALE:
      if(index==0) return {1450,150,140};
      return {1450,150,3100};
    case AL_NO_WATER: return {900,430,3300};
    case AL_REFILL:
      if(index==0) return {1150,105,140};
      return {1150,105,4600};
    case AL_SALINITY:
      if(index==0) return {1000,90,130};
      return {1300,90,8500};
    default: return {0,0,0};
  }
}
uint8_t alarmNoteCount(AlarmKind kind) {
  switch(kind) {
    case AL_EMERGENCY: return 3;
    case AL_FAULT: case AL_STALE: case AL_REFILL: case AL_SALINITY: return 2;
    case AL_NO_WATER: return 1;
    default: return 0;
  }
}
void alarm(unsigned long now) {
  const AlarmKind wanted=classifyAlarm();
  if(wanted!=currentAlarm) {
    noTone(BUZZER_PIN);
    currentAlarm=wanted;
    alarmStep=0;
    nextAlarmAt=now;
    buzzerAcknowledged=false; // A new category is a new, unacknowledged alert.
    Serial.printf("BUZZER ALERT=%s\n",alarmName(wanted));
  }
  if(wanted==AL_NONE || buzzerAcknowledged) return;
  if((int32_t)(now-nextAlarmAt)<0) return;
  const AlarmNote note=alarmNote(wanted,alarmStep);
  if(note.hz==0) return;
  tone(BUZZER_PIN,note.hz,note.ms);
  nextAlarmAt=now+(unsigned long)note.ms+(unsigned long)note.gapMs;
  if(++alarmStep>=alarmNoteCount(wanted)) alarmStep=0;
}
// === GIAI DOAN 2: MQTT TELEMETRY / COMMANDS ===
// ESP32 does NOT trust MQTT for direct pump ON or bypassing the safety controller.
// Network outages must not stop irrigation control; reconnects have retry intervals.
const char* mqttStateLabel(int code) {
  switch (code) {
    case MQTT_CONNECTED: return "CONNECTED";
    case MQTT_CONNECTION_TIMEOUT: return "TIMEOUT";
    case MQTT_CONNECTION_LOST: return "CONNECTION_LOST";
    case MQTT_CONNECT_FAILED: return "CONNECT_FAILED";
    case MQTT_DISCONNECTED: return "DISCONNECTED";
    case MQTT_CONNECT_BAD_PROTOCOL: return "BAD_PROTOCOL";
    case MQTT_CONNECT_BAD_CLIENT_ID: return "BAD_CLIENT_ID";
    case MQTT_CONNECT_UNAVAILABLE: return "SERVER_UNAVAILABLE";
    case MQTT_CONNECT_BAD_CREDENTIALS: return "BAD_CREDENTIALS";
    case MQTT_CONNECT_UNAUTHORIZED: return "UNAUTHORIZED";
    default: return "UNKNOWN";
  }
}
void printNetworkStatus() {
  const bool online=mqtt.connected();
  const int rc=mqtt.state();
  Serial.printf("NETWORK wifi=%s mqtt=%s rc=%d(%s) broker=%s:%u root=%s\n",
    WiFi.status()==WL_CONNECTED?"CONNECTED":"OFFLINE",
    online?"CONNECTED":"OFFLINE",rc,mqttStateLabel(rc),MQTT_HOST,MQTT_PORT,MQTT_ROOT);
  Serial.printf("TOPICS telemetry=%s status=%s command=%s ack=%s\n",
    topicTelemetry.c_str(),topicStatus.c_str(),topicCommand.c_str(),topicAck.c_str());
}
String jFloat(float v,int digits=1) {
  return isfinite(v)?String(v,digits):String("null");
}
const char* jBool(bool v) { return v?"true":"false"; }
const char* virtualFaultName();
void publishTelemetry(unsigned long now) {
  if(!mqtt.connected()) return;
  accrueEstimatedWater(now);
  String data;
  data.reserve(3000); // avoid repeated reallocations with extended telemetry
  data = String("{\"device\":\"") + MQTT_ROOT + "\",\"ms\":" + String(now);
  data += ",\"mode\":\"" + String(testMode?"PRESET":twinMode?"TWIN":"DYNAMIC") + "\"";
  data += ",\"test\":\"" + String(lastTest) + "\"";
  data += ",\"state\":\"" + String(stateName(state)) + "\"";
  data += ",\"reason\":\"" + String(reason) + "\"";
  data += ",\"source\":\"" + String(useCanal(state)?"CANAL":useTank(state)?"TANK":"NONE") + "\"";
  data += ",\"zone\":" + String(watering(state)?activeZone+1:0);
  data += ",\"zones\":" + String(configuredZones);
  data += ",\"salinity_ppt\":" + jFloat(saltPpt,2);
  data += ",\"canal_pct\":" + jFloat(canalPct,1);
  data += ",\"rain_pct\":" + jFloat(rainPct,1);
  data += ",\"soil1_pct\":" + jFloat(soil[0],1);
  data += ",\"soil2_pct\":" + jFloat(soil[1],1);
  data += ",\"soil_start_z1\":" + String(soilStartPct[0]);
  data += ",\"soil_stop_z1\":" + String(soilStopPct[0]);
  data += ",\"soil_start_z2\":" + String(soilStartPct[1]);
  data += ",\"soil_stop_z2\":" + String(soilStopPct[1]);
  data += ",\"soil_config_revision\":" + String(soilConfigRevision);
  data += ",\"tank_l\":" + jFloat(tankL,1);
  data += ",\"tank_sensor_valid\":" + String(jBool(testMode||twinMode||tankLevelValid));
  data += ",\"tank_distance_cm\":" + jFloat(tankDistanceCm,1);
  data += ",\"schedule_am_start\":" + String(morningStart);
  data += ",\"schedule_am_end\":" + String(morningEnd);
  data += ",\"schedule_pm_start\":" + String(afternoonStart);
  data += ",\"schedule_pm_end\":" + String(afternoonEnd);
  data += ",\"schedule_windows\":[";
  for(int wi=0;wi<windowCount;wi++) {
    if(wi)data+=",";
    data += String("{\"enabled\":")+jBool(irrigationWindows[wi].enabled)+",\"start\":"+String(irrigationWindows[wi].start)+",\"end\":"+String(irrigationWindows[wi].end)+"}";
  }
  data += "]";
  data += ",\"valves_mask\":" + String(valveMask);
  data += ",\"valve_v1\":" + String(jBool(valveMask & V1));
  data += ",\"valve_v2\":" + String(jBool(valveMask & V2));
  data += ",\"valve_v3\":" + String(jBool(valveMask & V3));
  data += ",\"valve_v4\":" + String(jBool(valveMask & V4));
  data += ",\"valve_v5\":" + String(jBool(valveMask & V5));
  data += ",\"tank_salt_ppt\":" + jFloat(tankSaltPpt,2);
  data += ",\"tank_quality_policy\":\"MONITOR_ONLY\"";
  data += ",\"tank_quality_safe\":null"; // Deprecated: not evaluated in Core 2.5
  data += ",\"tank_fill_on\":" + String(jBool(state==REFILL_TANK));
  data += ",\"fill_auto\":" + String(jBool(refillAuto));
  data += ",\"fill_queued\":" + String(jBool(refillRequested));
  data += ",\"fill_fault\":" + String(jBool(refillFault));
  data += ",\"air_c\":" + jFloat(airTempC,1);
  data += ",\"air_rh_pct\":" + jFloat(airRH,1);
  data += ",\"water_c\":" + jFloat(waterTempC,1);
  data += ",\"canal_safe\":" + String(jBool(canalOK()));
  data += ",\"tank_ok\":" + String(jBool(tankOK()));
  data += ",\"pump_on\":" + String(jBool(watering(state)));
  data += ",\"paused\":" + String(jBool(paused));
  data += ",\"paused_session_pending\":" + String(jBool(pausedSessionPending));
  data += ",\"paused_session_zone\":" + String(pausedSessionPending?pausedSessionZone+1:0);
  data += ",\"paused_session_remaining_ms\":" + String(pausedSessionPending?pausedSessionRemainingMs:0);
  data += ",\"irrigation_flow_z1_lpm\":" + String(flowLpm[0],2);
  data += ",\"irrigation_flow_z2_lpm\":" + String(flowLpm[1],2);
  data += ",\"irrigation_target_z1_l\":" + String(sessionTargetL[0],2);
  data += ",\"irrigation_target_z2_l\":" + String(sessionTargetL[1],2);
  data += ",\"irrigation_config_revision\":" + String(irrigationConfigRevision);
  data += ",\"irrigation_session_budget_ms\":" + String(sessionBudgetMs);
  data += ",\"irrigation_session_used_ms\":" + String(watering(state)?((int32_t)(now-sessionStart)>=0?min(now-sessionStart,sessionBudgetMs):0):(pausedSessionPending?sessionBudgetMs-pausedSessionRemainingMs:0));
  data += ",\"irrigation_session_estimated_l\":" + String((watering(state)||pausedSessionPending)?sessionEstimatedL:0.0f,3);
  data += ",\"irrigation_session_remaining_l\":" + String((watering(state)&&waterMeterZone>=0)?max(0.0f,sessionTargetL[waterMeterZone]-sessionEstimatedL):(pausedSessionPending&&pausedSessionZone>=0)?max(0.0f,sessionTargetL[pausedSessionZone]-sessionEstimatedL):0.0f,3);
  data += ",\"irrigation_zone1_estimated_total_l\":" + String(zoneEstimatedTotalL[0],3);
  data += ",\"irrigation_zone2_estimated_total_l\":" + String(zoneEstimatedTotalL[1],3);
  data += ",\"irrigation_estimate_only\":true";
  data += ",\"master_enabled\":" + String(jBool(masterEnabled));
  data += ",\"master_switch_on\":" + String(jBool(digitalRead(MASTER_SWITCH_PIN)==HIGH));
  data += ",\"master_armed\":" + String(jBool(masterArmed));
  data += ",\"clock_valid\":" + String(jBool(clockValid(now)));
  data += ",\"irrigation_window\":" + String(jBool(irrigationWindow(now)));
  data += ",\"zone1_hold\":" + String(jBool(zoneHold[0]));
  data += ",\"zone2_hold\":" + String(jBool(zoneHold[1]));
  // Legacy single-zone field retained for older Dashboard versions.
  data += ",\"extra_water_zone\":" + String(extraWaterGranted[0]?1:extraWaterGranted[1]?2:0);
  data += ",\"extra_water_allowed_z1\":" + String(jBool(extraWaterGranted[0]));
  data += ",\"extra_water_allowed_z2\":" + String(jBool(extraWaterGranted[1]));
  data += ",\"extra_water_started_z1\":" + String(jBool(extraWaterStarted[0]));
  data += ",\"extra_water_started_z2\":" + String(jBool(extraWaterStarted[1]));
  data += ",\"emergency_stop\":" + String(jBool(emergencyLatched));
  data += ",\"fault\":" + String(jBool(injectedFault || virtualFaultLatched));
  data += ",\"diag_fault_type\":\"" + String(virtualFaultName()) + "\"";
  data += ",\"diag_fault_latched\":" + String(jBool(virtualFaultLatched));
  data += ",\"diag_virtual_flow_lpm\":" + String((watering(state) && virtualFault!=VF_NO_FLOW)?flowLpm[activeZone]:0.0f,2);
  data += ",\"diag_virtual_valve_ok\":" + String(jBool(virtualFault!=VF_VALVE_STUCK));
  data += ",\"twin_active\":" + String(jBool(twinMode));
  data += ",\"twin_rx_count\":" + String(twinRxCount);
  data += "}";
  // Include MQTT fixed header and topic length in the packet budget.
  // PubSubClient may reject oversized JSON even when mqtt.connected() is true.
  const size_t payloadBytes=data.length();
  const size_t packetBytes=5 + 2 + topicTelemetry.length() + payloadBytes;
  const size_t packetLimit=mqtt.getBufferSize();
  if(packetBytes>packetLimit) {
    Serial.printf("MQTT ERROR telemetry oversized: payload=%u packet~=%u buffer=%u\n",
      (unsigned)payloadBytes,(unsigned)packetBytes,(unsigned)packetLimit);
    lastTelemetry=now; // avoid flooding logs every loop
    return;
  }
  if(!mqtt.publish(topicTelemetry.c_str(),data.c_str(),false)) {
    Serial.printf("MQTT WARN telemetry publish failed payload=%u buffer=%u rc=%d wifi=%d\n",
      (unsigned)payloadBytes,(unsigned)packetLimit,mqtt.state(),WiFi.status());
  }
  lastTelemetry=now; // throttle warnings as well as successful publishes

}
void publishAck(const char* command,bool accepted,const char* message,unsigned long now) {
  if(!mqtt.connected()) return;
  String data=String("{\"ms\":")+String(now)+",\"command\":\""+String(command)
    +"\",\"accepted\":"+String(jBool(accepted))+",\"message\":\""+String(message)
    +"\",\"state\":\""+String(stateName(state))+"\"}";
  mqtt.publish(topicAck.c_str(),data.c_str(),false);
}
void onMqttCommand(char* topic,byte* payload,unsigned int length) {
  if(topicTwin==String(topic)) {
    if(!twinMode || testMode || length==0 || length>=135) return;
    char input[136]; memcpy(input,payload,length); input[length]='\0';
    float a,b,c,d,e,f,g; char extra;
    // SGT2 adds virtual tank salinity (independent from canal salinity).
    // Reject malformed frames without partially applying values.
    if(sscanf(input,"SGT2,%f,%f,%f,%f,%f,%f,%f%c",&a,&b,&c,&d,&e,&f,&g,&extra)!=7 ||
       !isfinite(a)||!isfinite(b)||!isfinite(c)||!isfinite(d)||!isfinite(e)||!isfinite(f)||!isfinite(g)||
       a<0||a>3||b<0||b>100||c<0||c>100||d<0||d>100||e<0||e>100||f<0||f>TANK_CAPACITY||g<0||g>3) {
      Serial.println("TWIN INPUT REJECTED: invalid SGT2 frame");return;
    }
    const unsigned long now=millis();
    const bool wasStale=(lastTwinInput==0 || now-lastTwinInput>TWIN_INPUT_TIMEOUT_MS);
    saltPpt=a;canalPct=b;rainPct=c;soil[0]=d;soil[1]=e;tankL=f;tankSaltPpt=g;
    lastTwinInput=now;
    ++twinRxCount;
    if(customAwaitInput && customActive) {
      customAwaitInput=false;
      Serial.printf("CUSTOM DA NHAN: Z1=%.0f%% Z2=%.0f%% MAN=%.2fppt KENH=%.0f%% MUA=%.0f%% BON=%.0fL (rx=%lu)\n",
                    soil[0],soil[1],saltPpt,canalPct,rainPct,tankL,(unsigned long)twinRxCount);
      Serial.println("CUSTOM tiep tuc mo phong; khong co ket thuc tu dong.");
    }
    if(demoAwaitInput && demoCase>=1 && demoCase<=7) {
      demoAwaitInput=false;
      Serial.printf("\n========== KIEM THU TC%02d BAT DAU ==========\n",demoCase);
      Serial.printf("DA AP DUNG: Z1=%.0f%% Z2=%.0f%% MAN=%.2fppt KENH=%.0f%% BON=%.0fL\n",soil[0],soil[1],saltPpt,canalPct,tankL);
      Serial.println("Theo doi EVENT / relay / van; bat dau khong co nghia la PASS.");
    }
    if(wasStale) {
      activeZone=-1; enter(REST,"TWIN_DATA_RESTORED",now);
      Serial.println("TWIN DATA RECEIVED: REST 2s before irrigation");
    }
    updateSafety(now);control(now);
    return;
  }
  if(topicCommand!=String(topic)) return;
  if(length==0 || length>=128) {publishAck("INVALID",false,"INVALID_LENGTH",millis());return;}
  char command[128]; memcpy(command,payload,length);command[length]='\0';
  String cmd=String(command);cmd.trim();cmd.toUpperCase();
  const unsigned long now=millis();
  bool accepted=true;
  const char* result="OK";
  if(cmd=="EMERGENCY:STOP") {
    emergencyLatched=true;irrigationPrefs.putBool("emergency",true);clearAllOneTime();refillRequested=false;refillCycle=false;
    activeZone=-1;enter(FAULT,"REMOTE_EMERGENCY_STOP",now);
    applyOutputs();result="EMERGENCY_LATCHED";
  } else if(cmd=="EMERGENCY:RESET") {
    accepted=false;result="LOCAL_ACK_HOLD_REQUIRED"; // No remote clearing of emergency latch.
  } else if(cmd=="DEMO:CUSTOM:START" || cmd=="DEMO:CUSTOM:UPDATE" || cmd=="DEMO:CUSTOM:END") {
    if(cmd=="DEMO:CUSTOM:END") {
      if(customActive) Serial.println("========== TUY CHINH KET THUC ==========");
      customActive=false;customAwaitInput=false;
      result="CUSTOM_ENDED";
    } else if(!twinMode || testMode) {
      accepted=false;result="TWIN_NOT_ACTIVE";
    } else {
      customActive=true;customAwaitInput=true;
      Serial.println(cmd.endsWith(":START")?
        "\n========== TUY CHINH BAT DAU ==========" :
        "\n========== TUY CHINH CAP NHAT ==========");
      result="WAIT_CUSTOM_TWIN_FRAME";
    }
  } else if(cmd.startsWith("DEMO:TC") &&
      (cmd.endsWith(":START") || cmd.endsWith(":END"))) {
    int tc=cmd.substring(7,9).toInt();
    String canonical=String("DEMO:TC") + (tc<10?"0":"") + String(tc);
    bool start=cmd.endsWith(":START");
    if(tc<1 || tc>7 || cmd != canonical+(start?":START":":END")) {
      accepted=false;result="INVALID_TC";
    } else if(start) {
      if(!twinMode || testMode) {accepted=false;result="TWIN_NOT_ACTIVE";}
      else {
        demoCase=tc;demoAwaitInput=(tc!=7);
        result=(tc==7)?"STALE_TEST_STARTED":"WAIT_TWIN_FRAME";
        if(tc==7) Serial.println("\n========== KIEM THU TC07 BAT DAU: TAM NGUNG TWIN ==========");
      }
    } else {
      if(demoCase==tc) {
        Serial.printf("========== KIEM THU TC%02d KET THUC (Dashboard) ==========\n\n",tc);
        demoCase=0;demoAwaitInput=false;
      }
      result="DEMO_ENDED";
    }
  } else if(cmd=="TEST:FLOW:ZERO" || cmd=="TEST:VALVE:STUCK" || cmd=="TEST:SENSOR:BAD" || cmd=="TEST:CLEAR") {
    // Expert-only via Backend allowlist. No effect on physical MASTER or emergency latch.
    if(cmd=="TEST:CLEAR") {
      resetVirtualFault();
      if(state==FAULT && !emergencyLatched && !injectedFault) {
        activeZone=-1;enter(REST,"DIAG_CLEARED_RECHECK",now);
      }
      control(now); result="DIAG_CLEARED";
    } else if(!testMode && !twinMode) {accepted=false;result="DIAG_SIMULATION_ONLY";}
    else if(emergencyLatched || injectedFault || virtualFaultLatched) {accepted=false;result="DIAG_BLOCKED_BY_FAULT";}
    else {
      applyVirtualFault(cmd=="TEST:FLOW:ZERO"?VF_NO_FLOW:cmd=="TEST:VALVE:STUCK"?VF_VALVE_STUCK:VF_SOIL_INVALID,now);
      control(now);result="DIAG_INJECTED";
    }
  } else if(cmd.startsWith("WATER:")) {
    // WATER:flow1,target1,flow2,target2, in tenths of L/min and tenths of L.
    // Integer-only wire protocol avoids ambiguous float formatting/locale.
    int f1=0,v1=0,f2=0,v2=0;char tail=0;
    bool valid=sscanf(cmd.substring(6).c_str(),"%d,%d,%d,%d%c",&f1,&v1,&f2,&v2,&tail)==4
      && f1>=10 && f1<=1000 && f2>=10 && f2<=1000
      && v1>=10 && v1<=5000 && v2>=10 && v2<=5000;
    if(!valid) {accepted=false;result="INVALID_WATER_CONFIG";}
    else if(watering(state) || pausedSessionPending || paused) {
      accepted=false;result="WATER_CONFIG_BUSY"; // Never change the budget in a running/suspended session.
    } else {
      flowLpm[0]=f1/10.0f;flowLpm[1]=f2/10.0f;
      sessionTargetL[0]=v1/10.0f;sessionTargetL[1]=v2/10.0f;
      irrigationPrefs.putUShort("flow1",f1);irrigationPrefs.putUShort("flow2",f2);
      irrigationPrefs.putUShort("vol1",v1);irrigationPrefs.putUShort("vol2",v2);
      irrigationConfigRevision++;
      Serial.printf("WATER CONFIG SAVED Z1=%.1fLpm/%.1fL/%lums Z2=%.1fLpm/%.1fL/%lums\n",
        flowLpm[0],sessionTargetL[0],durationForZone(0),flowLpm[1],sessionTargetL[1],durationForZone(1));
      result="WATER_CONFIG_SAVED";
    }
  } else if(cmd.startsWith("SOIL:")) {
    // SOIL:start1,stop1,start2,stop2 — compact, validated atomically.
    int a=-1,b=-1,c=-1,d=-1;char tail=0;
    String raw=cmd.substring(5);
    bool ok=sscanf(raw.c_str(),"%d,%d,%d,%d%c",&a,&b,&c,&d,&tail)==4
         && a>=5 && a<=80 && b>=a+5 && b<=95
         && c>=5 && c<=80 && d>=c+5 && d<=95;
    if(!ok) {accepted=false;result="INVALID_SOIL_THRESHOLDS";}
    else {
      soilStartPct[0]=a;soilStopPct[0]=b;
      soilStartPct[1]=c;soilStopPct[1]=d;
      irrigationPrefs.putUChar("soilS1",a);
      irrigationPrefs.putUChar("soilT1",b);
      irrigationPrefs.putUChar("soilS2",c);
      irrigationPrefs.putUChar("soilT2",d);
      soilConfigRevision++;
      // Re-evaluate immediately; never bypass pauses, source checks or REST.
      updateDemand();control(now);
      result="SOIL_THRESHOLDS_SAVED";
      Serial.printf("SOIL CONFIG SAVED: Z1=%d/%d Z2=%d/%d rev=%lu\n",a,b,c,d,(unsigned long)soilConfigRevision);
    }
  } else if(cmd.startsWith("WIN:")) {
    // WIN:1,330,540;0,990,1110;...  (max four windows)
    IrrWindow candidate[MAX_WINDOWS];int count=0;bool valid=true;
    String raw=cmd.substring(4);
    if(raw.length()==0){valid=false;}
    while(valid && raw.length()>0 && count<MAX_WINDOWS) {
      int split=raw.indexOf(';');
      String item=split<0?raw:raw.substring(0,split);
      int p1=item.indexOf(','),p2=item.indexOf(',',p1+1);
      if(p1<0||p2<0||item.indexOf(',',p2+1)>=0){valid=false;break;}
      String en=item.substring(0,p1),a=item.substring(p1+1,p2),b=item.substring(p2+1);
      if((en!="0"&&en!="1")||a.length()==0||b.length()==0){valid=false;break;}
      for(unsigned int k=0;k<a.length();k++)if(!isDigit(a[k]))valid=false;
      for(unsigned int k=0;k<b.length();k++)if(!isDigit(b[k]))valid=false;
      if(!valid)break;
      int x=a.toInt(),y=b.toInt();
      if(x<0||y>1439||x>=y){valid=false;break;}
      candidate[count++]={en=="1",x,y};
      raw=split<0?"":raw.substring(split+1);
    }
    if(raw.length()>0 || count==0)valid=false;
    for(int i=0;i<count&&valid;i++)for(int j=i+1;j<count;j++){
      if(candidate[i].enabled&&candidate[j].enabled &&
          candidate[i].start<candidate[j].end && candidate[j].start<candidate[i].end)valid=false;
    }
    if(!valid){accepted=false;result="INVALID_WINDOWS";}
    else {
      windowCount=count;
      for(int i=0;i<count;i++)irrigationWindows[i]=candidate[i];
      irrigationPrefs.putUChar("winCount",windowCount);
      for(int i=0;i<count;i++) {
        String k="w"+String(i);
        irrigationPrefs.putBool((k+"e").c_str(),candidate[i].enabled);
        irrigationPrefs.putUShort((k+"s").c_str(),candidate[i].start);
        irrigationPrefs.putUShort((k+"t").c_str(),candidate[i].end);
      }
      updateSafety(now);updateDemand();control(now);
      result="WINDOWS_SAVED"; Serial.printf("WINDOWS SAVED: count=%d\n",count);
    }
  } else if(cmd.startsWith("HOURS:")) {
    // HOURS:HHMM,HHMM,HHMM,HHMM. Only change the permission windows;
    // never force pumps on and never clear emergency/PAUSE/FAULT.
    int hh[4]={0};
    String raw=cmd.substring(6);
    bool valid=(raw.length()==19 && raw[4]==',' && raw[9]==',' && raw[14]==',');
    int positions[4]={0,5,10,15};
    if(valid) {
      for(int i=0;i<4;i++) {
        int v=0;
        for(int j=0;j<4;j++) {
          char c=raw[positions[i]+j];
          if(c<'0'||c>'9') {valid=false;break;}
          v=v*10+c-'0';
        }
        int h=v/100,m=v%100;
        if(h>23||m>59)valid=false;
        hh[i]=h*60+m;
      }
    }
    if(!valid || hh[0]>=hh[1] || hh[2]>=hh[3] ||
        !(hh[1]<=hh[2] || hh[3]<=hh[0])) {
      accepted=false;result="INVALID_HOURS";
    } else {
      windowCount=2;
      irrigationWindows[0]={true,hh[0],hh[1]};
      irrigationWindows[1]={true,hh[2],hh[3]};
      irrigationPrefs.putUChar("winCount",2);
      for(int i=0;i<2;i++){String k="w"+String(i);irrigationPrefs.putBool((k+"e").c_str(),true);irrigationPrefs.putUShort((k+"s").c_str(),irrigationWindows[i].start);irrigationPrefs.putUShort((k+"t").c_str(),irrigationWindows[i].end);}
      morningStart=hh[0]; morningEnd=hh[1];
      afternoonStart=hh[2]; afternoonEnd=hh[3];
      irrigationPrefs.putUShort("amStart",morningStart);
      irrigationPrefs.putUShort("amEnd",morningEnd);
      irrigationPrefs.putUShort("pmStart",afternoonStart);
      irrigationPrefs.putUShort("pmEnd",afternoonEnd);
      // Re-evaluate the time rule immediately; all water-source and other
      // safety interlocks continue to be checked by control().
      updateSafety(now); updateDemand(); control(now);
      result="HOURS_SAVED";
      Serial.printf("HOURS SAVED: %02d:%02d-%02d:%02d / %02d:%02d-%02d:%02d\n",
        hh[0]/60,hh[0]%60,hh[1]/60,hh[1]%60,
        hh[2]/60,hh[2]%60,hh[3]/60,hh[3]%60);
    }
  } else if(cmd.startsWith("CLOCK:")) {
    String epoch=cmd.substring(6);
    bool valid=epoch.length()==10;
    for(unsigned int i=0;i<epoch.length();i++) if(epoch[i]<'0'||epoch[i]>'9')valid=false;
    unsigned long sec=valid?strtoul(epoch.c_str(),nullptr,10):0;
    if(!valid||sec<1700000000UL||sec>2200000000UL) {accepted=false;result="BAD_CLOCK";}
    else {clockEpoch=sec;clockAtMs=now;result="CLOCK_SYNCED";}
  } else if(cmd=="ZONE:1:HOLD" || cmd=="ZONE:1:RESUME" ||
            cmd=="ZONE:2:HOLD" || cmd=="ZONE:2:RESUME") {
    // Persistent farmer permission is available in every operating mode,
    // including PRESET and with MASTER OFF. Safety still gates pumping.
    {
      int zi=cmd[5]-'1';
      bool newHold=cmd.endsWith("HOLD");
      zoneHold[zi]=newHold;
      if(newHold) clearOneTime(zi);
      irrigationPrefs.putBool(zi==0?"hold1":"hold2",newHold);
      naturalDemand[zi]=false;
      updateDemand();
      if(newHold && watering(state) && activeZone==zi) {
        activeZone=-1;
        enter(REST,"ZONE_HOLD",now);
      }
      control(now);result=newHold?"ZONE_HELD":"ZONE_RESUMED";
    }
  } else if(cmd=="ZONE:1:CANCEL_ONCE" || cmd=="ZONE:2:CANCEL_ONCE") {
     const int zi=cmd[5]-'1';
     clearOneTime(zi);
     if(watering(state) && activeZone==zi && !irrigationWindow(now)) {
       activeZone=-1; enter(REST,"DEMO_PERMISSION_ENDED",now);
     }
     control(now); result="ONE_TIME_CANCELLED";
   } else if(cmd=="ZONE:1:ONCE" || cmd=="ZONE:2:ONCE") {
    const int zi=cmd[5]-'1';
    updateSafety(now);updateDemand();
    // A one-time exception ONLY to the preferred irrigation hours:
    // all physical, human, water-source and sensor interlocks stay in force.
    if(!masterEnabled) {accepted=false;result="MASTER_OFF";}
    else if(testMode) {accepted=false;result="ONLY_DYNAMIC_OR_TWIN";}
    else if(zi>=configuredZones) {accepted=false;result="ZONE_DISABLED";}
    else if(zoneHold[zi]) {accepted=false;result="ZONE_HELD";}
    else if(paused || injectedFault) {accepted=false;result="PAUSED_OR_FAULT";}
    else if(twinMode && (lastTwinInput==0 || now-lastTwinInput>TWIN_INPUT_TIMEOUT_MS))
      {accepted=false;result="TWIN_INPUT_STALE";}
    else if(!clockValid(now)) {accepted=false;result="CLOCK_UNKNOWN";}
    else if(irrigationWindow(now)) {accepted=false;result="ALREADY_IN_WINDOW";}
    else if(!demand[zi]) {accepted=false;result="SOIL_NOT_DRY";}
    else if(!canalOK() && !tankOK()) {accepted=false;result="NO_SOURCE";}
    else if(extraWaterGranted[zi]) {result="ALREADY_QUEUED";}
    else {
      bool otherPending=extraWaterGranted[1-zi];
      bool pumpBusy=watering(state) || state==REFILL_TANK;
      extraWaterGranted[zi]=true;
      extraWaterStarted[zi]=false;
      extraWaterQueuedAt[zi]=now;
      result=(otherPending || pumpBusy || state==REST)?"ONE_TIME_QUEUED":"ONE_TIME_ALLOWED";
      // Existing REST still applies, and this does not force the pump GPIO.
      control(now);
    }
  } else if(cmd=="TWIN:ON") {
    clearAllOneTime();
    if(testMode) { accepted=false; result="ONLY_DYNAMIC"; }
    else if(!twinMode) {
      twinMode=true;lastTwinInput=0;activeZone=-1;
      enter(HOLD_NO_WATER,"WAIT_TWIN_INPUT",now);
      Serial.println("SIMULATION ON: awaiting Python environment data");
    } else result="ALREADY_TWIN";
  } else if(cmd=="TWIN:OFF") {
    clearAllOneTime();
    if(twinMode) {
      twinMode=false;lastTwinInput=0;activeZone=-1;readKnobs();
      demoCase=0;demoAwaitInput=false;
      enter(REST,"TWIN_OFF",now);
      Serial.println("TWIN OFF: local DYNAMIC restored after REST");
    } else result="ALREADY_DYNAMIC";
  } else if(cmd=="FILL:REQUEST") {
    if(!masterEnabled){accepted=false;result="MASTER_OFF";}
    else if(testMode) {accepted=false;result="ONLY_DYNAMIC_OR_TWIN";}
    else if(refillFault) {accepted=false;result="FILL_TIMEOUT_RESET_REQUIRED";}
    else if(!canalOK()) {accepted=false;result="CANAL_UNSAFE";}
    else if(tankL>=REFILL_STOP_L) {accepted=false;result="TANK_AT_TARGET";}
    else {refillRequested=true;result="QUEUED_AFTER_IRRIGATION";control(now);}
  } else if(cmd=="FILL:CANCEL") {
    refillRequested=false;refillCycle=false;refillFault=false;refillAuto=false;
    if(state==REFILL_TANK) enter(IDLE,"FILL_CANCELLED",now);
    control(now);
  } else if(cmd=="FILL:AUTO:ON" || cmd=="FILL:AUTO:OFF") {
    if(testMode) {accepted=false;result="ONLY_DYNAMIC_OR_TWIN";}
    else {refillAuto=(cmd=="FILL:AUTO:ON");if(!refillAuto)refillCycle=false;control(now);}
  } else if(cmd=="STATUS") {
    // Passive telemetry request; does not change the controller.
  } else if(cmd=="ZONES:1" || cmd=="ZONES:2") {
    if(testMode) {accepted=false;result="ONLY_DYNAMIC";}
    else {
      const int count=(cmd=="ZONES:1"?1:2);
      configuredZones=count;
      updateDemand();
      if(activeZone>=configuredZones) {activeZone=-1;enter(REST,"ZONE_DISABLED",now);}
      control(now);
    }
  } else {accepted=false;result="UNSUPPORTED_COMMAND";}
  Serial.printf("MQTT CMD %s accepted=%s result=%s\n",cmd.c_str(),accepted?"YES":"NO",result);
  publishAck(cmd.c_str(),accepted,result,now);
  publishTelemetry(now);
}
void setupNetwork() {
  topicTelemetry=String(MQTT_ROOT)+"/telemetry";
  topicStatus=String(MQTT_ROOT)+"/status";
  topicCommand=String(MQTT_ROOT)+"/cmd";
  topicAck=String(MQTT_ROOT)+"/ack";
  topicTwin=String(MQTT_ROOT)+"/twin/input";
  mqtt.setServer(MQTT_HOST,MQTT_PORT);
  mqtt.setCallback(onMqttCommand);
  mqtt.setBufferSize(4096); // Phase 4.3.3: expanded telemetry; keep MQTT packet below 4096 bytes
  mqtt.setSocketTimeout(3); // allow public gateway latency, avoid excessive blocking
  mqtt.setKeepAlive(30);
  mqttTransport.setTimeout(1000);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID,"",6);
  lastWifiTry=millis();
  Serial.printf("WIFI START ssid=%s (outbound only)\n",WIFI_SSID);
  printNetworkStatus();
}
void tickNetwork(unsigned long now) {
  if(WiFi.status()!=WL_CONNECTED) {
    mqttWasOnline=false;
    if(now-lastWifiTry>=WIFI_RETRY_MS) {
      lastWifiTry=now;
      // retry is quiet; N command prints detailed connectivity
      WiFi.reconnect();
    }
    return;
  }
  if(mqtt.connected()) {
    if(!mqtt.loop()) {
      Serial.printf("MQTT LOOP FAILED rc=%d (%s) ms=%lu\n",
        mqtt.state(),mqttStateLabel(mqtt.state()),(unsigned long)now);
      return;
    }
    if(now-lastTelemetry>=MQTT_PUBLISH_MS) publishTelemetry(now);
    return;
  }
  if(mqttWasOnline) {
    const int rc=mqtt.state();
    Serial.printf("MQTT DISCONNECTED rc=%d (%s) ms=%lu (local controller continues)\n",
      rc,mqttStateLabel(rc),(unsigned long)now);
    mqttWasOnline=false;
  }
  if(now-lastMqttTry<MQTT_RETRY_MS) return;
  lastMqttTry=now;
  char clientId[90];
  snprintf(clientId,sizeof(clientId),"saltguard-%08lx-%04x",(unsigned long)millis(),(unsigned int)random(0xffff));
  if(mqtt.connect(clientId,topicStatus.c_str(),0,true,"offline")) {
    mqttWasOnline=true;
    Serial.printf("MQTT CONNECTED broker=%s:%u\n",MQTT_HOST,MQTT_PORT);
    mqtt.publish(topicStatus.c_str(),"online",true);
    bool subscribed=mqtt.subscribe(topicCommand.c_str());
    bool twinSubscribed=mqtt.subscribe(topicTwin.c_str());
    Serial.printf("MQTT SUBSCRIBE %s result=%s\n",topicTwin.c_str(),twinSubscribed?"OK":"FAIL");
    Serial.printf("MQTT SUBSCRIBE %s result=%s\n",topicCommand.c_str(),subscribed?"OK":"FAIL");
    publishTelemetry(now);
  } else {
    const int rc=mqtt.state();
    Serial.printf("MQTT RETRY rc=%d (%s) ms=%lu; irrigation controller remains local\n",
      rc,mqttStateLabel(rc),(unsigned long)now);
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(SR_DATA_PIN,OUTPUT);pinMode(SR_CLOCK_PIN,OUTPUT);pinMode(SR_LATCH_PIN,OUTPUT);
  pinMode(TANK_TRIG_PIN,OUTPUT);pinMode(TANK_ECHO_PIN,INPUT);
  digitalWrite(TANK_TRIG_PIN,LOW);
  for(int pin : {LED_WATER_PIN,LED_ALARM_PIN}) {pinMode(pin,OUTPUT);digitalWrite(pin,LOW);}
  pinMode(RELAY_PIN,OUTPUT);pinMode(FILL_RELAY_PIN,OUTPUT);
  pinMode(MASTER_SWITCH_PIN,INPUT); // SPDT is wired to GND or 3V3, no floating state
  pinMode(PAUSE_PIN,INPUT_PULLUP);pinMode(MANUAL_PIN,INPUT_PULLUP); // GPIO15 + existing 10k external pull-up; RX0 is UART only
  pinMode(REFILL_PIN,INPUT_PULLUP);pinMode(BUZZER_PIN,OUTPUT);
  digitalWrite(RELAY_PIN,RELAY_OFF);digitalWrite(FILL_RELAY_PIN,RELAY_OFF);
  writeValves(0);
  outputsOff();Wire.begin(SDA_PIN,SCL_PIN);
  lcd.init();lcd.clear();lcd.noDisplay();lcd.noBacklight(); // MASTER defaults OFF: LCD dark
  analogReadResolution(12);
  airSensor.setup(DHT_PIN,DHTesp::DHT22);
  Serial.printf("DHT22 INIT pin=%d\n",DHT_PIN);
  waterSensor.begin();waterSensor.setResolution(10);
  waterSensor.setWaitForConversion(false);
  Serial.printf("DS18B20 INIT pin=%d devices=%d\n",WATER_TEMP_PIN,waterSensor.getDeviceCount());
  waterSensor.requestTemperatures();
  waterStarted=lastWaterRequest=millis();waterPending=true;
  irrigationPrefs.begin("saltguard",false);
  zoneHold[0]=irrigationPrefs.getBool("hold1",false);
  zoneHold[1]=irrigationPrefs.getBool("hold2",false);
  emergencyLatched=irrigationPrefs.getBool("emergency",false);
  for(int zi=0;zi<2;zi++) {
    unsigned int f=irrigationPrefs.getUShort(zi==0?"flow1":"flow2",120);
    unsigned int v=irrigationPrefs.getUShort(zi==0?"vol1":"vol2",20);
    flowLpm[zi]=(f>=10&&f<=1000?f:120)/10.0f;
    sessionTargetL[zi]=(v>=10&&v<=5000?v:20)/10.0f;
  }
  soilStartPct[0]=irrigationPrefs.getUChar("soilS1",35);
  soilStopPct[0]=irrigationPrefs.getUChar("soilT1",60);
  soilStartPct[1]=irrigationPrefs.getUChar("soilS2",35);
  soilStopPct[1]=irrigationPrefs.getUChar("soilT2",60);
  for(int zi=0;zi<2;zi++) {
    if(soilStartPct[zi]<5 || soilStartPct[zi]>80 ||
       soilStopPct[zi]<soilStartPct[zi]+5 || soilStopPct[zi]>95) {
      soilStartPct[zi]=35;soilStopPct[zi]=60;
    }
  }
  morningStart=irrigationPrefs.getUShort("amStart",5*60+30);
  morningEnd=irrigationPrefs.getUShort("amEnd",9*60);
  afternoonStart=irrigationPrefs.getUShort("pmStart",16*60+30);
  afternoonEnd=irrigationPrefs.getUShort("pmEnd",18*60+30);
  if(morningStart>=morningEnd || afternoonStart>=afternoonEnd ||
     !(morningEnd<=afternoonStart || afternoonEnd<=morningStart)) {
    morningStart=330;morningEnd=540;afternoonStart=990;afternoonEnd=1110;
  }
  windowCount=irrigationPrefs.getUChar("winCount",2);
  if(windowCount<1||windowCount>MAX_WINDOWS)windowCount=2;
  for(int i=0;i<windowCount;i++) {
    String k="w"+String(i);
    irrigationWindows[i].enabled=irrigationPrefs.getBool((k+"e").c_str(),true);
    irrigationWindows[i].start=irrigationPrefs.getUShort((k+"s").c_str(),i==0?330:990);
    irrigationWindows[i].end=irrigationPrefs.getUShort((k+"t").c_str(),i==0?540:1110);
    if(irrigationWindows[i].start>=irrigationWindows[i].end||irrigationWindows[i].end>1439){
      windowCount=2;irrigationWindows[0]={true,330,540};irrigationWindows[1]={true,990,1110};break;
    }
  }
  masterEnabled=false;masterArmed=false;masterLastRaw=digitalRead(MASTER_SWITCH_PIN);
  masterRawChangedAt=millis();
  readKnobs();resetController(millis());
  updateSafety(millis());updateDemand();control(millis());updatePanelLeds();
  setupNetwork();
  Serial.println("SALTGUARD READY | S=status I=inputs ?=help");
}
void loop() {
  unsigned long now=millis();
  updateMaster(now); // physical OFF has priority over MQTT, UI, and moisture
  handleButtons(now);handleSerial(now);
  tickEnvironment(now);
  if(now-lastRead>=READ_MS) {lastRead=now;readKnobs();}
  sampleTankLevel(now);
  control(now);updatePanelLeds();
  if(now-lastWorld>=WORLD_MS) {
    lastWorld+=WORLD_MS;tickWorld(now);control(now);
  }
  if(now-lastPage>=PAGE_MS) {lastPage=now;page=(page+1)%2;}
  if(now-lastLCD>=LCD_MS) {lastLCD=now;updateLCD();}
  if(csvStream&&now-lastCSV>=CSV_MS) {lastCSV=now;printCSV(now);}
  alarm(now);
  tickNetwork(now);
}
