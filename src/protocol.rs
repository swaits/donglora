use heapless::Vec;
use serde::{Deserialize, Serialize};

/// Maximum LoRa payload size in bytes.
pub const MAX_PAYLOAD: usize = 256;

/// LoRa signal bandwidth.
#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, defmt::Format)]
#[repr(u8)]
pub enum Bandwidth {
    Khz7 = 0,
    Khz10 = 1,
    Khz15 = 2,
    Khz20 = 3,
    Khz31 = 4,
    Khz41 = 5,
    Khz62 = 6,
    Khz125 = 7,
    Khz250 = 8,
    Khz500 = 9,
}

/// Complete LoRa radio configuration.
#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, defmt::Format)]
pub struct RadioConfig {
    /// Frequency in Hz (150_000_000 - 960_000_000 for SX1262).
    pub freq_hz: u32,
    pub bw: Bandwidth,
    /// Spreading factor (5-12).
    pub sf: u8,
    /// Coding rate denominator (5-8). E.g. 5 = CR 4/5, 8 = CR 4/8.
    pub cr: u8,
    pub sync_word: u16,
    /// Transmit power in dBm (-9 to +22 for SX1262).
    pub tx_power_dbm: i8,
}

impl RadioConfig {
    /// Validate all fields are within SX1262 hardware limits.
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(150_000_000..=960_000_000).contains(&self.freq_hz) {
            return Err("frequency out of range (150-960 MHz)");
        }
        if !(5..=12).contains(&self.sf) {
            return Err("spreading factor out of range (5-12)");
        }
        if !(5..=8).contains(&self.cr) {
            return Err("coding rate out of range (5-8)");
        }
        if !(-9..=22).contains(&self.tx_power_dbm) {
            return Err("TX power out of range (-9 to +22 dBm)");
        }
        Ok(())
    }
}

/// Host → firmware commands.
// Payload variant is intentionally large (inline heapless::Vec) — no allocator available.
#[allow(clippy::large_enum_variant)]
#[derive(Serialize, Deserialize, Debug, PartialEq)]
pub enum Command {
    Ping,
    GetConfig,
    SetConfig(RadioConfig),
    StartRx,
    StopRx,
    Transmit {
        config: Option<RadioConfig>,
        payload: Vec<u8, MAX_PAYLOAD>,
    },
    DisplayOn,
    DisplayOff,
}

/// Firmware → host responses.
// Payload variant is intentionally large (inline heapless::Vec) — no allocator available.
#[allow(clippy::large_enum_variant)]
#[derive(Serialize, Deserialize, Debug, PartialEq)]
pub enum Response {
    Pong,
    Config(RadioConfig),
    RxPacket {
        rssi: i16,
        snr: i16,
        payload: Vec<u8, MAX_PAYLOAD>,
    },
    TxDone,
    Ok,
    Error(ErrorCode),
}

/// Error codes reported to the host.
///
/// Variant indices match postcard wire encoding (0-based).
#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, defmt::Format)]
#[repr(u8)]
pub enum ErrorCode {
    InvalidConfig = 0,
    RadioBusy = 1,
    TxTimeout = 2,
    CrcError = 3,
    NotConfigured = 4,
    NoDisplay = 5,
}
