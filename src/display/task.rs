use embassy_executor::task;
use embassy_futures::select::{select, Either};
use embassy_time::Timer;
use ssd1306::mode::DisplayConfig;
use ssd1306::prelude::DisplayRotation;
use ssd1306::size::DisplaySize128x64;
use ssd1306::{I2CDisplayInterface, Ssd1306};

use crate::board::DisplayParts;
use crate::channel::{DisplayCommand, DisplayCommandChannel, StatusWatch};

use super::render::{self, RSSI_HISTORY_LEN};

const BOARD_NAME: &str = if cfg!(feature = "rak_4631") {
    "rak_4631"
} else if cfg!(feature = "heltec_v3") {
    "heltec_v3"
} else {
    "unknown"
};

struct DisplayState {
    rssi_history: [i16; RSSI_HISTORY_LEN],
    rssi_count: usize,
    last_rx_count: u32,
    display_on: bool,
}

impl DisplayState {
    fn new() -> Self {
        Self {
            rssi_history: [0; RSSI_HISTORY_LEN],
            rssi_count: 0,
            last_rx_count: 0,
            display_on: true,
        }
    }

    fn push_rssi(&mut self, rssi: i16) {
        let idx = self.rssi_count % RSSI_HISTORY_LEN;
        self.rssi_history[idx] = rssi;
        self.rssi_count += 1;
    }
}

#[task]
pub async fn display_task(
    parts: DisplayParts,
    status: &'static StatusWatch,
    display_commands: &'static DisplayCommandChannel,
) {
    let interface = I2CDisplayInterface::new(parts.i2c);
    let mut display = Ssd1306::new(interface, DisplaySize128x64, DisplayRotation::Rotate0)
        .into_buffered_graphics_mode();

    if display.init().is_err() {
        defmt::error!("SSD1306 init failed");
        return;
    }

    // Splash screen
    render::splash(&mut display, BOARD_NAME, env!("CARGO_PKG_VERSION"));
    let _ = display.flush();
    Timer::after_millis(1500).await;

    // Dashboard
    let mut state = DisplayState::new();
    let mut receiver = status.receiver().unwrap();

    // Initial empty dashboard
    render::dashboard(
        &mut display,
        &crate::channel::RadioStatus::default(),
        &state.rssi_history,
        state.rssi_count,
    );
    let _ = display.flush();

    loop {
        match select(receiver.changed(), display_commands.receive()).await {
            Either::First(radio_status) => {
                if !state.display_on {
                    continue;
                }

                // Push new RSSI sample only when rx_count advances
                if radio_status.rx_count != state.last_rx_count {
                    state.last_rx_count = radio_status.rx_count;
                    if let Some(rssi) = radio_status.last_rssi {
                        state.push_rssi(rssi);
                    }
                }

                render::dashboard(
                    &mut display,
                    &radio_status,
                    &state.rssi_history,
                    state.rssi_count,
                );
                let _ = display.flush();
            }
            Either::Second(cmd) => match cmd {
                DisplayCommand::Off => {
                    state.display_on = false;
                    render::blank(&mut display);
                    let _ = display.flush();
                }
                DisplayCommand::On => {
                    state.display_on = true;
                    // Will re-render on next status update
                }
            },
        }
    }
}
