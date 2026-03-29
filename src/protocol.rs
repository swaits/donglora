//! Wire protocol types and fixed-size little-endian serialization.
//!
//! Every integer is fixed-width LE. No varints, no zigzag.
//! See `docs/PROTOCOL.md` for the complete specification.

use heapless::Vec;

/// Maximum LoRa payload size in bytes.
pub const MAX_PAYLOAD: usize = 256;

/// RadioConfig wire size (fixed).
pub const RADIO_CONFIG_SIZE: usize = 10;

/// Sentinel value for `tx_power_dbm`: use the board's maximum TX power.
pub const TX_POWER_MAX: i8 = i8::MIN; // -128 on the wire

/// LoRa signal bandwidth.
#[derive(Debug, Clone, Copy, PartialEq, Eq, defmt::Format)]
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

impl Bandwidth {
    fn from_u8(v: u8) -> Option<Self> {
        match v {
            0 => Some(Self::Khz7),
            1 => Some(Self::Khz10),
            2 => Some(Self::Khz15),
            3 => Some(Self::Khz20),
            4 => Some(Self::Khz31),
            5 => Some(Self::Khz41),
            6 => Some(Self::Khz62),
            7 => Some(Self::Khz125),
            8 => Some(Self::Khz250),
            9 => Some(Self::Khz500),
            _ => None,
        }
    }
}

/// Complete LoRa radio configuration.
///
/// Wire layout (10 bytes, all little-endian):
/// ```text
/// [freq_hz:4] [bw:1] [sf:1] [cr:1] [sync_word:2] [tx_power_dbm:1]
/// ```
#[derive(Debug, Clone, Copy, PartialEq, Eq, defmt::Format)]
pub struct RadioConfig {
    /// Frequency in Hz (150_000_000 - 960_000_000 for SX1262).
    pub freq_hz: u32,
    pub bw: Bandwidth,
    /// Spreading factor (5-12).
    pub sf: u8,
    /// Coding rate denominator (5-8). E.g. 5 = CR 4/5, 8 = CR 4/8.
    pub cr: u8,
    pub sync_word: u16,
    /// Transmit power in dBm. Set to [`TX_POWER_MAX`] (-128) for the
    /// board's maximum.
    pub tx_power_dbm: i8,
}

impl RadioConfig {
    /// Validate fields against hardware limits.
    pub fn validate(&self, power_range: (i8, i8)) -> Result<(), &'static str> {
        if !(150_000_000..=960_000_000).contains(&self.freq_hz) {
            return Err("frequency out of range (150-960 MHz)");
        }
        if !(5..=12).contains(&self.sf) {
            return Err("spreading factor out of range (5-12)");
        }
        if !(5..=8).contains(&self.cr) {
            return Err("coding rate out of range (5-8)");
        }
        if self.tx_power_dbm != TX_POWER_MAX
            && !(power_range.0..=power_range.1).contains(&self.tx_power_dbm)
        {
            return Err("TX power out of range for this board");
        }
        Ok(())
    }

    /// Resolve the TX_POWER_MAX sentinel to the board's actual maximum.
    pub fn resolve_power(mut self, power_range: (i8, i8)) -> Self {
        if self.tx_power_dbm == TX_POWER_MAX {
            self.tx_power_dbm = power_range.1;
        }
        self
    }

    /// Serialize to fixed-size LE bytes. Returns number of bytes written (always 10).
    pub fn write_to(self, buf: &mut [u8]) -> usize {
        buf[0..4].copy_from_slice(&self.freq_hz.to_le_bytes());
        buf[4] = self.bw as u8;
        buf[5] = self.sf;
        buf[6] = self.cr;
        buf[7..9].copy_from_slice(&self.sync_word.to_le_bytes());
        buf[9] = self.tx_power_dbm as u8;
        RADIO_CONFIG_SIZE
    }

    /// Deserialize from fixed-size LE bytes.
    pub fn from_bytes(buf: &[u8]) -> Option<Self> {
        if buf.len() < RADIO_CONFIG_SIZE {
            return None;
        }
        Some(Self {
            freq_hz: u32::from_le_bytes(buf[0..4].try_into().ok()?),
            bw: Bandwidth::from_u8(buf[4])?,
            sf: buf[5],
            cr: buf[6],
            sync_word: u16::from_le_bytes(buf[7..9].try_into().ok()?),
            tx_power_dbm: buf[9] as i8,
        })
    }
}

/// Host → firmware commands.
#[allow(clippy::large_enum_variant)]
#[derive(Debug, PartialEq)]
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

impl Command {
    /// Deserialize from a COBS-decoded frame.
    pub fn from_bytes(buf: &[u8]) -> Option<Self> {
        let tag = *buf.first()?;
        let rest = &buf[1..];
        match tag {
            0 => Some(Self::Ping),
            1 => Some(Self::GetConfig),
            2 => Some(Self::SetConfig(RadioConfig::from_bytes(rest)?)),
            3 => Some(Self::StartRx),
            4 => Some(Self::StopRx),
            5 => {
                // Transmit: has_config:u8 + [RadioConfig if 1] + len:u16 LE + payload
                if rest.is_empty() {
                    return None;
                }
                let (config, pos) = if rest[0] == 0 {
                    (None, 1)
                } else if rest[0] == 1 && rest.len() > RADIO_CONFIG_SIZE {
                    (Some(RadioConfig::from_bytes(&rest[1..])?), 1 + RADIO_CONFIG_SIZE)
                } else {
                    return None;
                };
                if rest.len() < pos + 2 {
                    return None;
                }
                let len = u16::from_le_bytes(rest[pos..pos + 2].try_into().ok()?) as usize;
                let data_start = pos + 2;
                if rest.len() < data_start + len {
                    return None;
                }
                let mut payload = Vec::new();
                let _ = payload.extend_from_slice(&rest[data_start..data_start + len]);
                Some(Self::Transmit { config, payload })
            }
            6 => Some(Self::DisplayOn),
            7 => Some(Self::DisplayOff),
            _ => None,
        }
    }
}

/// Firmware → host responses.
#[allow(clippy::large_enum_variant)]
#[derive(Debug, PartialEq)]
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

impl Response {
    /// Serialize to fixed-size LE bytes. Returns number of bytes written.
    pub fn write_to(self, buf: &mut [u8]) -> usize {
        match self {
            Self::Pong => {
                buf[0] = 0;
                1
            }
            Self::Config(cfg) => {
                buf[0] = 1;
                1 + cfg.write_to(&mut buf[1..])
            }
            Self::RxPacket { rssi, snr, payload } => {
                buf[0] = 2;
                buf[1..3].copy_from_slice(&rssi.to_le_bytes());
                buf[3..5].copy_from_slice(&snr.to_le_bytes());
                buf[5..7].copy_from_slice(&(payload.len() as u16).to_le_bytes());
                buf[7..7 + payload.len()].copy_from_slice(&payload);
                7 + payload.len()
            }
            Self::TxDone => {
                buf[0] = 3;
                1
            }
            Self::Ok => {
                buf[0] = 4;
                1
            }
            Self::Error(code) => {
                buf[0] = 5;
                buf[1] = code as u8;
                2
            }
        }
    }
}

/// Error codes reported to the host.
#[derive(Debug, Clone, Copy, PartialEq, Eq, defmt::Format)]
#[repr(u8)]
#[allow(dead_code)]
pub enum ErrorCode {
    InvalidConfig = 0,
    RadioBusy = 1,
    TxTimeout = 2,
    CrcError = 3,
    NotConfigured = 4,
    NoDisplay = 5,
}
