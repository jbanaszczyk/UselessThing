from machine import Pin, I2C
import time
import struct

# ---- Pins & I2C ----
I2C_ID = 0                 # I2C0 on RP2040
I2C_SDA = 20               # GP20
I2C_SCL = 21               # GP21
SW_ADDR = 0x42
PIN_RST = 17               # GP17
PIN_XFER = 27              # GP27 (a.k.a. TSXFR / XFER)

# ---- Identifiers & masks (per MGC3130 / Pimoroni) ----
SW_SYSTEM_STATUS = 0x15
SW_REQUEST_MSG   = 0x06
SW_FW_VERSION    = 0x83
SW_SET_RUNTIME   = 0xA2
SW_SENSOR_DATA   = 0x91

# Data Output config bits
SW_DATA_DSP      = 1 << 0
SW_DATA_GESTURE  = 1 << 1
SW_DATA_TOUCH    = 1 << 2
SW_DATA_AIRWHEEL = 1 << 3
SW_DATA_XYZ      = 1 << 4

# SystemInfo flags
SYS_POSITION_VALID  = 1 << 0
SYS_AIRWHEEL_VALID  = 1 << 1

# Touch action bit order (from Pimoroni/Arduino mapping)
TOUCH_ACTIONS = [
    ('doubletap', 'center'),
    ('doubletap', 'east'),
    ('doubletap', 'north'),
    ('doubletap', 'west'),
    ('doubletap', 'south'),
    ('tap',       'center'),
    ('tap',       'east'),
    ('tap',       'north'),
    ('tap',       'west'),
    ('tap',       'south'),
    ('touch',     'center'),
    ('touch',     'east'),
    ('touch',     'north'),
    ('touch',     'west'),
    ('touch',     'south'),
]

# Gesture IDs (byte d_gesture[0])
GESTURES = {
    1: ('garbage', '', ''),
    2: ('flick', 'west',  'east'),
    3: ('flick', 'east',  'west'),
    4: ('flick', 'south', 'north'),
    5: ('flick', 'north', 'south'),
    6: ('circle', 'clockwise', ''),
    7: ('circle', 'counter-clockwise', '')
}

# ---- Helpers ----
def u16(lsb, msb):
    return (msb << 8) | lsb

def normalize_0_1(val_u16):
    # Convert 0..65535 to 0.0..1.0
    return round(val_u16 / 65536.0, 4)

# ---- Bus & pins ----
i2c = I2C(I2C_ID, scl=Pin(I2C_SCL), sda=Pin(I2C_SDA), freq=400000)
pin_rst = Pin(PIN_RST, Pin.OUT, value=1)
# Important: XFER defaults to input with pull-up; we will temporarily drive it LOW when reading
pin_xfer = Pin(PIN_XFER, Pin.IN, Pin.PULL_UP)

# ---- Low-level write: MGC3130 expects writes at "register" 0x10 like Pimoroni does ----
def write_block(reg, data_bytes):
    # In Linux smbus they use write_i2c_block_data(addr, 0x10, [...])
    # In MicroPython use writeto_mem
    i2c.writeto_mem(SW_ADDR, reg, bytes(data_bytes))

# ---- Device control ----
def hw_reset():
    pin_rst.value(0)
    time.sleep_ms(100)
    pin_rst.value(1)
    # Datasheet ~200ms; give it a bit more
    time.sleep_ms(500)

def get_status_expect(cmd_id, tries=10):
    # After issuing SET_RUNTIME, the device posts a status frame (0x15 with matching id)
    for _ in range(tries):
        time.sleep_ms(1)
        if pin_xfer.value() == 0:
            data = read_frame_raw()
            if data and data[3] == SW_SYSTEM_STATUS and data[4] == cmd_id:
                return True
    return False

def configure_runtime():
    # 1) Enable AirWheel (arg0=0x20, arg1=0x20)
    write_block(0x10, [
        0x00, 0x00, SW_SET_RUNTIME, 0x90, 0x00,  0x00, 0x00,
        0x20, 0x00, 0x00, 0x00,
        0x20, 0x00, 0x00, 0x00
    ])
    if not get_status_expect(SW_SET_RUNTIME):
        raise RuntimeError("SET_RUNTIME (AirWheel) no status")

    # 2) Enable all gestures (garbage/flicks/circles)
    write_block(0x10, [
        0x00, 0x00, SW_SET_RUNTIME, 0x85, 0x00,  0x00, 0x00,
        0b01111111, 0x00, 0x00, 0x00,            # mask A
        0b01111111, 0x00, 0x00, 0x00             # mask B
    ])
    if not get_status_expect(SW_SET_RUNTIME):
        raise RuntimeError("SET_RUNTIME (gestures) no status")

    # 3) Enable data outputs: DSP, Gesture, Touch, AirWheel, XYZ
    enable_mask = (SW_DATA_DSP | SW_DATA_GESTURE | SW_DATA_TOUCH |
                   SW_DATA_AIRWHEEL | SW_DATA_XYZ)
    write_block(0x10, [
        0x00, 0x00, SW_SET_RUNTIME, 0xA0, 0x00,  0x00, 0x00,
        enable_mask, 0x00, 0x00, 0x00,
        enable_mask, 0x00, 0x00, 0x00
    ])
    if not get_status_expect(SW_SET_RUNTIME):
        raise RuntimeError("SET_RUNTIME (data outputs) no status")

    # 4) (Opcjonalnie) Disable auto-calibration (improves stability while testing)
    write_block(0x10, [
        0x00, 0x00, SW_SET_RUNTIME, 0x80, 0x00,  0x00, 0x00,
        0x00, 0x00, 0x00, 0x00,                  # disable
        enable_mask, 0x00, 0x00, 0x00
    ])
    if not get_status_expect(SW_SET_RUNTIME):
        raise RuntimeError("SET_RUNTIME (autocal off) no status")

# ---- Reading frames ----
def read_frame_raw():
    """
    Protocol (as used by Pimoroni):
      Host waits until XFER==LOW (device has data)
      Host drives XFER LOW (OUTPUT) to freeze buffer
      Read N bytes from 0x00 (they use 26..32; 32 is safe)
      Release XFER (HIGH) and set back to input with pull-up
    Returns a bytearray of up to 32 bytes (header + payload) or None.
    """
    if pin_xfer.value() != 0:
        return None

    # Drive XFER low while reading
    pin_xfer.init(Pin.OUT, value=0)

    # Read up to 32 bytes from register 0x00
    # On MicroPython there's no readfrom_mem_into with 0 length header here; use readfrom_mem
    try:
        buf = bytearray(32)
        # read header first to know size? Spec header[0]=size. But 32 is fine; device will send what's available.
        rx = i2c.readfrom_mem(SW_ADDR, 0x00, 32)
        # Release XFER: HIGH then back to input with pull-up
    finally:
        pin_xfer.value(1)
        pin_xfer.init(Pin.IN, Pin.PULL_UP)

    return bytearray(rx)

def handle_sensor_data(payload):
    # payload layout (after 4-byte header):
    # 0-1: configmask (LSB first)
    # 2: timestamp (ignored)
    # 3: sysinfo
    # 4-5: dspstatus (ignored)
    # 6-9: gesture[4]
    # 10-13: touch[4]
    # 14-15: airwheel[2]
    # 16-21: xyz (x_l,x_h,y_l,y_h,z_l,z_h)
    configmask = payload[0] | (payload[1] << 8)
    sysinfo = payload[3]

    # XYZ
    if (configmask & SW_DATA_XYZ) and (sysinfo & SYS_POSITION_VALID):
        x_u = u16(payload[16], payload[17])
        y_u = u16(payload[18], payload[19])
        z_u = u16(payload[20], payload[21])
        x = normalize_0_1(x_u)
        y = normalize_0_1(y_u)
        z = normalize_0_1(z_u)
        print(f"XYZ: x={x:.4f} y={y:.4f} z={z:.4f}")

    # Gesture
    if (configmask & SW_DATA_GESTURE) and payload[6] != 0:
        gid = payload[6]
        g = GESTURES.get(gid)
        if g:
            kind, a, b = g
            if kind == 'flick':
                print(f"GESTURE: flick {a}->{b}")
            elif kind == 'circle':
                print(f"GESTURE: circle {a}")
            else:
                print(f"GESTURE: {kind}")
        else:
            print(f"GESTURE: id={gid}")

    # Touch
    if (configmask & SW_DATA_TOUCH):
        action = (payload[11] << 8) | payload[10]  # d_touch[1]<<8 | d_touch[0]
        comp = 1 << 14  # start from MSB of 15..0 (like Arduino example)
        for idx in range(16):
            if action & comp:
                # Map to human-readable
                if idx < len(TOUCH_ACTIONS):
                    kind, pos = TOUCH_ACTIONS[idx]
                    print(f"TOUCH: {kind} {pos}")
                else:
                    print(f"TOUCH: bit={idx}")
                break
            comp >>= 1

    # AirWheel
    if (configmask & SW_DATA_AIRWHEEL) and (sysinfo & SYS_AIRWHEEL_VALID):
        # airwheel[0] is rotation accumulator; compare with previous if keeping state.
        # For minimal demo just print raw byte:
        rot_byte = payload[14]
        # 32 steps per full turn; direction indicated by delta vs last.
        print(f"AIRWHEEL raw={rot_byte}")

def process_frame(frame):
    if not frame or len(frame) < 4:
        return
    d_size  = frame[0]
    d_flags = frame[1]
    d_seq   = frame[2]
    d_ident = frame[3]

    payload = frame[4:]
    if d_ident == SW_SENSOR_DATA:
        handle_sensor_data(payload)
    elif d_ident == SW_SYSTEM_STATUS:
        # Byte 4 should echo command id from last SET_RUNTIME
        # print("STATUS frame:", payload[:8])
        pass
    elif d_ident == SW_FW_VERSION:
        # Firmware string from payload[8:]
        fw = bytes(payload[8:]).decode(errors='ignore').strip('\x00\r\n ')
        print("FW:", fw)
    else:
        # Unknown/unused
        pass

def main():
    print("Skywriter (MGC3130) – MicroPython minimal poller")
    print("I2C0 on GP20/GP21, RST=GP17, TSXFR=GP27, addr=0x42")
    hw_reset()
    configure_runtime()
    print("Configured. Polling... (Ctrl+C to stop)")
    # Optional: ask for FW version – device may publish it spontaneously; minimal demo just polls.
    last_print = time.ticks_ms()

    # while True:
    #     if pin_xfer.value() == 0:
    #         frame = read_frame_raw()
    #         process_frame(frame)
    #     else:
    #         # Tiny idle
    #         time.sleep_ms(1)

# ---- Run ----
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        # Restore XFER as input just in case
        pin_xfer.init(Pin.IN, Pin.PULL_UP)
        print("\nStopped.")
