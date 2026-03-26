use embassy_sync::blocking_mutex::raw::CriticalSectionRawMutex;
use embassy_sync::channel::Channel;
use embassy_sync::watch::Watch;

use crate::protocol::{Command, RadioConfig, Response};

/// Host-to-radio command channel.
pub type CommandChannel = Channel<CriticalSectionRawMutex, Command, 16>;

/// Radio-to-host response channel.
pub type ResponseChannel = Channel<CriticalSectionRawMutex, Response, 32>;

/// Observable radio status for the display task.
pub type StatusWatch = Watch<CriticalSectionRawMutex, RadioStatus, 2>;

/// Current radio state exposed to observers (e.g. display).
#[derive(Debug, Clone, defmt::Format)]
pub struct RadioStatus {
    pub state: RadioState,
    pub config: Option<RadioConfig>,
    pub rx_count: u32,
    pub tx_count: u32,
    pub last_rssi: Option<i16>,
    pub last_snr: Option<i8>,
}

/// Radio state machine states.
#[derive(Debug, Clone, Copy, PartialEq, Eq, defmt::Format)]
pub enum RadioState {
    Idle,
    Receiving,
    Transmitting,
}

impl Default for RadioStatus {
    fn default() -> Self {
        Self {
            state: RadioState::Idle,
            config: None,
            rx_count: 0,
            tx_count: 0,
            last_rssi: None,
            last_snr: None,
        }
    }
}
