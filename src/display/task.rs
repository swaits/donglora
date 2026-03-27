use embassy_executor::task;
use embassy_futures::select::{select3, Either3};
use embassy_time::Timer;
use ssd1306::mode::DisplayConfigAsync;
use ssd1306::prelude::DisplayRotation;
use ssd1306::size::DisplaySize128x64;
use ssd1306::{I2CDisplayInterface, Ssd1306Async};

use crate::board::DisplayParts;
use crate::channel::{DisplayCommand, DisplayCommandChannel, RadioStatus, StatusWatch};

use super::render::{self, RSSI_HISTORY_LEN};

const BOARD_NAME: &str = if cfg!(feature = "rak_wisblock_4631") {
    "RAK WisBlock 4631"
} else if cfg!(feature = "heltec_v3") {
    "Heltec v3"
} else if cfg!(feature = "heltec_v4") {
    "Heltec v4"
} else {
    "unknown"
};

/// Duration per sparkline slot. 64 slots * 1s = ~1 minute of history.
const SPARK_SLOT_MS: u64 = 1000;

/// Sentinel: no packet received in this slot.
const NO_SIGNAL: i16 = -121;

struct DisplayState {
    rssi_history: [i16; RSSI_HISTORY_LEN],
    rssi_count: usize,
    current_slot_rssi: i16,
    display_on: bool,
    disconnected: bool,
    last_status: RadioStatus,
}

impl DisplayState {
    fn new() -> Self {
        Self {
            rssi_history: [NO_SIGNAL; RSSI_HISTORY_LEN],
            rssi_count: 0,
            current_slot_rssi: NO_SIGNAL,
            display_on: true,
            disconnected: true,
            last_status: RadioStatus::default(),
        }
    }

    /// Record an RSSI sample in the current time slot (keep best).
    fn record_rssi(&mut self, rssi: i16) {
        if self.current_slot_rssi == NO_SIGNAL || rssi > self.current_slot_rssi {
            self.current_slot_rssi = rssi;
        }
    }

    /// Advance to the next time slot, committing the current slot's RSSI.
    fn advance_slot(&mut self) {
        let idx = self.rssi_count % RSSI_HISTORY_LEN;
        self.rssi_history[idx] = self.current_slot_rssi;
        self.rssi_count += 1;
        self.current_slot_rssi = NO_SIGNAL;
    }
}

#[task]
pub async fn display_task(
    parts: DisplayParts,
    status: &'static StatusWatch,
    display_commands: &'static DisplayCommandChannel,
) {
    let interface = I2CDisplayInterface::new(parts.i2c);
    let mut display = Ssd1306Async::new(interface, DisplaySize128x64, DisplayRotation::Rotate0)
        .into_buffered_graphics_mode();

    if display.init().await.is_err() {
        defmt::error!("SSD1306 init failed");
        return;
    }
    let _ = display.set_brightness(ssd1306::prelude::Brightness::BRIGHTEST).await;

    // Splash screen
    render::splash(&mut display, BOARD_NAME, env!("CARGO_PKG_VERSION"));
    let _ = display.flush().await;
    Timer::after_millis(1500).await;

    let mut state = DisplayState::new();
    let mut receiver = status.receiver().unwrap();

    // Initial dashboard
    render_and_flush(&mut display, &state).await;

    loop {
        match select3(
            receiver.changed(),
            display_commands.receive(),
            Timer::after_millis(SPARK_SLOT_MS),
        )
        .await
        {
            Either3::First(radio_status) => {
                if state.disconnected {
                    continue;
                }
                if let Some(rssi) = radio_status.last_rssi {
                    if radio_status.rx_count != state.last_status.rx_count {
                        state.record_rssi(rssi);
                    }
                }
                state.last_status = radio_status;

                if state.display_on {
                    render_and_flush(&mut display, &state).await;
                }
            }
            Either3::Second(cmd) => match cmd {
                DisplayCommand::Off => {
                    state.disconnected = false;
                    state.display_on = false;
                    render::blank(&mut display);
                    let _ = display.flush().await;
                }
                DisplayCommand::On => {
                    state.disconnected = false;
                    state.display_on = true;
                    if let Some(s) = receiver.try_get() {
                        state.last_status = s;
                    }
                    render_and_flush(&mut display, &state).await;
                }
                DisplayCommand::Reset => {
                    state.disconnected = true;
                    state.last_status = RadioStatus::default();
                    state.rssi_history = [NO_SIGNAL; RSSI_HISTORY_LEN];
                    state.rssi_count = 0;
                    state.current_slot_rssi = NO_SIGNAL;
                    render_and_flush(&mut display, &state).await;
                }
            },
            Either3::Third(()) => {
                // Timer tick: advance sparkline slot
                state.advance_slot();
                if state.display_on {
                    render_and_flush(&mut display, &state).await;
                }
            }
        }
    }
}

// The concrete display type is verbose but avoids making this generic
// over both DrawTarget and the SSD1306-specific flush method.
type Display<I> = ssd1306::Ssd1306Async<
    I,
    DisplaySize128x64,
    ssd1306::mode::BufferedGraphicsModeAsync<DisplaySize128x64>,
>;

async fn render_and_flush<I>(display: &mut Display<I>, state: &DisplayState)
where
    I: display_interface::AsyncWriteOnlyDataCommand,
{
    render::dashboard(
        display,
        &state.last_status,
        &state.rssi_history,
        state.rssi_count,
    );
    let _ = display.flush().await;
}
