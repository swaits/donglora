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

/// LoRa forward error correction coding rate.
#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, defmt::Format)]
#[repr(u8)]
pub enum CodingRate {
    Cr4_5 = 1,
    Cr4_6 = 2,
    Cr4_7 = 3,
    Cr4_8 = 4,
}

/// Complete LoRa radio configuration.
#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, defmt::Format)]
pub struct RadioConfig {
    pub freq_hz: u32,
    pub bw: Bandwidth,
    pub sf: u8,
    pub cr: CodingRate,
    pub sync_word: u16,
    pub tx_power_dbm: i8,
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
#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, defmt::Format)]
#[repr(u8)]
pub enum ErrorCode {
    InvalidConfig = 1,
    RadioBusy = 2,
    TxTimeout = 3,
    CrcError = 4,
    NotConfigured = 5,
    NoDisplay = 6,
}
