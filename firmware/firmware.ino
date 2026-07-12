#include <BluetoothSerial.h>
BluetoothSerial ESP_BT;

// Left front
const int PIN_MOTOR_L1 = 18;
const int PIN_MOTOR_L2 = 19;
// Left back
const int PIN_MOTOR_L3 = 32;
const int PIN_MOTOR_L4 = 33;

// Right back
const int PIN_MOTOR_R1 = 14;
const int PIN_MOTOR_R2 = 27;
// Right front
const int PIN_MOTOR_R3 = 26;
const int PIN_MOTOR_R4 = 25;

const int N_MOTOR_PIN = 8;
const int MOTOR_PINS[N_MOTOR_PIN] = {PIN_MOTOR_L1, PIN_MOTOR_L2, PIN_MOTOR_L3,
                                     PIN_MOTOR_L4, PIN_MOTOR_R1, PIN_MOTOR_R2,
                                     PIN_MOTOR_R3, PIN_MOTOR_R4};

enum class MotorDirection { FORWARD, BACKWARD, STOP };
enum class Side { LEFT, RIGHT };

void setMotor(int in1, int in2, MotorDirection dir) {
  switch (dir) {
  case MotorDirection::FORWARD:
    digitalWrite(in1, HIGH);
    digitalWrite(in2, LOW);
    break;
  case MotorDirection::BACKWARD:
    digitalWrite(in1, LOW);
    digitalWrite(in2, HIGH);
    break;
  case MotorDirection::STOP:
    digitalWrite(in1, LOW);
    digitalWrite(in2, LOW);
    break;
  }
}

void driveMotor_LF(MotorDirection dir) {
  setMotor(PIN_MOTOR_L1, PIN_MOTOR_L2, dir);
}

void driveMotor_RF(MotorDirection dir) {
  setMotor(PIN_MOTOR_R3, PIN_MOTOR_R4, dir);
}

void driveMotor_LB(MotorDirection dir) {
  setMotor(PIN_MOTOR_L3, PIN_MOTOR_L4, dir);
}

void driveMotor_RB(MotorDirection dir) {
  setMotor(PIN_MOTOR_R1, PIN_MOTOR_R2, dir);
}

void driveWheels(MotorDirection lfDir, MotorDirection lbDir,
                 MotorDirection rfDir, MotorDirection rbDir) {
  driveMotor_LF(lfDir);
  driveMotor_LB(lbDir);

  driveMotor_RF(rfDir);
  driveMotor_RB(rbDir);
}

void driveSides(MotorDirection leftDir, MotorDirection rightDir) {
  driveWheels(leftDir, leftDir, rightDir, rightDir);
}

void driveForward() {
  driveWheels(MotorDirection::FORWARD, MotorDirection::FORWARD,
              MotorDirection::FORWARD, MotorDirection::FORWARD);
}

void driveBackward() {
  driveWheels(MotorDirection::BACKWARD, MotorDirection::BACKWARD,
              MotorDirection::BACKWARD, MotorDirection::BACKWARD);
}

void spin(Side side) {
  if (side == Side::LEFT) {
    driveSides(MotorDirection::BACKWARD, MotorDirection::FORWARD);
  } else {
    driveSides(MotorDirection::FORWARD, MotorDirection::BACKWARD);
  }
}

void arcForward(Side side) {
  if (side == Side::LEFT) {
    driveWheels(MotorDirection::FORWARD, MotorDirection::BACKWARD,
                MotorDirection::FORWARD, MotorDirection::FORWARD);
  } else {
    driveWheels(MotorDirection::FORWARD, MotorDirection::FORWARD,
                MotorDirection::FORWARD, MotorDirection::BACKWARD);
  }
}

void stopCar() { driveSides(MotorDirection::STOP, MotorDirection::STOP); }

void setup() {
  Serial.begin(115200);
  ESP_BT.begin("roboS");

  for (int i = 0; i < N_MOTOR_PIN; ++i) {
    pinMode(MOTOR_PINS[i], OUTPUT);
    digitalWrite(MOTOR_PINS[i], LOW);
  }

  stopCar();

  Serial.println("ESP32 car ready. Bluetooth name: roboS");
}

void loop() {
  if (ESP_BT.available()) {
    char cmd = ESP_BT.read();
    Serial.println(cmd);

    switch (cmd) {
    case 'F':
      driveForward();
      break;
    case 'B':
      driveBackward();
      break;
    case 'A':
      spin(Side::LEFT);
      break;
    case 'D':
      spin(Side::RIGHT);
      break;
    case 'L':
      arcForward(Side::LEFT);
      break;
    case 'R':
      arcForward(Side::RIGHT);
      break;
    case 'S':
      stopCar();
      break;
    }
  }
}
